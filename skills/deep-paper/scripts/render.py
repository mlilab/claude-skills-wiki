#!/usr/bin/env python3
"""Build the static site: one split-view page per paper and an index of all papers.

usage: render.py --id PAPER_ID     # render that paper, then the index
       render.py --all             # re-render every paper that has summary.json/md
       render.py --index           # only the index

Writes <data_dir>/papers/<id>/index.html, <data_dir>/index.html, <data_dir>/index.json and copies
assets/. A paper page shows the write-up on the left and the original PDF (rendered in the
browser with PDF.js from arxiv.org, or the local paper.pdf for non-arXiv papers) on the right.
Section headings and figures carry the PDF page, so a click scrolls the original to that page.
The site is plain static files: open index.html, run `serve.py`, or host the folder anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil

import markdown

from check import FIG_REF, split_front
from common import SKILL_DIR, load_config, out, paper_dir, read_json, write_json

PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174"
KATEX = "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9"
CALLOUT = {"KEY": ("📌", "key"), "RESULT": ("✅", "result"), "LIMIT": ("⚖️", "limit")}
L10N = {
    "en": {"back": "All papers", "split": "Split", "summary": "Write-up", "pdf": "PDF", "open_pdf": "Open PDF",
           "tldr": "TL;DR", "submitted": "Submitted", "venue": "Venue", "loading": "Loading PDF…",
           "pdf_fail": "The PDF could not be loaded here.", "search": "Search title, tags, venue…",
           "all": "All", "title": "Title", "category": "Category", "tags": "Tags", "added": "Added",
           "papers": "papers", "page": "p."},
    "ko": {"back": "전체 논문", "split": "나란히", "summary": "정리본", "pdf": "원문", "open_pdf": "PDF 열기",
           "tldr": "3줄 요약", "submitted": "제출", "venue": "학회", "loading": "PDF 불러오는 중…",
           "pdf_fail": "이 화면에서 PDF를 불러오지 못했습니다.", "search": "제목, 태그, 학회 검색…",
           "all": "전체", "title": "제목", "category": "분야", "tags": "태그", "added": "추가일",
           "papers": "편", "page": "p."},
}


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


# ---------------------------------------------------------------- Markdown -> HTML


def protect_math(text: str):
    """Swap math for placeholders so Markdown does not touch underscores or asterisks."""
    stash = []

    def keep(m):
        stash.append(m.group(0))
        return f"\x00M{len(stash) - 1}\x00"
    text = re.sub(r"\$\$.+?\$\$", keep, text, flags=re.S)
    text = re.sub(r"(?<![\\$])\$(?!\s)[^$\n]+?(?<!\s)\$", keep, text)
    return text, stash


def restore_math(text: str, stash: list) -> str:
    return re.sub(r"\x00M(\d+)\x00", lambda m: html.escape(stash[int(m.group(1))], quote=False), text)


def callouts(md_text: str) -> str:
    """> [!KEY] Title\n> body  ->  <div class="callout key" markdown="1">...</div>"""
    lines, outl, i = md_text.split("\n"), [], 0
    while i < len(lines):
        m = re.match(r"^>\s*\[!(KEY|RESULT|LIMIT)\]\s*(.*)$", lines[i], re.I)
        if not m:
            outl.append(lines[i])
            i += 1
            continue
        kind = m.group(1).upper()
        icon, cls = CALLOUT[kind]
        body = [m.group(2)] if m.group(2).strip() else []
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            body.append(re.sub(r"^>\s?", "", lines[i]))
            i += 1
        title = body[0] if body else ""
        rest = "\n".join(body[1:])
        outl += [f'<div class="callout {cls}" markdown="1">', "",
                 f'<p class="callout-title"><span class="ci">{icon}</span> <strong>{inline_md(title, False)}</strong></p>'
                 if title else "", "", rest, "", "</div>", ""]
    return "\n".join(outl)


def figure_html(num: str, caption: str, figs: dict, t: dict, protect: bool = True) -> str:
    f = figs.get(num)
    if not f:
        return f'<p class="missing">Figure {esc(num)} not found</p>'
    imgs = "".join(f'<img src="{esc(src)}" loading="lazy" alt="Figure {esc(num)}">' for src in (f.get("files") or []))
    if not imgs and f.get("image_urls"):
        urls = [u if isinstance(u, str) else u[0] for u in f["image_urls"]]
        imgs = "".join(f'<img src="{esc(u)}" loading="lazy" alt="Figure {esc(num)}">' for u in urls)
    page = f.get("page")
    jump = (f'<button class="pg" data-page="{page}" title="Show in the PDF">{t["page"]}{page}</button>'
            if page else "")
    return (f'<figure class="fig" id="fig-{esc(num)}"><div class="fig-imgs">{imgs}</div>'
            f'<figcaption><span class="fig-label">Figure {esc(num)}</span>{jump} '
            f'{inline_md(caption, protect)}</figcaption></figure>')


def inline_md(text: str, protect: bool = True) -> str:
    """Markdown for one line. protect=False when the caller already swapped math for placeholders."""
    t, stash = protect_math(text or "") if protect else (text or "", [])
    h = markdown.markdown(t, extensions=["sane_lists"])
    h = re.sub(r"^<p>(.*)</p>$", r"\1", h.strip(), flags=re.S)
    return restore_math(h, stash) if protect else h


def body_html(body: str, figs: dict, outline: list, t: dict) -> str:
    def fig_sub(m):
        cap = m.group(1)
        cap = re.sub(r"^(Figure|Fig\.)\s*[A-Za-z]?\d+[a-z]?\s*[:.]\s*", "", cap)
        return "\n\n" + figure_html(m.group(2), cap, figs, t, protect=False) + "\n\n"
    # math first (placeholders survive Markdown); captions and callout titles reuse the same stash
    text, stash = protect_math(body)
    text = callouts(text)
    text = FIG_REF.sub(fig_sub, text)
    # toggles: let Markdown work inside <details> (tables, lists)
    text = re.sub(r"<details>\s*", '<details markdown="1">\n', text)
    text = re.sub(r"(<summary>.*?</summary>)", r"\1\n", text)
    text = text.replace("<u>", "\x00U").replace("</u>", "\x00/U")
    h = markdown.markdown(text, extensions=["tables", "fenced_code", "md_in_html", "sane_lists"])
    h = h.replace("\x00U", "<u>").replace("\x00/U", "</u>")
    h = restore_math(h, stash)
    # external links open in a new tab
    h = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', h)
    # PDF page buttons on section headings
    pages = {}
    for s in outline:
        if s.get("page"):
            if s["number"]:
                pages.setdefault(("n", s["number"]), s["page"])
            pages.setdefault(("t", s["title"].lower()[:40]), s["page"])

    def head_sub(m):
        tag, inner = m.group(1), m.group(2)
        txt = re.sub(r"<[^>]+>", "", inner).strip()
        num = re.match(r"^([A-Z]?\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s", txt)
        page = pages.get(("n", num.group(1))) if num else None
        if page is None:
            title = re.sub(r"^([A-Z]?\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+", "", txt).lower()[:40]
            page = pages.get(("t", title))
        anchor = re.sub(r"[^\w]+", "-", txt.lower()).strip("-")[:60]
        btn = (f' <button class="pg" data-page="{page}" title="Show in the PDF">{t["page"]}{page}</button>'
               if page else "")
        return f'<{tag} id="{anchor}">{inner}{btn}</{tag}>'
    h = re.sub(r"<(h[2-5])>(.*?)</\1>", head_sub, h, flags=re.S)
    return h


# ---------------------------------------------------------------- pages


def page_shell(title: str, body: str, rel: str, lang: str, head_extra: str = "", body_class: str = "") -> str:
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{rel}assets/style.css">
<link rel="stylesheet" href="{KATEX}/katex.min.css">
<script defer src="{KATEX}/katex.min.js"></script>
<script defer src="{KATEX}/contrib/auto-render.min.js"></script>
{head_extra}
</head>
<body class="{body_class}">
{body}
<script defer src="{rel}assets/app.js"></script>
</body>
</html>"""


