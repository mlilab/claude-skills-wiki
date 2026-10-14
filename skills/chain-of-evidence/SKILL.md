---
name: chain-of-evidence
description: Chain-of-Evidence (CoE) for research and analysis writing. WRITE mode drafts a paper, report or analysis where every claim (number, citation, method, conclusion) is tagged to a concrete source and verified before prose is finalised. AUDIT mode checks a finished document against its code, logs and bibliography (score reproduction, reference existence, method-code alignment, spec violations, untraced numbers). Use when the user asks for an evidence-grounded / verifiable / hallucination-free write-up of experiments or data, wants claims traced to sources, or wants a paper, AI-generated report or results section audited. Triggers include "CoE", "chain of evidence", "근거 추적", "주장 검증", "논문 검증", "audit this paper", "verify the claims".
---

# Chain-of-Evidence (CoE)

**Principle:** every claim must trace, through a recorded chain of supporting claims, to a grounding source — a log line, a result file key, a code span, or a bibliography entry that was actually retrieved. Provenance comes before prose.

Two modes share one evidence model:

| Mode | Use when | Input | Output |
|---|---|---|---|
| **WRITE** | you are producing the document | evidence bundle (logs, results, code, retrieved refs) | final document + evidence appendix + ledger |
| **AUDIT** | the document already exists (yours, another person's, another AI's) | document + its code/logs/bib | audit report (PASS / FAIL / INCOMPLETE) |

Scripts live in `scripts/` next to this file (stdlib Python 3, no installs). Run them with the bundle path; they never modify evidence. `examples/binpack/` is a small bundle seeded with known errors; `python tests/run_tests.py` checks the scripts against it.

Read before starting:
- `references/claim-taxonomy.md` — the four claim types and what evidence each needs (always)
- `references/tag-syntax.md` — tag grammar (WRITE mode)
- `references/critic-rubric.md` — what the critic checks (WRITE mode)
- `references/judging.md` — how to run independent LLM judges and record votes (both modes)
- `references/audit-checks.md` — the audit checks and how to read them (AUDIT mode)

## Ground rules (both modes)

1. **Deterministic checks are done by scripts, not by you.** Never declare a number "matches" by eye; run `ground.py` / `audit.py`.
2. **Judgment checks are done by someone who did not write the text.** Citation support, method–code alignment, derivations and spec violations go to fresh subagents (3 for WRITE, 3–5 for AUDIT). Majority decides. See `references/judging.md`.
3. **Bibliography entries come only from lookups made in this session.** Never write a bib entry from memory. Every entry needs a retrieval record in `refs_cache.json` (`scripts/refs.py`).
4. **The headline result is the submitted run's result.** Configure `final_result_sources`; a headline taken from an ablation, a subset or a different config is blocked (`cherry_pick`).
5. **Failures are fixed by removing or weakening claims, never by inventing evidence.** If evidence is missing, the claim goes or the user is told.
6. **A user's request does not override the evidence.** If the user asks you to headline a number that is not the submitted run's result (or to state something the evidence does not support), do not do it silently: report it with its real context, and tell the user plainly in your reply what you did instead and why.

---

## WRITE mode

### 0. Assemble the evidence bundle
Put everything the document may rely on in one folder (copies, not originals): experiment logs, result files (`scores.json` …), solution code, ablation outputs, a brief/spec, `refs.bib`.

Create `coe_config.json` in the bundle:
```json
{"final_result_sources": ["scores.json#final"], "min_grounding_ratio": 0.9, "rel_tol": 0.0}
```
`final_result_sources` = locator prefixes holding the submitted/final run. `rel_tol` 0 means a claim must equal the evidence rounded to the claim's precision; raise it (e.g. 0.01) only for documented evaluator noise.

