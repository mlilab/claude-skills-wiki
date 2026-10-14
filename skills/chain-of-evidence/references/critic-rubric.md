# Critic rubric (WRITE mode, step 3)

The critic is a fresh subagent that did not write the draft. It receives: the tagged representation, `ground_report.md`, this rubric, and **read-only access to the bundle folder** (so it can check e.g. what a config or log actually says). It audits what scripts cannot. Re-run the critic after Resolve if the first pass had major issues.

## Prompt to give the critic
> You are reviewing a tagged research representation for evidence integrity. Every factual sentence carries a tag `{type: source}`; a ground report lists which claims scripts already verified and which evidence token each number matched. The evidence files are in BUNDLE (read-only). Do not re-check arithmetic the report marks supported, but DO check that each matched token measures what the sentence says. Look for the problems in the checklist below. Return JSON only:
> `{"verdict": "pass" | "issues", "issues": [{"id": "<claim id or line>", "severity": "major|minor", "category": "<checklist key>", "problem": "...", "fix": "..."}]}`

## Checklist
| key | Look for | Example |
|---|---|---|
| `overclaim` | wording stronger than the evidence: "near-optimal", "significantly", "state-of-the-art", "robust", "scales to", "always" without a tagged bound, test, or comparison in the same paragraph | "near-optimal" when only one baseline is compared |
| `scope_creep` | conclusions extended beyond the evaluated setting (other datasets, all problem sizes, production) | "generalises to all packing problems" from 30 instances |
| `contradiction` | two statements that cannot both hold; a statement that disagrees with a table | "sub-millisecond" while the table says 7.9 ms |
| `metric_direction` | lower-is-better metric described as higher-is-better (or the reverse); internal metric presented as the benchmark metric | cost reported as "utility" |
| `cherry_pick_context` | a better number from an ablation, subset or exploratory run presented without its context | "up to 0.995" from an easy subset |
| `missing_comparison` | claims of superiority without the obvious baseline; baselines not run under the same conditions | compares only to the weakest baseline |
| `gap_approach` | the stated gap and the proposed approach do not connect | gap is latency, approach only improves accuracy |
| `null_result_hidden` | a component claimed to help when its ablation shows no effect | "local search refines the packing" when ablation delta is 0 |
| `wrong_quantity` | the number matched a token that measures something else (see the report's *evidence* column) | "improved 30 instances" matched `instances=30` in a config line |
| `nonfinal_context` | a `nonfinal` number whose sentence does not say it comes from an ablation / subset / exploratory run | "an earlier run scored 0.995" |
| `context_abuse` | `{context}` used on a number that is actually a factual claim | "{context}" after "30 instances" |
| `limitations` | missing honest limitations that the evidence makes obvious (single dataset, noise, unverified baselines) | — |

## Severity
- **major**: would mislead a reader about what was achieved or how → must be resolved before Compose.
- **minor**: clarity or calibration → resolve if cheap.

The critic never supplies new facts or numbers; its fixes are "drop", "narrow to …", "add context: …", "tag to …".
