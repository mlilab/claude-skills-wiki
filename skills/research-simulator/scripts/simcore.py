"""Python mirror of assets/sim-core.js (v2): scoring, the n-hop graph and the agent-update merge.

The page computes everything with sim-core.js; this module gives the CLI the same numbers
(init/anchor, brief, apply). tests/run_tests.py checks parity with the JS implementation.
"""
from __future__ import annotations

import json
import math
import re

FACETS = ("problem", "method")
KINDS = ("problem", "method", "data", "evaluation", "scope", "positioning", "other")
STOP = set((
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "we our us via using use based new approach approaches method methods problem problems paper propose proposed study "
    "into over under than then these those which while can also such both each more most other only their them they "
    "not no but if how what when where who why all any between through towards toward without within upon per vs "
    "show shows shown results result task tasks").split())
_TOK = re.compile(r"[^\W_]+")


def tokenize(text):
    out = []
    for w in _TOK.findall(str(text or "").lower()):
        if len(w) < 2 or w in STOP:
            continue
        if len(w) > 4 and w[-1] == "s" and w[-2] != "s":
            w = w[:-1]
        out.append(w)
    return out


def norm_tag(t):
    s = str("" if t is None else t).lower().strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^\w\-+.]", "", s).replace("_", "")
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def uniq(xs):
    seen, out = set(), []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def expand_tags(tags, hier, f):
    m = (hier or {}).get(f) or {}
    cur = uniq([norm_tag(t) for t in tags or []])
    for _ in range(8):
        nxt = []
        for t in cur:
            e = m.get(t)
            nxt += [norm_tag(x) for x in e] if e else [t]
        nxt = uniq(nxt)
        if nxt == cur:
            break
        cur = nxt
    return cur


def tags_of(obj, f):
    return uniq([norm_tag(t) for t in ((obj or {}).get(f + "_tags") or [])])


def idf(df, n):
    return math.log((n + 1) / (df + 1)) + 1


def build_stats(papers):
    base = [p for p in papers if p.get("verified") is not False]
    st = {"N": len(base), "tagDf": {f: {} for f in FACETS}, "txtDf": {f: {} for f in FACETS}}
    for p in base:
        for f in FACETS:
            for t in tags_of(p, f):
                st["tagDf"][f][t] = st["tagDf"][f].get(t, 0) + 1
            for w in uniq(tokenize(p.get(f))):
                st["txtDf"][f][w] = st["txtDf"][f].get(w, 0) + 1
    return st


class Vec:
    __slots__ = ("v", "keys", "norm")

    def __init__(self, v):
        self.v, self.keys = v, sorted(v)
        n = 0.0
        for k in self.keys:
            n += v[k] * v[k]
        self.norm = math.sqrt(n)


def tag_vec(obj, f, st):
    return Vec({t: idf(st["tagDf"][f].get(t, 0), st["N"]) for t in tags_of(obj, f)})


def txt_vec(obj, f, st):
    c = {}
    for w in tokenize((obj or {}).get(f)):
        c[w] = c.get(w, 0) + 1
    return Vec({w: (1 + math.log(k)) * idf(st["txtDf"][f].get(w, 0), st["N"]) for w, k in c.items()})


def cos(a, b):
    if not a.norm or not b.norm:
        return 0.0
    small, big = (a, b) if len(a.keys) <= len(b.keys) else (b, a)
    dot = 0.0
    for k in small.keys:
        if k in big.v:
            dot += small.v[k] * big.v[k]
    return dot / (a.norm * b.norm)


def prep(obj, st):
    return {f: {"tag": tag_vec(obj, f, st), "txt": txt_vec(obj, f, st)} for f in FACETS}


def facet_sim(pa, pb, f, alpha):
    a, b = pa[f], pb[f]
    wsum = s = 0.0
    if a["tag"].norm and b["tag"].norm:
        wsum += alpha
        s += alpha * cos(a["tag"], b["tag"])
    if a["txt"].norm and b["txt"].norm:
        wsum += 1 - alpha
        s += (1 - alpha) * cos(a["txt"], b["txt"])
    return s / wsum if wsum > 0 else 0.0


