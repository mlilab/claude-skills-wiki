#!/usr/bin/env python3
"""Check summary.md against the writing guide before it is published.

usage: check.py --id PAPER_ID

Prints {"errors": [...], "warnings": [...], "stats": {...}}; exit code 1 if there are errors.
Errors: bad front matter, missing main sections, unknown figure numbers, figures collected at the
end, callout kinds other than KEY/RESULT/LIMIT, arXiv links that are not in refs.json/meta.json.
Warnings: prose above the limit, long prose paragraphs, sections compressed too far, too few
figures, figures placed in another section, translated headings, few citation links.
"""
from __future__ import annotations

import argparse
import re
import sys

import yaml

from common import load_config, out, paper_dir, read_json

FIG_REF = re.compile(r"!\[([^\]]*)\]\(fig:([A-Za-z]?\d+[a-z]?)\)")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
HANGUL = re.compile(r"[가-힣]")


def split_front(text: str):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError as e:
        return {"__error__": str(e)}, m.group(2)


def blocks(body: str):
    """(kind, text, heading_path) per block; kinds: heading, prose, list, table, callout, image,
    toggle, code, html."""
    res, cur_heads = [], []
    lines = body.split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < n and not lines[j].startswith("```"):
                j += 1
            res.append(("code", "\n".join(lines[i:j + 1]), list(cur_heads)))
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            cur_heads = [h for h in cur_heads if h[0] < level] + [(level, m.group(2).strip())]
            res.append(("heading", m.group(2).strip(), list(cur_heads)))
            i += 1
            continue
        j = i
        while j < n and lines[j].strip() and not re.match(r"^#{1,6}\s", lines[j]) and not lines[j].startswith("```"):
            j += 1
        chunk = "\n".join(lines[i:j])
        first = lines[i].lstrip()
        if first.startswith(">"):
            kind = "callout"
        elif first.startswith("|"):
            kind = "table"
        elif re.match(r"^([-*+]|\d+[.)])\s", first):
            kind = "list"
        elif FIG_REF.match(first) or first.startswith("!["):
            kind = "image"
        elif first.startswith(("<details", "</details", "<summary")):
            kind = "toggle"
        elif first.startswith("<"):
            kind = "html"
        else:
            kind = "prose"
        res.append((kind, chunk, list(cur_heads)))
        i = j
    return res


def plain(text: str) -> str:
    text = FIG_REF.sub("", text)
    text = LINK.sub(r"\1", text)
    text = re.sub(r"\$\$.*?\$\$|\$[^$]*\$", "x", text, flags=re.S)
    text = re.sub(r"<[^>]+>|[*_`>|#]|^\s*([-*+]|\d+[.)])\s", " ", text, flags=re.M)
    return " ".join(text.split())


def sentences(text: str) -> int:
    t = plain(text)
    parts = re.split(r"(?<=[.!?])\s+(?=\S)|(?<=다\.)\s*", t)
    return len([p for p in parts if len(p.strip()) > 3])


