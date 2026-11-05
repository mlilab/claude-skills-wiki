#!/usr/bin/env python3
"""Regression tests for research-simulator v2. Run: python3 tests/run_tests.py  (node needed for parity tests)."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import sim  # noqa: E402
import simcore as sc  # noqa: E402

FIX = os.path.join(HERE, "fixture")
TMP = tempfile.mkdtemp(prefix="rsim-test-")
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def cli(*args, ok=True):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "sim.py"), *args], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise AssertionError(f"sim.py {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
    return p


def fresh(name="st.json", *extra):
    path = os.path.join(TMP, name)
    cli("init", "--papers", f"{FIX}/papers.json", "--facets", f"{FIX}/facets.json", "--research", f"{FIX}/research.json",
        "-o", path, *extra)
    return path


def node_eval(state_path, req):
    rp = os.path.join(TMP, "req.json")
    json.dump(req, open(rp, "w"), ensure_ascii=False)
    p = subprocess.run(["node", os.path.join(HERE, "js_eval.js"), state_path, rp], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError("node failed: " + p.stderr)
    return json.loads(p.stdout)


def close(a, b, tol=1e-9, where=""):
    if isinstance(a, dict):
        assert set(a) == set(b), f"{where}: keys differ {set(a) ^ set(b)}"
        for k in a:
            close(a[k], b[k], tol, f"{where}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), f"{where}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, tol, f"{where}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert abs(a - b) <= tol, f"{where}: {a} != {b}"
    else:
        assert a == b, f"{where}: {a!r} != {b!r}"


# ---------------------------------------------------------------- parity

@test
def parity_text_helpers():
    st = fresh()
    strs = ["Online 3D bin-packing, boxes & containers!", "온라인 3차원 빈 패킹 강화학습", "PPO's policies (2021)",
            "  Multi_Depot  vehicle  routing ", "glass mass analysis"]
    out = node_eval(st, {"tokenize": strs, "normTag": strs, "hash": [sc.norm_title(s) for s in strs]})
    assert out["tokenize"] == [sc.tokenize(s) for s in strs]
    assert out["normTag"] == [sc.norm_tag(s) for s in strs]
    assert out["hash"] == [sc.hash_str(sc.norm_title(s)) for s in strs]


@test
def parity_anchor_and_graph():
    st = fresh()
    state = json.load(open(st))
    upd = json.load(open(f"{FIX}/update.json"))
    researches = [state["nodes"][0]["research"]] + [sc.clean_research(o["projected"], state["nodes"][0]["research"]) for o in upd["options"]]
    for hops in (1, 2, 3):
        js = node_eval(st, {"researches": researches, "hops": hops})
        ctx = sc.context(state)
        close(js["anchor"], state["anchor"], where="anchor")
        close(js["graphs"], [sc.graph(ctx, r, sc.pool_ids(state, "s0"), hops) for r in researches], where=f"graph(h={hops})")


@test
def parity_apply_and_choose():
    st = fresh()
    state = json.load(open(st))
    upd = json.load(open(f"{FIX}/update.json"))
    js = node_eval(st, {"update": {"node": "s0", "body": upd, "action": {"type": "expand"}, "choose": 0}})
    py = copy.deepcopy(state)
    summ = sc.apply_update(py, "s0", upd, {"type": "expand"})
    sc.new_child(py, "s0", py["nodes"][0]["options"][0])
    assert js["applySummary"] == summ
    close(js["afterApply"]["nodes"], py["nodes"], where="nodes")
    close(js["afterApply"]["papers"], py["papers"], where="papers")


# ---------------------------------------------------------------- hop graph semantics

@test
def hop_structure():
    state = json.load(open(fresh()))
    ctx = sc.context(state)
    r = state["nodes"][0]["research"]
    g = sc.graph(ctx, r, sc.pool_ids(state, "s0"), 3, {"k1": 4, "k": 2})
    hop = {n["id"]: n["hop"] for n in g["nodes"]}
    assert len(hop) == len(g["nodes"]), "a paper was placed twice"
    assert sum(1 for h in hop.values() if h == 1) == 4
    for n in g["nodes"]:
        if n["hop"] > 1:
            assert hop[n["parent"]] == n["hop"] - 1
        else:
            assert n["parent"] == "@"
    kids = {}
    for n in g["nodes"]:
        kids[n["parent"]] = kids.get(n["parent"], 0) + 1
    assert all(v <= 2 for k, v in kids.items() if k != "@")
    assert len(g["edges"]) == len(g["nodes"]) and all(0 <= e["w"] <= 100 for e in g["edges"])
    # hop 1 = the most related papers
    s_all = sorted((sc.overall(sc.pair_sim(sc.prep(r, ctx.st), ctx.pv[i], 0.75)), i) for i in ctx.pv)
    top4 = {i for _, i in s_all[-4:]}
    assert {i for i, h in hop.items() if h == 1} == top4


@test
def hop2_is_closest_to_hop1_not_to_research():
    state = json.load(open(fresh()))
    ctx = sc.context(state)
    g = sc.graph(ctx, state["nodes"][0]["research"], sc.pool_ids(state, "s0"), 2, {"k1": 2, "k": 1})
    h1 = [n for n in g["nodes"] if n["hop"] == 1]
    h2 = [n for n in g["nodes"] if n["hop"] == 2]
    placed = {n["id"] for n in g["nodes"]}
    for n in h2:
        s = sc.overall(sc.pp_sim(ctx, n["parent"], n["id"]))
        # no unplaced paper is strictly closer to that parent
        for other in ctx.pv:
            if other not in placed:
                assert sc.overall(sc.pp_sim(ctx, n["parent"], other)) <= s + 1e-12
    assert h1 and h2


@test
def more_hops_only_add():
    state = json.load(open(fresh()))
    ctx = sc.context(state)
    r = state["nodes"][0]["research"]
    a = sc.graph(ctx, r, sc.pool_ids(state, "s0"), 1)
    b = sc.graph(ctx, r, sc.pool_ids(state, "s0"), 3)
    assert {n["id"] for n in a["nodes"]} <= {n["id"] for n in b["nodes"]} and len(b["nodes"]) > len(a["nodes"])


@test
def a_move_reshapes_the_graph():
    state = json.load(open(fresh()))
    ctx = sc.context(state)
    upd = json.load(open(f"{FIX}/update.json"))
    pool = sc.pool_ids(state, "s0")
    g0 = sc.graph(ctx, state["nodes"][0]["research"], pool, 2)
    g1 = sc.graph(ctx, sc.clean_research(upd["options"][1]["projected"], state["nodes"][0]["research"]), pool, 2)
    h0 = {n["id"] for n in g0["nodes"] if n["hop"] == 1}
    h1 = {n["id"] for n in g1["nodes"] if n["hop"] == 1}
    assert h0 != h1, "transferring to vehicle routing should change who is closest"


# ---------------------------------------------------------------- agent protocol

@test
def agent_cannot_write_scores():
    state = json.load(open(fresh()))
    upd = json.load(open(f"{FIX}/update.json"))
    upd["options"][0]["score"] = 99
    upd["options"][0]["projected"]["relatedness"] = 100
    sc.apply_update(state, "s0", upd)
    for o in state["nodes"][0]["options"]:
        assert set(o) == {"id", "label", "kind", "why", "projected"}
        assert set(o["projected"]) == {"title", "problem", "method", "problem_tags", "method_tags", "status"}


@test
def todo_merges_into_status():
    state = json.load(open(fresh()))
    sc.apply_update(state, "s0", json.load(open(f"{FIX}/update.json")))
    o = state["nodes"][0]["options"][0]
    texts = [s["text"] for s in o["projected"]["status"]]
    assert texts[-1] == "Solve 50 small instances with MILP" and o["projected"]["status"][-1]["kind"] == "todo"
    assert "Compare against MILP lower bound" in texts, "projection inherits the node's updated status"
    child = sc.new_child(state, "s0", o)
    assert child["research"]["status"][-1]["text"] == "Solve 50 small instances with MILP"
    assert child["move"] == {"label": o["label"], "kind": "method", "custom": False}


@test
def status_cleaning():
    out = sc.clean_status(["[todo] run X", "done: got 0.8", {"kind": "weird", "text": "n"}, {"kind": "todo", "text": ""}])
    assert out == [{"kind": "todo", "text": "run X"}, {"kind": "done", "text": "got 0.8"}, {"kind": "note", "text": "n"}]


@test
def custom_child_copies_research_until_agent_answers():
    state = json.load(open(fresh()))
    c = sc.new_child(state, "s0", {"label": "use real logs", "custom": True})
    assert c["research"] == state["nodes"][0]["research"] and c["research"] is not state["nodes"][0]["research"]
    sc.apply_update(state, c["id"], {"research": {"method_tags": ["milp"], "status": [{"kind": "todo", "text": "t"}]}})
    assert c["research"]["method_tags"] == ["milp"] and c["research"]["problem_tags"] == state["nodes"][0]["research"]["problem_tags"]


@test
def unverified_papers_never_move_verified_scores():
    state = json.load(open(fresh()))
    r = state["nodes"][0]["research"]
    pool = sc.pool_ids(state, "s0")
    before = {n["id"]: n["score"] for n in sc.graph(sc.context(state), r, pool, 1)["nodes"]}
    sc.apply_update(state, "s0", {"add_papers": [{"title": "Claimed", "problem_tags": ["bin-packing"], "method_tags": ["ppo"]}]})
    g = sc.graph(sc.context(state), r, sc.pool_ids(state, "s0"), 1)
    for n in g["nodes"]:
        if n["id"] in before:
            assert abs(before[n["id"]] - n["score"]) < 1e-12
    assert state["papers"][-1]["verified"] is False


@test
def verified_needs_link_and_readding_verifies():
    state = json.load(open(fresh()))
    sc.apply_update(state, "s0", {"add_papers": [{"title": "Maybe real", "verified": True, "problem_tags": ["x"], "method_tags": ["y"]}]})
    assert state["papers"][-1]["verified"] is False
    s = sc.apply_update(state, "s0", {"add_papers": [{"title": "Maybe  REAL", "verified": True, "doi": "10.9/x"}]})
    assert s["verified"] == 1 and state["papers"][-1]["verified"] is True and state["papers"][-1]["url"] == "https://doi.org/10.9/x"


@test
def branch_papers_stay_on_their_branch():
    state = json.load(open(fresh()))
    a = sc.new_child(state, "s0", {"label": "a"})
    b = sc.new_child(state, "s0", {"label": "b"})
    sc.apply_update(state, a["id"], {"add_papers": [{"title": "Branch only", "problem_tags": ["bin-packing"], "method_tags": ["milp"]}]})
    pid = state["papers"][-1]["id"]
    assert pid in sc.pool_ids(state, a["id"]) and pid not in sc.pool_ids(state, b["id"]) and pid not in sc.pool_ids(state, "s0")


@test
def prompt_protocol():
    st = fresh()
    p = node_eval(st, {"prompt": {"node": "s0", "action": {"type": "custom", "text": "use warehouse logs"}}})["prompt"]
    for needle in ("never output scores", "Never invent experimental results", "use warehouse logs", "hop 1", '"todo"',
                   "[todo] Evaluate on real warehouse order logs", "Reply with ONLY one JSON object"):
        assert needle in p, needle
    p2 = node_eval(st, {"prompt": {"node": "s0", "action": {"type": "import", "text": "We train TabPFN on streams"}}})["prompt"]
    assert "We train TabPFN on streams" in p2


@test
def js_clusters_are_deterministic_and_cover_nodes():
    st = fresh()
    state = json.load(open(st))
    ids = [n["id"] for n in sc.graph(sc.context(state), state["nodes"][0]["research"], sc.pool_ids(state, "s0"), 3)["nodes"]]
    a = node_eval(st, {"clusters": ids})["clusters"]
    b = node_eval(st, {"clusters": ids})["clusters"]
    assert a == b
    for c in a:
        assert sorted(c["assign"]) == sorted(ids) and len(c["groups"]) >= 2
    # method clusters in the fixture separate rl / heuristic / milp
    by = {p["id"]: p["title"].split(" with ")[-1] for p in state["papers"]}
    for g in a[1]["groups"]:
        assert len({by[i] for i in g["members"]}) == 1, g


@test
def loose_json():
    script = ("const SC=require(process.argv[1]);process.stdout.write(JSON.stringify([SC.parseLooseJSON('```json\\n{\"a\":1}\\n```'),"
              "SC.parseLooseJSON('Sure: {\"a\":2} done')]))")
    p = subprocess.run(["node", "-e", script, os.path.join(ROOT, "assets", "sim-core.js")], capture_output=True, text=True)
    assert json.loads(p.stdout) == [{"a": 1}, {"a": 2}], p.stderr


# ---------------------------------------------------------------- CLI

@test
def init_checks():
    facets = json.load(open(f"{FIX}/facets.json"))
    del facets["W103"]
    json.dump(facets, open(os.path.join(TMP, "f_bad.json"), "w"))
    p = cli("init", "--papers", f"{FIX}/papers.json", "--facets", os.path.join(TMP, "f_bad.json"), "--research",
            f"{FIX}/research.json", "-o", os.path.join(TMP, "x.json"), ok=False)
    assert p.returncode != 0 and "W103" in p.stderr
    state = json.load(open(fresh("h.json", "--hops", "3", "--k1", "4")))
    assert state["config"]["hops"] == 3 and state["config"]["k1"] == 4 and state["anchor"] > 0


@test
def retag_hierarchy_applies_to_later_agent_tags():
    st = fresh()
    json.dump({"problem": {"online-packing": ["bin-packing"], "bin-packing": ["packing"]}, "method": {"ppo": ["deep-rl"]}},
              open(os.path.join(TMP, "h.json"), "w"))
    cli("retag", st, os.path.join(TMP, "h.json"))
    out = cli("retag", st, os.path.join(TMP, "h.json")).stdout
    assert "retagged 0" in out, "retag must be idempotent"
    state = json.load(open(st))
    upd = {"options": [{"label": "x", "projected": {"problem_tags": ["online-packing"], "method_tags": ["ppo"]}}]}
    js = node_eval(st, {"update": {"node": "s0", "body": upd, "action": {"type": "expand"}}})
    sc.apply_update(state, "s0", upd)
    for s2 in (js["afterApply"], state):
        o = s2["nodes"][0]["options"][0]["projected"]
        assert o["problem_tags"] == ["online-packing", "bin-packing", "packing"] and o["method_tags"] == ["ppo", "deep-rl"]


@test
def choose_and_apply_cli():
    st = fresh()
    cli("apply", st, f"{FIX}/update.json", "--node", "s0")
    cli("choose", st, "--option", "2")
    state = json.load(open(st))
    assert state["current"] == "s1" and state["nodes"][1]["move"]["label"].startswith("Transfer")
    cli("choose", st, "--custom", "try real logs")
    state = json.load(open(st))
    assert state["current"] == "s2" and state["nodes"][2]["move"]["custom"] is True
    assert "moves:" not in cli("brief", st).stdout and "graph:" in cli("brief", st).stdout


@test
def validate_flags():
    state = json.load(open(fresh()))
    state["papers"][0]["problem_tags"] = []
    state["current"] = "nope"
    errs, _ = sim.validate(state)
    assert any("problem_tags" in e for e in errs) and any("current" in e for e in errs)


@test
def build_modes_escape_and_parse():
    st = fresh()
    state = json.load(open(st))
    state["papers"][0]["title"] = "Evil </script><script>alert(1)</script> title"
    json.dump(state, open(st, "w"))
    for mode in ("html", "artifact"):
        out = os.path.join(TMP, f"p_{mode}.html")
        cli("build", st, "--mode", mode, "-o", out, "--force")
        page = open(out, encoding="utf-8").read()
        assert page.startswith("<!doctype html>") == (mode == "html")
        m = re.search(r'<script type="application/json" id="sim-state">(.*?)</script>', page, re.S)
        assert "<" not in m.group(1)
        assert json.loads(m.group(1))["papers"][0]["title"].startswith("Evil </script>")
        for tok in ("__STATE_JSON__", "/*__SIMCORE__*/", "__MODE__", "__TITLE__"):
            assert tok not in page
        for i, js in enumerate(re.findall(r"<script>(.*?)</script>", page, re.S)):
            f = os.path.join(TMP, f"chk_{mode}_{i}.js")
            open(f, "w").write(js)
            p = subprocess.run(["node", "--check", f], capture_output=True, text=True)
            assert p.returncode == 0, p.stderr


@test
def collect_merge_dedupes_and_rebuilds_abstracts():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import collect
    recs = [{"id": "https://openalex.org/W1", "display_name": "TabPFN: A Transformer", "cited_by_count": 5,
             "abstract_inverted_index": {"fast": [1], "TabPFN": [0]}},
            {"id": "W2", "title": "TabPFN: a transformer", "cited_by": 900, "doi": "10.1/x", "problem_tags": ["t"]},
            {"id": "W3", "title": "Other", "year": 2020},
            {"id": "W3", "title": "Other", "abstract": "later digest"}, {"title": "no id"}]
    pool = collect.merge(recs)
    assert [p["id"] for p in pool] == ["W2", "W3"], pool
    assert pool[0]["url"] == "https://doi.org/10.1/x" and pool[0]["problem_tags"] == ["t"]
    assert pool[1]["abstract"] == "later digest" and pool[1]["url"] == "https://openalex.org/W3"
    assert collect.norm_record(recs[0])["abstract"] == "TabPFN fast"


def main():
    have_node = shutil.which("node") is not None
    ok = bad = 0
    for fn in TESTS:
        if not have_node and fn.__name__ in ("parity_text_helpers", "parity_anchor_and_graph", "parity_apply_and_choose",
                                             "prompt_protocol", "js_clusters_are_deterministic_and_cover_nodes",
                                             "loose_json", "retag_hierarchy_applies_to_later_agent_tags"):
            print(f"SKIP {fn.__name__} (node not found)")
            continue
        try:
            fn()
            ok += 1
            print(f"ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{ok} passed, {bad} failed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
