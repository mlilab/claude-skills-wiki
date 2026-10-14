# Running independent LLM judges

Some checks need judgment: does this abstract support the sentence, does this code implement the described method, does the conclusion follow, does the solution break the task rules. The writer must not grade its own work, so these go to **fresh subagents** that see only the packet.

## How
- Spawn N subagents in parallel (WRITE: 3 per packet; AUDIT: 3–5 per check). Use the general-purpose agent type. Give each **only** the packet text (or the file path) and the instruction below — never the conversation, your draft rationale, or what you expect.
- Ask for JSON only. Collect the answers, keep every vote (do not drop dissent), and write the judgments file.
- No subagent tool? A fresh CLI process that sees only the packet is the next best option (e.g. `claude -p "<instruction>" < review_packet.md` if the Claude CLI is installed). Only if neither exists: judge yourself in a separate pass, run the scripts with `--min-votes 1`, and tell the user the judgment step was not independent.
- Majority decides. A tie or plurality without majority counts as **not passed** (`judge_partial`). Fewer votes than `--min-votes` (default 3) leaves the item pending / INCOMPLETE.
- Save each judge's raw answer to a file and merge with `scripts/merge_judgments.py` (handles prose and code fences, attaches claim hashes, drops votes for claims whose wording or evidence changed).

## WRITE mode — `review_packet.md`
Instruction for each judge:
> Judge each item in this packet only from the evidence shown in it. For each item answer supported / partial / unsupported with a one-sentence reason. Citation items: does the cited work's title/abstract support the specific assertion (not just the topic)? Code items: does the code implement what the sentence claims? Omitting detail is fine; a different algorithm, a missing component, a degenerate fallback or a hidden switch is not. Derivation items: does the conclusion follow from the listed claims (arithmetic, direction, scope)? Return JSON only: {"<id>": {"verdict": "...", "reason": "..."}, ...}

Merge:
```bash
python scripts/merge_judgments.py --packet coe_out/review_packet.md --out judgments.json \
       judge1.txt judge2.txt judge3.txt [--existing judgments.json]
```
Result — keyed by claim id, one list of votes per id, each tied to the claim hash:
```json
{
  "LIT1": [{"verdict": "supported", "reason": "abstract covers FFD worst-case bounds", "hash": "3f9a1c0b2d"},
           {"verdict": "supported", "reason": "..."},
           {"verdict": "partial", "reason": "..."}],
  "M2":   [{"verdict": "unsupported", "reason": "code is greedy item moves, not simulated annealing"}, ...]
}
```
Pass it to `ground.py --judgments judgments.json`. After a rewrite, the new packet lists only claims still pending (changed claims have new hashes) — judge just those and merge with `--existing`.

## AUDIT mode — `audit_packet.md`
Split by section; each judge gets one section.

**I4 Method–Code** instruction:
> Compare the method section with the code. Acceptable simplification (omitted details) is ALIGNED. MISALIGNED if a described mechanism is missing, partial or replaced by a degenerate fallback (incomplete_broken); the code implements a different algorithm class, e.g. paper claims simulated annealing or an LLM-guided search but code is a deterministic greedy loop (algorithm_class_mismatch); or the code has undisclosed switches or output shaped to game the metric (deceptive_dummy_code). Return JSON only: {"verdict": "aligned|misaligned", "reason": "...", "findings": [{"category": "...", "detail": "... with line numbers"}]}

**I2 Specification Violation** instruction:
> Given the task spec, evaluator and solution code, decide whether the solution solves the task or games the score. Flag: importing or calling the evaluator as an optimisation oracle; editing forbidden regions; hardcoding answers for known test instances; data leakage; exploiting something the evaluator does not check. Return JSON only: {"verdict": "clean|flagged", "category": "evaluator_import|evaluator_exploitation|specification_exploit|data_leakage|hardcoding|none", "reason": "..."}

Merge with `python scripts/merge_judgments.py --check I4 --out judgments.json j1.txt j2.txt j3.txt` (same for I2) and pass with `audit.py --judgments judgments.json`. If no separate evaluator exists, tell I2 judges the score is computed inside the author's code and ask them to check it matches the spec.

## Noise
LLM judges disagree. The paper saw a real evaluator exploit flagged by only 1–2 of 5 judges. When any judge flags something with concrete line numbers, look at it yourself before accepting the majority, and mention dissent in the report.
