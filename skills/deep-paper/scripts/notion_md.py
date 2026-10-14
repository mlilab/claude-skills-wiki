#!/usr/bin/env python3
"""Convert summary.md into what the Notion MCP tools need for one database row.

usage: notion_md.py --id PAPER_ID [--out FILE]

Prints JSON with:
  properties  values for the row: Title, Abbr, Link, Venue, Submitted (date), Category, Tags
  icon        the emoji from the front matter
  content     Notion-flavored Markdown for the page body: links and authors, the 3-line summary,
              a divider, then the write-up (callouts, toggles, tables, underline, math and
              figures converted; figures point at arXiv image URLs)
  uploads     figures that exist only as local files (PDF-only papers, or SVG figures that Notion
              may not display). Upload them with notion_upload.py if a token is configured;
              otherwise report that they were left out.

Pass `content` and `properties` to notion-create-pages with the configured data source as parent,
then set `notion_url` with `notion_md.py --id ID --set-url URL` so the local index links the row.
"""
from __future__ import annotations

import argparse
import json
import re

from check import FIG_REF, split_front
from common import load_config, out, paper_dir, read_json, write_json

CALLOUT = {"KEY": ("📌", "yellow_bg"), "RESULT": ("✅", "green_bg"), "LIMIT": ("⚖️", "gray_bg")}


def indent(text: str) -> str:
    return "\n".join(("\t" + ln) if ln.strip() else ln for ln in text.split("\n"))


def pipe_table_to_notion(block: str) -> str:
    rows = [r.strip() for r in block.strip().split("\n") if r.strip().startswith("|")]
    rows = [r for r in rows if not re.match(r"^\|\s*:?-{2,}", r)]
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    width = max(len(c) for c in cells) if cells else 0
    out_rows = []
    for row in cells:
        row = row + [""] * (width - len(row))
        out_rows.append("<tr>\n" + "\n".join(f"<td>{c}</td>" for c in row) + "\n</tr>")
    return f'<table header-row="true">\n' + "\n".join(out_rows) + "\n</table>"


def convert_body(body: str, figs: dict, uploads: list) -> str:
    lines, outl, i, indents = body.split("\n"), [], 0, []
    while i < len(lines):
        ln = lines[i]
        # callouts
        m = re.match(r"^>\s*\[!(KEY|RESULT|LIMIT)\]\s*(.*)$", ln, re.I)
        if m:
            icon, color = CALLOUT[m.group(1).upper()]
            body_lines = [m.group(2)] if m.group(2).strip() else []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                body_lines.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            title = body_lines[0] if body_lines else ""
            rest = "\n".join(body_lines[1:]).strip()
            inner = f"**{title}**" + (("\n" + indent(rest)) if rest else "")
            outl += [f'<callout icon="{icon}" color="{color}">', "\t" + inner.split("\n")[0]] + \
                inner.split("\n")[1:] + ["</callout>"]
            continue
        # pipe tables
        if ln.strip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            outl.append(pipe_table_to_notion("\n".join(lines[i:j])))
            i = j
            continue
        # toggles: <details><summary>T</summary> ... </details>
        m = re.match(r"^<details>\s*<summary>(.*?)</summary>\s*$", ln.strip())
        if m:
            j, depth, inner = i + 1, 1, []
            while j < len(lines):
                if lines[j].strip().startswith("<details"):
                    depth += 1
                if lines[j].strip() == "</details>":
                    depth -= 1
                    if depth == 0:
                        break
                inner.append(lines[j])
                j += 1
            outl += ["<details>", f"<summary>{m.group(1)}</summary>",
                     indent(convert_body("\n".join(inner).strip("\n"), figs, uploads)), "</details>"]
            i = j + 1
            continue
        # Notion has headings 1-4; deeper ones become heading 4
        m = re.match(r"^(#{5,6})\s+(.*)$", ln)
        if m:
            outl.append(f"#### {m.group(2)}")
            i += 1
            continue
        # nested list items: Notion nests children by tabs, Markdown by spaces. The depth is the
        # number of distinct, smaller indents seen since the list started.
        m = re.match(r"^( *)(?=([-*+]|\d+[.)])\s)", ln)
        if m:
            ind = len(m.group(1))
            indents = [x for x in indents if x < ind] + [ind]
            ln = "\t" * (len(indents) - 1) + ln.lstrip(" ")
        elif ln.strip() and not ln.startswith(" "):
            indents = []
        outl.append(ln)
        i += 1
    text = "\n".join(outl)

    def fig_sub(m):
        cap, num = m.group(1).strip(), m.group(2)
        f = figs.get(num)
        if not f:
            return f"*(Figure {num} missing)*"
        cap = cap if re.match(r"^(Figure|Fig\.)\s*\d", cap) else f"Figure {num}: {cap}"
        urls = [u if isinstance(u, str) else u[0] for u in (f.get("image_urls") or [])]
        local = f.get("png_files") or f.get("files") or []
        parts = []
        if urls:
            for k, u in enumerate(urls):
                if u.lower().endswith(".svg"):
                    uploads.append({"figure": num, "file": local[k] if k < len(local) else None,
                                    "caption": cap, "reason": "SVG may not display in Notion", "fallback_url": u})
                parts.append(f"![{cap if k == 0 else ''}]({u})")
        else:
            for fl in local:
                uploads.append({"figure": num, "file": fl, "caption": cap, "reason": "no public image URL"})
            parts.append(f"[[upload Figure {num}]]")
        return "\n".join(parts)
    text = FIG_REF.sub(fig_sub, text)
    text = re.sub(r"<u>(.*?)</u>", r'<span underline="true">\1</span>', text)
    return notion_inline(text)


