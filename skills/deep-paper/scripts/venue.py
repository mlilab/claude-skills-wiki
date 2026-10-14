#!/usr/bin/env python3
"""Decide where a paper was published by matching its title against official accepted lists.

usage: venue.py --id PAPER_ID            # uses meta.json (title, submitted, comments)
       venue.py --title "..." [--year 2025]
       venue.py --refresh                # drop cached lists and download them again

Sources (official, no login):
  iclr / icml / neurips   https://<conf>.cc/static/virtual/data/<conf>-<year>-orals-posters.json
  cvpr / iccv / wacv      https://openaccess.thecvf.com/<CONF><year>?day=all
  eccv                    https://www.ecva.net/papers.php
Lists are cached in ~/.cache/deep-paper/venues/ (14 days; an empty or missing list 1 day).

Why: arXiv comments are often not updated after acceptance, so "no venue in the comments" does
not mean preprint. The decision order is: an official-list match, then a venue claim in the
arXiv comments or journal-ref (report it as unverified), then "arXiv YYYY.MM" from the
first submission date. Writes the result to meta.json["venue"] when --id is given.
"""
from __future__ import annotations

import argparse
import html as htmllib
import re
import shutil
import time

from common import (cache_dir, http_get, load_config, norm_title, out, paper_dir, read_json,
                    title_tokens, write_json)

VIRTUAL = {"iclr": "ICLR", "icml": "ICML", "neurips": "NeurIPS"}
CVF = {"cvpr": "CVPR", "iccv": "ICCV", "wacv": "WACV"}
TTL_OK, TTL_EMPTY = 14 * 86400, 86400
CLAIM = re.compile(r"\b(ICLR|ICML|NeurIPS|NIPS|CVPR|ICCV|ECCV|WACV|ACL|EMNLP|NAACL|COLING|AAAI|IJCAI|"
                   r"KDD|SIGGRAPH(?: Asia)?|CoRL|RSS|ICRA|IROS|TPAMI|TMLR|JMLR|COLM|UAI|AISTATS|MICCAI)"
                   r"\s*['’]?\s*(\d{4}|\d{2})\b(?:\s*\(?(Oral|Spotlight|Poster|Findings|Workshop)\)?)?", re.I)


def vdir():
    d = cache_dir() / "venues"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cached(key: str, loader) -> list[dict]:
    p = vdir() / f"{key}.json"
    data = read_json(p)
    if data is not None:
        age = time.time() - data.get("at", 0)
        if age < (TTL_OK if data.get("papers") else TTL_EMPTY):
            return data["papers"]
    try:
        papers = loader()
    except Exception as e:  # network or format problems: treat as unavailable for now
        papers = []
        print(f"warning: {key}: {e}", flush=True)
    write_json(p, {"at": time.time(), "papers": papers})
    return papers


def load_virtual(conf: str, year: int) -> list[dict]:
    def loader():
        r = http_get(f"https://{conf}.cc/static/virtual/data/{conf}-{year}-orals-posters.json",
                     timeout=180, retries=2)
        if r.status_code != 200:
            return []
        rows = r.json().get("results", [])
        out_rows = []
        for x in rows:
            kind = (x.get("decision") or x.get("eventtype") or "").replace("Accept (", "").rstrip(")")
            if x.get("name"):
                out_rows.append({"t": x["name"], "k": kind})
        return out_rows
    return _cached(f"{conf}{year}", loader)


def load_cvf(conf: str, year: int) -> list[dict]:
    def loader():
        r = http_get(f"https://openaccess.thecvf.com/{CVF[conf]}{year}?day=all", timeout=180, retries=2)
        if r.status_code != 200:
            return []
        titles = re.findall(r'<dt class="ptitle">\s*<br>\s*<a href="?[^>"]*"?>(.*?)</a>', r.text, re.S)
        return [{"t": htmllib.unescape(" ".join(t.split())), "k": ""} for t in titles]
    return _cached(f"{conf}{year}", loader)


def load_eccv(year: int) -> list[dict]:
    def loader():
        r = http_get("https://www.ecva.net/papers.php", timeout=180, retries=2)
        if r.status_code != 200:
            return []
        rows = re.findall(r'<a href="?papers/eccv_(\d{4})/[^>"]*"?>\s*(.*?)\s*</a>', r.text, re.S)
        return [{"t": htmllib.unescape(" ".join(t.split())), "k": "", "y": int(y)} for y, t in rows]
    return [x for x in _cached("eccv_all", loader) if x.get("y") == year]


