#!/usr/bin/env python3
"""Merge raw judge outputs into a judgments file.

WRITE mode (claim-level, from review_packet.md):
  python merge_judgments.py --packet coe_out/review_packet.md --out judgments.json \
         judge1.txt judge2.txt judge3.txt [--existing judgments.json]

  Each raw file is a judge's answer: a JSON object {"<id>": {"verdict":..,"reason":..,"hash":..}}
  possibly wrapped in prose or ```json fences. Missing hashes are filled from the packet,
  so votes are tied to the exact sentence + evidence they judged. With --existing, old votes
  are kept only if their hash still matches the packet (changed claims start fresh).

AUDIT mode (check-level, from audit_packet.md):
  python merge_judgments.py --check I4 --out judgments.json judge1.txt judge2.txt judge3.txt
  Each raw file holds one vote object {"verdict": .., ...}; votes are appended under "I4".
"""
import argparse
import json
import os
import re
import sys


def extract_json(text: str):
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--packet")
    ap.add_argument("--existing")
    ap.add_argument("--check", help="audit check name (I2 / I4) for check-level votes")
    a = ap.parse_args()

    merged = {}
    if a.existing and os.path.exists(a.existing):
        merged = json.load(open(a.existing, encoding="utf-8"))
    elif os.path.exists(a.out):
        merged = json.load(open(a.out, encoding="utf-8"))

    if a.check:
        for f in a.raw:
            vote = extract_json(open(f, encoding="utf-8").read())
            vote["judge_file"] = os.path.basename(f)
            merged.setdefault(a.check, []).append(vote)
        json.dump(merged, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{a.check}: {len(merged[a.check])} votes -> {a.out}")
        return

    if not a.packet:
        sys.exit("--packet is required for claim-level merging")
    hashes = dict(re.findall(r"^## (\S+) — .*?\(hash ([0-9a-f]+)\)", open(a.packet, encoding="utf-8").read(), re.M))
    # drop stale votes
    for cid in list(merged):
        if cid in hashes:
            merged[cid] = [v for v in merged[cid] if v.get("hash") == hashes[cid]]
    bad = 0
    for f in a.raw:
        try:
            obj = extract_json(open(f, encoding="utf-8").read())
        except ValueError as e:
            print(f"WARNING {f}: {e}", file=sys.stderr)
            bad += 1
            continue
        for cid, vote in obj.items():
            if not isinstance(vote, dict) or "verdict" not in vote:
                continue
            if cid not in hashes:
                print(f"WARNING {f}: id {cid} not in packet — skipped", file=sys.stderr)
                continue
            if vote.get("hash") and vote["hash"] != hashes[cid]:
                print(f"WARNING {f}: {cid} judged an older version (hash mismatch) — skipped", file=sys.stderr)
                continue
            vote["hash"] = hashes[cid]
            vote["judge_file"] = os.path.basename(f)
            merged.setdefault(cid, []).append(vote)
    json.dump(merged, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    counts = {cid: len(v) for cid, v in merged.items() if cid in hashes}
    missing = [cid for cid in hashes if counts.get(cid, 0) == 0]
    print(f"merged {len(a.raw) - bad} judge files -> {a.out}; votes per claim: {counts}"
          + (f"; NO votes for {missing}" if missing else ""))


if __name__ == "__main__":
    main()
