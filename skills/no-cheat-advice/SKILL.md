---
name: no-cheat-advice
description: NoCheatAdvice — provenance check for research advice. After the agent finishes giving research advice (directions, methods, experiment designs, fixes), it splits the advice into items and checks each one against the literature with live search, so the user can tell which ideas were actually derived in this conversation and which were recalled from existing papers without attribution. For recalled items it attaches the closest prior work as a side note (authors, year, title, link, one-line core idea, how the advice relates). Common-practice items and items with no prior work found are skipped with just a label. Use whenever the user says NoCheatAdvice, no-cheat, or asks "is this an existing method?", "where did this idea come from", "출처 확인", "기존 연구 있는지 확인", "이거 원래 있는 방법이야?", "parametric knowledge로 뱉은 거야?", or wants research advice checked for uncredited prior work. That includes advice from an earlier turn or pasted from another agent. Not for auditing a written paper or report (use chain-of-evidence for that).
---

# NoCheatAdvice

Research advice from an agent comes from two places. Some of it is reasoned out from the user's own experiments, data and results in this conversation. Some of it is recalled from papers the model saw in training. Recalled advice is fine and often very good, but without attribution it reads like original insight. The user may then treat a known method as a new contribution, miss related work they must cite, or spend weeks rediscovering a published result. This skill separates the two so the user knows which is which.

## When it runs

- **Together with a request for advice:** write the advice first, completely and normally, as if this skill weren't loaded. Don't trim or hedge the advice to make the check easier. The check is an appendix that comes after it.
- **On existing advice** (an earlier turn, or text pasted from another agent): check it as it stands.

## Step 1: Itemize

Number every distinct recommendation in the advice: each method, design choice, experiment, fix or direction. Claims about the literature ("X is known to help with Y", "people usually do Z here") count as items too. They are the most likely to be recalled. Merge items that are really the same idea and split compound ones. Give each item a label of one line or less.

## Step 2: Recall first, honestly

Before searching, note for yourself (in working notes, not the output) whether each item feels like it came from a specific known work, and which paper or authors you suspect. Treat these as hypotheses only. Remembered author names, years and titles are exactly where confident errors happen. This step makes the search targeted, and it makes you face where the idea came from instead of rationalizing it as your own afterwards.

## Step 3: Triage common practice

An item is **common practice (기초)** if it is textbook material, a default in standard tooling, or something a paper in the field would not bother to cite in related work. Examples: train/val/test splits, k-fold CV, feature standardization, early stopping, grid or random search, ablating one component at a time, using Adam. A named technique used in its standard way counts as common practice (dropout, batch norm, LR warmup).

An item is *not* common practice if the advice depends on a specific nontrivial variant, a recent technique (roughly the last few years), or a particular paper's finding. When unsure, search. Misfiling a recalled idea as "basic" is the exact failure this skill exists to prevent.

Every other item goes to Step 4.

## Step 4: Search and verify

For each remaining item:

1. Run 1–3 searches. Describe the mechanism in plain words, not only the name you guessed. A guessed name pulls the search toward confirming your guess. Also search for the recall candidate from Step 2, if you had one.
2. Prefer primary sources: arXiv, OpenReview, ACL Anthology, DBLP, Semantic Scholar, PMLR/NeurIPS/CVF proceedings, publisher pages. Open the paper page and confirm the title, author list, year and venue, and that the abstract or method section actually describes the idea.
3. Cite only papers you opened in this session. Copy author names from the page. With more than three authors, write "First Author et al.".
4. Prefer the original source over surveys or blog posts. If you found a later, better-known paper and the origin is visible, mention the origin.
5. If a recall candidate can't be confirmed, drop it. Never repair a half-remembered citation by guessing.

Then classify each item by how it relates to the closest work you found:

- **기존·동일 (same):** the advice is essentially an existing method or finding.
- **기존·변형 (variant):** an existing core, adapted or combined for this user's setting. Say what the advice adds. When the advice reasons from the user's own results ("your ablation shows X, so try Y") and Y already exists, the item is a variant: Y is known, but applying it from that evidence is new. Say both.
- **기존·부분 (partial overlap):** only some elements overlap. Don't inflate loose relatedness into "same".
- **신규 (not found):** no close prior work after searching. This means "not found in this search", not "doesn't exist anywhere". Phrase it that way.

Check every non-basic item. The user wants all of them checked, not a sample. Give each 1–3 searches so the work stays bounded.

## Step 5: Output

Append this after the advice, in the user's language (keep paper titles and author names as published):

```
---
## NoCheatAdvice 검증

**요약:** 항목 N개 — 기존 a · 변형 b · 부분 c · 신규 d · 기초 e(생략)

**1. <item label>** — [기존·동일]
📎 Author A, Author B (Year). *Title*. Venue. <link>
핵심: <the paper's core idea, one sentence>
관계: <how the advice maps to it; for variant/partial, what differs>

**4. <item label>** — [신규] 문헌 미발견 (검색: "query 1", "query 2")

**기초·생략:** 2 (train/val split), 6 (LR warmup)
```

Rules for the output:
- Go in item order. Put common-practice items together in one line at the end.
- Novel items get the one-line label plus the queries you tried, so the user can judge how hard you looked. No citation.
- Use at most 1–2 references per item: the closest match, plus the origin if it differs.
- If the earlier advice presented an existing method as if it were a fresh idea, say so plainly in 관계 (e.g., "앞 조언에서 출처 없이 제시함"). No excuses or long apologies. The user needs the fact, not the contrition.
- If the paper you found shows the advice is wrong, outdated or known to fail in the user's setting, flag it in one line. Don't silently rewrite the advice. Leave that to the user.
- Keep each block short. The user scans this list.

## When search isn't available

Say so at the top of the check. Don't present remembered citations as verified. You may list recall candidates labeled **[미검증·기억]** and warn that authors and years may be wrong. Mark non-basic items as **미확인** rather than 신규, because novelty can't be judged without searching.

## Principles

- A missing citation is far better than a fabricated one. One fake reference destroys the user's trust in the whole check.
- Don't inflate novelty and don't deflate it. Report the closest work at its true distance.
- The check never changes the advice. It only labels where each piece came from.