def venue_list(cfg, year: int) -> list[tuple[str, int]]:
    """(conf, year) pairs to check. 'auto': major ML/CV venues of the submission year and the next."""
    v = cfg.get("venues", "auto")
    if v != "auto":
        pairs = []
        for item in v:  # "ICLR 2026"
            m = re.match(r"(\w+)\s+(\d{4})", str(item))
            if m:
                pairs.append((m.group(1).lower(), int(m.group(2))))
        return pairs
    pairs = []
    for y in (year, year + 1):
        pairs += [("iclr", y), ("icml", y), ("neurips", y), ("cvpr", y)]
        pairs.append(("iccv", y) if y % 2 else ("eccv", y))
    return pairs


def load(conf: str, year: int) -> list[dict]:
    if conf in VIRTUAL:
        return load_virtual(conf, year)
    if conf in CVF:
        return load_cvf(conf, year)
    if conf == "eccv":
        return load_eccv(year)
    return []


def match(title: str, papers: list[dict]) -> dict | None:
    want, want_tok = norm_title(title), title_tokens(title)
    best, best_s = None, 0.0
    for p in papers:
        if norm_title(p["t"]) == want:
            return {**p, "score": 1.0}
    if len(want_tok) < 5:
        return None
    for p in papers:
        tok = title_tokens(p["t"])
        s = len(want_tok & tok) / max(1, len(want_tok | tok))
        if s > best_s:
            best, best_s = p, s
    return {**best, "score": round(best_s, 3)} if best and best_s >= 0.9 else None


def claims(text: str) -> list[str]:
    found = []
    for m in CLAIM.finditer(text or ""):
        name, yr, kind = m.group(1), m.group(2), m.group(3)
        yr = yr if len(yr) == 4 else "20" + yr
        name = {"nips": "NeurIPS"}.get(name.lower(), name)
        found.append(f"{name} {yr}" + (f" {kind.title()}" if kind else ""))
    return list(dict.fromkeys(found))


def decide(cfg, title: str, submitted: str, comments: str = "") -> dict:
    year = int((submitted or "0000")[:4] or 0) or time.gmtime().tm_year
    checked, hits = [], []
    for conf, y in venue_list(cfg, year):
        papers = load(conf, y)
        name = VIRTUAL.get(conf) or CVF.get(conf) or conf.upper()
        checked.append(f"{name} {y}" + ("" if papers else " (list unavailable)"))
        m = match(title, papers) if papers else None
        if m:
            hits.append({"venue": f"{name} {y}", "kind": m.get("k") or "", "matched_title": m["t"],
                         "score": m["score"]})
    claimed = claims(comments)
    if hits:
        best = max(hits, key=lambda h: h["score"])
        v = best["venue"] + (f" ({best['kind']})" if best["kind"] and best["kind"].lower() not in
                             ("poster", "accept") else "")
        return {"venue": v, "evidence": "official accepted list", "match": best,
                "comment_claims": claimed, "checked": checked}
    fallback = f"arXiv {submitted[:7].replace('-', '.')}" if submitted else "arXiv"
    if claimed:
        return {"venue": claimed[0], "evidence": "arXiv comments only (not in the official lists checked)",
                "verify": True, "fallback": fallback, "comment_claims": claimed, "checked": checked}
    return {"venue": fallback, "evidence": "no official match and no venue claim", "checked": checked}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--title")
    ap.add_argument("--year", type=int)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if args.refresh:
        shutil.rmtree(vdir(), ignore_errors=True)
        if not (args.id or args.title):
            out({"refreshed": True})
            return
    if args.id:
        pdir = paper_dir(cfg, args.id)
        meta = read_json(pdir / "meta.json")
        if not meta:
            raise SystemExit("run fetch.py first")
        res = decide(cfg, meta["title"], meta.get("submitted", ""),
                     " ".join([meta.get("comments", ""), meta.get("journal_ref", "")]))
        meta["venue"] = res["venue"]
        meta["venue_evidence"] = res["evidence"]
        write_json(pdir / "meta.json", meta)
        out(res)
    elif args.title:
        out(decide(cfg, args.title, f"{args.year or time.gmtime().tm_year}-01-01"))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
