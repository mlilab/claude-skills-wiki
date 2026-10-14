#!/usr/bin/env python3
"""Turn a title, arXiv id or arXiv URL into one verified arXiv record, and check for duplicates.

usage: resolve.py "<title | arXiv id | arxiv.org URL>"

Prints JSON: {"id", "arxiv_id", "title", "authors", "abstract", "submitted", "comments",
"links", "duplicate"}. A title is searched with the arXiv API (exact-title match first, then the
closest title with a token overlap of at least 0.85). An id or URL is fetched directly. The
"duplicate" field is the local entry with the same arXiv id or title, if the paper was already
written up; with the Notion backend also search the database before creating a row.
Exit code 2 means nothing matched; report it instead of guessing.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

from common import (http_get, load_config, norm_title, out, parse_arxiv_id, read_json,
                    title_tokens)

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
API = "https://export.arxiv.org/api/query"


def _entry(e) -> dict:
    aid = e.findtext(f"{ATOM}id").rsplit("/abs/", 1)[-1]
    base = parse_arxiv_id(aid) or aid
    title = " ".join(e.findtext(f"{ATOM}title").split())
    links = {"abs": f"https://arxiv.org/abs/{base}", "pdf": f"https://arxiv.org/pdf/{base}",
             "html": f"https://arxiv.org/html/{base}"}
    return {
        "id": base, "arxiv_id": base, "version": aid[len(base):] or "v1", "title": title,
        "authors": [a.findtext(f"{ATOM}name") for a in e.findall(f"{ATOM}author")],
        "abstract": " ".join((e.findtext(f"{ATOM}summary") or "").split()),
        # <published> is the first version's date: the paper's original submission date
        "submitted": (e.findtext(f"{ATOM}published") or "")[:10],
        "updated": (e.findtext(f"{ATOM}updated") or "")[:10],
        "comments": " ".join((e.findtext(f"{ARXIV}comment") or "").split()),
        "journal_ref": " ".join((e.findtext(f"{ARXIV}journal_ref") or "").split()),
        "categories": [c.get("term") for c in e.findall(f"{ATOM}category")],
        "links": links,
    }


def by_id(aid: str) -> dict | None:
    r = http_get(API, params={"id_list": aid, "max_results": 1}, timeout=60)
    r.raise_for_status()
    entries = ET.fromstring(r.content).findall(f"{ATOM}entry")
    if not entries or entries[0].findtext(f"{ATOM}title") in (None, "Error"):
        return None
    return _entry(entries[0])


def by_title(title: str) -> dict | None:
    words = [w for w in title.replace('"', " ").split() if len(w) > 1]
    queries = [f'ti:"{title.strip()}"', " AND ".join(f"ti:{w}" for w in words[:12])]
    want, want_tok = norm_title(title), title_tokens(title)
    best, best_score = None, 0.0
    for q in queries:
        r = http_get(API, params={"search_query": q, "max_results": 10}, timeout=60)
        r.raise_for_status()
        for e in ET.fromstring(r.content).findall(f"{ATOM}entry"):
            rec = _entry(e)
            if norm_title(rec["title"]) == want:
                return rec
            tok = title_tokens(rec["title"])
            score = len(want_tok & tok) / max(1, len(want_tok | tok))
            if score > best_score:
                best, best_score = rec, score
    return best if best_score >= 0.85 else None


def find_duplicate(cfg, rec: dict) -> dict | None:
    index = read_json(cfg["data_dir"] / "index.json", {"papers": []})
    for p in index.get("papers", []):
        if p.get("arxiv_id") == rec["arxiv_id"] or norm_title(p.get("title")) == norm_title(rec["title"]):
            return {"id": p["id"], "title": p["title"], "page": p.get("page"),
                    "notion_url": p.get("notion_url")}
    return None


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    arg = sys.argv[1]
    cfg = load_config()
    aid = parse_arxiv_id(arg)
    rec = by_id(aid) if aid else by_title(arg)
    if rec is None:
        out({"error": f"no arXiv paper matches {arg!r}"})
        sys.exit(2)
    if not aid and norm_title(rec["title"]) != norm_title(arg):
        rec["note"] = f"closest title match for {arg!r}; confirm it is the intended paper"
    rec["duplicate"] = find_duplicate(cfg, rec)
    out(rec)


if __name__ == "__main__":
    main()