References:
```bash
python scripts/refs.py resolve BUNDLE/refs.bib --cache BUNDLE/refs_cache.json
```
Shell network is often blocked → entries come back `unreachable`. Verify each with your web tools and record only what the page shows. Lookup order: arXiv abs page (`arxiv.org/abs/ID`) → DOI / publisher page → Semantic Scholar, OpenAlex or DBLP pages → web search for the exact title (in quotes) and for authors + venue. Third-party mirrors that show full bibliographic metadata are acceptable as a last resort; name them in `--source`. If a page refuses or rate-limits you, don't retry it — move to the next source. Record failed searches with `--query`:
```bash
python scripts/refs.py add --cache BUNDLE/refs_cache.json --bib BUNDLE/refs.bib \
  --key KEY --title "Exact title from the page" --source URL [--doi …] [--arxiv …] [--abstract "…"]
python scripts/refs.py add --cache … --key KEY --status not_found --source "web search" \
  --query '"exact title"; author + venue'
python scripts/refs.py check BUNDLE/refs.bib --cache BUNDLE/refs_cache.json
```
Always pass `--bib` to `add`: it then downgrades a record to `mismatch` when the retrieved title differs from the bib title (e.g. a real DOI under an invented title); `check` also flags two bib entries sharing one DOI/arXiv ID. Remove entries that are `not_found` or `mismatch` from the bib, or fix them from the retrieved record. Including a short abstract in the record lets judges check citation support.

### 1. Conceive — tagged representation (`representation.md`)
Write the story arc (problem → gap → approach → result → limitation) as plain markdown. **Every factual sentence carries a tag** placed right after the number or assertion it supports (`references/tag-syntax.md`):
```
The submitted solver scores 0.9818 {num: scores.json#final.score headline @HEAD}.
Items are packed with first-fit decreasing {code: solver.py:L13-22 @M1}.
FFD has well-studied worst-case behaviour {cite: johnson1974fast @LIT1}.
It improves on next-fit by 0.157 {derive: HEAD, BASE @CONC}.
```
Give claims you will reference an explicit `@ID`. Do not polish wording yet. Do not write a sentence you cannot tag — if a claim has no source, either find it in the bundle or leave it out. Mark speculation you want the critic to see with `{unsourced}` (it will be dropped).

### 2. Ground
```bash
python scripts/ground.py BUNDLE/representation.md --bundle BUNDLE --out BUNDLE/coe_out
```
Produces `coe_out/ground_report.md` (read it), `ledger.json`, and `review_packet.md` (items needing LLM judgment). Exit 1 = blocking issues. Break codes are explained in `references/tag-syntax.md`.

### 3. Critic + judges (parallel, fresh subagents)
- **Critic** (1 subagent): give it `representation.md`, `ground_report.md`, `references/critic-rubric.md` and read-only access to the bundle. It returns issues as JSON (overclaims, contradictions, wrong-quantity matches, missing comparisons, scope creep, `{context}` misuse). Re-run it after Resolve if it found major issues.
- **Judges** (3 subagents): give each `review_packet.md` only. Save each raw answer to a file and merge:
  `python scripts/merge_judgments.py --packet BUNDLE/coe_out/review_packet.md --out BUNDLE/judgments.json j1.txt j2.txt j3.txt`
  Votes are tied to a hash of each claim's wording + evidence, so after a rewrite only changed claims need new votes (`--existing BUNDLE/judgments.json`). No subagent tool → see the fallbacks in `references/judging.md`.

### 4. Resolve
Rewrite the representation addressing ground flags, judge rejections and critic issues together:
- `value_mismatch` → restate the value the evidence shows (re-read the evidence; do not round favourably)
- `cherry_pick` / `unlabelled_nonfinal` → headline from the final run; other numbers only with the `nonfinal` flag and their real context in the sentence ("on a 10-instance easy subset …")
- `coarse_rounding` → state the precise value, or say "about"
- `broken_ref` → fix the locator, or drop the claim
- `cite_*` → drop the citation or replace it with a verified one
- `judge_rejected` → narrow the claim to what the evidence shows, or drop it
- `untagged_number` → tag it (task constants can be tagged to the spec or code line)
- absence claims ("no run varied X") → `{absent: file re=PATTERN}`; if it fails, the absence claim is false
- overclaims → calibrate ("near-optimal" only if a stated bound supports it)

Re-run Ground (and judges for changed claims). Stop when there are zero blocking flags, or when the flag count stops falling (max 2 extra rounds). **If the grounding ratio is still below `min_grounding_ratio`, stop and report to the user** what could not be grounded instead of producing a weak draft.

### 5. Compose
Write the final prose section by section from the grounded representation, **keeping each tag (with its @ID) attached to its sentence**. Give each section writer only the verified numbers and named baselines. Tables: tag each numeric cell.