def pair_sim(pa, pb, alpha):
    return {"problem": facet_sim(pa, pb, "problem", alpha), "method": facet_sim(pa, pb, "method", alpha)}


def overall(s):
    return (s["problem"] + s["method"]) / 2


def cfg(state):
    c = (state or {}).get("config") or {}
    g = lambda k, d: d if c.get(k) is None else float(c[k])
    return {"alpha": g("alpha", 0.75), "hops": g("hops", 2), "k1": g("k1", 6), "k": g("k", 3),
            "max_nodes": g("max_nodes", 90), "min_sim": g("min_sim", 0.03)}


class Ctx:
    def __init__(self, state):
        self.state = state
        self.st = build_stats(state.get("papers") or [])
        self.pv = {p["id"]: prep(p, self.st) for p in state.get("papers") or []}
        self.cfg = cfg(state)
        self.cache = {}


def context(state):
    return Ctx(state)


def pp_sim(ctx, a, b):
    key = (a, b) if a < b else (b, a)
    if key not in ctx.cache:
        ctx.cache[key] = pair_sim(ctx.pv[a], ctx.pv[b], ctx.cfg["alpha"])
    return ctx.cache[key]


def root_node(state):
    for n in state.get("nodes") or []:
        if not n.get("parent"):
            return n
    ns = state.get("nodes") or []
    return ns[0] if ns else None


def node_by_id(state, nid):
    for n in state.get("nodes") or []:
        if n["id"] == nid:
            return n
    return None


def path_to(state, nid):
    out, n, guard = [], node_by_id(state, nid), 0
    while n and guard < 1000:
        out.insert(0, n["id"])
        n = node_by_id(state, n["parent"]) if n.get("parent") else None
        guard += 1
    return out


def pool_ids(state, node_id):
    path = set(path_to(state, node_id))
    return [p["id"] for p in state.get("papers") or [] if not p.get("introduced_at") or p["introduced_at"] in path]


def compute_anchor(state, ctx=None):
    ctx = ctx or context(state)
    ids = [p["id"] for p in state.get("papers") or [] if p.get("verified") is not False]
    root = root_node(state)
    rp = prep(root["research"], ctx.st) if root else None
    vals = []
    for i, a in enumerate(ids):
        if rp:
            r = overall(pair_sim(rp, ctx.pv[a], ctx.cfg["alpha"]))
            if r > 0:
                vals.append(r)
        for b in ids[i + 1:]:
            v = overall(pp_sim(ctx, a, b))
            if v > 0:
                vals.append(v)
    if not vals:
        return 1.0
    vals.sort()
    return vals[int(math.floor(0.99 * (len(vals) - 1)))]


def anchor_of(state, ctx=None):
    a = state.get("anchor")
    return a if a and a > 0 else compute_anchor(state, ctx)


def scale(state, ctx, raw):
    return min(100.0, 100 * raw / anchor_of(state, ctx))