def links_html(meta: dict) -> str:
    L = meta.get("links") or {}
    items = [("arXiv", L.get("abs")), ("PDF", L.get("pdf")), ("HTML", L.get("html")),
             ("Code", L.get("code")), ("Project", L.get("project"))]
    return "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{n}</a>' for n, u in items if u)


def render_paper(cfg, pid: str) -> dict:
    t = L10N.get(cfg.get("language"), L10N["en"])
    pdir = paper_dir(cfg, pid)
    meta = read_json(pdir / "meta.json")
    src = pdir / "summary.md"
    if not meta or not src.exists():
        raise SystemExit(f"{pid}: meta.json or summary.md missing")
    front, body = split_front(src.read_text(encoding="utf-8"))
    front = front or {}
    outline = read_json(pdir / "outline.json", {"sections": []})["sections"]
    figs = {f["number"]: f for f in read_json(pdir / "figures.json", {"figures": []})["figures"]
            if f["kind"] == "figure"}
    cats = front.get("category") or []
    cats = [cats] if isinstance(cats, str) else cats
    tags = front.get("tags") or []
    pdf_url = (meta.get("links") or {}).get("pdf") or ("paper.pdf" if (pdir / "paper.pdf").exists() else "")
    chips = "".join(f'<span class="chip cat">{esc(c)}</span>' for c in cats) + \
        "".join(f'<span class="chip">{esc(x)}</span>' for x in tags)
    tldr = "".join(f"<li>{inline_md(x)}</li>" for x in (front.get("tldr") or []))
    authors = ", ".join(meta.get("authors") or [])
    abbr = f'<span class="abbr">{esc(front.get("abbr"))}</span>' if front.get("abbr") else ""
    venue = meta.get("venue") or ""
    body_h = body_html(body, figs, outline, t)
    page = f"""<header class="bar">
<a class="back" href="../../index.html">← {t["back"]}</a>
<div class="bar-title">{esc(front.get("icon", ""))} {esc(front.get("abbr") or meta["title"])}</div>
<div class="modes" role="tablist">
<button data-mode="split" class="on">{t["split"]}</button><button data-mode="summary">{t["summary"]}</button><button data-mode="pdf">{t["pdf"]}</button>
</div>
</header>
<main class="split" data-pdf="{esc(pdf_url)}">
<article class="pane left" id="summary">
<header class="paper-head">
<h1>{esc(meta["title"])} {abbr}</h1>
<p class="authors">{esc(authors)}</p>
<p class="meta-line">{f'<span class="venue">{esc(venue)}</span>' if venue else ''}<span>{t["submitted"]} {esc(meta.get("submitted", ""))}</span>{links_html(meta)}</p>
<div class="chips">{chips}</div>
<section class="tldr"><h2>{t["tldr"]}</h2><ul>{tldr}</ul></section>
</header>
<div class="body">{body_h}</div>
</article>
<div class="gutter" title="Drag to resize"></div>
<section class="pane right" id="pdf">
<div class="pdf-bar"><span class="pdf-page">–</span><a href="{esc(pdf_url)}" target="_blank" rel="noopener">{t["open_pdf"]} ↗</a></div>
<div class="pdf-pages" data-loading="{t["loading"]}" data-fail="{t["pdf_fail"]}"></div>
</section>
</main>"""
    head = (f'<script defer src="{PDFJS}/pdf.min.js"></script>'
            f'<meta name="pdfjs-worker" content="{PDFJS}/pdf.worker.min.js">')
    (pdir / "index.html").write_text(page_shell(meta["title"], page, "../../", cfg.get("language", "en"),
                                                head, "paper-page"), encoding="utf-8")
    return {"id": meta["id"], "arxiv_id": meta.get("arxiv_id"), "title": meta["title"],
            "abbr": front.get("abbr") or "", "icon": front.get("icon") or "", "venue": venue,
            "submitted": meta.get("submitted", ""), "category": cats, "tags": tags,
            "tldr": front.get("tldr") or [], "page": f"papers/{pdir.name}/index.html",
            "links": {k: v for k, v in (meta.get("links") or {}).items() if k in ("pdf", "abs")}}


