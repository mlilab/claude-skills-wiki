# Building the paper pool

Hops are by similarity, not citations:
- **hop 1** = the `k1` papers (default 6) most related to the research,
- **hop h+1** = for each hop-h paper, its `k` (default 3) most related papers not placed yet; each paper is placed once, strongest pair first.

The page computes this from the pool for any n the user types, so the pool must contain the closest work *and* the neighbours of that closest work, deep enough for the n you expect. When the pool runs out, the page says "pool runs out at hop h".

## Size
| n the user wants | pool size |
|---|---|
| 1-2 | 30-50 |
| 3 | 50-80 |
| 4+ | 80-120 (and expect thinner deep hops) |

## Rounds
1. **Round 1, hop-1 candidates.** 3-6 searches built from the research's problem and method (one per distinct angle: the problem setting, the method family, the baseline names, the closest named systems).
2. **Round 2, their neighbours.** Take the 6-10 best round-1 papers; for each, search its own topic and fetch its related works / top citers. This is what fills hop 2.
3. **Round 3+** only if n ≥ 3: repeat from round 2's best papers.
Keep off-topic hits out unless they would plausibly sit next to a hop-1 paper.

## Direct mode
`collect.py fetch -q "..." -q "..." --rounds 2 -o pool.json` does the rounds against api.openalex.org.

## Web-tool mode (the shell is blocked)
`collect.py urls search -q "..."`, `urls abstracts --ids ...`, `urls neighbours --ids ...` print URLs; fetch them with the web tool **one at a time** (parallel fetches get rate-limited; on a rate-limit error retry once, then move on). Light `select` lists are reliable for 8-12 works; ask for abstracts 5 ids at a time; very long URLs are refused. Save what you get as JSON lists and `collect.py merge a.json b.json -o pool.json` (deduplicates by id and by title, keeping the most-cited record).

For a large pool, a subagent can do the fetching and facet writing; give it the research status, the areas to cover, the tag vocabulary, and the output shape (`collect.py` docstring + `facets.md`).

Never add a paper you did not see in an OpenAlex (or publisher) response. Abstract digests from the web tool are summaries: use them to write facets, show them as "abstract", don't quote them as the authors' words.