def graph(ctx, research, ids, hops=None, opts=None):
    c = dict(ctx.cfg, **(opts or {}))
    hops = max(1, min(8, int(math.floor(hops or c["hops"]))))
    rp = prep(research, ctx.st)
    to_r = {}
    for i in ids:
        s = pair_sim(rp, ctx.pv[i], c["alpha"])
        to_r[i] = dict(s, overall=overall(s))
    placed, nodes, edges, frontier = set(), [], [], []
    for i in sorted(ids, key=lambda x: (-to_r[x]["overall"], x)):
        if len(frontier) >= c["k1"]:
            break
        if to_r[i]["overall"] < c["min_sim"]:
            break
        placed.add(i)
        frontier.append(i)
        nodes.append({"id": i, "hop": 1, "parent": "@"})
        edges.append({"a": "@", "b": i, "raw": to_r[i]["overall"]})
    h = 2
    while h <= hops and frontier and len(nodes) < c["max_nodes"]:
        pairs = []
        for f in frontier:
            for x in ids:
                if x in placed:
                    continue
                s = overall(pp_sim(ctx, f, x))
                if s >= c["min_sim"]:
                    pairs.append((s, f, x))
        pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
        count, nxt = {}, []
        for s, f, x in pairs:
            if len(nodes) >= c["max_nodes"]:
                break
            if x in placed or count.get(f, 0) >= c["k"]:
                continue
            placed.add(x)
            count[f] = count.get(f, 0) + 1
            nxt.append(x)
            nodes.append({"id": x, "hop": h, "parent": f})
            edges.append({"a": f, "b": x, "raw": s})
        frontier = nxt
        h += 1
    for n in nodes:
        t = to_r[n["id"]]
        n["score"] = scale(ctx.state, ctx, t["overall"])
        n["problem"] = scale(ctx.state, ctx, t["problem"])
        n["method"] = scale(ctx.state, ctx, t["method"])
    for e in edges:
        e["w"] = scale(ctx.state, ctx, e["raw"])
    hop1 = [n for n in nodes if n["hop"] == 1]
    reach = 0.0
    if hop1:
        acc = 0
        for n in hop1:
            acc += n["score"]
        reach = acc / len(hop1)
    return {"nodes": nodes, "edges": edges, "reach": reach, "depth": max([n["hop"] for n in nodes], default=0)}


# ---------------------------------------------------------------- research status & updates

def clean_status(items):
    out = []
    for it in (items if isinstance(items, list) else [])[:16]:
        if isinstance(it, str):
            kind = "todo" if re.match(r"^\s*\[?todo", it, re.I) else "done"
            it = {"kind": kind, "text": re.sub(r"^\s*\[?(todo|done)\]?\s*[:\-]?\s*", "", it, flags=re.I)}
        it = it or {}
        o = {"kind": it.get("kind") if it.get("kind") in ("done", "todo", "note") else "note",
             "text": str(it.get("text") or "")[:300]}
        if it.get("result"):
            o["result"] = str(it["result"])[:300]
        if o["text"]:
            out.append(o)
    return out


def clean_research(r, fallback=None, hier=None):
    r, fb = r or {}, fallback or {}
    out = {
        "title": str(r.get("title") or fb.get("title") or "")[:200],
        "problem": str(r.get("problem") or fb.get("problem") or "")[:1200],
        "method": str(r.get("method") or fb.get("method") or "")[:1200],
        "problem_tags": expand_tags(r["problem_tags"] if isinstance(r.get("problem_tags"), list)
                                    else fb.get("problem_tags") or [], hier, "problem")[:20],
        "method_tags": expand_tags(r["method_tags"] if isinstance(r.get("method_tags"), list)
                                   else fb.get("method_tags") or [], hier, "method")[:20],
        "status": clean_status(r["status"] if isinstance(r.get("status"), list) else fb.get("status")),
    }
    if isinstance(r.get("todo"), list):
        todos = clean_status([{"kind": "todo", "text": t if isinstance(t, str) else (t or {}).get("text")}
                              for t in r["todo"]])
        for t in todos:
            if not any(s["text"] == t["text"] for s in out["status"]):
                out["status"].append(t)
        out["status"] = out["status"][:16]
    return out


def clean_option(o, base, i, prefix, hier=None):
    o = o or {}
    label = str(o.get("label") or o.get("title") or f"Move {i + 1}")[:140]
    return {"id": str(o.get("id") or f"{prefix}-{i + 1}-{norm_tag(label)[:40] or 'opt'}")[:80],
            "label": label, "kind": o.get("kind") if o.get("kind") in KINDS else "other",
            "why": str(o.get("why") or o.get("rationale") or "")[:400],
            "projected": clean_research(o.get("projected") or {}, base, hier)}