def head_number(h: str) -> str:
    m = re.match(r"^([A-Z]?\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s", h)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    args = ap.parse_args()
    cfg = load_config()
    pdir = paper_dir(cfg, args.id)
    p = pdir / "summary.md"
    if not p.exists():
        raise SystemExit(f"{p} not found")
    errors, warnings = [], []
    meta = read_json(pdir / "meta.json", {})
    outline = read_json(pdir / "outline.json", {"sections": []})["sections"]
    figs = read_json(pdir / "figures.json", {"figures": []})["figures"]
    refs = read_json(pdir / "refs.json", {"refs": {}})["refs"]
    front, body = split_front(p.read_text(encoding="utf-8"))

    # ---- front matter
    if front is None:
        errors.append("missing YAML front matter (--- ... ---) at the top")
        front = {}
    elif "__error__" in front:
        errors.append(f"front matter is not valid YAML: {front['__error__']}")
        front = {}
    tldr = front.get("tldr")
    if isinstance(tldr, list):
        for k, x in enumerate(tldr, 1):
            if isinstance(x, dict):
                errors.append(f"tldr line {k} was read as a mapping because it contains ': '; put the line in quotes")
    if not isinstance(tldr, list) or len(tldr) != 3 or not all(isinstance(x, str) and x.strip() for x in tldr):
        errors.append("front matter 'tldr' must be a list of exactly 3 non-empty lines (quote each line)")
    cats = front.get("category")
    cats = [cats] if isinstance(cats, str) else (cats or [])
    if not cats:
        errors.append("front matter 'category' is empty")
    allowed = cfg["taxonomy"]["categories"]
    bad = [c for c in cats if c not in allowed]
    if bad:
        (warnings if cfg["taxonomy"].get("allow_new_options") else errors).append(
            f"category not in taxonomy.categories: {bad}")
    if not front.get("tags"):
        warnings.append("front matter 'tags' is empty")
    survey = bool(front.get("survey"))

    bl = blocks(body)
    headings = [b for b in bl if b[0] == "heading"]

    # ---- sections present and in order
    main_secs = [s for s in outline if not s["in_appendix"] and s["level"] <= 2 and (s["number"] or s["title"])]
    head_texts = [h[1] for h in headings]
    positions = []
    for s in main_secs:
        want_num, want_title = s["number"], s["title"].lower()
        idx = next((k for k, h in enumerate(head_texts)
                    if (want_num and head_number(h) == want_num) or want_title[:40] in h.lower()), None)
        if idx is None:
            errors.append(f"missing section heading: {s['number']} {s['title']}".strip())
        else:
            positions.append(idx)
    if positions != sorted(positions):
        warnings.append("section headings are not in the paper's order")
    for h in head_texts:
        if HANGUL.search(h) and not h.lower().startswith("appendix"):
            warnings.append(f"heading looks translated (keep the original English title): {h!r}")

    # ---- compression per top-level section
    top_src = {}
    for s in outline:
        if s["in_appendix"]:
            continue
        top = (s["number"] or s.get("parent") or "").split(".")[0]
        if top:
            top_src[top] = top_src.get(top, 0) + s.get("chars", 0)
    top_sum, cur = {}, None
    for kind, text, path in bl:
        if kind == "heading":
            n = head_number(text)
            if path and path[-1][0] <= 2:
                cur = n.split(".")[0] if n else None  # an unnumbered ## (e.g. Appendix highlights) ends the section
            continue
        if cur:
            top_sum[cur] = top_sum.get(cur, 0) + len(plain(text))
    lang_factor = 2.2 if cfg.get("language") == "ko" else 1.0  # Hangul packs more per character
    for top, src in top_src.items():
        if src < 800:
            continue
        ratio = top_sum.get(top, 0) * lang_factor / src
        if ratio < cfg["check"]["min_compression"]:
            warnings.append(f"section {top} looks over-compressed ({ratio:.0%} of the original length); "
                            "check that every paragraph is represented")

    # ---- prose ratio and long paragraphs
    prose = sum(len(plain(t)) for k, t, _ in bl if k == "prose")
    total = sum(len(plain(t)) for k, t, _ in bl if k in ("prose", "list", "table", "callout", "toggle", "html"))
    ratio = prose / total if total else 0
    if ratio > cfg["check"]["max_prose_ratio"]:
        warnings.append(f"prose is {ratio:.0%} of the text (limit {cfg['check']['max_prose_ratio']:.0%}): "
                        "turn enumerations, steps and numbers into lists or tables")
    long_paras = [plain(t)[:60] for k, t, _ in bl if k == "prose" and sentences(t) >= 4]
    for lp in long_paras[:8]:
        warnings.append(f"prose paragraph with 4+ sentences: {lp!r}...")

    # ---- callouts
    for k, t, _ in bl:
        if k == "callout":
            m = re.match(r"^>\s*\[!(\w+)\]", t)
            if m and m.group(1).upper() not in ("KEY", "RESULT", "LIMIT"):
                errors.append(f"callout kind [!{m.group(1)}] is not allowed (use KEY, RESULT or LIMIT)")

    # ---- figures
    by_num = {f["number"]: f for f in figs if f["kind"] == "figure"}
    used = []
    for k, t, path in bl:
        for m in FIG_REF.finditer(t):
            num = m.group(2)
            f = by_num.get(num)
            if f is None:
                errors.append(f"fig:{num} does not exist in figures.json")
                continue
            if not (f.get("files") or f.get("image_urls")):
                errors.append(f"Figure {num} has no image file")
            used.append(num)
            if f["in_appendix"]:
                warnings.append(f"Figure {num} is an appendix figure")
            sec_heads = [head_number(h[1]).split(".")[0] for h in path if head_number(h[1])]
            if f.get("top_section") and sec_heads and sec_heads[0] != f["top_section"]:
                warnings.append(f"Figure {num} belongs to section {f['top_section']} but is placed under "
                                f"section {sec_heads[0]}")
            if not m.group(1).strip():
                warnings.append(f"Figure {num} has an empty caption")
    if headings and re.search(r"\bfigures?\b|그림", headings[-1][1], re.I):
        errors.append("figures are collected under a final heading; place each one in its section")
    main_avail = [n for n, f in by_num.items() if not f["in_appendix"] and (f.get("files") or f.get("image_urls"))]
    want = min(cfg["figures"]["min_main"], len(main_avail))
    if len(set(used)) < want:
        warnings.append(f"only {len(set(used))} main figures used; {len(main_avail)} are available "
                        f"(aim for {cfg['figures']['min_main']}-{cfg['figures']['max_main']})")
    if len(set(used)) > cfg["figures"]["max_main"] + 2:
        warnings.append(f"{len(set(used))} figures used; keep the 6-8 that carry the paper")

    # ---- links
    known = {r["url"].rstrip("/") for r in refs.values() if r.get("url")}
    known |= {f"https://arxiv.org/pdf/{r['arxiv_id']}" for r in refs.values() if r.get("arxiv_id")}
    known |= {u.rstrip("/") for u in (meta.get("links") or {}).values() if u}
    linked_urls = [m.group(2).rstrip("/") for m in LINK.finditer(body)]
    for u in linked_urls:
        norm = re.sub(r"v\d+$", "", u.replace("http://", "https://"))
        if norm in known or norm.replace("/pdf/", "/abs/") in known:
            continue
        if "arxiv.org" in norm:
            errors.append(f"arXiv link not found in refs.json or meta.json (possibly invented): {u}")
        else:
            warnings.append(f"link not found in refs.json or meta.json; keep it only if the paper gives it: {u}")
    cited_main = {k for k, r in refs.items() if r.get("url") and any(
        not s["in_appendix"] and (s["number"] or s["title"]) in (r.get("cited_in") or []) for s in outline)}
    linked = {k for k, r in refs.items() if r.get("url") and r["url"].rstrip("/") in
              {re.sub(r"v\d+$", "", u) for u in linked_urls}}
    cov = len(linked & cited_main) / len(cited_main) if cited_main else 1.0
    if not survey and cited_main and cov < 0.5:
        warnings.append(f"only {len(linked & cited_main)}/{len(cited_main)} linkable citations of the main "
                        "body are linked; link each cited model/method by name")

    stats = {"sections_expected": len(main_secs), "headings": len(headings), "prose_ratio": round(ratio, 3),
             "figures_used": sorted(set(used), key=lambda x: (len(x), x)), "links": len(linked_urls),
             "citation_link_coverage": round(cov, 2)}
    out({"errors": errors, "warnings": warnings, "stats": stats})
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
