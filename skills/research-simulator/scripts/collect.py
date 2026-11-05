#!/usr/bin/env python3
"""Gather a candidate pool of real papers from OpenAlex.

Hops are NOT citation hops: the simulator computes them from similarity (hop 1 = papers closest to the
research, hop k+1 = papers closest to hop k). So the pool must hold the closest work AND the neighbours of
that closest work. Build it in rounds:

  round 1  search the research question            -> candidates for hop 1
  round 2  for the best hop-1 candidates, their related works / references / citers, plus searches on
           their own topics                         -> candidates for hop 2
  round n  repeat from the previous round's best papers

Direct mode (shell can reach api.openalex.org):
  collect.py fetch -q "tabpfn context compression" -q "streaming sparse gaussian process" --rounds 2 -o pool.json

Web-tool mode (shell blocked; fetch the printed URLs with the agent's web tool, one at a time):
  collect.py urls search -q "..."            light search URL (ids, titles, years, venues, citations)
  collect.py urls abstracts --ids W1,W2,...   abstract URLs, 5 ids per URL
  collect.py urls neighbours --ids W1,W2      related-works + citing URLs for expanding a round
  collect.py merge found1.json found2.json -o pool.json   merge whatever was saved into one pool

Pool record: {id, title, year, venue, doi, url, cited_by, abstract} (+ facets added later).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org"
LIGHT = "id,doi,display_name,publication_year,cited_by_count,primary_location"
FULL = LIGHT + ",abstract_inverted_index,related_works,referenced_works"


def short_id(x):
    m = re.search(r"(W\d+)", str(x or ""), re.I)
    return m.group(1).upper() if m else str(x or "").strip()


def abstract_from_index(inv):
    if not inv:
        return ""
    return " ".join(w for _, w in sorted((i, w) for w, idxs in inv.items() for i in idxs))


def norm_record(w):
    if not isinstance(w, dict) or not w.get("id") or not (w.get("title") or w.get("display_name")):
        return None
    loc = w.get("primary_location") or {}
    src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
    doi = str(w.get("doi") or "").replace("https://doi.org/", "")
    rid = short_id(w["id"])
    keep = {k: w[k] for k in ("problem", "method", "problem_tags", "method_tags") if w.get(k)}
    return {"id": rid, "title": str(w.get("title") or w.get("display_name")).strip(),
            "year": w.get("year") or w.get("publication_year"), "venue": w.get("venue") or src.get("display_name") or "",
            "doi": doi, "url": w.get("url") or (f"https://doi.org/{doi}" if doi else f"https://openalex.org/{rid}"),
            "cited_by": w.get("cited_by") if w.get("cited_by") is not None else w.get("cited_by_count"),
            "abstract": w.get("abstract") or abstract_from_index(w.get("abstract_inverted_index")), **keep}


def norm_title(t):
    return re.sub(r"[\W_]+", " ", str(t or "").lower()).strip()


def merge(records):
    """Merge by id, then drop duplicate titles (arXiv vs proceedings), keeping the most cited."""
    by = {}
    for w in records:
        r = norm_record(w)
        if not r:
            continue
        o = by.setdefault(r["id"], r)
        if o is not r:
            for k, v in r.items():
                if v and not o.get(k):
                    o[k] = v
    best = {}
    for r in by.values():
        t = norm_title(r["title"])
        if t not in best or (r.get("cited_by") or 0) > (best[t].get("cited_by") or 0):
            best[t] = r
    return sorted(best.values(), key=lambda r: r["id"])


# ------------------------------------------------------------------ direct HTTP

def get(path, **params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-simulator/2"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                time.sleep(0.12)
                return json.load(resp)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise RuntimeError(f"OpenAlex request failed ({e}). If the shell is blocked, use `collect.py urls`.")
            time.sleep(1.5 * (attempt + 1))


def works(ids, select=FULL):
    out = []
    ids = [short_id(i) for i in ids]
    for i in range(0, len(ids), 50):
        out += get("/works", filter="openalex:" + "|".join(ids[i:i + 50]), **{"per-page": 50, "select": select})["results"]
    return out


def cmd_fetch(a):
    raw = []
    for q in a.query:
        raw += get("/works", search=q, **{"per-page": a.per_query, "select": FULL})["results"]
    frontier = sorted(raw, key=lambda w: -(w.get("cited_by_count") or 0))[: a.expand]
    for rnd in range(2, a.rounds + 1):
        nxt = []
        for w in frontier:
            rel = [short_id(x) for x in (w.get("related_works") or [])[: a.per_paper]]
            nxt += works(rel) if rel else []
            nxt += get("/works", filter=f"cites:{short_id(w['id'])}", sort="cited_by_count:desc",
                       **{"per-page": a.per_paper, "select": FULL})["results"]
        raw += nxt
        frontier = sorted(nxt, key=lambda w: -(w.get("cited_by_count") or 0))[: a.expand]
        print(f"round {rnd}: +{len(nxt)} candidates", file=sys.stderr)
    pool = merge(raw)[: a.max]
    json.dump({"meta": {"source": "openalex", "queries": a.query}, "papers": pool}, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"wrote {a.out}: {len(pool)} papers ({sum(1 for p in pool if p['abstract'])} with abstracts)")


# ------------------------------------------------------------------ web-tool mode

def cmd_urls(a):
    if a.what == "search":
        for q in a.query:
            print(f"{API}/works?" + urllib.parse.urlencode({"search": q, "per-page": a.k, "select": LIGHT}))
    elif a.what == "abstracts":
        ids = [short_id(i) for i in a.ids.split(",")]
        for i in range(0, len(ids), 5):
            print(f"{API}/works?" + urllib.parse.urlencode({"filter": "openalex:" + "|".join(ids[i:i + 5]),
                                                            "select": "id,display_name,abstract_inverted_index"}))
    else:
        for i in a.ids.split(","):
            print(f"{API}/works/{short_id(i)}?select=id,display_name,related_works")
            print(f"{API}/works?" + urllib.parse.urlencode({"filter": f"cites:{short_id(i)}", "sort": "cited_by_count:desc",
                                                            "per-page": a.k, "select": LIGHT}))
    print("\nFetch ONE url at a time; ask the web tool for id, title, year, venue, doi, cited_by_count (and a faithful "
          "1-2 sentence abstract digest for abstract URLs). Save what you get as a JSON list, then `collect.py merge`.",
          file=sys.stderr)


def cmd_merge(a):
    raw, queries = [], []
    for path in a.files:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d, dict):
            queries += (d.get("meta") or {}).get("queries") or []
            d = d.get("papers") or d.get("results") or d.get("records") or []
        raw += d
    pool = merge(raw)
    json.dump({"meta": {"source": "openalex (web tool)", "queries": queries}, "papers": pool}, open(a.out, "w"),
              indent=1, ensure_ascii=False)
    miss = [p["id"] for p in pool if not p.get("abstract")]
    print(f"wrote {a.out}: {len(pool)} papers" + (f"; {len(miss)} without abstract: {', '.join(miss[:12])}" if miss else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("-q", "--query", action="append", required=True)
    p.add_argument("--rounds", type=int, default=2, help="1 = searches only; each extra round expands the best papers")
    p.add_argument("--per-query", type=int, default=12); p.add_argument("--expand", type=int, default=8)
    p.add_argument("--per-paper", type=int, default=6); p.add_argument("--max", type=int, default=120)
    p.add_argument("-o", "--out", default="pool.json"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("urls")
    p.add_argument("what", choices=["search", "abstracts", "neighbours"])
    p.add_argument("-q", "--query", action="append"); p.add_argument("--ids"); p.add_argument("-k", type=int, default=8)
    p.set_defaults(fn=cmd_urls)
    p = sub.add_parser("merge"); p.add_argument("files", nargs="+"); p.add_argument("-o", "--out", default="pool.json")
    p.set_defaults(fn=cmd_merge)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
