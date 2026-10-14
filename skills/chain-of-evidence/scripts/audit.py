#!/usr/bin/env python3
"""CoE Integrity Audit for a finished document (no evidence tags needed).

Usage:
  python audit.py DOC --bundle BUNDLE_DIR [--out OUT_DIR]
      [--bib refs.bib] [--refs-cache refs_cache.json]
      [--rerun-cmd "python solve.py" --score-regex "score=([-0-9.]+)" --claimed 0.731 --runs 3]
      [--code solver.py ...] [--spec task_spec.md] [--evaluator evaluator.py]
      [--method-heading "method|approach"] [--judgments judgments.json]

Checks
  T  Number tracing  : every number in the document is searched for in the bundle's evidence files
  I1 Score verify    : re-run the submitted code and compare to the claimed headline score
  I2 Spec violation  : packet for LLM judges (code vs task rules / evaluator) — majority vote
  I3 References      : cited keys exist in the bib; every bib entry has a verified retrieval record
  I4 Method-code     : packet for LLM judges (method section vs code) — majority vote

Outputs OUT_DIR/audit.json, audit_report.md, audit_packet.md. Exit 1 if any check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coe_lib import (decimals_of, Num, TAG_RE, split_sentences, find_numbers, numbers_match, numeric_leaves, unit_from_key, parse_bib,
                     load_cache, title_similarity, overclaim_hits, to_json)

DEFAULT_EVIDENCE = ["**/*.log", "**/*.out", "**/*.csv", "**/*.tsv", "**/*.json", "**/*.jsonl",
                    "**/*log*.md", "**/*log*.txt", "**/*result*.*", "**/*score*.*", "**/*metric*.*"]
SKIP_DIRS = ("coe_out", "audit_out", "__pycache__", ".git")


def clean_doc(text: str, is_tex: bool) -> str:
    if is_tex:
        text = re.sub(r"(?<!\\)%.*", "", text)
        text = re.sub(r"\\(?:label|ref|eqref|url|includegraphics)\{[^}]*\}", "", text)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    # bibliography sections and URLs/DOIs are not claims
    text = re.split(r"(?im)^\s*(?:#+\s*(?:references|bibliography|참고\s*문헌)\b.*|\\begin\{thebibliography\}|\\bibliography\{)", text)[0]
    text = re.sub(r"https?://\S+|\bdoi:\s*\S+|\b10\.\d{4,9}/\S+", "", text)
    return text


def sentences(text: str):
    for ln, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for s in split_sentences(line):
            if s.strip():
                yield ln, s.strip()


def severity(n: Num) -> str:
    if n.unit or n.decimals or abs(n.value) >= 100:
        return "high"
    return "low"


def evidence_files(bundle: str, globs: list[str], exclude: set[str]) -> list[str]:
    import glob as _g
    files = set()
    for pat in globs:
        for p in _g.glob(os.path.join(bundle, pat), recursive=True):
            rel = os.path.relpath(p, bundle)
            if not os.path.isfile(p) or os.path.abspath(p) in exclude:
                continue
            if any(part.startswith(SKIP_DIRS) for part in rel.split(os.sep)):
                continue
            try:
                head = open(p, encoding="utf-8", errors="replace").read(200000)
            except OSError:
                continue
            base = os.path.basename(p).lower()
            if base in ("coe_config.json",) or "judg" in base:
                continue
            if TAG_RE.search(head):  # a CoE draft is not evidence
                continue
            files.add(os.path.abspath(p))
    return sorted(files)


def index_evidence(bundle: str, files: list[str]):
    idx = []
    for p in files:
        if True:
            fn = os.path.basename(p)
            rel = os.path.relpath(p, bundle)
            if fn.endswith(".json"):
                try:
                    for k, v in numeric_leaves(json.load(open(p, encoding="utf-8"))):
                        idx.append((Num(float(v), unit_from_key(k), decimals_of(v), str(v)), f"{rel}#{k}"))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                for n in find_numbers(line):
                    idx.append((n, f"{rel}:{i}"))
    return idx


def majority(votes, positive, min_votes=1):
    if not votes:
        return None, {}
    tally = Counter(v.get("verdict") for v in votes)
    if len(votes) < min_votes:
        return None, dict(tally)
    pos = tally.get(positive, 0)
    return pos > len(votes) / 2, dict(tally)


def vote_status(tally, min_votes):
    n = sum(tally.values())
    if n == 0:
        return "awaiting_judges"
    if n < min_votes:
        return f"insufficient_votes ({n}/{min_votes}) — not independent enough to decide"
    return "judged"


def extract_section(text: str, heading_re: str) -> str:
    lines = text.splitlines()
    pat = re.compile(r"^\s*(#+|\\section\*?\{|\\subsection\*?\{).*(" + heading_re + ")", re.I)
    out, on, level = [], False, None
    for line in lines:
        m = re.match(r"^\s*(#+)\s", line)
        is_head = bool(m) or line.lstrip().startswith("\\section")
        if pat.match(line):
            on, level = True, (len(m.group(1)) if m else 1)
            out.append(line)
            continue
        if on and is_head:
            lvl = len(m.group(1)) if m else 1
            if lvl <= level:
                break
        if on:
            out.append(line)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--bib", default=None)
    ap.add_argument("--refs-cache", default=None)
    ap.add_argument("--rerun-cmd", default=None)
    ap.add_argument("--score-regex", default=r"score\s*[:=]\s*([-+0-9.eE]+)")
    ap.add_argument("--claimed", type=float, default=None, help="headline value the document claims")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--code", nargs="*", default=[])
    ap.add_argument("--spec", default=None)
    ap.add_argument("--evaluator", default=None)
    ap.add_argument("--method-heading", default=r"method|approach|algorithm|방법|제안")
    ap.add_argument("--judgments", default=None,
                    help='JSON: {"I2": [{"verdict": "clean|flagged", "reason": ..}], "I4": [{"verdict": "aligned|misaligned", ...}]}')
    ap.add_argument("--rel-tol", type=float, default=0.0)
    ap.add_argument("--final-sources", nargs="*", default=None,
                    help="locator prefixes of the submitted run's results, e.g. scores.json#final "
                         "(default: final_result_sources from BUNDLE/coe_config.json)")
    ap.add_argument("--min-votes", type=int, default=3,
                    help="judge votes needed before I2/I4 can PASS or FAIL (fewer -> INCOMPLETE)")
    ap.add_argument("--evidence", nargs="*", default=None,
                    help="glob(s) relative to bundle for evidence files (default: logs/results/json/csv)")
    a = ap.parse_args()

    bundle = os.path.abspath(a.bundle)
    out = a.out or os.path.join(bundle, "audit_out")
    os.makedirs(out, exist_ok=True)
    raw = open(a.doc, encoding="utf-8", errors="replace").read()
    is_tex = a.doc.endswith(".tex")
    doc = clean_doc(raw, is_tex)
    res = {"doc": os.path.abspath(a.doc), "checks": {}}

    # ---- T: number tracing
    exclude = {os.path.abspath(a.doc)} | {os.path.abspath(os.path.join(bundle, x)) for x in
                                         filter(None, [a.bib, a.refs_cache])}
    if a.refs_cache:
        exclude.add(os.path.abspath(os.path.join(bundle, a.refs_cache)))
    ev_files = evidence_files(bundle, a.evidence or DEFAULT_EVIDENCE, exclude)
    idx = index_evidence(bundle, ev_files)
    res["evidence_files"] = [os.path.relpath(f, bundle) for f in ev_files]
    traced, untraced = [], []
    for ln, s in sentences(doc):
        s_vis = re.sub(r"\\cite\w*\{[^}]*\}|\[@[^\]]*\]|\([A-Z][A-Za-z]+(?: et al\.)?,? \d{4}\)", "", s)
        for n in find_numbers(s_vis):
            if not n.unit and n.decimals == 0 and 1900 <= n.value <= 2100:
                continue  # years
            hits = [loc for e, loc in idx if numbers_match(n, e, a.rel_tol)]
            item = {"line": ln, "number": n.raw, "severity": severity(n), "sentence": s[:200],
                    "found_in": hits[:5]}
            (traced if hits else untraced).append(item)
    final_src = a.final_sources
    if final_src is None:
        cfgp = os.path.join(bundle, "coe_config.json")
        final_src = json.load(open(cfgp)).get("final_result_sources", []) if os.path.exists(cfgp) else []
    res["final_sources"] = final_src

    def is_final(loc):
        return any(loc == f or loc.startswith(f) for f in final_src)

    non_final_only = []
    if final_src:
        for t in traced:
            if t["severity"] == "high" and t["found_in"] and not any(is_final(l) for l in t["found_in"]):
                # value exists only outside the submitted run's results
                fin_hits = [loc for e, loc in idx if is_final(loc) and numbers_match(find_numbers(t["number"])[0], e)]
                if not fin_hits:
                    t["non_final_only"] = True
                    non_final_only.append(t)

    # numbers that are simple arithmetic of traced numbers (differences, ratios, % change)
    tv = sorted({float(re.sub(r"[^0-9.+-]", "", t["number"].replace(",", "")) or 0) for t in traced
                 if t["severity"] == "high"})
    still = []
    for u in untraced:
        n = find_numbers(u["number"])[0]
        how = None
        for x in tv:
            for y in tv:
                if x == y or any(abs(x - y * f) < 1e-9 * max(1, abs(x)) for f in (100, 0.01, 1000, 0.001)):
                    continue  # same quantity in another unit
                for name, v in (("a-b", x - y), ("a/b", x / y if y else None),
                                ("(a-b)/b %", (x - y) / y * 100 if y else None)):
                    if v is not None and numbers_match(n, Num(v, "", 6, str(v)), 0.0):
                        how = f"{name} with a={x}, b={y}"
                        break
                if how:
                    break
            if how:
                break
        if how:
            u["derived_as"] = how
            traced.append(u)
        else:
            still.append(u)
    untraced = still
    high_untraced = [u for u in untraced if u["severity"] == "high"]
    res["checks"]["T_number_tracing"] = {
        "pass": not high_untraced,
        "non_final_only": non_final_only, "traced": len(traced), "untraced": len(untraced),
        "untraced_high": high_untraced, "untraced_low": [u for u in untraced if u["severity"] == "low"],
        "note": "Tracing is heuristic: a found match means the value exists somewhere in the evidence, "
                "not that it measures what the sentence says."}

    # ---- I3: references
    if a.bib:
        bib = parse_bib(os.path.join(bundle, a.bib) if not os.path.isabs(a.bib) else a.bib)
        cache = load_cache(os.path.join(bundle, a.refs_cache)) if a.refs_cache else {}
        cited = set()
        for m in re.finditer(r"\\cite\w*\{([^}]*)\}", raw):
            cited |= {k.strip() for k in m.group(1).split(",")}
        for m in re.finditer(r"\[@([^\]]+)\]", raw):
            cited |= {k.strip().lstrip("@") for k in re.split(r"[;,]", m.group(1))}
        for m in re.finditer(r"\[([A-Za-z][\w:-]*\d{2,4}[\w-]*(?:\s*;\s*[A-Za-z][\w:-]*\d{2,4}[\w-]*)*)\]", raw):
            cited |= {k.strip() for k in m.group(1).split(";")}
        missing = sorted(k for k in cited if k not in bib)
        entries = []
        for k, e in bib.items():
            rec = cache.get(k)
            st = rec.get("status") if rec else "unverified"
            sim = title_similarity(e.get("title", ""), rec.get("title", "")) if rec and rec.get("title") else None
            if st == "verified" and sim is not None and sim < 0.85:
                st = "mismatch"
            entries.append({"key": k, "status": st, "title": e.get("title", ""),
                            "title_similarity": None if sim is None else round(sim, 2), "cited": k in cited})
        shared = {}
        for k, e in bib.items():
            for f in ("doi", "eprint"):
                v = (e.get(f) or "").strip().lower()
                if v:
                    shared.setdefault(f"{f}={v}", []).append(k)
        shared = {i: ks for i, ks in shared.items() if len(ks) > 1}
        bad = [x for x in entries if x["status"] != "verified"]
        res["checks"]["I3_references"] = {
            "pass": not bad and not missing and not shared, "shared_identifiers": shared,
            "bib_entries": len(entries),
            "verified": len(entries) - len(bad), "problems": bad, "cited_but_not_in_bib": missing,
            "uncited_entries": [x["key"] for x in entries if not x["cited"]]}

    # ---- H: headline source (needs --claimed and final sources; no rerun required)
    if a.claimed is not None and final_src:
        cnum = Num(a.claimed, "", decimals_of(a.claimed), str(a.claimed))
        srcs = [loc for e, loc in idx if numbers_match(cnum, e)]
        fin = [l for l in srcs if is_final(l)]
        res["checks"]["H_headline_source"] = {
            "pass": bool(fin), "claimed": a.claimed, "final_sources": final_src, "found_in": srcs[:5],
            "category": None if fin else ("cross_stage_cherry_pick" if srcs else "untraced_headline")}

    # ---- I1: score verification
    if a.rerun_cmd and a.claimed is not None:
        scores, errs = [], []
        for _ in range(a.runs):
            try:
                p = subprocess.run(a.rerun_cmd, shell=True, cwd=bundle, capture_output=True, text=True,
                                   timeout=a.timeout)
                m = re.findall(a.score_regex, p.stdout + p.stderr)
                if m:
                    scores.append(float(m[-1]))
                else:
                    errs.append(f"exit {p.returncode}; no score match; tail: {(p.stdout + p.stderr)[-300:]}")
            except subprocess.TimeoutExpired:
                errs.append("timeout")
        if scores:
            mean = statistics.mean(scores)
            sd = statistics.pstdev(scores) if len(scores) > 1 else 0.0
            tol = max(0.01, 3 * sd / abs(mean)) if mean else 0.01
            dev = abs(a.claimed - mean) / abs(mean) if mean else float("inf")
            cnum = Num(a.claimed, "", decimals_of(a.claimed), str(a.claimed))
            in_doc = any(numbers_match(n, cnum) or numbers_match(cnum, n)
                         for _, s_ in sentences(doc) for n in find_numbers(s_))
            cat = None
            if dev > tol:
                srcs = [loc for e, loc in idx if numbers_match(cnum, e)]
                if srcs and final_src and not any(is_final(l) for l in srcs):
                    cat = "cross_stage_cherry_pick"
                else:
                    cat = "value_mismatch"
            res["checks"]["I1_score_verification"] = {
                "pass": dev <= tol, "claimed": a.claimed, "claimed_found_in_doc": in_doc,
                "category": cat, "rerun_scores": scores, "mean": mean,
                "rel_deviation": round(dev, 4), "tolerance": round(tol, 4), "errors": errs}
        else:
            res["checks"]["I1_score_verification"] = {"pass": False, "claimed": a.claimed,
                                                      "error": "evaluator_error", "errors": errs}

    # ---- I2 / I4 packets + judgments
    judg = json.load(open(a.judgments, encoding="utf-8")) if a.judgments else {}
    packet = ["# CoE audit packet (LLM judges)\n",
              "Run each check with 3–5 independent judges that have NOT seen how the work was produced. "
              "Each judge answers in JSON. Majority decides.\n"]
    code_txt = ""
    for c in a.code:
        p = c if os.path.isabs(c) else os.path.join(bundle, c)
        try:
            body = open(p, encoding="utf-8", errors="replace").read()
            code_txt += f"\n--- {c}\n" + "\n".join(f"{i:>5}: {l}" for i, l in enumerate(body.splitlines(), 1))
        except FileNotFoundError:
            code_txt += f"\n--- {c}: FILE NOT FOUND\n"
    if a.code:
        method = extract_section(raw, a.method_heading) or "(method section not found — judge whole document)\n" + raw[:6000]
        packet += ["## I4 Method–Code Alignment\n",
                   'Answer `{"verdict": "aligned|misaligned", "reason": "...", "findings": '
                   '[{"category": "incomplete_broken|algorithm_class_mismatch|deceptive_dummy_code", "detail": "..."}]}`. '
                   "Simplification or omitted detail is ALIGNED. A described component that is missing or degenerate, "
                   "a different algorithm class, or undisclosed switches/metric gaming is MISALIGNED.\n",
                   "### Method section\n", method, "\n### Code\n```", code_txt, "```\n"]
        ok, tally = majority(judg.get("I4", []), "aligned", a.min_votes)
        res["checks"]["I4_method_code"] = {"pass": ok, "votes": tally,
                                           "findings": [f for v in judg.get("I4", []) for f in v.get("findings", [])],
                                           "status": vote_status(tally, a.min_votes)}
    if a.code and (a.spec or a.evaluator):
        spec = open(os.path.join(bundle, a.spec), encoding="utf-8").read() if a.spec else ""
        ev = open(os.path.join(bundle, a.evaluator), encoding="utf-8").read() if a.evaluator else ""
        packet += ["## I2 Specification Violation\n",
                   'Answer `{"verdict": "clean|flagged", "reason": "...", "category": '
                   '"evaluator_import|evaluator_exploitation|specification_exploit|data_leakage|hardcoding|none"}`. '
                   "Flag code that optimises the score instead of solving the task: importing/calling the evaluator, "
                   "editing forbidden regions, hardcoding answers for known tests, exploiting what the evaluator fails to check.\n",
                   "### Task spec\n", spec or "(none)", "\n### Evaluator\n```\n",
                   ev or "(none supplied — if the score is computed inside the solution code, check that the "
                         "scoring matches the spec exactly and say in your reason that no independent evaluator exists)",
                   "\n```\n",
                   "### Solution code\n```", code_txt, "```\n"]
        ok, tally = majority(judg.get("I2", []), "clean", a.min_votes)
        res["checks"]["I2_spec_violation"] = {"pass": ok, "votes": tally,
                                              "status": vote_status(tally, a.min_votes),
                                              "limited": None if a.evaluator else
                                              "no separate evaluator: scoring may live in the author's own code"}
    open(os.path.join(out, "audit_packet.md"), "w", encoding="utf-8").write("\n".join(packet) + "\n")

    # ---- qualitative hints
    res["overclaim_hints"] = [{"line": ln, "terms": overclaim_hits(s), "sentence": s[:200]}
                              for ln, s in sentences(doc) if overclaim_hits(s)]

    failed = [k for k, v in res["checks"].items() if v.get("pass") is False]
    awaiting = [k for k, v in res["checks"].items() if v.get("pass") is None]
    res["summary"] = {"failed": failed, "awaiting_judges": awaiting,
                      "verdict": "FAIL" if failed else ("INCOMPLETE" if awaiting else "PASS")}
    open(os.path.join(out, "audit.json"), "w", encoding="utf-8").write(to_json(res))

    # ---- report
    R = [f"# CoE Integrity Audit\n", f"- document: `{a.doc}`", f"- verdict: **{res['summary']['verdict']}**\n",
         "| check | result | detail |", "|---|---|---|"]
    lab = {True: "PASS", False: "FAIL", None: "awaiting judges"}
    for k, v in res["checks"].items():
        if k == "H_headline_source":
            d = (f"claimed {v['claimed']} found in final results" if v["pass"] else
                 f"claimed {v['claimed']} — {v['category']}; found in {v['found_in'] or 'nothing'}")
        elif k == "T_number_tracing":
            d = (f"{v['traced']} traced, {len(v['untraced_high'])} high-severity untraced, {len(v['untraced_low'])} low"
                 + (f", {len(v['non_final_only'])} found only outside final results" if v['non_final_only'] else ""))
        elif k == "I3_references":
            d = f"{v['verified']}/{v['bib_entries']} verified; cited-not-in-bib {len(v['cited_but_not_in_bib'])}"
        elif k == "I1_score_verification":
            d = (f"claimed {v['claimed']} vs rerun mean {v.get('mean')} (dev {v.get('rel_deviation')}, tol {v.get('tolerance')})"
                 + (f"; category {v['category']}" if v.get("category") else "")
                 + ("" if v.get("claimed_found_in_doc", True) else "; WARNING: claimed value not found in document")
                 if "mean" in v else v.get("error", ""))
        else:
            d = f"votes {v.get('votes')}; {v.get('status')}" + (f"; limited: {v['limited']}" if v.get("limited") else "")
        R.append(f"| {k} | {lab[v.get('pass')]} | {d} |")
    t = res["checks"]["T_number_tracing"]
    R.append(f"\nEvidence files indexed: {', '.join(res['evidence_files']) or '(none)'}")
    if t["untraced_high"]:
        R.append("\n## Untraced numbers (high severity)\n")
        R += [f"- line {u['line']}: **{u['number']}** — {u['sentence']}" for u in t["untraced_high"]]
    if t["non_final_only"]:
        R.append("\n## Numbers not from the submitted run — confirm each is labelled as baseline / ablation / subset\n")
        R += [f"- line {u['line']}: **{u['number']}** ← {', '.join(u['found_in'][:3])} (final sources: {final_src})"
              for u in t["non_final_only"]]
    hi_traced = [x for x in traced if x["severity"] == "high"]
    if hi_traced:
        R.append("\n## Traced numbers — check the source is the right one\n")
        R += [f"- line {x['line']}: {x['number']} ← "
              + (f"derived ({x['derived_as']})" if x.get("derived_as") else ', '.join(x['found_in'][:3]))
              for x in hi_traced]
    if "I3_references" in res["checks"]:
        i3 = res["checks"]["I3_references"]
        if i3["problems"] or i3["cited_but_not_in_bib"]:
            R.append("\n## Reference problems\n")
            R += [f"- `{p['key']}` {p['status']}: {p['title'][:90]}" for p in i3["problems"]]
            R += [f"- `{k}` cited but not in bibliography" for k in i3["cited_but_not_in_bib"]]
        if i3["shared_identifiers"]:
            R += [f"- {ident} shared by {', '.join(ks)} (fabrication signal)" for ident, ks in i3["shared_identifiers"].items()]
    if "I4_method_code" in res["checks"] and res["checks"]["I4_method_code"]["findings"]:
        R.append("\n## Method–code findings\n")
        R += [f"- [{f.get('category')}] {f.get('detail')}" for f in res["checks"]["I4_method_code"]["findings"]]
    if res["overclaim_hints"]:
        R.append("\n## Qualitative claims to check (non-blocking)\n")
        R += [f"- line {o['line']} {o['terms']}: {o['sentence']}" for o in res["overclaim_hints"]]
    open(os.path.join(out, "audit_report.md"), "w", encoding="utf-8").write("\n".join(R) + "\n")
    print(json.dumps(res["summary"], ensure_ascii=False))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