COLUMNS = ["Title", "Abbr", "Venue", "Submitted", "Category", "Tags", "Link", "Added"]
SORTABLE = {"Title", "Abbr", "Venue", "Submitted", "Added"}


def render_index(cfg, entries: list):
    t = L10N.get(cfg.get("language"), L10N["en"])
    entries = sorted(entries, key=lambda e: e.get("submitted", ""), reverse=True)
    cats = sorted({c for e in entries for c in e.get("category", [])})
    bar = [f'<button class="filter on" data-cat="">{t["all"]} <b>{len(entries)}</b></button>']
    bar += [f'<button class="filter" data-cat="{esc(c)}">{esc(c)} <b>'
            f'{sum(1 for e in entries if c in e.get("category", []))}</b></button>' for c in cats]
    rows = []
    for e in entries:
        search = " ".join([e["title"], e.get("abbr", ""), e.get("venue", ""), " ".join(e.get("tags", [])),
                           " ".join(e.get("category", []))]).lower()
        links = e.get("links") or {}
        link_cell = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{n}</a> '
                            for n, u in (("PDF", links.get("pdf")), ("arXiv", links.get("abs"))) if u)
        rows.append(f"""<tr data-cats="{esc('|'.join(e.get('category', [])))}" data-search="{esc(search)}">
<td class="t"><a href="{esc(e['page'])}">{esc(e['title'])}</a></td>
<td data-sort="{esc(e.get('abbr', ''))}">{f'<span class="abbr">{esc(e["abbr"])}</span>' if e.get('abbr') else ''}</td>
<td data-sort="{esc(e.get('venue', ''))}">{esc(e.get('venue', ''))}</td>
<td data-sort="{esc(e.get('submitted', ''))}">{esc(e.get('submitted', ''))}</td>
<td>{''.join(f'<span class="chip cat">{esc(c)}</span>' for c in e.get('category', []))}</td>
<td>{''.join(f'<span class="chip">{esc(x)}</span>' for x in e.get('tags', []))}</td>
<td class="links">{link_cell}</td>
<td data-sort="{esc(e.get('added', ''))}">{esc(e.get('added', ''))}</td></tr>""")
    hl = cfg["html"].get("home_link") or {}
    home = (f'<a class="home" href="{esc(hl.get("href"))}">← {esc(hl.get("label", "Home"))}</a>'
            if hl.get("href") else "")
    # column names match the Notion database
    head = "".join(f'<th data-col="{i}">{n}</th>' if n in SORTABLE else f"<th>{n}</th>"
                   for i, n in enumerate(COLUMNS))
    body = f"""<main class="wrap index">
<header class="masthead">{home}<h1>{esc(cfg["html"]["title"])}</h1><p class="sub">{len(entries)} {t["papers"]}</p></header>
<div class="toolbar"><div class="filters">{"".join(bar)}</div>
<input class="search" type="search" placeholder="{t["search"]}"></div>
<div class="table-wrap"><table class="db">
<thead><tr>{head}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
</main>"""
    root = cfg["data_dir"]
    (root / "index.html").write_text(page_shell(cfg["html"]["title"], body, "", cfg.get("language", "en"),
                                                "", "index-page"), encoding="utf-8")


