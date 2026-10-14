#!/usr/bin/env python3
"""Regression tests for the CoE scripts, using examples/binpack (seeded with known errors).

  python tests/run_tests.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
S = os.path.join(SKILL, "scripts")
sys.path.insert(0, S)
from coe_lib import find_numbers, numbers_match  # noqa: E402

failures = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))
    if not cond:
        failures.append(name)


def run(*args, cwd):
    p = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def ledger(path):
    return json.load(open(path, encoding="utf-8"))


def reasons(led):
    return {c["id"]: c["reason"] for c in led["claims"]}


def main():
    # ---- number matching
    def m(c, e):
        return numbers_match(find_numbers(c)[0], find_numbers(e)[0], 0.0, 0.01)
    cases = [("14.4 ms", "14.38", True), ("0.9952", "1", False), ("98.18%", "0.9818", True),
             ("0.0144 s", "14.4 ms", True), ("1", "0.9818", False), ("0.731", "0.73", False),
             ("1,538,006.69", "1538006.69", True), ("15 ms", "14.4 ms", False)]
    for c, e, want in cases:
        check(f"match {c!r} ~ {e!r} == {want}", m(c, e) == want)
    check("zero-padded ids are not numbers", [n.raw for n in find_numbers("run 005 score=0.98")] == ["0.98"])

    tmp = tempfile.mkdtemp(prefix="coe_test_")
    b = os.path.join(tmp, "binpack")
    shutil.copytree(os.path.join(SKILL, "examples", "binpack"), b)

    # ---- WRITE: seeded errors
    rc, out = run(os.path.join(S, "ground.py"), "rep_bad.md", "--out", "o_bad", cwd=b)
    r = reasons(ledger(os.path.join(b, "o_bad", "ledger.json")))
    check("bad draft blocked", rc == 1, out)
    expect = {"LIT3": "cite_not_verified", "LIT4": "cite_title_mismatch", "M3": "broken_ref",
              "HEAD": "cherry_pick", "LAT": "value_mismatch", "CONC": "derive_broken", "GEN": "unsourced"}
    for cid, code in expect.items():
        check(f"bad draft {cid} -> {code}", r.get(cid) == code, r.get(cid))
    check("bad draft unit conversions accepted (PCT, LATS)", r.get("PCT") is None and r.get("LATS") is None, r)
    led = ledger(os.path.join(b, "o_bad", "ledger.json"))
    check("untagged numbers found", len(led["untagged"]) == 2, led["untagged"])

    # ---- WRITE: clean draft
    rc, out = run(os.path.join(S, "ground.py"), "rep_good.md", "--out", "o_good", cwd=b)
    check("good draft passes ground", rc == 0, out)
    rc, out = run(os.path.join(S, "ground.py"), "rep_good.md", "--out", "o_good", "--require-reviews", cwd=b)
    check("final verify blocks without judges", rc == 1 and "reviews_pending" in out, out)

    packet = open(os.path.join(b, "o_good", "review_packet.md"), encoding="utf-8").read()
    import re
    ids = re.findall(r"^## (\S+) — ", packet, re.M)
    raws = []
    for j in range(3):
        p = os.path.join(tmp, f"judge{j}.txt")
        open(p, "w").write("```json\n" + json.dumps({i: {"verdict": "supported", "reason": "t"} for i in ids}) + "\n```")
        raws.append(p)
    rc, out = run(os.path.join(S, "merge_judgments.py"), "--packet", "o_good/review_packet.md", "--out", "j.json",
                  *raws, cwd=b)
    check("merge_judgments", rc == 0, out)
    rc, out = run(os.path.join(S, "ground.py"), "rep_good.md", "--out", "o_good", "--require-reviews",
                  "--judgments", "j.json", cwd=b)
    check("final verify passes with 3 judges", rc == 0, out)
    rc, out = run(os.path.join(S, "strip_tags.py"), "rep_good.md", "--ledger", "o_good/ledger.json",
                  "--out", "final.md", "--appendix", "appendix.md", cwd=b)
    final = open(os.path.join(b, "final.md"), encoding="utf-8").read()
    check("strip removes tags and adds references", rc == 0 and "{num" not in final and "## References" in final, out)

    # stale votes
    txt = open(os.path.join(b, "rep_good.md"), encoding="utf-8").read().replace("repeatedly tries", "tries")
    open(os.path.join(b, "rep_good2.md"), "w", encoding="utf-8").write(txt)
    rc, out = run(os.path.join(S, "ground.py"), "rep_good2.md", "--out", "o_g2", "--require-reviews",
                  "--judgments", "j.json", cwd=b)
    check("reworded claim loses old votes", rc == 1 and "M2" in out and "reviews_pending" in out, out)

    # probes
    open(os.path.join(b, "probe.md"), "w").write(
        "Our best result is 0.9952 {num: ablation_summary.json#exploratory_easy_subset.score @P1}.\n"
        "On a 10-instance exploratory subset an earlier run scored 0.9952 {num: ablation_summary.json#exploratory_easy_subset.score nonfinal @P2}.\n"
        "It reaches a perfect score of 1 {num: scores.json#final.score @P3}.\n"
        "It scores about 1 {num: scores.json#final.score @P4}.\n"
        "No run varied the seed {absent: experimental_log.md re=seed @P5}.\n"
        "No run used simulated annealing {absent: experimental_log.md re=anneal @P6}.\n"
        "The headline is 0.9818 {num: scores.json#final.score headline @H}.\n")
    run(os.path.join(S, "ground.py"), "probe.md", "--out", "o_probe", cwd=b)
    r = reasons(ledger(os.path.join(b, "o_probe", "ledger.json")))
    for cid, code in {"P1": "unlabelled_nonfinal", "P2": None, "P3": "coarse_rounding", "P4": None,
                      "P5": "absence_violated", "P6": None, "H": None}.items():
        check(f"probe {cid} -> {code}", r.get(cid) == code, r.get(cid))

    # ---- refs
    rc, out = run(os.path.join(S, "refs.py"), "check", "refs.bib", "--cache", "refs_cache.json", cwd=b)
    check("refs check flags not_found, mismatch and shared DOI", rc == 1 and "SHARED doi" in out
          and "not_found" in out and "mismatch" in out, out)

    # ---- AUDIT
    ev = ["--evidence", "experimental_log.md", "scores.json", "ablation_summary.json"]
    rc, out = run(os.path.join(S, "audit.py"), "paper_foreign.md", "--bundle", ".", "--bib", "refs.bib",
                  "--refs-cache", "refs_cache.json", "--claimed", "0.9952", "--rerun-cmd", f"{sys.executable} solver.py",
                  "--runs", "1", "--code", "solver.py", "--spec", "task_spec.md", *ev, cwd=b)
    a = json.load(open(os.path.join(b, "audit_out", "audit.json")))
    ch = a["checks"]
    check("audit FAIL", a["summary"]["verdict"] == "FAIL", out)
    check("audit H cherry-pick", ch["H_headline_source"]["category"] == "cross_stage_cherry_pick", ch.get("H_headline_source"))
    check("audit I1 fails with category", ch["I1_score_verification"]["pass"] is False
          and ch["I1_score_verification"]["category"] == "cross_stage_cherry_pick", ch["I1_score_verification"])
    check("audit I3 shared DOI", bool(ch["I3_references"]["shared_identifiers"]), ch["I3_references"])
    untr = [u["number"] for u in ch["T_number_tracing"]["untraced_high"]]
    check("audit T finds 9.4 ms untraced", "9.4 ms" in untr, untr)
    check("audit judges pending -> INCOMPLETE-able", ch["I4_method_code"]["pass"] is None, ch["I4_method_code"])

    rc, out = run(os.path.join(S, "audit.py"), "final.md", "--bundle", ".", "--claimed", "0.9818",
                  "--rerun-cmd", f"{sys.executable} solver.py", "--runs", "1", "--out", "aud_ok",
                  "--evidence", "experimental_log.md", "scores.json", "ablation_summary.json", "solver.py", cwd=b)
    check("audit of verified write-up PASS", rc == 0, out)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED: {failures}'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
