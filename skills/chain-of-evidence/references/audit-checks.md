# Audit checks (AUDIT mode)

`audit.py` implements the CoE Integrity Audit of Meng et al. (2026) plus a number-tracing pass. Each check targets one way a claim loses its grounding. Checks are independent; any FAIL makes the verdict FAIL; unjudged LLM checks make it INCOMPLETE.

| Check | Question | How | Inputs |
|---|---|---|---|
| **T** Number tracing | Does every number in the document exist in the evidence? | every number is searched in the `--evidence` files (rounding + unit aware); unmatched numbers are tried as simple arithmetic of matched ones | doc, `--evidence` |
| **H** Headline source | Does the claimed headline come from the submitted run? | `--claimed` value must be found in `--final-sources`; found only elsewhere → `cross_stage_cherry_pick`, nowhere → `untraced_headline` | `--claimed`, `--final-sources` |
| **I1** Score verification | Does the claimed headline reproduce? | runs `--rerun-cmd` `--runs` times, parses `--score-regex`, compares to `--claimed` within max(1%, 3σ/|mean|) | command, claimed value |
| **I2** Specification violation | Does the code solve the task or game the evaluator? | LLM judges, majority vote | `--code`, `--spec`, `--evaluator` |
| **I3** Reference verification | Do all bib entries exist, and are cited keys in the bib? | retrieval records in `refs_cache.json`; title similarity ≥ 0.85 | `--bib`, `--refs-cache` |
| **I4** Method–code alignment | Does the method section describe what the code does? | LLM judges, majority vote | `--code`, method section (`--method-heading`) |

## Reading the results
- **T, high severity** = numbers with units, decimals, or ≥ 100. Untraced high-severity numbers fail T. Low-severity integers (counts like "3 layers") are listed but do not fail.
- **T, not from the submitted run** lists numbers found only outside `--final-sources`. Baselines and ablations legitimately live there; confirm each is labelled as such in the text.
- **T, traced** lists where each number was found. Check the source is the *right* one: a headline found only in an ablation or exploratory file is a cherry-pick even though it is "traced".
- A traced value only proves the value exists somewhere — not that it measures what the sentence says.
- **I1** `evaluator_error` = the code did not produce a parsable score (crash, missing helper module, timeout). That is a failure of the artifact, not of the audit.
- Some scores legitimately vary by hardware (e.g. time-based metrics); say so and exclude rather than fail.
- **I1** also reports whether the claimed value appears in the document and names the failure category.
- **I2 / I4** stay INCOMPLETE with fewer than `--min-votes` judge votes. I2 is marked *limited* when no separate evaluator was supplied.
- **I3** also fails when two bib entries share one DOI / arXiv ID (a real identifier under an invented title).
- **I3** `unverified` = no lookup recorded yet → do the lookup; only `not_found` / `mismatch` after a real lookup are failures. Uncited bib entries are listed but not failures.

## Failure categories to name in the report
- I1: `value_mismatch`, `cross_stage_cherry_pick`, `paper_score_unavailable`, `evaluator_error`, `metric_mismatch` (different metric, scale, or optimisation direction)
- I2: `evaluator_import`, `evaluator_exploitation`, `specification_exploit`, `data_leakage`, `hardcoding`
- I4: `incomplete_broken`, `algorithm_class_mismatch`, `deceptive_dummy_code`

## Confirming positives
Before reporting, open each flagged item: re-read the sentence, the evidence location, and the code lines the judges cite. Dismiss and explain false positives (e.g. a hardware constant "80GB" matched to nothing; a LaTeX subscript parsed as a number). The audit is designed to have no unconfirmed positives, but it will have false negatives — say that the true failure rate may be higher.