def copy_assets(cfg):
    dst = cfg["data_dir"] / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    for f in (SKILL_DIR / "assets").glob("*"):
        if f.suffix in (".css", ".js"):
            shutil.copy2(f, dst / f.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--index", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    root = cfg["data_dir"]
    root.mkdir(parents=True, exist_ok=True)
    copy_assets(cfg)
    index = read_json(root / "index.json", {"papers": []})
    by_id = {p["id"]: p for p in index["papers"]}
    ids = []
    if args.id:
        ids = [args.id]
    elif args.all:
        ids = [m["id"] for m in (read_json(d / "meta.json") for d in (root / "papers").glob("*"))
               if m and (paper_dir(cfg, m["id"]) / "summary.md").exists()]
    rendered = []
    for pid in ids:
        e = render_paper(cfg, pid)
        old = by_id.get(e["id"], {})
        e["added"] = old.get("added") or dt.date.today().isoformat()
        if old.get("notion_url"):
            e["notion_url"] = old["notion_url"]
        by_id[e["id"]] = e
        rendered.append(e["page"])
    index["papers"] = list(by_id.values())
    write_json(root / "index.json", index)
    render_index(cfg, index["papers"])
    out({"rendered": rendered, "index": str(root / "index.html"), "papers": len(index["papers"])})


if __name__ == "__main__":
    main()