def norm_title(t):
    return re.sub(r"[\W_]+", " ", str(t or "").lower()).strip()


def hash_str(s):
    h = 2166136261
    for ch in s:
        cp = ord(ch)
        units = [cp] if cp < 0x10000 else [0xD800 + ((cp - 0x10000) >> 10), 0xDC00 + ((cp - 0x10000) & 0x3FF)]
        for u in units:
            h ^= u
            h = (h * 16777619) & 0xFFFFFFFF
    digits, s2 = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    if h == 0:
        return "0"
    while h:
        h, r = divmod(h, 36)
        s2 = digits[r] + s2
    return s2


def apply_update(state, node_id, upd, action=None):
    node = node_by_id(state, node_id)
    if not node:
        raise ValueError(f"unknown node {node_id}")
    upd = upd or {}
    summary = {"options": 0, "papers": 0, "verified": 0, "research": False}
    hier = state.get("hierarchy")
    if upd.get("research"):
        node["research"] = clean_research(upd["research"], node["research"], hier)
        summary["research"] = True
    raw = upd.get("options") if isinstance(upd.get("options"), list) else upd.get("moves") if isinstance(upd.get("moves"), list) else []
    opts = [clean_option(o, node["research"], i, node["id"], hier) for i, o in enumerate(raw[:7])]
    seen = set()
    for o in opts:
        while o["id"] in seen:
            o["id"] += "_"
        seen.add(o["id"])
    if opts:
        node["options"] = opts
        summary["options"] = len(opts)
    known = {norm_title(p["title"]): p for p in state["papers"]}
    for p in (upd.get("add_papers") or [])[:10]:
        if not p or not p.get("title"):
            continue
        linked = bool(p.get("url") or p.get("doi") or p.get("openalex"))
        ex = known.get(norm_title(p["title"]))
        if ex:
            if ex.get("verified") is False and p.get("verified") is True and linked:
                ex["verified"] = True
                ex["url"] = str(p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi")
                                                  else f"https://openalex.org/{p['openalex']}"))
                if p.get("doi"):
                    ex["doi"] = str(p["doi"])
                summary["verified"] += 1
            continue
        paper = {
            "id": "x" + hash_str(norm_title(p["title"])), "title": str(p["title"])[:300],
            "year": int(p["year"]) if str(p.get("year") or "").isdigit() else None,
            "venue": str(p.get("venue") or "")[:120], "url": str(p.get("url") or ""), "doi": str(p.get("doi") or ""),
            "problem": str(p.get("problem") or "")[:800], "method": str(p.get("method") or "")[:800],
            "problem_tags": expand_tags(p.get("problem_tags") or [], hier, "problem")[:16],
            "method_tags": expand_tags(p.get("method_tags") or [], hier, "method")[:16],
            "why": str(p.get("why") or p.get("relation") or "")[:300],
            "verified": p.get("verified") is True and linked, "origin": "agent", "introduced_at": node["id"],
        }
        state["papers"].append(paper)
        known[norm_title(p["title"])] = paper
        summary["papers"] += 1
    if upd.get("notes"):
        node["notes"] = str(upd["notes"])[:800]
    node["status"] = "ready"
    return summary


def new_child(state, parent_id, move):
    parent = node_by_id(state, parent_id)
    n = 0
    for x in state["nodes"]:
        k = re.sub(r"^s", "", str(x["id"]))
        if k.isdigit() and int(k) >= n:
            n = int(k) + 1
    child = {"id": f"s{n}", "parent": parent_id,
             "move": {"label": move["label"], "kind": move.get("kind", "other"), "custom": bool(move.get("custom"))},
             "research": (clean_research(move["projected"], parent["research"], state.get("hierarchy"))
                          if move.get("projected") else json.loads(json.dumps(parent["research"]))),
             "options": [], "status": "pending", "notes": ""}
    state["nodes"].append(child)
    return child
