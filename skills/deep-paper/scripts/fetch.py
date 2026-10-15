#!/usr/bin/env python3
"""Download one paper and extract everything the write-up needs.

usage: fetch.py --id ARXIV_ID [--force]          # after resolve.py
       fetch.py --pdf FILE --record RECORD.json  # a non-arXiv paper (record: id, title, authors, ...)

Writes <data_dir>/papers/<id>/:
  meta.json      title, authors, affiliations, abstract, submitted date, comments, links, source
  content.md     the full text in reading order. Every paragraph carries an id like [S3.2.p1];
                 citations appear as [@bib.bib12 Smith et al., 2024]; math as $LaTeX$;
                 figure positions as [[Figure 3]]. The appendix follows a "# APPENDIX" line.
  outline.json   sections in order: number, title, level, in_appendix, pdf page, chars, paragraphs
  figures.json   figures and tables: number, caption, section, in_appendix, pdf page, image URLs
                 (verified image/*), local files in figures/
  refs.json      bibliography: key, label, title, arXiv id/URL if the entry names one, cited_in
  paper.pdf      the PDF (used for page numbers and, without HTML, for text and figures)

Source order: arXiv HTML (versions newest first), then the PDF. The HTML title is checked
against the arXiv title so a wrong or stale page is never used.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from common import (http_get, load_config, norm_title, out, paper_dir, read_json, title_tokens,
                    write_json)

IMG_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
             "image/svg+xml": ".svg", "image/webp": ".webp"}
SEC_CLASSES = ("ltx_section", "ltx_subsection", "ltx_subsubsection", "ltx_appendix",
               "ltx_paragraph", "ltx_subparagraph")
LEVEL = {"ltx_section": 1, "ltx_appendix": 1, "ltx_subsection": 2, "ltx_subsubsection": 3,
         "ltx_paragraph": 4, "ltx_subparagraph": 5}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- HTML text extraction


def node_text(node, refs_label: dict) -> str:
    """Readable text: math as $alttext$, citations as [@key label], figure refs kept."""
    parts = []

    def walk(n):
        if isinstance(n, NavigableString):
            parts.append(str(n))
            return
        if not isinstance(n, Tag):
            return
        cls = n.get("class") or []
        if n.name == "math":
            alt = n.get("alttext") or n.get_text(" ")
            parts.append(f"${alt.strip()}$" if n.get("display") != "block" else f"\n$${alt.strip()}$$\n")
            return
        if "ltx_equation" in cls or "ltx_equationgroup" in cls:
            maths = [m.get("alttext", "") for m in n.find_all("math")]
            if maths:
                parts.append("\n$$" + " ".join(x.strip() for x in maths) + "$$\n")
            return
        if n.name == "cite":
            keys = [a["href"][1:] for a in n.find_all("a", href=True) if a["href"].startswith("#bib.")]
            if keys:
                parts.append(" ".join(f"[@{k} {refs_label.get(k, '')}]".replace(" ]", "]") for k in keys))
                return
        if n.name == "a" and (n.get("href") or "").startswith("#bib."):
            k = n["href"][1:]
            parts.append(f"[@{k} {refs_label.get(k, '')}]".replace(" ]", "]"))
            return
        if n.name in ("figure",) or "ltx_note_outer" in cls:
            return  # figures are listed separately; footnotes are noise in the reading order
        for c in n.children:
            walk(c)

    walk(node)
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def nearest_sec(node):
    return node.find_parent(lambda t: any(c in SEC_CLASSES for c in (t.get("class") or [])))


def numbered_ancestor(node) -> tuple[str, str]:
    """(number, top-level number) of the nearest section around `node` that has a number."""
    if node is None:
        return "", ""
    cur = node if node is not None and any(c in SEC_CLASSES for c in (node.get("class") or [])) else nearest_sec(node)
    while cur is not None:
        num = heading_of(cur)[0]
        if num:
            return num, num.split(".")[0]
        cur = nearest_sec(cur)
    return "", ""


def heading_of(sec: Tag):
    h = sec.find(re.compile(r"^h[1-6]$"), class_="ltx_title", recursive=False)
    if h is None:
        h = sec.find(re.compile(r"^h[1-6]$"), recursive=False)
    if h is None:
        return "", ""
    tag = h.find(class_="ltx_tag")
    number = tag.get_text(" ", strip=True) if tag else ""
    if tag:
        tag.extract()
    title = " ".join(h.get_text(" ", strip=True).split())
    if tag:
        h.insert(0, tag)
    number = re.sub(r"^(Appendix|Section)\s+", "", number).rstrip(".").strip()
    if not number:  # some builds print the number inline: "1  Introduction", "A.2  Details"
        in_app = "ltx_appendix" in (sec.get("class") or []) or sec.find_parent(class_="ltx_appendix") is not None
        m = re.match(r"^(?:Appendix\s+)?(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\.?\s+(\S.*)$", title)
        if m and (m.group(1)[0].isdigit() or in_app):
            number, title = m.group(1), m.group(2)
    return number, title.rstrip(".")


def parse_refs(soup) -> tuple[dict, dict]:
    refs, labels = {}, {}
    for li in soup.select("li.ltx_bibitem"):
        key = li.get("id")
        if not key:
            continue
        tag = li.find(class_="ltx_tag_bibitem")
        label = " ".join(tag.get_text(" ", strip=True).split()) if tag else ""
        label = label.strip("[]")
        title_el = li.find(class_="ltx_bib_title")
        blocks = [b.get_text(" ", strip=True) for b in li.find_all(class_="ltx_bibblock")
                  if "ltx_bib_cited" not in (b.get("class") or [])]
        full = " ".join(" ".join(blocks).split())
        title = " ".join(title_el.get_text(" ", strip=True).split()) if title_el else ""
        if not title and len(blocks) >= 2:
            title = " ".join(blocks[1].split()).rstrip(".")
        urls = [a["href"] for a in li.find_all("a", href=True) if a["href"].startswith("http")]
        m = re.search(r"arXiv[:\s]*(\d{4}\.\d{4,5})", full, re.I) or next(
            (re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", u) for u in urls
             if re.search(r"arxiv\.org/(?:abs|pdf)/\d{4}\.\d{4,5}", u)), None)
        arxiv = m.group(1) if m else None
        refs[key] = {"key": key, "label": label, "title": title, "text": full[:400],
                     "arxiv_id": arxiv,
                     "url": f"https://arxiv.org/abs/{arxiv}" if arxiv else (urls[0] if urls else None),
                     "url_source": "bibliography" if (arxiv or urls) else None, "cited_in": []}
        labels[key] = label
    return refs, labels


def parse_html(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    base = soup.find("base", href=True)
    base_url = urljoin(base_url, base["href"]) if base else base_url
    # arXiv pages live at .../html/<id>v1 (no slash) while image src is "<id>v1/x.png"; other
    # builds use .../html/<id>v1/ with src "x.png". Keep both resolutions and let the download
    # step keep whichever returns an image.
    bases = [base_url.rstrip("/"), base_url.rstrip("/") + "/"]
    title_el = soup.find(class_="ltx_title_document")
    title = " ".join(title_el.get_text(" ", strip=True).split()) if title_el else ""
    refs, labels = parse_refs(soup)

    abstract_el = soup.find(class_="ltx_abstract")
    abstract = ""
    if abstract_el:
        abstract = "\n\n".join(node_text(p, labels) for p in abstract_el.find_all(class_="ltx_p"))

    authors_el = soup.find(class_="ltx_authors")
    authors_text = " ".join(authors_el.get_text(" ", strip=True).split()) if authors_el else ""

    sections, figures = [], []
    sec_nodes = [s for s in soup.find_all(["section", "div"])
                 if any(c in SEC_CLASSES for c in (s.get("class") or []))
                 and not s.find_parent(class_="ltx_bibliography")]
    for s in sec_nodes:
        cls = next(c for c in (s.get("class") or []) if c in SEC_CLASSES)
        number, stitle = heading_of(s)
        in_app = s.find_parent(class_="ltx_appendix") is not None or cls == "ltx_appendix"
        paras = []
        # paragraphs of this section only; a paragraph nested in another one (list items) is part of it
        own = [p for p in s.find_all(class_="ltx_para") if nearest_sec(p) is s
               and p.find_parent(class_="ltx_para") is None]
        for i, para in enumerate(own, 1):
            txt = node_text(para, labels)
            if txt:
                paras.append({"id": f"S{number or s.get('id', '?')}.p{i}", "text": txt})
        parent = numbered_ancestor(nearest_sec(s))[0] if not number else ""
        sections.append({"html_id": s.get("id"), "number": number, "parent": parent, "title": stitle,
                         "level": LEVEL[cls], "in_appendix": in_app, "paragraphs": paras})
        for a in s.find_all("a", href=True):
            if a["href"].startswith("#bib.") and nearest_sec(a) is s:
                k = a["href"][1:]
                if k in refs and (number or stitle) not in refs[k]["cited_in"]:
                    refs[k]["cited_in"].append(number or stitle)

    # figures and tables: outermost <figure> whose caption carries the "Figure N" / "Table N" tag
    for fig in soup.find_all("figure"):
        cap = fig.find("figcaption", recursive=False) or fig.find("figcaption")
        if cap is None or (fig.find_parent("figure") is not None and fig.find_parent("figure").find("figcaption")):
            continue
        tag = cap.find(class_=re.compile(r"ltx_tag_(figure|table)"))
        tag_text = tag.get_text(" ", strip=True) if tag else ""
        m = re.match(r"(Figure|Fig\.|Table)\s*([A-Z]?\d+[a-z]?)", tag_text)
        if not m:
            continue
        kind = "table" if m.group(1) == "Table" else "figure"
        number = m.group(2)
        caption = " ".join(node_text(cap, labels).split())
        caption = re.sub(r"^(Figure|Fig\.|Table)\s*[A-Z]?\d+[a-z]?\s*[:.]?\s*", "", caption)
        imgs = []
        for img in fig.find_all(["img", "object"]):
            src = img.get("src") or img.get("data")
            if not src or src.startswith("data:"):
                continue
            imgs.append(list(dict.fromkeys(urljoin(b, src) for b in bases)))
        sec = nearest_sec(fig)
        sec_title = heading_of(sec)[1] if sec else ""
        sec_num, top_num = numbered_ancestor(fig)
        in_app = fig.find_parent(class_="ltx_appendix") is not None
        table_html = None
        if kind == "table":
            t = fig.find("table")
            table_html = str(t) if t is not None else None
        figures.append({"kind": kind, "number": number, "html_id": fig.get("id"), "caption": caption,
                        "section": sec_num, "section_title": sec_title, "top_section": top_num,
                        "in_appendix": in_app, "image_urls": imgs, "table_html": table_html})
    for s in sections:  # figure mentions in the text, for placement checks
        for p in s["paragraphs"]:
            p["mentions"] = sorted(set(re.findall(r"(?:Figure|Fig\.)\s*~?(\d+)", p["text"])))
    return {"title": title, "abstract": abstract, "authors_text": authors_text,
            "sections": sections, "figures": figures, "refs": refs}


# ---------------------------------------------------------------- PDF


def pdf_pages(pdf: Path, sections: list, figures: list) -> int:
    """Fill section["page"] and figure["page"] (1-based) by searching the PDF text."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # older PyMuPDF
        except ImportError:
            log("PyMuPDF not installed: no page numbers")
            return 0
    doc = pymupdf.open(pdf)
    texts = [" ".join(page.get_text().split()).lower() for page in doc]
    # headings start a line; the same words inside a sentence ("see Section 3 method") must not count
    lines = [[" ".join(ln.split()).lower() for ln in page.get_text().splitlines() if ln.strip()] for page in doc]

    def starts(i, needle):
        pg = lines[i]
        for k, ln in enumerate(pg):
            joined = (ln + " " + pg[k + 1]) if k + 1 < len(pg) else ln  # number and title may be split
            if ln.startswith(needle) or joined.startswith(needle):
                return True
        return False

    cursor = 0
    for s in sections:
        needle = " ".join(s["title"].split()).lower()[:40]
        cands = [f"{s['number']} {needle}".strip(), f"{s['number']}. {needle}"] if s["number"] else [needle]
        hit = None
        for i in range(cursor, len(lines)):
            if any(starts(i, c) for c in cands):
                hit = i
                break
        if hit is not None:
            s["page"], cursor = hit + 1, hit
    for f in figures:
        # a caption is "Figure 3:" / "Figure 3." / "Figure 3 |" (the separator may sit on the next line);
        # "see Figure 3)" in the text is not a caption
        word = r"table" if f["kind"] == "table" else r"(?:figure|fig\.)"
        num = re.escape(f["number"].lower())
        inline = re.compile(rf"\b{word}\s*{num}\s*[:.|]")
        alone = re.compile(rf"^{word}\s*{num}\s*([:.|].*)?$")  # "Figure 1" on its own line
        for i, t in enumerate(texts):
            if inline.search(t) or any(alone.match(ln) for ln in lines[i]):
                f["page"] = i + 1
                break
    return len(texts)


