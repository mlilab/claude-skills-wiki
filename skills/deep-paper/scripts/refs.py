#!/usr/bin/env python3
"""Find arXiv links for bibliography entries that do not name one, so citations can be linked.

usage: refs.py --id PAPER_ID [--all] [--max N]

Only entries cited in the main body are looked up (--all: every entry). Each title is searched
with the arXiv API (exact normalized-title match, or token overlap >= 0.9 with the same first
author surname when one is given). Matches are stored in refs.json with url_source "arxiv-search";
entries that still have no URL keep url null and must not be linked. Results are cached in
~/.cache/deep-paper/ref_titles.json. The arXiv API asks for >= 3 s between calls, so 40 lookups
take about two minutes; run it in the background while reading content.md.
"""
from __future__ import annotations

import argparse
import re
import time
import xml.etree.ElementTree as ET

from common import (cache_dir, http_get, load_config, norm_title, out, paper_dir, read_json,
                    title_tokens, write_json)

ATOM = "{http://www.w3.org/2005/Atom}"


def search(title: str, first_author: str | None) -> str | None:
    title = title.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    q = re.sub(r"[^\w\s-]", " ", title)
    q = " ".join(q.split()[:16])
    if len(q) < 8:
        return None
    want, want_tok = norm_title(title), title_tokens(title)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title.replace("'", "")) if len(w) > 3][:8]
    queries = [f'ti:"{q}"'] + ([" AND ".join(f"ti:{w}" for w in words)] if len(words) >= 2 else [])
    for query in queries:
        r = http_get("https://export.arxiv.org/api/query",
                     params={"search_query": query, "max_results": 5}, timeout=60, retries=3)
        if r.status_code != 200:
            continue
        hit = best_entry(r.content, want, want_tok, first_author)
        if hit:
            return hit
        time.sleep(3.1)
    return None


def best_entry(content: bytes, want: str, want_tok: set, first_author: str | None) -> str | None:
    for e in ET.fromstring(content).findall(f"{ATOM}entry"):
        t = " ".join((e.findtext(f"{ATOM}title") or "").split())
        aid = (e.findtext(f"{ATOM}id") or "").rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        authors = " ".join(a.findtext(f"{ATOM}name") or "" for a in e.findall(f"{ATOM}author")).lower()
        if norm_title(t) == want:
            return aid
        tok = title_tokens(t)
        overlap = len(want_tok & tok) / max(1, len(want_tok | tok))
        if overlap >= 0.9 and (not first_author or first_author.lower() in authors):
            return aid
    return None


def first_surname(ref: dict) -> str | None:
    m = re.match(r"\s*([A-Z][A-Za-z'\-]+)", ref.get("label") or "")
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max", type=int, default=80)
    args = ap.parse_args()
    cfg = load_config()
    pdir = paper_dir(cfg, args.id)
    data = read_json(pdir / "refs.json", {"refs": {}})
    outline = read_json(pdir / "outline.json", {"sections": []})
    main_secs = {s["number"] or s["title"] for s in outline["sections"] if not s["in_appendix"]}
    cache_path = cache_dir() / "ref_titles.json"
    cache = read_json(cache_path, {})
    todo = [r for r in data["refs"].values()
            if not r.get("arxiv_id") and r.get("title") and len(r["title"]) > 12
            and (args.all or set(r.get("cited_in") or []) & main_secs)]
    found, looked = 0, 0
    for ref in todo[:args.max]:
        key = norm_title(ref["title"])
        if key in cache:
            aid = cache[key]
        else:
            try:
                aid = search(ref["title"], first_surname(ref))
            except RuntimeError:
                aid = None
            cache[key] = aid
            looked += 1
            time.sleep(3.1)
        if aid:
            ref["arxiv_id"], ref["url"], ref["url_source"] = aid, f"https://arxiv.org/abs/{aid}", "arxiv-search"
            found += 1
    write_json(pdir / "refs.json", data)
    write_json(cache_path, cache)
    refs = data["refs"].values()
    out({"searched": len(todo[:args.max]), "api_calls": looked, "found": found,
         "refs": len(data["refs"]), "with_url": sum(1 for r in refs if r.get("url")),
         "with_arxiv": sum(1 for r in refs if r.get("arxiv_id"))})


if __name__ == "__main__":
    main()
