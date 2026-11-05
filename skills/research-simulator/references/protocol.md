# State and agent protocol

## state.json (`schema: research-simulator/2`)
```text
meta       {title, created, source, queries[], status_source}
config     {alpha 0.75, hops 2, k1 6, k 3, max_nodes 90, min_sim 0.03}
anchor     the 0-100 ruler (99th percentile of pairwise similarity at init), fixed for the whole session
hierarchy  {problem: {tag: [tag, broader...]}, method: {...}}   applied to every tag an agent writes
papers[]   {id, title, year, venue, doi, url, cited_by, abstract, problem, method, problem_tags[], method_tags[],
            verified, origin collected|agent, introduced_at (agent papers: the step that added them), why}
nodes[]    steps: {id s0.., parent, move {label, kind, custom}, research {title, problem, method, problem_tags,
            method_tags, status[{kind done|todo|note, text, result?}]}, options[], status pending|ready, notes}
current    the step on screen
```
Steps form a tree: going back on the trail and taking another move starts a branch. A paper an agent adds at a step is visible on that step and its descendants only.

## Numbers
- facet similarity = 0.75 × IDF-weighted tag cosine + 0.25 × TF-IDF text cosine; relatedness = mean of the problem and method similarity; IDF over verified papers only.
- 0-100 = `min(100, 100 × similarity / anchor)`. Same ruler for research→paper and paper→paper edges and for every step.
- edge width grows with the square of the edge's 0-100 value; reach = mean relatedness of hop 1.
- clustering (layout only): k-medoids on one facet's similarity over the papers on screen, k picked by silhouette; labels = the two most distinctive tags.

## Agent reply (in-page agent, API mode, copy/paste, and you in chat)
```json
{"research": {"title", "problem", "method", "problem_tags", "method_tags",
              "status": [{"kind": "done|todo|note", "text": "...", "result": "only if reported"}]},
 "options": [{"label": "short imperative", "kind": "problem|method|data|evaluation|scope|positioning|other",
              "why": "one sentence",
              "projected": {"problem", "method", "problem_tags", "method_tags", "todo": ["experiment the move needs"]}}],
 "add_papers": [{"title", "year", "venue", "url|doi", "verified", "problem", "method", "problem_tags", "method_tags", "why"}],
 "notes": "one sentence"}
```
Merge rules (`SimCore.applyUpdate` / `simcore.apply_update`):
- `research` replaces the step's status fields that are given; missing fields keep their value.
- `options` replace the step's moves (max 7). Unknown fields, such as scores, are dropped. A projection inherits whatever it omits from the step's research; its `todo` list is appended to the status as todo items.
- `add_papers`: max 10, deduplicated by title. `verified` only with a url, doi or OpenAlex id; re-sending a known unverified title with a link verifies it. Unverified papers never enter the IDF statistics, so they cannot move real papers' numbers.

## Actions
| action | when | the agent returns |
|---|---|---|
| expand | a numbered move was taken (the step already holds the move's projection) | updated `research` (results entered in blanks become done; new todos), 3-5 `options`, optional `add_papers` |
| custom | the user typed their own move | `research` after that move (todos for its experiments), 3-5 `options` |
| refresh | the user wants other moves | `options` only |
| import | plain text pasted in ⇅ | `research` built from the text, 3-5 `options` |

## Good moves
- Real forks a researcher faces next: reframe the problem, change the method family, change data or evaluation, narrow or widen scope, position against a named line of work.
- They pull toward different parts of the map (`sim.py brief` shows each move's reach change and how many papers enter); replace near-duplicates.
- Include one move toward the nearest competitors and one away from the crowd.
- Never claim a result. A move that needs an experiment adds a todo with the metric to fill in; the page shows it as a blank.
