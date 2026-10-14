#!/usr/bin/env python3
"""Reference verification cache for CoE.

Every bibliography entry must be backed by a *retrieval record* — proof that the work was
looked up in a scholarly source during this session — before a citation claim can pass.

  python refs.py resolve refs.bib --cache refs_cache.json
      Try arXiv / Crossref / OpenAlex for each entry. Network failures are recorded as
      status "unreachable" (NOT verified) so you know to verify them another way.

  python refs.py add --cache refs_cache.json --key KEY --title "Exact title" --source URL
                     [--doi DOI] [--arxiv ID] [--year Y] [--authors "A; B"]
                     [--abstract TEXT | --abstract-file F] [--status verified|not_found|mismatch]
      Record a lookup you did with a web tool (e.g. WebFetch of the arXiv / DOI page).
      Only record what the fetched page actually says.

  python refs.py check refs.bib --cache refs_cache.json
      Summarise which bib entries are verified, missing or mismatched. Exit 1 if any
      entry is not verified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coe_lib import parse_bib, load_cache, title_similarity

UA = {"User-Agent": "coe-skill/1.0 (reference verification)"}


def _get(url: str, timeout=15) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def lookup(entry: dict):
    """Return (record|None, error|None)."""
    title = entry.get("title", "")
    errors = []
    arx = entry.get("eprint") or ""
    m = re.search(r"(\d{4}\.\d{4,5})", arx + " " + entry.get("journal", "") + " " + entry.get("url", ""))
    if m:
        try:
            xml = _get(f"http://export.arxiv.org/api/query?id_list={m.group(1)}")
            t = re.search(r"<entry>.*?<title>(.*?)</title>", xml, re.S)
            s = re.search(r"<summary>(.*?)</summary>", xml, re.S)
            if t:
                return {"title": " ".join(t.group(1).split()), "arxiv": m.group(1),
                        "abstract": " ".join(s.group(1).split()) if s else "",
                        "source": f"https://arxiv.org/abs/{m.group(1)}"}, None
        except Exception as e:  # noqa: BLE001
            errors.append(f"arxiv: {e}")
    doi = entry.get("doi")
    if doi:
        try:
            js = json.loads(_get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"))["message"]
            return {"title": (js.get("title") or [""])[0], "doi": doi,
                    "abstract": re.sub(r"<[^>]+>", "", js.get("abstract", "")),
                    "source": f"https://doi.org/{doi}"}, None
        except Exception as e:  # noqa: BLE001
            errors.append(f"crossref doi: {e}")
    if title:
        try:
            q = urllib.parse.quote(title)
            js = json.loads(_get(f"https://api.openalex.org/works?search={q}&per-page=3"))
            best = max(js.get("results", []), key=lambda r: title_similarity(title, r.get("title") or ""),
                       default=None)
            if best:
                return {"title": best.get("title"), "doi": (best.get("doi") or "").replace("https://doi.org/", ""),
                        "abstract": "", "source": best.get("id")}, None
            return None, "not_found"
        except Exception as e:  # noqa: BLE001
            errors.append(f"openalex: {e}")
    return None, "; ".join(errors) or "no identifiers to look up"


def cmd_resolve(a):
    bib = parse_bib(a.bib)
    cache = load_cache(a.cache)
    for key, e in bib.items():
        if cache.get(key, {}).get("status") == "verified" and not a.refresh:
            continue
        rec, err = lookup(e)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        if rec:
            sim = title_similarity(e.get("title", ""), rec.get("title", ""))
            rec.update(key=key, checked_at=now, title_similarity=round(sim, 3),
                       status="verified" if sim >= a.threshold else "mismatch")
            cache[key] = rec
        elif err == "not_found":
            cache[key] = {"key": key, "status": "not_found", "checked_at": now}
        else:
            cache[key] = {"key": key, "status": "unreachable", "error": err[:300], "checked_at": now}
        print(f"{key:30s} {cache[key]['status']}")
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    unreach = [k for k, v in cache.items() if v.get("status") == "unreachable"]
    if unreach:
        print(f"\n{len(unreach)} entries unreachable from this shell. Verify them with a web tool "
              f"(fetch the arXiv/DOI/publisher page) and record with `refs.py add`.", file=sys.stderr)


def cmd_add(a):
    cache = load_cache(a.cache)
    abstract = a.abstract or (open(a.abstract_file, encoding="utf-8").read() if a.abstract_file else "")
    if a.status in ("verified", "mismatch") and not a.title:
        sys.exit("--title (as shown on the retrieved page) is required for verified/mismatch records")
    rec = {"key": a.key, "status": a.status, "title": a.title or "", "source": a.source,
           "queries": a.query or "",
           "doi": a.doi or "", "arxiv": a.arxiv or "", "year": a.year or "", "authors": a.authors or "",
           "abstract": " ".join(abstract.split()), "method": "manual-web-lookup",
           "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if a.bib:
        bib = parse_bib(a.bib)
        if a.key in bib:
            if a.title:
                rec["title_similarity"] = round(title_similarity(bib[a.key].get("title", ""), a.title), 3)
                if rec["status"] == "verified" and rec["title_similarity"] < a.threshold:
                    rec["status"] = "mismatch"
                    print(f"NOTE: bib title differs from the retrieved title "
                          f"(similarity {rec['title_similarity']}) -> recorded as mismatch", file=sys.stderr)
    cache[a.key] = rec
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"recorded {a.key}: {rec['status']}" +
          (f" (bib title similarity {rec['title_similarity']})" if "title_similarity" in rec else ""))


def shared_identifiers(bib: dict) -> dict:
    seen = {}
    for k, e in bib.items():
        for f in ("doi", "eprint"):
            v = (e.get(f) or "").strip().lower()
            if v:
                seen.setdefault(f"{f}={v}", []).append(k)
    return {i: ks for i, ks in seen.items() if len(ks) > 1}


def cmd_check(a):
    bib = parse_bib(a.bib)
    cache = load_cache(a.cache)
    bad, shared_n = 0, 0
    for key, e in bib.items():
        rec = cache.get(key)
        st = rec.get("status") if rec else "absent"
        sim = title_similarity(e.get("title", ""), rec.get("title", "")) if rec and rec.get("title") else None
        if st == "verified" and sim is not None and sim < a.threshold:
            st = "mismatch"
        bad += st != "verified"
        print(f"{key:30s} {st:12s} {'' if sim is None else f'title_sim={sim:.2f}'}  {e.get('title', '')[:60]}")
    for kind, keys in shared_identifiers(bib).items():
        print(f"SHARED {kind}: {', '.join(keys)} — two entries with one identifier is a fabrication signal")
        shared_n += 1
    print(f"\n{len(bib) - bad}/{len(bib)} verified" + (f"; {shared_n} shared identifier(s)" if shared_n else ""))
    bad += shared_n
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("resolve"); r.add_argument("bib"); r.add_argument("--cache", required=True)
    r.add_argument("--refresh", action="store_true"); r.add_argument("--threshold", type=float, default=0.85)
    ad = sp.add_parser("add")
    for f in ("cache", "key", "source"):
        ad.add_argument(f"--{f}", required=True)
    for f in ("title", "doi", "arxiv", "year", "authors", "abstract", "abstract-file", "bib", "query"):
        ad.add_argument(f"--{f}")
    ad.add_argument("--threshold", type=float, default=0.85)
    ad.add_argument("--status", default="verified", choices=["verified", "not_found", "mismatch"])
    c = sp.add_parser("check"); c.add_argument("bib"); c.add_argument("--cache", required=True)
    c.add_argument("--threshold", type=float, default=0.85)
    a = ap.parse_args()
    {"resolve": cmd_resolve, "add": cmd_add, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
