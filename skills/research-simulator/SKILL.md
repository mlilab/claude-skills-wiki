---
name: research-simulator
description: Research-direction simulator. Puts the user's current research at the centre of a zoomable map, spreads the n-hop neighbourhood of related papers around it as draggable dots (hop 1 = closest to the research, hop 2 = closest to hop 1, ...), with edge thickness by relatedness, offers numbered next moves plus a custom move, and re-maps the neighbourhood and the research status after every move, leaving needed experiments as TODO blanks; problem/method clustering on demand. Builds an artifact or a standalone HTML file. Use whenever someone wants to see their research among related work, explore "what if I change the method / problem / data", plan next research steps against the literature, or asks for a research simulator, research map, related-work neighbourhood, 연구 시뮬레이터, 연구 방향 선택지, n-hop 주변 연구 — even if they don't say "simulator".
---

# Research simulator

A game-like page: the research is a glowing dot at the centre of a zoomable space; related papers are dots around it.

- **Hops by similarity.** hop 1 = the papers most related to the research; hop h+1 = the papers most related to each hop-h paper. The user types n on the page; the graph is recomputed from the pool.
- **Edges** link each paper to the dot it was reached from; thickness and brightness grow with relatedness (0-100). Titles show next to dots; clicking a dot opens the full paper card.
- **Moves.** Numbered next moves (keys 1-9) and a custom-move box. Taking a move updates the research status, re-maps the neighbourhood (dots enter and leave, edges re-weight, changed scores float up as +n / −n) and asks the agent for the next moves. Experiments a move needs become TODO items with a blank for the result. Repeat; the trail at the top goes back to any step.
- **Layouts.** Free (default), Problem, Method: in a cluster layout the dots regroup by problem or method cluster around the research, ignoring hops, with every edge kept.
- Dots are draggable and stay where dropped (double-click releases them); scroll or pinch zooms; drag the background to pan.

The rule that keeps it honest: **agents write text and tags, never numbers.** Relatedness, hops and edges are computed by `assets/sim-core.js` (page) and `scripts/simcore.py` (CLI), which are tested to agree. Results are never invented: anything that needs an experiment is a TODO.

## Files
| path | role |
|---|---|
| `scripts/collect.py` | build the paper pool from OpenAlex (`fetch`, or `urls` + web tool + `merge`) |
| `scripts/sim.py` | `init`, `vocab`, `retag`, `apply`, `choose`, `brief`, `validate`, `build` |
| `assets/sim-core.js`, `scripts/simcore.py` | scoring, hop graph, clustering (JS), update merge, agent prompt |
| `assets/template.html` | the page |
| `references/status.md` | getting the research status from a conversation, Claude Code, another chat, notes; the export prompt |
| `references/collection.md` | pool size and rounds, web-tool limits |
| `references/facets.md` | writing problem/method facets and tags (read before tagging) |
| `references/protocol.md` | state shape, the formulas, the agent reply and merge rules |
| `examples/tabular-compression/` | the real example and `rebuild.sh` |
| `tests/` | `run_tests.py` (parity + semantics), `ui_smoke.py` (headless click-through) |

## Workflow

1. **Get the research status** from wherever it lives — this conversation, a repo in Claude Code, another Claude chat (export prompt or its artifacts), notes — following `references/status.md`. Write `research.json` (problem, method, tags in English; status items done/todo/note). Tell the user in one line where it came from and anything you could not determine.
2. **Ask only what you must**: n (default 2) and artifact vs html if not clear. Default: artifact.
3. **Build the pool** (`references/collection.md`): round 1 around the research, round 2 around the best round-1 papers, more rounds for bigger n. 30-50 papers for n ≤ 2.
4. **Write facets** for every paper (`references/facets.md`), one shared vocabulary; add parent tags with `retag` when narrow tags keep neighbours apart.
5. **Initialise and check**:
   ```bash
   python3 scripts/sim.py init --papers pool.json [--facets facets.json] --research research.json --hops N --status-source "..." -o state.json
   python3 scripts/sim.py vocab state.json
   python3 scripts/sim.py brief state.json      # the hop tree; are each paper's children plausible neighbours?
   ```
6. **Write the first 3-5 moves** as an update file (`references/protocol.md`; each with `projected` and `todo`) and `sim.py apply state.json moves.json --node s0 --brief`. The brief shows each move's reach change and how many papers enter; moves that do the same thing get replaced.
7. **Build and deliver**:
   ```bash
   python3 scripts/sim.py validate state.json
   python3 scripts/sim.py build state.json --mode artifact -o page.html   # or --mode html -o simulator.html
   ```
   Artifact: publish with `capabilities: {"sample": {}, "downloads": true}`; moves then call Claude inside the page. HTML: send the file; its agent runs on the user's own API key (⚙, kept in tab memory only) or by copy/paste with any Claude chat.
8. **Tell the user** in a few sentences: the closest papers, what the moves trade off, where the status came from, and that relatedness is overlap of the facets you wrote, not a quality judgement.

## Continuing in chat
The in-page agent cannot browse, so papers it adds are marked unverified. When the user brings back a state (⇅ → copy state) or wants a move explored with real searches:
```bash
python3 scripts/sim.py choose state.json --option 2          # or --custom "their idea"
python3 scripts/sim.py apply state.json update.json --node sN [--action custom] --brief
```
Verify a suggested paper by finding it and re-sending it in `add_papers` with `verified: true` and its doi/url. Rebuild and republish to the same artifact.

## Testing
`python3 tests/run_tests.py` (needs node) and `python3 tests/ui_smoke.py <built page>` (needs playwright + Chrome) after any change to scripts or the template.
