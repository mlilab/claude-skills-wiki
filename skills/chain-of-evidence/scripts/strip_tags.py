#!/usr/bin/env python3
"""Remove CoE evidence tags from a verified draft and emit the final document.

Usage:
  python strip_tags.py DRAFT.md --ledger coe_out/ledger.json --out final.md
                       [--cite-style md|latex|none] [--appendix evidence.md] [--force]

Refuses to run if the ledger is not a passing verify (blocking issues or pending reviews)
unless --force is given. Citation tags become [key] (md), \\cite{key} (latex) or vanish (none).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coe_lib import TAG_RE, parse_tag, parse_bib


def render(text: str, style: str) -> str:
    def repl(m):
        t = parse_tag(m)
        if t.type == "cite" and t.targets and style != "none":
            keys = ",".join(t.targets)
            return f" \\cite{{{keys}}}" if style == "latex" else f" [{'; '.join(t.targets)}]"
        return ""
    out = re.sub(r"\s*" + TAG_RE.pattern, repl, text)
    return re.sub(r"[ \t]+([.,;:)])", r"\1", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cite-style", default="md", choices=["md", "latex", "none"])
    ap.add_argument("--appendix", default=None, help="write an evidence appendix (claim -> source)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-references", action="store_true",
                    help="do not append a References list (md style) built from the retrieval records")
    a = ap.parse_args()

    led = json.load(open(a.ledger, encoding="utf-8"))
    s = led["summary"]
    if os.path.abspath(led["draft"]) != os.path.abspath(a.draft):
        print(f"WARNING: ledger was built from {led['draft']}, not {a.draft}", file=sys.stderr)
        if not a.force:
            sys.exit(1)
    if (not s["pass"] or s["reviews_pending"]) and not a.force:
        print(f"REFUSED: ledger is not a passing final verify (blocking={s['blocking']}, "
              f"reviews_pending={s['reviews_pending']}). Fix and re-run ground.py --require-reviews.",
              file=sys.stderr)
        sys.exit(1)

    text = open(a.draft, encoding="utf-8").read()
    body = render(text, a.cite_style)
    cited = []
    for m in TAG_RE.finditer(text):
        t = parse_tag(m)
        if t.type == "cite":
            cited += [k for k in t.targets if k not in cited]
    if cited and a.cite_style == "md" and not a.no_references:
        cfg = led.get("config", {})
        cache_p = os.path.join(led.get("bundle", "."), cfg.get("refs_cache", "refs_cache.json"))
        bib = parse_bib(os.path.join(led.get("bundle", "."), cfg.get("bib", "refs.bib")))
        cache = json.load(open(cache_p, encoding="utf-8")) if os.path.exists(cache_p) else {}
        refs = ["", "## References", ""]
        for k in cited:
            e, r = bib.get(k, {}), cache.get(k, {})
            authors = e.get("author", r.get("authors", "")).replace(" and ", "; ")
            venue = e.get("journal") or e.get("booktitle") or ""
            doi = e.get("doi") or r.get("doi")
            arx = e.get("eprint") or r.get("arxiv")
            link = (f"https://doi.org/{doi}" if doi else f"https://arxiv.org/abs/{arx}" if arx else
                    r.get("source") if str(r.get("source", "")).startswith("http") else "")
            refs.append(f"- [{k}] {authors} ({e.get('year', r.get('year', ''))}). "
                        f"{r.get('title') or e.get('title', '')}. {venue}. {link}".replace(" .", "").strip())
        body = body.rstrip() + "\n" + "\n".join(refs) + "\n"
    open(a.out, "w", encoding="utf-8").write(body)
    if a.appendix:
        L = ["# Evidence appendix\n", "| claim | type | evidence | check |", "|---|---|---|---|"]
        for c in led["claims"]:
            L.append(f"| {c['sentence'][:100].replace('|', '/')} | {c['type']} | "
                     f"{', '.join(c['targets'])} | {c['status']}"
                     f"{' / review ' + c['review'] if c.get('review') else ''} |")
        open(a.appendix, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"wrote {a.out}" + (f" and {a.appendix}" if a.appendix else ""))


if __name__ == "__main__":
    main()
