# Claim taxonomy

CoE (Meng et al., 2026, "ScientistOne", arXiv:2605.26340) defines four claim types that are tractably verifiable. Each needs a specific evidence-chain shape.

| Type | Example | Evidence chain must end at | Tag | Checked by |
|---|---|---|---|---|
| Citation | "Smith et al. showed X" | a bib entry backed by a retrieval record whose title matches, and whose content supports X | `{cite: key}` | script (existence, title match) + judge (support) |
| Numerical | "achieves 87.3% on Prism" | a recorded output: log line, result-file key, measurement | `{num: file:line}` / `{num: file.json#key}` | script (value match after rounding/unit scaling) |
| Methodological | "we use a 3-layer MLP" | the implementing code span, or the log region that records the procedure | `{code: file:L1-L2}` / `{log: file:line}` | script (span exists) + judge (alignment) |
| Conclusion | "outperforms the baseline by 5%" | other claims (numerical/methodological) via verifiable reasoning | `{derive: ID1, ID2}` | script (all inputs supported, arithmetic hint) + judge (reasoning) |

A conclusion is only as strong as its weakest input: if any supporting claim fails, the conclusion fails (`derive_broken`).

## What is NOT a claim
- Section numbers, step numbers, dates of the document itself, the number of a figure/table → no tag needed only if they carry no factual content; prefer rephrasing to avoid digits. `{context}` exists for true non-claims (e.g. "Step 2") and the critic checks it is not abused.
- Definitions the document introduces ("we call this X") → no tag.
- Task constants ("capacity 100") ARE claims about the setup → tag them to the spec or code line.

## Qualitative claims (the known blind spot)
"near-optimal", "robust", "significantly better", "scales to millions" are not numerically falsifiable, and the paper reports that uncaught qualitative overclaiming drove the variance in review outcomes. CoE handles them through the critic: each such phrase must be backed by a tagged number or bound in the same paragraph, or be rewritten. `ground.py` lists them under *Overclaim hints*.

## Common failure modes this catches (observed in the paper's 75-paper audit)
- Fabricated references from model memory, or a real DOI attached to an invented title
- Headline score copied from an ablation/exploratory node instead of the submitted run (cross-stage cherry-pick)
- Inverted metric direction (cost presented as "higher is better")
- Internal metric presented as the benchmark metric (wrong scale)
- Method section describing an algorithm the code does not implement (missing component, different algorithm class, hidden environment switches)
- Scores that do not reproduce with the canonical evaluator

## Mapping outside research
| Research | Business / analysis report |
|---|---|
| citation | source document, URL or filing — recorded with `refs.py add` (use the URL as key source) |
| numerical | cell/key in a data export (`{num: sales_q3.csv:42}`), dashboard export, query result file |
| methodological | the SQL / notebook / script that produced the number |
| conclusion | YoY change, share, ranking derived from the above |
