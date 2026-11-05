#!/usr/bin/env python3
"""research-simulator CLI (v2).

  init      papers + facets + research status -> state.json (fixes the 0-100 ruler)
  vocab     tag vocabulary report (near-duplicates, singletons)
  retag     rename tags or add broader parent tags everywhere (stored as the tag hierarchy)
  apply     merge an agent update (research / options / add_papers / notes) into a step
  choose    take a move at a step -> new step (then `apply` the agent's follow-up)
  brief     text briefing of a step: status, n-hop graph, moves and their computed effect
  validate  schema checks
  build     inject state into the simulator page (--mode artifact|html)

Agents write text and tags; every number comes from simcore.py / sim-core.js.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simcore as sc  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SCHEMA = "research-simulator/2"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(2)


def cmd_init(a):
    papers = load(a.papers)
    meta_in = {}
    if isinstance(papers, dict):
        meta_in, papers = papers.get("meta", {}), papers["papers"]
    facets = load(a.facets) if a.facets else {}
    if isinstance(facets, list):
        facets = {f["id"]: f for f in facets}
    missing = []
    for p in papers:
        for k, v in (facets.get(p["id"]) or {}).items():
            if k in ("problem", "method", "problem_tags", "method_tags") and v:
                p[k] = v
        for f in sc.FACETS:
            p[f + "_tags"] = sc.uniq([sc.norm_tag(t) for t in p.get(f + "_tags") or []])
        p.pop("hop", None)
        p.pop("via", None)
        p.setdefault("verified", True)
        p.setdefault("origin", "collected")
        if not (p.get("problem") and p.get("method") and p["problem_tags"] and p["method_tags"]):
            missing.append(p["id"])
    if missing:
        die(f"{len(missing)} papers lack facets: " + ", ".join(missing[:20]))
    if len({p["id"] for p in papers}) != len(papers):
        die("duplicate paper ids")
    research = sc.clean_research(load(a.research))
    if not (research["problem"] and research["method"] and research["problem_tags"] and research["method_tags"]):
        die("research status needs problem, method, problem_tags and method_tags")
    state = {
        "schema": SCHEMA,
        "meta": {"title": a.title or research.get("title") or "Research simulator", "created": dt.date.today().isoformat(),
                 "source": meta_in.get("source", ""), "queries": meta_in.get("queries", []),
                 "status_source": a.status_source or ""},
        "config": {"alpha": 0.75, "hops": a.hops, "k1": a.k1, "k": a.k, "max_nodes": 90, "min_sim": 0.03},
        "papers": papers, "hierarchy": {"problem": {}, "method": {}},
        "nodes": [{"id": "s0", "parent": None, "move": None, "research": research, "options": [],
                   "status": "pending", "notes": ""}],
        "current": "s0",
    }
    state["anchor"] = sc.compute_anchor(state)
    save(a.out, state)
    g = sc.graph(sc.context(state), research, sc.pool_ids(state, "s0"))
    print(f"wrote {a.out}: pool {len(papers)} papers, graph {len(g['nodes'])} nodes to hop {g['depth']} "
          f"(hops={a.hops}, k1={a.k1}, k={a.k}), anchor {state['anchor']:.3f}")
    vocab_report(state, brief=True)


def vocab_report(state, brief=False):
    for f in sc.FACETS:
        c = {}
        for p in state["papers"]:
            for t in sc.tags_of(p, f):
                c[t] = c.get(t, 0) + 1
        tags = sorted(c, key=lambda t: (-c[t], t))
        single = [t for t in tags if c[t] == 1]
        near = [(t, u) for i, t in enumerate(tags) for u in tags[i + 1:]
                if difflib.SequenceMatcher(None, t, u).ratio() >= 0.84 or set(t.split("-")) == set(u.split("-"))]
        print(f"{f}: {len(tags)} tags, {len(single)} used once")
        if not brief:
            print("  " + ", ".join(f"{t}({c[t]})" for t in tags))
        if near:
            print("  possible duplicates: " + "; ".join(f"{t} ~ {u}" for t, u in near[:25]))
        if tags and len(single) / len(tags) > 0.6:
            print("  warning: most tags are used once; merge synonyms or add parent tags (sim.py retag)")


def cmd_vocab(a):
    vocab_report(load(a.state))


def cmd_retag(a):
    """map value: "new-tag" renames; ["broader", ...] keeps the tag and adds broader ones."""
    state = load(a.state)
    m = load(a.map)
    maps = m if set(m) <= {"problem", "method"} else {"problem": m, "method": m}
    maps = {f: {sc.norm_tag(k): (sc.uniq([sc.norm_tag(k)] + [sc.norm_tag(x) for x in v]) if isinstance(v, list)
                                 else [sc.norm_tag(v)])
                for k, v in maps.get(f, {}).items()} for f in sc.FACETS}
    hier = state.setdefault("hierarchy", {"problem": {}, "method": {}})
    for f in sc.FACETS:
        for k, v in maps[f].items():
            if len(v) > 1 and v[0] == k:
                hier.setdefault(f, {})[k] = v
    n = 0

    def fix(obj):
        nonlocal n
        for f in sc.FACETS:
            key = f + "_tags"
            if obj.get(key):
                new = sc.expand_tags(obj[key], maps, f)
                if new != obj[key]:
                    n += 1
                obj[key] = new

    for p in state["papers"]:
        fix(p)
    for nd in state["nodes"]:
        fix(nd["research"])
        for o in nd.get("options") or []:
            fix(o["projected"])
    if a.reanchor:
        state["anchor"] = sc.compute_anchor(state)
    save(a.state, state)
    print(f"retagged {n} objects" + ("; re-anchored" if a.reanchor else ""))


def cmd_apply(a):
    state = load(a.state)
    node = a.node or state["current"]
    s = sc.apply_update(state, node, load(a.update), {"type": a.action})
    save(a.state, state)
    print(f"step {node}: {s['options']} moves, {s['papers']} papers added, {s['verified']} verified"
          + (", status updated" if s["research"] else ""))
    unv = [p for p in state["papers"] if p.get("introduced_at") == node and p.get("verified") is False]
    if unv:
        print(f"  {len(unv)} added papers are unverified (no url/doi)")
    if a.brief:
        print(brief_text(state, node))


def cmd_choose(a):
    state = load(a.state)
    node = sc.node_by_id(state, a.node or state["current"])
    if not node:
        die("unknown step")
    if a.custom:
        child = sc.new_child(state, node["id"], {"label": a.custom, "kind": "other", "custom": True})
    else:
        opt = next((o for o in node.get("options") or [] if o["id"] == a.option or o["id"].startswith(f"{node['id']}-{a.option}-")), None)
        if not opt:
            die("move not found; have: " + ", ".join(o["id"] for o in node.get("options") or []))
        child = sc.new_child(state, node["id"], opt)
    state["current"] = child["id"]
    save(a.state, state)
    print(f"step {child['id']} created. Write the agent follow-up and run: "
          f"sim.py apply {a.state} update.json --node {child['id']}" + (" --action custom" if a.custom else ""))


def brief_text(state, node_id, hops=None):
    ctx = sc.context(state)
    node = sc.node_by_id(state, node_id)
    r = node["research"]
    by = {p["id"]: p for p in state["papers"]}
    pool = sc.pool_ids(state, node_id)
    g = sc.graph(ctx, r, pool, hops)
    L = [f"# step {node_id}: {node['move']['label'] if node.get('move') else 'start'}",
         f"problem: {r['problem']}  [{', '.join(r['problem_tags'])}]",
         f"method:  {r['method']}  [{', '.join(r['method_tags'])}]"]
    for s in r["status"]:
        L.append(f"  [{s['kind']}] {s['text']}" + (f" -> {s['result']}" if s.get("result") else ""))
    L.append(f"graph: {len(g['nodes'])} papers to hop {g['depth']}, hop-1 mean relatedness {g['reach']:.1f}")
    for n in g["nodes"]:
        ind = "  " * n["hop"]
        L.append(f"{ind}{n['score']:5.1f}  edge {next(e['w'] for e in g['edges'] if e['b'] == n['id']):5.1f}  "
                 f"{by[n['id']]['title'][:80]}{'' if by[n['id']].get('verified', True) else '  [unverified]'}")
    if node.get("options"):
        L.append("moves:")
        for i, o in enumerate(node["options"], 1):
            g2 = sc.graph(ctx, o["projected"], pool, hops)
            new = len({n["id"] for n in g2["nodes"]} - {n["id"] for n in g["nodes"]})
            L.append(f"  {i}. [{o['kind']}] {o['label']}  -> hop-1 mean {g2['reach']:.1f} ({g2['reach'] - g['reach']:+.1f}), "
                     f"{new} papers enter")
    return "\n".join(L)


def cmd_brief(a):
    state = load(a.state)
    print(brief_text(state, a.node or state["current"], a.hops))


def validate(state):
    errs, warns = [], []
    if state.get("schema") != SCHEMA:
        errs.append(f"schema should be {SCHEMA}")
    ids = [p.get("id") for p in state.get("papers", [])]
    if len(set(ids)) != len(ids):
        errs.append("duplicate paper ids")
    for p in state.get("papers", []):
        for k in ("title", "problem", "method"):
            if not p.get(k):
                errs.append(f"paper {p.get('id')} missing {k}")
        for f in sc.FACETS:
            if not p.get(f + "_tags"):
                errs.append(f"paper {p.get('id')} has no {f}_tags")
    nids = [n["id"] for n in state.get("nodes", [])]
    if len(set(nids)) != len(nids):
        errs.append("duplicate step ids")
    for n in state.get("nodes", []):
        if n.get("parent") and n["parent"] not in nids:
            errs.append(f"step {n['id']} parent missing")
        for k in ("problem_tags", "method_tags"):
            if not n["research"].get(k):
                errs.append(f"step {n['id']} research has no {k}")
    if state.get("current") not in nids:
        errs.append("current step missing")
    if not state.get("anchor"):
        warns.append("no anchor; the page will compute one")
    cur = sc.node_by_id(state, state.get("current")) if state.get("current") in nids else None
    if cur and not cur.get("options"):
        warns.append("current step has no moves yet")
    return errs, warns


def cmd_validate(a):
    errs, warns = validate(load(a.state))
    for w in warns:
        print("warn: " + w)
    for e in errs:
        print("ERROR: " + e)
    print("OK" if not errs else f"{len(errs)} errors")
    sys.exit(1 if errs else 0)


SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>:root{{color-scheme:dark;padding:env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0)}}'
            'body{{margin:0;font:14px system-ui,sans-serif}}img{{max-width:100%}}[hidden]{{display:none!important}}'
            '</style></head><body>\n{body}\n</body></html>\n')


def build_page(state, mode):
    with open(os.path.join(ASSETS, "template.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    with open(os.path.join(ASSETS, "sim-core.js"), encoding="utf-8") as fh:
        core = fh.read()
    # escape every "<" so nothing in the data can close or confuse the script block
    data = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    title = (state.get("meta", {}).get("title") or "Research simulator").replace("<", "").replace("&", "and")
    page = (tpl.replace("__TITLE__", title).replace("__MODE__", mode)
               .replace("/*__SIMCORE__*/", core.replace("</script", "<\\/script"))
               .replace("__STATE_JSON__", data))
    return SKELETON.format(body=page) if mode == "html" else page


def cmd_build(a):
    state = load(a.state)
    errs, warns = validate(state)
    if errs and not a.force:
        die("state has errors (run validate; --force to build anyway): " + "; ".join(errs[:5]))
    page = build_page(state, a.mode)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {a.out} ({len(page) // 1024} KB, mode={a.mode})" + (f"; {len(warns)} warnings" if warns else ""))
    if a.mode == "artifact":
        print('publish with the Artifact tool, capabilities {"sample": {}, "downloads": true}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--papers", required=True); p.add_argument("--facets"); p.add_argument("--research", required=True)
    p.add_argument("--hops", type=int, default=2); p.add_argument("--k1", type=int, default=6); p.add_argument("--k", type=int, default=3)
    p.add_argument("--title"); p.add_argument("--status-source", help="where the research status came from")
    p.add_argument("-o", "--out", default="state.json"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("vocab"); p.add_argument("state"); p.set_defaults(fn=cmd_vocab)
    p = sub.add_parser("retag"); p.add_argument("state"); p.add_argument("map")
    p.add_argument("--reanchor", action="store_true"); p.set_defaults(fn=cmd_retag)
    p = sub.add_parser("apply"); p.add_argument("state"); p.add_argument("update"); p.add_argument("--node")
    p.add_argument("--action", default="expand", choices=["expand", "custom", "refresh", "import"])
    p.add_argument("--brief", action="store_true"); p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("choose"); p.add_argument("state"); p.add_argument("--node")
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--option", help="move id or its number"); g.add_argument("--custom")
    p.set_defaults(fn=cmd_choose)
    p = sub.add_parser("brief"); p.add_argument("state"); p.add_argument("--node"); p.add_argument("--hops", type=int)
    p.set_defaults(fn=cmd_brief)
    p = sub.add_parser("validate"); p.add_argument("state"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("build"); p.add_argument("state"); p.add_argument("--mode", choices=["artifact", "html"], default="html")
    p.add_argument("-o", "--out", default="simulator.html"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_build)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