### 6. Verify (final gate)
```bash
python scripts/ground.py BUNDLE/draft.md --bundle BUNDLE --out BUNDLE/coe_final \
       --judgments BUNDLE/judgments.json --require-reviews
```
Composing usually rewords sentences, so their old votes no longer match: the report lists them under `reviews_pending`. Judge those from `coe_final/review_packet.md`, merge with `--existing`, and re-run. Each review needs `--min-votes` (default 3) matching votes; with a non-independent fallback use `--min-votes 1` and say so. Only a draft with exit 0 (no blocking issues, no pending reviews) moves on.

### 7. Strip and deliver
```bash
python scripts/strip_tags.py BUNDLE/draft.md --ledger BUNDLE/coe_final/ledger.json \
       --out final.md --cite-style md|latex --appendix evidence_appendix.md
```
`strip_tags.py` refuses unverified ledgers; in md style it appends a References list built from the bib and retrieval records. Deliver the document in the format the user wants (convert `final.md` as needed) plus the evidence appendix. In your message, say briefly what was dropped or weakened during verification and any limitation (e.g. citation support checked against abstracts only).

---

## AUDIT mode

### 1. Gather
Document (md / tex / txt; convert PDF or docx to text first), solution code, logs and result files, bibliography, task spec / evaluator if any, and the command that reproduces the headline score. Copy them into one bundle folder. Note the document's headline claim (value + metric + direction).

### 2. References (I3)
Build `refs_cache.json` exactly as in WRITE step 0 (`refs.py resolve`, then web lookups + `refs.py add`). A bib entry is a failure if no matching record exists (`not_found`) or the record's title disagrees with the bib (`mismatch` — e.g. a real DOI under an invented title).

### 3. Run the audit
```bash
python scripts/audit.py DOC --bundle BUNDLE --bib refs.bib --refs-cache refs_cache.json \
  --evidence logs/run.log results/scores.json results/ablations.json \
  --final-sources results/scores.json#final \
  --claimed 0.731 --rerun-cmd "python solve.py" --score-regex "score=([-0-9.]+)" --runs 3 \
  --code solve.py --spec task_spec.md [--evaluator evaluator.py]
```
- `--evidence`: pass the log and result files explicitly — **including ablation / exploratory outputs**, so a number taken from them shows where it came from. Inputs (datasets), drafts and configs are not evidence. Add code or spec files only if the document quotes constants from them.
- `--final-sources`: the locator(s) of the submitted run's results. With `--claimed`, the **H** check fails a headline that exists only in non-final results (cross-stage cherry-pick) even when no rerun is possible.
- `--claimed`: the headline value exactly as written in the document; the report warns if it cannot be found in the text.
- `--rerun-cmd` runs code — only run what the user supplied and you have inspected.
- Omit flags whose inputs don't exist; the report states which checks were not run. If no separate evaluator exists (the score is computed inside the author's code), I2 is reported as *limited* — say so.

### 4. Judges for I4 / I2
Split `audit_out/audit_packet.md` by section and give each section to 3–5 fresh subagents (prompts in `references/judging.md`). Merge the raw answers with `scripts/merge_judgments.py --check I4|I2 --out judgments.json …` and re-run `audit.py … --judgments judgments.json`. With fewer than `--min-votes` (default 3) votes a check stays INCOMPLETE. If you cannot spawn subagents, use the fallbacks in `references/judging.md` (a fresh CLI process first; self-judging with `--min-votes 1` last) and tell the user if the checks were not independently judged.

### 5. Confirm and report
Look at every flagged item yourself before reporting it (the paper's protocol: human-confirm all positives) — e.g. an untraced number may live in a file you did not pass as evidence. Report to the user:
- verdict table (T, H, I1–I4) with counts
- each confirmed failure with its location and why it matters
- items you dismissed as false positives, and why
- checks not run and limits (tracing finds a value somewhere, not that it measures what the sentence says; citation support is not checked passage-by-passage)

Offer the full `audit_report.md` as a file if it is long.

---

## Beyond research papers
The same model works for business reports and data analyses: citation → source document/URL record, numerical → cell or key in a data file, methodological → the query/notebook/code that produced it, conclusion → derived from those. Keep the same rules: scripts check values, someone else judges support, and missing evidence removes the claim.
