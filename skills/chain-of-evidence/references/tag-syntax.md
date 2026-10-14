# Tag syntax

A tag is `{TYPE: TARGETS [flags] [@ID]}` placed **immediately after** the number or assertion it supports, inside the same sentence. Paths are relative to the bundle folder.

## Types

| Tag | Targets | Notes |
|---|---|---|
| `{num: LOC}` | one or more locators | The verified number is the **last number before the tag** in its sentence segment (text since the previous tag or sentence start). One tag per number. |
| `{cite: key1, key2}` | bib keys | Each key must be in `refs.bib` and have a `verified` record in `refs_cache.json` with a matching title. |
| `{code: file:L10-48}` | code span(s) | Span must exist. A judge decides whether the code does what the sentence says. |
| `{log: file:LINE}` | log region | Line must exist (±window is shown to the judge). For procedures recorded in run notes. |
| `{derive: ID1, ID2}` | claim IDs | All referenced claims must be supported. The script tries simple arithmetic (difference, ratio, % change) and a judge checks the reasoning. |
| `{absent: file re=PATTERN}` | file + regex (no spaces; use `\s`) | For claims of absence ("no run varied the seed"). Passes only if the pattern occurs nowhere in the file. |
| `{unsourced}` | — | Explicit marker for speculation; always blocking, must be dropped or sourced. |
| `{context}` | — | Placed right after a non-claim number (e.g. "Step 2 {context}"). Not verified; the critic checks it is not hiding a claim. Never use it as a sentence-level escape. |

## Locators
| Form | Meaning |
|---|---|
| `log.md:142` | line 142. For `num`, only that exact line is searched (`num_line_window`, default 0). For `code`/`log`, judges see ±3 lines; a single `code` line expands to its enclosing function. Prefer explicit ranges for code. |
| `log.md:L140-L150` or `log.md:140-150` | exact line range |
| `scores.json#final.score` | JSON key path (dots; list indices allowed: `runs.0.score`) |
| `solver.py` | whole file (code/log only; not allowed for `num`) |

Units for JSON values are inferred from key suffixes: `_ms`, `_us`, `_s`, `_sec`, `_pct`, `_percent`.

## Flags and IDs
- `@ID` — explicit claim id (letters/digits/underscore). Required for anything a `derive` refers to. IDs must be unique. Judge votes are tied to a hash of the sentence + evidence, so rewording a claim automatically invalidates its old votes — you don't need to rename IDs.
- `headline` — marks the main result. Its locator must start with one of `final_result_sources`; otherwise `cherry_pick`. If `final_result_sources` is configured, at least one claim must carry `headline`.
- `nonfinal` — required when a result-sounding sentence ("our", "best", "achieves", "outperforms" …) cites a number from outside `final_result_sources` (ablation, subset, exploratory run). Without it: `unlabelled_nonfinal`. With it, the sentence itself must state the context; the critic checks that.

## Number matching rules
- A claim matches when it equals the evidence **rounded to the claim's precision** (`14.4 ms` ← `14.38`), plus `rel_tol` if configured.
- Evidence less precise than the claim cannot support it (`1` in a log does not support `0.9952`).
- A claim less precise than the evidence may not round away more than 1% (`max_round_rel`): "a perfect score of 1" for 0.9818 fails (`coarse_rounding`) unless marked approximate ("about 1", "~1", "약 1").
- Free-text strings inside JSON are not evidence unless the locator points at that string itself.
- The report shows which token and line matched. A value can match a number that measures something else (e.g. `instances=30` for "improved 30 instances") — the critic reviews this column.
- Unit scaling is automatic: `%` ↔ fraction (`98.18%` ← `0.9818`), time units (`0.0144 s` ← `latency_ms: 14.4`).
- Commas in thousands are fine (`1,538,006.69`).

## Examples
```
The next-fit baseline scores 0.8248 {num: scores.json#baseline.score @BASE}.
The submitted solver scores 0.9818 {num: scores.json#final.score headline @HEAD}, i.e. 98.18% {num: scores.json#final.score} of the lower bound.
Each run takes 14.4 ms {num: logs/run_003.log:7 @LAT}.
| Method | Score |
|---|---|
| Next-fit | 0.8248 {num: scores.json#baseline.score} |
| Ours | 0.9818 {num: scores.json#final.score} |
The improvement over next-fit is 0.157 {derive: HEAD, BASE @GAIN}.
Removing local search leaves the score at 0.9818 {num: ablation.json#no_ls.score @ABL}, so the gain comes from FFD {derive: ABL, HEAD}.
```

## Break codes (ground.py)
| Code | Meaning | Typical fix |
|---|---|---|
| `value_mismatch` | the number is not in the evidence | restate what the evidence says |
| `no_number_in_claim` | `num` tag with no number before it | move the tag next to the number |
| `broken_ref` | file / line / key not found | fix locator or drop claim |
| `malformed_tag` | tag missing targets | fix the tag |
| `cherry_pick` | headline not from the final run | use the final run's value |
| `cite_not_in_bib` | key missing from bib | add a verified entry or drop |
| `cite_not_verified` | no `verified` retrieval record | look it up (`refs.py add`) or drop |
| `cite_title_mismatch` | bib title ≠ retrieved title | fix bib from the record, or drop |
| `derive_missing` / `derive_cycle` | unknown or circular IDs | fix references |
| `derive_broken` | depends on an unsupported claim | fix the input claim or drop the conclusion |
| `judge_rejected` / `judge_partial` | LLM judges did not accept support | narrow or drop |
| `unsourced` | explicit unsourced marker | drop or source |
| `unlabelled_nonfinal` | result-sounding sentence cites a non-final source | use the final value, or add `nonfinal` and state the context |
| `coarse_rounding` | claim only matches after >1% rounding | give the precise value or say "about" |
| `absence_violated` | `absent` pattern occurs in the file | the absence claim is false — drop or narrow it |
| `duplicate_id` | same @ID twice | rename |
| `untagged_number` | sentence with a number but no tag | tag it |
| `low_grounding_ratio` | supported/total below threshold | resolve, or stop and report |
| `reviews_pending` | final verify with unjudged items | run judges |
