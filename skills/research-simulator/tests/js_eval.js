// Evaluate sim-core.js on a state so tests can compare with simcore.py.
// usage: node js_eval.js <state.json> <request.json>
const fs = require('fs');
const path = require('path');
const SC = require(path.join(__dirname, '..', 'assets', 'sim-core.js'));
const state = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const req = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = {};
if (req.tokenize) out.tokenize = req.tokenize.map(SC.tokenize);
if (req.normTag) out.normTag = req.normTag.map(SC.normTag);
if (req.hash) out.hash = req.hash.map(SC.hashStr);
const ctx = SC.context(state);
out.anchor = SC.computeAnchor(state, SC.context(state));
const node = req.node || state.current;
out.graphs = (req.researches || []).map(r => SC.graph(ctx, r, SC.poolIds(state, node), req.hops || 2, req.opts || {}));
if (req.clusters) out.clusters = ['problem', 'method'].map(f => SC.clusters(SC.context(state), req.clusters, f));
if (req.update) {
  const st2 = JSON.parse(JSON.stringify(state));
  out.applySummary = SC.applyUpdate(st2, req.update.node, req.update.body, req.update.action);
  if (req.update.choose != null) SC.newChild(st2, req.update.node, st2.nodes.find(n => n.id === req.update.node).options[req.update.choose]);
  out.afterApply = st2;
}
if (req.prompt) out.prompt = SC.buildPrompt(state, req.prompt.node, req.prompt.action, 2);
process.stdout.write(JSON.stringify(out));