def pdf_lines(doc):
    """(page, text, size, bold) per text line, in reading order per page."""
    rows = []
    for pno, page in enumerate(doc, 1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [sp for sp in line["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                text = " ".join("".join(sp["text"] for sp in spans).split())
                size = max(sp["size"] for sp in spans)
                bold = all(("Bold" in sp["font"] or sp["flags"] & 16) for sp in spans)
                rows.append((pno, text, round(size, 1), bold))
    return rows


HEAD_RE = re.compile(r"^((?:[1-9]\d?|[A-H])(?:\.\d+){0,2})\.?\s+([A-Z][^.!?]{1,90})$")


def pdf_extract(pdf: Path, out_dir: Path) -> dict:
    """Fallback without HTML: outline from the PDF TOC or from numbered headings that are bold or
    larger than body text, paragraphs from the lines between them, figures cropped above captions."""
    import statistics
    import pymupdf
    doc = pymupdf.open(pdf)
    rows = pdf_lines(doc)
    body_size = statistics.median([r[2] for r in rows]) if rows else 10
    toc = {(t.strip().lower()[:40]): (lvl, pno) for lvl, t, pno in doc.get_toc()}
    sections, cur, app, para = [], None, False, []

    def flush():
        if cur is not None and para:
            txt = " ".join(para)
            cur["paragraphs"].append({"id": f"S{cur['number']}.p{len(cur['paragraphs']) + 1}", "text": txt,
                                      "mentions": sorted(set(re.findall(r"(?:Figure|Fig\.)\s*(\d+)", txt)))})
        para.clear()

    for pno, text, size, bold in rows:
        m = HEAD_RE.match(text)
        is_head = bool(m) and (bold or size > body_size + 0.5 or text.lower()[:40] in toc)
        if m and m.group(1)[0].isalpha() and not app:
            is_head = is_head and bool(re.match(r"^[A-H]$", m.group(1)))  # appendix letters only at top level
        if is_head:
            flush()
            num, title = m.group(1), m.group(2).strip()
            if re.match(r"^[A-H]", num):
                app = True
            cur = {"html_id": None, "number": num, "title": title, "level": num.count(".") + 1,
                   "in_appendix": app, "page": pno, "paragraphs": []}
            sections.append(cur)
            continue
        if re.match(r"^(references|bibliography)$", text, re.I) and (bold or size > body_size + 0.5):
            flush()
            cur = None
            continue
        if re.match(r"^(appendix|appendices|supplementary material)", text, re.I) and (bold or size > body_size + 0.5):
            app = True
        if cur is None:
            continue
        para.append(text)
        if text.endswith((".", ":")) and len(text) < 0.7 * 90:  # a short line ending a sentence closes a paragraph
            flush()
    flush()
    figures = crop_pdf_figures(doc, out_dir)
    for f in figures:  # the section that first mentions the figure, else the section on its page
        first = next((s for s in sections for p in s["paragraphs"] if f["number"] in p["mentions"]), None)
        on_page = [first] if first else [s for s in sections if s.get("page", 0) <= f["page"]]
        if on_page:
            f["section"] = on_page[-1]["number"]
            f["top_section"] = on_page[-1]["number"].split(".")[0]
            f["in_appendix"] = on_page[-1]["in_appendix"]
    return {"sections": sections, "figures": figures}


def crop_pdf_figures(doc, out_dir: Path, only: set | None = None) -> list:
    """Crop each 'Figure N:' region: the union of images/drawings above the caption, rendered at 2x."""
    import pymupdf
    figs, seen = [], set()
    out_dir.mkdir(parents=True, exist_ok=True)
    for pno, page in enumerate(doc, 1):
        blocks = page.get_text("blocks")
        visuals = [pymupdf.Rect(r) for r in
                   [x["bbox"] for x in page.get_image_info()] + [d["rect"] for d in page.get_drawings()]]
        for b in blocks:
            # "Figure 3: ..." or "Figure 3" alone on the first line of the caption block
            m = re.match(r"^\s*(Figure|Fig\.)\s*(\d+)\s*(?:[:.|]|\n)\s*(.*)", b[4], re.S)
            if not m or m.group(2) in seen or (only is not None and m.group(2) not in only):
                continue
            cap = pymupdf.Rect(b[:4])
            above = [v for v in visuals if v.y1 <= cap.y0 + 2 and v.y0 >= cap.y0 - page.rect.height * 0.75
                     and v.x1 > cap.x0 - 20 and v.x0 < cap.x1 + 20 and v.width > 4 and v.height > 4]
            # a frame around a long paragraph (e.g. an abstract box) is not part of a figure
            long_text = [pymupdf.Rect(tb[:4]) for tb in blocks if len(tb[4].strip()) > 200]
            above = [v for v in above if not any(v.contains(t) for t in long_text)]
            if not above:
                continue
            # grow upward from the caption; stop at a body paragraph between two drawings
            above.sort(key=lambda v: -v.y1)
            region = pymupdf.Rect(above[0])
            for v in above[1:]:
                gap_top, gap_bottom = v.y1, region.y0
                if any(t.y0 >= gap_top - 2 and t.y1 <= gap_bottom + 2 and t.x1 > region.x0 and t.x0 < region.x1
                       for t in long_text):
                    break
                if gap_bottom - gap_top > 18 and region.height > 120:  # clear white band above a full figure
                    break
                region |= v
            for tb in blocks:  # short labels just above or inside the drawing (panel titles, axis names)
                r = pymupdf.Rect(tb[:4])
                if (len(tb[4].strip()) < 60 and r.y1 <= cap.y0 and r.y0 >= region.y0 - 30
                        and r.x1 > region.x0 and r.x0 < region.x1):
                    region |= r
            region = pymupdf.Rect(region.x0 - 4, region.y0 - 4, region.x1 + 4, min(region.y1 + 4, cap.y0 - 1))
            region &= page.rect
            if region.height < 30:
                continue
            name = f"fig_{m.group(2)}_1.png"
            page.get_pixmap(clip=region, dpi=200).save(out_dir / name)
            seen.add(m.group(2))
            figs.append({"kind": "figure", "number": m.group(2), "html_id": None,
                         "caption": " ".join(m.group(3).split())[:600], "section": "", "section_title": "",
                         "top_section": "", "in_appendix": False, "page": pno, "image_urls": [],
                         "files": [f"figures/{name}"], "png_files": [f"figures/{name}"], "table_html": None})
    return sorted(figs, key=lambda f: int(f["number"]))


# ---------------------------------------------------------------- images


def svg_to_png(svg: Path) -> Path | None:
    import shutil
    import subprocess
    png = svg.with_suffix(".png")
    exe = shutil.which("rsvg-convert")
    if exe:
        r = subprocess.run([exe, "-z", "2", "-b", "white", "-o", str(png), str(svg)], capture_output=True)
        if r.returncode == 0 and png.exists():
            return png
    try:  # PyMuPDF renders SVG too
        import pymupdf
        doc = pymupdf.open(svg)
        doc[0].get_pixmap(dpi=200, alpha=False).save(png)
        return png
    except Exception as e:
        log(f"  SVG to PNG failed for {svg.name}: {e}")
        return None


def download_images(figs: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in figs:
        if f["kind"] != "figure" or f.get("files"):
            continue
        files, ok_urls = [], []
        for k, cands in enumerate(f["image_urls"][:12], 1):
            for url in ([cands] if isinstance(cands, str) else cands):
                try:
                    r = http_get(url, timeout=60, retries=2, backoff=3)
                except RuntimeError as e:
                    log(f"  image failed {url}: {e}")
                    continue
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
                if r.status_code != 200 or ctype not in IMG_TYPES:
                    continue
                name = f"fig_{f['number']}_{k}{IMG_TYPES[ctype]}"
                (out_dir / name).write_bytes(r.content)
                if name.endswith(".svg"):  # raster copy for viewers that do not show SVG
                    png = svg_to_png(out_dir / name)
                    if png:
                        f.setdefault("png_files", []).append(f"figures/{png.name}")
                files.append(f"figures/{name}")
                ok_urls.append(url)
                break
            else:
                log(f"  no image at any of {cands}")
        f["files"], f["image_urls"] = files, ok_urls
        f["png_files"] = f.get("png_files") or [x for x in files if not x.endswith(".svg")]


# ---------------------------------------------------------------- content.md


def table_text(table_html: str, max_rows: int = 60) -> str:
    """A pipe table of the cell texts (math as $..$), so results can be transcribed exactly."""
    soup = BeautifulSoup(table_html, "html.parser")
    rows, carry = [], {}  # carry: column -> (text, rows left) for rowspan cells
    for tr in soup.find_all("tr")[:max_rows]:
        cells, col = [], 0
        tds = list(tr.find_all(["td", "th"]))
        while tds or col in carry:
            if col in carry:
                text, left = carry[col]
                cells.append(text)
                carry[col] = (text, left - 1)
                if left - 1 <= 0:
                    del carry[col]
                col += 1
                continue
            td = tds.pop(0)
            text = " ".join(node_text(td, {}).split()).replace("|", "/")
            span = int(td.get("rowspan", 1) or 1)
            for k in range(int(td.get("colspan", 1) or 1)):
                cells.append(text if k == 0 else "")
                if span > 1:
                    carry[col] = (text, span - 1)
                col += 1
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def write_content(pdir: Path, meta: dict, sections: list, figures: list):
    lines = [f"# {meta['title']}", "", "## Abstract", "", meta.get("abstract", ""), ""]
    fig_by_sec, loose = {}, []
    for f in figures:
        key = f.get("section") or f.get("top_section")
        (fig_by_sec.setdefault(key, []) if key else loose).append(f)
    for f in loose:  # figures before the first section (e.g. a teaser): once, after the abstract
        kind = "Table" if f["kind"] == "table" else "Figure"
        lines += [f"[[{kind} {f['number']}]] {f['caption']}", ""]
    app_started = False
    for s in sections:
        if s["in_appendix"] and not app_started:
            lines += ["", "# APPENDIX", ""]
            app_started = True
        hashes = "#" * min(6, s["level"] + 1)
        page = f" (pdf p.{s['page']})" if s.get("page") else ""
        lines += [f"{hashes} {s['number']} {s['title']}{page}".replace("  ", " "), ""]
        for p in s["paragraphs"]:
            lines += [f"[{p['id']}] {p['text']}", ""]
        for f in (fig_by_sec.get(s["number"], []) if s["number"] else []):
            kind = "Table" if f["kind"] == "table" else "Figure"
            lines += [f"[[{kind} {f['number']}]] {f['caption']}", ""]
            if f.get("table_html"):
                lines += [table_text(f["table_html"]), ""]
    (pdir / "content.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- main


def fetch_html(meta: dict):
    versions = [meta.get("version") or "v1"]
    n = int(re.sub(r"\D", "", versions[0]) or 1)
    tried = [f"v{i}" for i in range(n, 0, -1)] + [""]
    want = title_tokens(meta["title"])
    for v in tried:
        url = f"https://arxiv.org/html/{meta['arxiv_id']}{v}"
        try:
            r = http_get(url, timeout=90, retries=2)
        except RuntimeError:
            continue
        if r.status_code != 200 or "ltx_document" not in r.text:
            continue
        r.encoding = "utf-8"
        parsed = parse_html(r.text, r.url)
        got = title_tokens(parsed["title"])
        if got:
            same = len(want & got) / max(1, len(want)) >= 0.7
        else:  # the title is an image (logo): compare the abstracts instead
            a, b = title_tokens(meta.get("abstract", "")), title_tokens(parsed["abstract"])
            same = bool(a) and len(a & b) / max(1, len(a)) >= 0.6
        if want and not same:
            log(f"HTML does not match the arXiv record at {url}: title {parsed['title']!r}")
            continue
        return parsed, r.url
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--pdf")
    ap.add_argument("--record")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = load_config()

    if args.record:
        meta = read_json(Path(args.record))
        if not meta or not meta.get("id") or not meta.get("title"):
            raise SystemExit("record needs at least id and title")
        meta.setdefault("arxiv_id", None)
        meta.setdefault("links", {})
    elif args.id:
        import resolve
        meta = resolve.by_id(args.id)
        if meta is None:
            raise SystemExit(f"arXiv id {args.id} not found")
    else:
        raise SystemExit(__doc__)

    pdir = paper_dir(cfg, meta["id"])
    if (pdir / "outline.json").exists() and not args.force:
        out({"dir": str(pdir), "cached": True, **{k: meta[k] for k in ("id", "title")}})
        return
    pdir.mkdir(parents=True, exist_ok=True)
    old_meta = read_json(pdir / "meta.json", {}) or {}
    for k in ("venue", "venue_evidence", "notion_url"):  # results of later steps survive a re-fetch
        if old_meta.get(k) and not meta.get(k):
            meta[k] = old_meta[k]

    pdf = pdir / "paper.pdf"
    if args.pdf:
        pdf.write_bytes(Path(args.pdf).read_bytes())
    elif meta.get("links", {}).get("pdf"):
        try:
            r = http_get(meta["links"]["pdf"], timeout=120, retries=2)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                pdf.write_bytes(r.content)
        except RuntimeError as e:
            log(f"PDF download failed: {e}")

    parsed, html_url = (fetch_html(meta) if meta.get("arxiv_id") else (None, None))
    if parsed:
        source = "html"
        sections, figures, refs = parsed["sections"], parsed["figures"], parsed["refs"]
        meta["abstract"] = meta.get("abstract") or parsed["abstract"]
        meta["authors_text"] = parsed["authors_text"]
        meta["links"]["html"] = html_url
        download_images(figures, pdir / "figures")
        n_pages = pdf_pages(pdf, sections, figures) if pdf.exists() else 0
        # main figures the HTML could not render (e.g. TikZ drawings): crop them from the PDF
        missing = {f["number"] for f in figures if f["kind"] == "figure" and not f["in_appendix"] and not f.get("files")}
        if missing and pdf.exists():
            import pymupdf
            for crop in crop_pdf_figures(pymupdf.open(pdf), pdir / "figures", only=missing):
                f = next(x for x in figures if x["kind"] == "figure" and x["number"] == crop["number"])
                f.update({"files": crop["files"], "png_files": crop["png_files"], "page": f.get("page") or crop["page"],
                          "source": "pdf-crop"})
                log(f"  Figure {crop['number']}: cropped from the PDF (no image in the HTML)")
    elif pdf.exists():
        source = "pdf"
        got = pdf_extract(pdf, pdir / "figures")
        sections, figures, refs = got["sections"], got["figures"], {}
        import pymupdf
        n_pages = len(pymupdf.open(pdf))
    else:
        raise SystemExit("neither arXiv HTML nor a PDF could be read; stop and report")

    for s in sections:
        s["chars"] = sum(len(p["text"]) for p in s["paragraphs"])
    main_figs = [f for f in figures if f["kind"] == "figure" and not f["in_appendix"]]
    meta.update({"source": source, "pdf_pages": n_pages, "fetched": __import__("datetime").date.today().isoformat()})
    write_json(pdir / "meta.json", meta)
    write_json(pdir / "outline.json", {"sections": sections})
    write_json(pdir / "figures.json", {"figures": figures})
    old_refs = (read_json(pdir / "refs.json", {}) or {}).get("refs", {})
    for k, r in refs.items():  # keep links that refs.py already found
        o = old_refs.get(k)
        if o and o.get("url_source") == "arxiv-search" and not r.get("arxiv_id") and o.get("title") == r.get("title"):
            r.update({x: o[x] for x in ("arxiv_id", "url", "url_source")})
    write_json(pdir / "refs.json", {"refs": refs})
    write_content(pdir, meta, sections, figures)
    out({"dir": str(pdir), "id": meta["id"], "title": meta["title"], "source": source,
         "sections": sum(1 for s in sections if not s["in_appendix"]),
         "appendix_sections": sum(1 for s in sections if s["in_appendix"]),
         "main_figures": len(main_figs),
         "main_figures_with_images": sum(1 for f in main_figs if f.get("files")),
         "tables": sum(1 for f in figures if f["kind"] == "table"),
         "refs": len(refs), "refs_with_url": sum(1 for r in refs.values() if r["url"]),
         "pdf_pages": n_pages})


if __name__ == "__main__":
    main()