ALLOWED_TAGS = re.compile(r"</?(callout|table|tr|td|colgroup|col|details|summary|span|empty-block|br)\b[^>]*>")


def notion_inline(text: str) -> str:
    """Math and escaping in Notion's Markdown dialect: inline math is $`x`$, display math sits on
    its own lines between $$, and a bare < or ~ in prose is escaped."""
    stash = []

    def keep(s):
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"
    text = re.sub(r"```.*?```", lambda m: keep(m.group(0)), text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", lambda m: keep(m.group(0)), text)
    text = re.sub(r"\$\$\s*(.+?)\s*\$\$", lambda m: keep("\n$$\n" + m.group(1).strip() + "\n$$\n"), text, flags=re.S)
    text = re.sub(r"(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$", lambda m: keep("$`" + m.group(1) + "`$"), text)
    text = re.sub(r"!?\[[^\]]*\]\([^)]+\)", lambda m: keep(m.group(0)), text)  # links and images
    text = ALLOWED_TAGS.sub(lambda m: keep(m.group(0)), text)
    text = re.sub(r"(?<!\\)<", r"\\<", text)  # remaining "<" is prose, not a tag
    text = re.sub(r"(?<![~\\])~(?!~)", r"\\~", text)
    while "\x00" in text:
        text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
    return re.sub(r"\n{3,}", "\n\n", text)


def build(cfg, pid: str) -> dict:
    pdir = paper_dir(cfg, pid)
    meta = read_json(pdir / "meta.json")
    front, body = split_front((pdir / "summary.md").read_text(encoding="utf-8"))
    front = front or {}
    figs = {f["number"]: f for f in read_json(pdir / "figures.json", {"figures": []})["figures"]
            if f["kind"] == "figure"}
    uploads = []
    L = meta.get("links") or {}
    link_line = " · ".join(f"[{n}]({u})" for n, u in
                           [("PDF", L.get("pdf")), ("arXiv", L.get("abs")), ("Code", L.get("code")),
                            ("Project", L.get("project"))] if u)
    head = [link_line, f"**Authors:** {', '.join(meta.get('authors') or [])}", ""]
    head += [f"- {x}" for x in (front.get("tldr") or [])] + ["", "---", ""]
    content = "\n".join(head) + convert_body(body.strip(), figs, uploads)
    cats = front.get("category") or []
    cats = [cats] if isinstance(cats, str) else cats
    props = {"Title": meta["title"], "Abbr": front.get("abbr") or "", "Link": L.get("pdf") or L.get("abs") or "",
             "Venue": meta.get("venue") or "", "date:Submitted:start": meta.get("submitted") or None,
             "date:Submitted:is_datetime": 0, "Category": json.dumps(cats, ensure_ascii=False),
             "Tags": json.dumps(front.get("tags") or [], ensure_ascii=False)}
    if not props["date:Submitted:start"]:
        props.pop("date:Submitted:start")
        props.pop("date:Submitted:is_datetime")
    return {"properties": props, "icon": front.get("icon") or "📄", "content": content, "uploads": uploads}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--out")
    ap.add_argument("--set-url")
    args = ap.parse_args()
    cfg = load_config()
    if args.set_url:
        idx_path = cfg["data_dir"] / "index.json"
        idx = read_json(idx_path, {"papers": []})
        meta = read_json(paper_dir(cfg, args.id) / "meta.json") or {"id": args.id, "title": args.id}
        entry = next((p for p in idx["papers"] if p["id"] == meta["id"]), None)
        if entry is None:
            entry = {"id": meta["id"], "arxiv_id": meta.get("arxiv_id"), "title": meta["title"]}
            idx["papers"].append(entry)
        entry["notion_url"] = args.set_url
        write_json(idx_path, idx)
        meta["notion_url"] = args.set_url
        write_json(paper_dir(cfg, args.id) / "meta.json", meta)
        out({"notion_url": args.set_url})
        return
    res = build(cfg, args.id)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        out({"written": args.out, "chars": len(res["content"]), "uploads": res["uploads"]})
    else:
        out(res)


if __name__ == "__main__":
    main()
