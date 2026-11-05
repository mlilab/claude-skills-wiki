# Writing facets

Every paper, the research itself, and every option projection has two facets:

- **problem**: what is being solved and under which conditions — task, setting, constraints, objective, application domain.
- **method**: how — model family, algorithm, learning signal, search, solver, representation, kind of contribution (survey, benchmark, tool).

Each facet has a 1–2 sentence **text** and a list of **tags**. Similarity = 0.75 × IDF-weighted tag cosine + 0.25 × TF-IDF text cosine (α adjustable). Tags carry most of the signal, so they deserve the care.

## Tag rules
1. **English, lowercase, hyphenated** (`online-3d-bpp`, `action-masking`). `normTag` normalises case and spaces, nothing else — synonyms are your job.
2. **One shared vocabulary.** Before tagging, skim all titles and draft the vocabulary; reuse a tag rather than coin a near-synonym. `sim.py vocab` lists near-duplicates and singletons afterwards.
3. **3–6 tags per facet.** Fewer and nothing overlaps; more and everything does.
4. **Granularity = how a reviewer would say "same problem" / "same method".** "deep-rl" alone lumps half a field together; "ppo-with-feasibility-mask-and-buffer" matches nothing. Combine one broad and one or two specific tags.
5. **Hierarchy through a file, not by hand.** Narrow tags should also carry their broader parents so an online-3D paper and an offline-3D paper share `3d-bin-packing`. Write `hierarchy.json`:
   ```json
   {"problem": {"online-3d-bpp": ["online-3d-bpp", "3d-bin-packing"], "3d-bin-packing": ["3d-bin-packing", "bin-packing"]},
    "method":  {"ppo": ["ppo", "policy-gradient"]}}
   ```
   and run `sim.py retag state.json hierarchy.json --reanchor`. It expands to a fixed point (idempotent), and the hierarchy is stored in the state, so tags the in-page agent writes later are expanded the same way. A string value (`{"rl": "deep-rl"}`) renames instead.
   Stop at the level that still discriminates: adding `combinatorial-optimization` to every packing paper makes the problem clusters collapse.
6. **Contribution type is a method tag** when it is the point: `literature-review`, `benchmarking` (problem side if the problem is "lack of benchmarks"), `open-source-tool`, `lower-bounds`.
7. **Problem tags describe the problem, not the method.** "learning-based packing" is a method claim; write `online-3d-bpp` + method `deep-rl`.

## Text rules
- Plain, specific, and consistent wording: if tags say `online-3d-bpp`, the text says "online 3D bin packing", not "dynamic cubic loading".
- From the abstract when there is one; from the title when there is not (say so to the user — `ingest` lists them).
- No evaluations ("state-of-the-art", "novel"): they add noise tokens.

## The research and the options
- The research's facets use the same vocabulary. Add a tag that no paper has only when the project really is new on that point — new tags lower similarity on purpose.
- An option's `projected` is the **whole** research state after the decision, not a diff: full problem and method text, full tag lists. Missing fields fall back to the current state.

## Why it matters for hops
Hop 2 is "closest to a hop-1 paper", so paper-to-paper similarity drives the whole outer map. If two papers that a
reviewer would call neighbours share no tag, the map will separate them. After `init`, read `sim.py brief` and check
that each hop-1 paper's children are plausible neighbours; fix tags (or add parent tags) where they are not.
