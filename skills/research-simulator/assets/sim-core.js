/* research-simulator core (v2) — single source of truth for every number on screen.
 * Browser (simulator page) and node (tests). scripts/simcore.py mirrors scoring, the hop graph and the
 * update merge; tests/run_tests.py checks they agree.
 *
 * Agents only ever write TEXT and TAGS (research status, moves, paper facets). Relatedness, the hop
 * graph and edge weights are computed here.
 */
(function (root) {
  'use strict';

  var FACETS = ['problem', 'method'];
  var KINDS = ['problem', 'method', 'data', 'evaluation', 'scope', 'positioning', 'other'];
  var STOP = new Set(('a an and are as at be by for from has have in is it its of on or that the this to was were will with ' +
    'we our us via using use based new approach approaches method methods problem problems paper propose proposed study ' +
    'into over under than then these those which while can also such both each more most other only their them they ' +
    'not no but if how what when where who why all any between through towards toward without within upon per vs ' +
    'show shows shown results result task tasks').split(/\s+/));

  function tokenize(text) {
    var out = [], m = String(text || '').toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
    for (var i = 0; i < m.length; i++) {
      var w = m[i];
      if (w.length < 2 || STOP.has(w)) continue;
      if (w.length > 4 && w.charAt(w.length - 1) === 's' && w.charAt(w.length - 2) !== 's') w = w.slice(0, -1);
      out.push(w);
    }
    return out;
  }

  function normTag(t) {
    return String(t == null ? '' : t).toLowerCase().trim()
      .replace(/[\s_]+/g, '-').replace(/[^\p{L}\p{N}\-+.]/gu, '').replace(/-+/g, '-').replace(/^-+|-+$/g, '');
  }

  function uniq(arr) {
    var seen = new Set(), out = [];
    for (var i = 0; i < arr.length; i++) if (arr[i] && !seen.has(arr[i])) { seen.add(arr[i]); out.push(arr[i]); }
    return out;
  }

  /* Tag hierarchy {facet: {tag: [tag, broader...]}}, expanded to a fixed point. */
  function expandTags(tags, hier, f) {
    var map = (hier && hier[f]) || {}, cur = uniq((tags || []).map(normTag));
    for (var i = 0; i < 8; i++) {
      var nxt = [];
      cur.forEach(function (t) {
        var e = Object.prototype.hasOwnProperty.call(map, t) ? map[t] : null;
        if (!e) nxt.push(t); else e.forEach(function (x) { nxt.push(normTag(x)); });
      });
      nxt = uniq(nxt);
      if (nxt.join('|') === cur.join('|')) break;
      cur = nxt;
    }
    return cur;
  }

  function tagsOf(obj, f) { return uniq(((obj && obj[f + '_tags']) || []).map(normTag)); }
  function idf(df, N) { return Math.log((N + 1) / (df + 1)) + 1; }

  /* Corpus statistics over verified papers only, so unverified suggestions never move real scores. */
  function buildStats(papers) {
    var base = papers.filter(function (p) { return p.verified !== false; });
    var st = { N: base.length, tagDf: { problem: {}, method: {} }, txtDf: { problem: {}, method: {} } };
    base.forEach(function (p) {
      FACETS.forEach(function (f) {
        tagsOf(p, f).forEach(function (t) { st.tagDf[f][t] = (st.tagDf[f][t] || 0) + 1; });
        uniq(tokenize(p[f])).forEach(function (w) { st.txtDf[f][w] = (st.txtDf[f][w] || 0) + 1; });
      });
    });
    return st;
  }

  function finish(v) {
    var keys = Object.keys(v).sort(), n = 0;
    for (var i = 0; i < keys.length; i++) n += v[keys[i]] * v[keys[i]];
    return { v: v, keys: keys, norm: Math.sqrt(n) };
  }
  function tagVec(obj, f, st) {
    var v = {};
    tagsOf(obj, f).forEach(function (t) { v[t] = idf(st.tagDf[f][t] || 0, st.N); });
    return finish(v);
  }
  function txtVec(obj, f, st) {
    var c = {}, v = {};
    tokenize(obj && obj[f]).forEach(function (w) { c[w] = (c[w] || 0) + 1; });
    Object.keys(c).forEach(function (w) { v[w] = (1 + Math.log(c[w])) * idf(st.txtDf[f][w] || 0, st.N); });
    return finish(v);
  }
  function cos(a, b) {
    if (!a.norm || !b.norm) return 0;
    var small = a.keys.length <= b.keys.length ? a : b, big = small === a ? b : a, dot = 0;
    for (var i = 0; i < small.keys.length; i++) {
      var k = small.keys[i];
      if (Object.prototype.hasOwnProperty.call(big.v, k)) dot += small.v[k] * big.v[k];
    }
    return dot / (a.norm * b.norm);
  }
  function prep(obj, st) {
    var r = {};
    FACETS.forEach(function (f) { r[f] = { tag: tagVec(obj, f, st), txt: txtVec(obj, f, st) }; });
    return r;
  }
  /* facet similarity in [0,1]: alpha * tag cosine + (1 - alpha) * text cosine, renormalised. */
  function facetSim(pa, pb, f, alpha) {
    var a = pa[f], b = pb[f], wsum = 0, s = 0;
    if (a.tag.norm && b.tag.norm) { wsum += alpha; s += alpha * cos(a.tag, b.tag); }
    if (a.txt.norm && b.txt.norm) { wsum += 1 - alpha; s += (1 - alpha) * cos(a.txt, b.txt); }
    return wsum > 0 ? s / wsum : 0;
  }
  function pairSim(pa, pb, alpha) {
    return { problem: facetSim(pa, pb, 'problem', alpha), method: facetSim(pa, pb, 'method', alpha) };
  }
  function overall(s) { return (s.problem + s.method) / 2; }

  function cfg(state) {
    var c = (state && state.config) || {};
    return {
      alpha: c.alpha == null ? 0.75 : +c.alpha,
      hops: c.hops == null ? 2 : +c.hops,
      k1: c.k1 == null ? 6 : +c.k1,
      k: c.k == null ? 3 : +c.k,
      max_nodes: c.max_nodes == null ? 90 : +c.max_nodes,
      min_sim: c.min_sim == null ? 0.03 : +c.min_sim
    };
  }

  function context(state) {
    var st = buildStats(state.papers || []), pv = {};
    (state.papers || []).forEach(function (p) { pv[p.id] = prep(p, st); });
    return { st: st, pv: pv, cfg: cfg(state), state: state, cache: {} };
  }

  function ppSim(ctx, a, b) {
    var key = a < b ? a + '|' + b : b + '|' + a;
    if (!(key in ctx.cache)) ctx.cache[key] = pairSim(ctx.pv[a], ctx.pv[b], ctx.cfg.alpha);
    return ctx.cache[key];
  }

  /* The 0-100 ruler: 99th percentile of positive overall similarity over all pairs of verified papers
   * and the root research. Computed once at init and stored, so every step is measured the same way. */
  function computeAnchor(state, ctx) {
    ctx = ctx || context(state);
    var ids = (state.papers || []).filter(function (p) { return p.verified !== false; }).map(function (p) { return p.id; });
    var root = rootNode(state), vals = [];
    var rp = root ? prep(root.research, ctx.st) : null;
    for (var i = 0; i < ids.length; i++) {
      if (rp) { var r = overall(pairSim(rp, ctx.pv[ids[i]], ctx.cfg.alpha)); if (r > 0) vals.push(r); }
      for (var j = i + 1; j < ids.length; j++) { var v = overall(ppSim(ctx, ids[i], ids[j])); if (v > 0) vals.push(v); }
    }
    if (!vals.length) return 1;
    vals.sort(function (a, b) { return a - b; });
    return vals[Math.floor(0.99 * (vals.length - 1))];
  }
  function anchorOf(state, ctx) { return state.anchor > 0 ? state.anchor : computeAnchor(state, ctx); }
  function scale(state, ctx, raw) { return Math.min(100, 100 * raw / anchorOf(state, ctx)); }

  /* ---------- decision tree ---------- */
  function rootNode(state) {
    var ns = state.nodes || [];
    for (var i = 0; i < ns.length; i++) if (!ns[i].parent) return ns[i];
    return ns[0];
  }
  function nodeById(state, id) {
    var ns = state.nodes || [];
    for (var i = 0; i < ns.length; i++) if (ns[i].id === id) return ns[i];
    return null;
  }
  function pathTo(state, id) {
    var out = [], n = nodeById(state, id), guard = 0;
    while (n && guard++ < 1000) { out.unshift(n.id); n = n.parent ? nodeById(state, n.parent) : null; }
    return out;
  }
  /* Papers available at a step: everything collected plus papers agents added on this branch. */
  function poolIds(state, nodeId) {
    var path = new Set(pathTo(state, nodeId));
    return (state.papers || []).filter(function (p) { return !p.introduced_at || path.has(p.introduced_at); })
      .map(function (p) { return p.id; });
  }

  /* ---------- the n-hop graph ----------
   * hop 1   = the k1 papers most related to the research.
   * hop h+1 = for each hop-h paper, its k most related papers not yet placed (each paper placed once,
   *           strongest pair first). Edge weight = relatedness of the two ends, 0-100. */
  function graph(ctx, research, ids, hops, opts) {
    var c = Object.assign({}, ctx.cfg, opts || {});
    hops = Math.max(1, Math.min(8, Math.floor(hops || c.hops)));
    var rp = prep(research, ctx.st), toR = {};
    ids.forEach(function (id) {
      var s = pairSim(rp, ctx.pv[id], c.alpha);
      toR[id] = { problem: s.problem, method: s.method, overall: overall(s) };
    });
    var placed = {}, nodes = [], edges = [];
    var sorted = ids.slice().sort(function (a, b) { return toR[b].overall - toR[a].overall || (a < b ? -1 : 1); });
    var frontier = [];
    for (var i = 0; i < sorted.length && frontier.length < c.k1; i++) {
      var id = sorted[i];
      if (toR[id].overall < c.min_sim) break;
      placed[id] = 1; frontier.push(id);
      nodes.push({ id: id, hop: 1, parent: '@' });
      edges.push({ a: '@', b: id, raw: toR[id].overall });
    }
    for (var h = 2; h <= hops && frontier.length && nodes.length < c.max_nodes; h++) {
      var pairs = [];
      frontier.forEach(function (f) {
        ids.forEach(function (x) {
          if (placed[x]) return;
          var s = overall(ppSim(ctx, f, x));
          if (s >= c.min_sim) pairs.push([s, f, x]);
        });
      });
      pairs.sort(function (p, q) { return q[0] - p[0] || (p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : (p[2] < q[2] ? -1 : 1)); });
      var count = {}, next = [];
      for (var j = 0; j < pairs.length && nodes.length < c.max_nodes; j++) {
        var s2 = pairs[j][0], f2 = pairs[j][1], x2 = pairs[j][2];
        if (placed[x2] || (count[f2] || 0) >= c.k) continue;
        placed[x2] = 1; count[f2] = (count[f2] || 0) + 1; next.push(x2);
        nodes.push({ id: x2, hop: h, parent: f2 });
        edges.push({ a: f2, b: x2, raw: s2 });
      }
      frontier = next;
    }
    nodes.forEach(function (n) {
      var t = toR[n.id];
      n.score = scale(ctx.state, ctx, t.overall);
      n.problem = scale(ctx.state, ctx, t.problem);
      n.method = scale(ctx.state, ctx, t.method);
    });
    edges.forEach(function (e) { e.w = scale(ctx.state, ctx, e.raw); });
    var hop1 = nodes.filter(function (n) { return n.hop === 1; });
    return {
      nodes: nodes, edges: edges,
      reach: hop1.length ? hop1.reduce(function (a, n) { return a + n.score; }, 0) / hop1.length : 0,
      depth: nodes.reduce(function (m, n) { return Math.max(m, n.hop); }, 0)
    };
  }

  /* ---------- clustering of the visible papers by one facet (layout only) ---------- */
  function kMedoids(D, k) {
    var n = D.length, med = [], i, p;
    var tot = D.map(function (row) { return row.reduce(function (a, b) { return a + b; }, 0); });
    var first = 0; for (i = 1; i < n; i++) if (tot[i] < tot[first] - 1e-12) first = i;
    med.push(first);
    while (med.length < k) {
      var best = -1, bg = -1;
      for (var c = 0; c < n; c++) {
        if (med.indexOf(c) >= 0) continue;
        var g = 0;
        for (p = 0; p < n; p++) { var dm = Infinity; med.forEach(function (m) { if (D[p][m] < dm) dm = D[p][m]; }); g += Math.max(0, dm - D[p][c]); }
        if (g > bg + 1e-12) { bg = g; best = c; }
      }
      med.push(best);
    }
    function assign() {
      return D.map(function (row) { var b = med[0]; med.forEach(function (m) { if (row[m] < row[b] - 1e-12) b = m; }); return b; });
    }
    function cost(ms) {
      var s = 0;
      for (var q = 0; q < n; q++) { var dm = Infinity; ms.forEach(function (m) { if (D[q][m] < dm) dm = D[q][m]; }); s += dm; }
      return s;
    }
    for (var it = 0; it < 40; it++) {
      var cur = cost(med), improved = false;
      for (var mi = 0; mi < med.length && !improved; mi++) {
        for (var o = 0; o < n; o++) {
          if (med.indexOf(o) >= 0) continue;
          var trial = med.slice(); trial[mi] = o;
          if (cost(trial) < cur - 1e-12) { med = trial; improved = true; break; }
        }
      }
      if (!improved) break;
    }
    return assign();
  }
  function silhouette(D, lab) {
    var n = D.length, tot = 0, groups = {};
    lab.forEach(function (l, i) { (groups[l] = groups[l] || []).push(i); });
    var keys = Object.keys(groups);
    for (var i = 0; i < n; i++) {
      var own = groups[lab[i]];
      if (own.length < 2) continue;
      var a = 0; own.forEach(function (j) { if (j !== i) a += D[i][j]; }); a /= own.length - 1;
      var b = Infinity;
      keys.forEach(function (k) { if (+k === lab[i]) return; var s = 0; groups[k].forEach(function (j) { s += D[i][j]; }); b = Math.min(b, s / groups[k].length); });
      var mx = Math.max(a, b); tot += mx > 0 ? (b - a) / mx : 0;
    }
    return tot / n;
  }
  function clusters(ctx, ids, f) {
    var n = ids.length;
    if (n < 4) return { groups: [{ id: 0, members: ids.slice(), label: tagLabel(ctx, ids, f) }], assign: ids.reduce(function (o, id) { o[id] = 0; return o; }, {}) };
    var D = ids.map(function (a) { return ids.map(function (b) { return a === b ? 0 : 1 - ppSim(ctx, a, b)[f]; }); });
    var best = null;
    for (var k = 2; k <= Math.min(6, Math.floor(n / 3)); k++) {
      var lab = kMedoids(D, k), sizes = {};
      lab.forEach(function (l) { sizes[l] = (sizes[l] || 0) + 1; });
      var singles = Object.keys(sizes).filter(function (l) { return sizes[l] === 1; }).length;
      var q = silhouette(D, lab) - 0.03 * singles;
      if (!best || q > best.q + 1e-12) best = { q: q, lab: lab };
    }
    var byMed = {}, groups = [];
    best.lab.forEach(function (m, i) { (byMed[m] = byMed[m] || []).push(ids[i]); });
    Object.keys(byMed).map(function (m) { return byMed[m]; })
      .sort(function (a, b) { return b.length - a.length || (a[0] < b[0] ? -1 : 1); })
      .forEach(function (ms, gi) { groups.push({ id: gi, members: ms, label: tagLabel(ctx, ms, f) }); });
    var assign = {};
    groups.forEach(function (g) { g.members.forEach(function (id) { assign[id] = g.id; }); });
    return { groups: groups, assign: assign };
  }
  function tagLabel(ctx, ms, f) {
    var inside = {}, corpus = {}, papers = ctx.state.papers || [], N = papers.length || 1;
    papers.forEach(function (p) { tagsOf(p, f).forEach(function (t) { corpus[t] = (corpus[t] || 0) + 1; }); });
    var by = {}; papers.forEach(function (p) { by[p.id] = p; });
    ms.forEach(function (id) { tagsOf(by[id], f).forEach(function (t) { inside[t] = (inside[t] || 0) + 1; }); });
    var m = ms.length || 1;
    return Object.keys(inside).sort(function (a, b) {
      var sa = (inside[a] / m) * Math.log(1 + (inside[a] / m) / (corpus[a] / N)), sb = (inside[b] / m) * Math.log(1 + (inside[b] / m) / (corpus[b] / N));
      return sb - sa || (a < b ? -1 : 1);
    }).slice(0, 2).join(' · ');
  }

  /* ---------- research status & agent updates ---------- */
  function cleanStatus(items) {
    return (Array.isArray(items) ? items : []).slice(0, 16).map(function (it) {
      if (typeof it === 'string') it = { kind: /^\s*\[?todo/i.test(it) ? 'todo' : 'done', text: it.replace(/^\s*\[?(todo|done)\]?\s*[:\-]?\s*/i, '') };
      var kind = ['done', 'todo', 'note'].indexOf(it && it.kind) >= 0 ? it.kind : 'note';
      var out = { kind: kind, text: String((it && it.text) || '').slice(0, 300) };
      if (it && it.result) out.result = String(it.result).slice(0, 300);
      return out;
    }).filter(function (it) { return it.text; });
  }

  function cleanResearch(r, fallback, hier) {
    r = r || {}; fallback = fallback || {};
    var out = {
      title: String(r.title || fallback.title || '').slice(0, 200),
      problem: String(r.problem || fallback.problem || '').slice(0, 1200),
      method: String(r.method || fallback.method || '').slice(0, 1200),
      problem_tags: expandTags(Array.isArray(r.problem_tags) ? r.problem_tags : fallback.problem_tags || [], hier, 'problem').slice(0, 20),
      method_tags: expandTags(Array.isArray(r.method_tags) ? r.method_tags : fallback.method_tags || [], hier, 'method').slice(0, 20),
      status: cleanStatus(Array.isArray(r.status) ? r.status : fallback.status)
    };
    if (Array.isArray(r.todo)) {
      cleanStatus(r.todo.map(function (t) { return { kind: 'todo', text: typeof t === 'string' ? t : (t && t.text) }; }))
        .forEach(function (t) {
          if (!out.status.some(function (s) { return s.text === t.text; })) out.status.push(t);
        });
      out.status = out.status.slice(0, 16);
    }
    return out;
  }

  function slug(s) { return normTag(s).slice(0, 40) || 'opt'; }

  function cleanOption(o, base, i, prefix, hier) {
    o = o || {};
    var label = String(o.label || o.title || ('Move ' + (i + 1))).slice(0, 140);
    var proj = o.projected || {};
    return {
      id: String(o.id || (prefix + '-' + (i + 1) + '-' + slug(label))).slice(0, 80),
      label: label,
      kind: KINDS.indexOf(o.kind) >= 0 ? o.kind : 'other',
      why: String(o.why || o.rationale || '').slice(0, 400),
      projected: cleanResearch(proj, base, hier)
    };
  }

  function normTitle(t) { return String(t || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim(); }
  function hashStr(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(36);
  }

  /* Merge an agent reply into node nodeId. upd = {research?, options?, add_papers?, notes?}.
   * Unknown fields (scores, ranks) are dropped. Returns a summary. */
  function applyUpdate(state, nodeId, upd, action) {
    var node = nodeById(state, nodeId);
    if (!node) throw new Error('unknown node ' + nodeId);
    upd = upd || {}; action = action || { type: 'expand' };
    var summary = { options: 0, papers: 0, verified: 0, research: false };
    if (upd.research) { node.research = cleanResearch(upd.research, node.research, state.hierarchy); summary.research = true; }
    var opts = (Array.isArray(upd.options) ? upd.options : Array.isArray(upd.moves) ? upd.moves : []).slice(0, 7)
      .map(function (o, i) { return cleanOption(o, node.research, i, node.id, state.hierarchy); });
    var ids = new Set();
    opts.forEach(function (o) { while (ids.has(o.id)) o.id += '_'; ids.add(o.id); });
    if (opts.length) { node.options = opts; summary.options = opts.length; }
    var known = {};
    (state.papers || []).forEach(function (p) { known[normTitle(p.title)] = p; });
    (Array.isArray(upd.add_papers) ? upd.add_papers : []).slice(0, 10).forEach(function (p) {
      if (!p || !p.title) return;
      var linked = !!(p.url || p.doi || p.openalex), ex = known[normTitle(p.title)];
      if (ex) {
        if (ex.verified === false && p.verified === true && linked) {
          ex.verified = true;
          ex.url = String(p.url || (p.doi ? 'https://doi.org/' + p.doi : 'https://openalex.org/' + p.openalex));
          if (p.doi) ex.doi = String(p.doi);
          summary.verified++;
        }
        return;
      }
      var paper = {
        id: 'x' + hashStr(normTitle(p.title)), title: String(p.title).slice(0, 300),
        year: p.year ? +p.year || null : null, venue: p.venue ? String(p.venue).slice(0, 120) : '',
        url: p.url ? String(p.url) : '', doi: p.doi ? String(p.doi) : '',
        problem: String(p.problem || '').slice(0, 800), method: String(p.method || '').slice(0, 800),
        problem_tags: expandTags(p.problem_tags || [], state.hierarchy, 'problem').slice(0, 16),
        method_tags: expandTags(p.method_tags || [], state.hierarchy, 'method').slice(0, 16),
        why: String(p.why || p.relation || '').slice(0, 300),
        verified: p.verified === true && linked, origin: 'agent', introduced_at: node.id
      };
      state.papers.push(paper); known[normTitle(p.title)] = paper;
      summary.papers++;
    });
    if (upd.notes) node.notes = String(upd.notes).slice(0, 800);
    node.status = 'ready';
    return summary;
  }

  function newChild(state, parentId, move) {
    var parent = nodeById(state, parentId), n = 0;
    (state.nodes || []).forEach(function (x) { var k = +String(x.id).replace(/^s/, ''); if (k >= n) n = k + 1; });
    var child = {
      id: 's' + n, parent: parentId,
      move: { label: move.label, kind: move.kind || 'other', custom: !!move.custom },
      research: move.projected ? cleanResearch(move.projected, parent.research, state.hierarchy) : JSON.parse(JSON.stringify(parent.research)),
      options: [], status: 'pending', notes: ''
    };
    state.nodes.push(child);
    return child;
  }

  /* ---------- prompt shared by in-page agent, API mode and copy/paste ---------- */
  function vocab(state, f, limit) {
    var c = {};
    (state.papers || []).forEach(function (p) { tagsOf(p, f).forEach(function (t) { c[t] = (c[t] || 0) + 1; }); });
    return Object.keys(c).sort(function (a, b) { return c[b] - c[a] || (a < b ? -1 : 1); }).slice(0, limit || 50);
  }

  function buildPrompt(state, nodeId, action, hops) {
    var ctx = context(state), node = nodeById(state, nodeId), r = node.research;
    var g = graph(ctx, r, poolIds(state, nodeId), hops || ctx.cfg.hops);
    var by = {}; state.papers.forEach(function (p) { by[p.id] = p; });
    var moves = pathTo(state, nodeId).map(function (id) { return nodeById(state, id); }).filter(function (n) { return n.move; })
      .map(function (n, i) { return (i + 1) + '. ' + n.move.label + (n.move.custom ? ' (researcher\'s own)' : ''); });
    var L = [];
    L.push('You are the research-direction agent inside a research simulator. A researcher explores which move to make');
    L.push('next. You write TEXT and TAGS only; the simulator computes every relatedness number itself from the tags and');
    L.push('text, so never output scores. Never invent experimental results: anything that needs an experiment is a todo.');
    L.push('');
    L.push('## Research status');
    if (r.title) L.push('Title: ' + r.title);
    L.push('Problem: ' + r.problem);
    L.push('Problem tags: ' + r.problem_tags.join(', '));
    L.push('Method: ' + r.method);
    L.push('Method tags: ' + r.method_tags.join(', '));
    L.push('Status:');
    (r.status || []).forEach(function (s) {
      L.push('- [' + s.kind + '] ' + s.text + (s.kind === 'todo' ? (s.result ? ' → result entered: ' + s.result : ' → no result yet') : (s.result ? ' → ' + s.result : '')));
    });
    L.push('Moves so far: ' + (moves.length ? moves.join('  ') : 'none'));
    L.push('');
    L.push('## Neighbourhood (computed; relatedness 0-100; hop 1 = closest to the research, hop k+1 = closest to hop k)');
    g.nodes.slice(0, 30).forEach(function (n) {
      var p = by[n.id];
      L.push('- hop ' + n.hop + ' | ' + Math.round(n.score) + ' | ' + p.title + ' (' + (p.year || '?') + ')' + (n.hop > 1 ? ' | via ' + by[n.parent].title.slice(0, 50) : '') +
        ' | ' + tagsOf(p, 'problem').join(', ') + ' || ' + tagsOf(p, 'method').join(', ') + (p.verified === false ? ' | UNVERIFIED' : ''));
    });
    L.push('');
    L.push('Tag vocabulary in use (reuse these exact tags; coin a new tag only for a genuinely new concept):');
    L.push('Problem: ' + vocab(state, 'problem').join(', '));
    L.push('Method: ' + vocab(state, 'method').join(', '));
    L.push('');
    L.push('## Task');
    if (action.type === 'custom') {
      L.push('The researcher makes their own move: "' + String(action.text || '').replace(/"/g, "'") + '".');
      L.push('1. "research": the full research status AFTER this move. Keep done items; add todo items for every');
      L.push('   experiment the move needs (concrete: what to run, on what, which metric to fill in).');
      L.push('2. "options": 3-5 next moves from that new state.');
    } else if (action.type === 'import') {
      L.push('Convert the following material into a research status (problem, method, tags, status items: what is done');
      L.push('with its reported numbers, what is still todo). Material:');
      L.push('"""'); L.push(String(action.text || '').slice(0, 20000)); L.push('"""');
      L.push('Then give 3-5 options as moves from that state.');
    } else if (action.type === 'refresh') {
      L.push('Give a fresh set of 3-5 next moves, different in kind from: ' + (node.options || []).map(function (o) { return o.label; }).join('; '));
      L.push('Do not change "research".');
    } else {
      L.push('The researcher just made the latest move above. 1. "research": update the status for it (keep done items,');
      L.push('mark todos the move makes obsolete as notes, add todos for experiments it needs; results entered by the researcher');
      L.push('become done items with that result). 2. "options": 3-5 next moves.');
      L.push('3. Optionally "add_papers": up to 4 real papers this direction makes relevant that are missing above.');
    }
    L.push('');
    L.push('Moves are real forks (problem framing, method, data, evaluation, scope, positioning) that pull toward different');
    L.push('parts of the neighbourhood. Each move\'s "projected" is the research AFTER it: full problem and method text and');
    L.push('full tag lists, plus "todo": the experiments it requires. Problem/method text and tags in English.');
    L.push('');
    L.push('Reply with ONLY one JSON object:');
    L.push('{"research":{"title":"...","problem":"...","method":"...","problem_tags":[],"method_tags":[],');
    L.push('  "status":[{"kind":"done|todo|note","text":"...","result":"only if reported"}]},');
    L.push(' "options":[{"label":"short imperative","kind":"problem|method|data|evaluation|scope|positioning|other","why":"one sentence",');
    L.push('  "projected":{"problem":"...","method":"...","problem_tags":[],"method_tags":[],"todo":["experiment to run"]}}],');
    L.push(' "add_papers":[{"title":"...","year":2024,"venue":"...","problem":"...","method":"...","problem_tags":[],"method_tags":[],"why":"..."}],');
    L.push(' "notes":"one sentence"}');
    return L.join('\n');
  }

  function parseLooseJSON(text) {
    var t = String(text || '').trim();
    try { return JSON.parse(t); } catch (e) { /* fall through */ }
    var fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (fence) { try { return JSON.parse(fence[1]); } catch (e) { /* fall through */ } }
    var a = t.indexOf('{'), b = t.lastIndexOf('}');
    if (a >= 0 && b > a) return JSON.parse(t.slice(a, b + 1));
    throw new Error('No JSON object found in the reply');
  }

  var api = {
    FACETS: FACETS, KINDS: KINDS, tokenize: tokenize, normTag: normTag, expandTags: expandTags, buildStats: buildStats,
    prep: prep, facetSim: facetSim, pairSim: pairSim, overall: overall, context: context, computeAnchor: computeAnchor,
    anchorOf: anchorOf, scale: scale, rootNode: rootNode, nodeById: nodeById, pathTo: pathTo, poolIds: poolIds,
    graph: graph, clusters: clusters, cleanStatus: cleanStatus, cleanResearch: cleanResearch, applyUpdate: applyUpdate,
    newChild: newChild, buildPrompt: buildPrompt, parseLooseJSON: parseLooseJSON, hashStr: hashStr, normTitle: normTitle
  };
  root.SimCore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
