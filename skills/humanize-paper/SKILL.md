---
name: humanize-paper
description: Rewrite or draft English ML paper prose (abstract, intro, related work, method, experiments, captions, rebuttals) so it reads human-written and is easy to parse. LaTeX-safe.
---

# Humanize paper prose

Scope: English prose for ML venues (ICLR, NeurIPS, CVPR, ICCV): abstract, introduction, related work, method, experiments, discussion, captions, rebuttals, and reviews. LaTeX source is welcome. For resumes, statements, and Korean documents, use `humanize-writing`.

If the user provides their own writing rules (a lab style guide or a personal rules file), those take priority where they conflict with this skill.

Two modes: rewrite (the user pastes AI-drafted prose) and draft (write new prose with these rules applied, then run the check pass).

## Principles

Write for a tired reviewer reading the PDF once. Every sentence adds a claim, a number, a definition, or a reason the reader needs next. Short clear sentences, few modifiers, no grand abstract nouns, no AI-typical phrasing. If deleting a word leaves the meaning intact, delete it; if a word makes a claim, support it in the same sentence.

AI-drafted paper prose goes wrong in two ways. The first is the default choice: hype openers, inflated significance, triads, contrast framing, decorative bold. Fix it by cutting and stating the specific result. The second is density: objects that act like people, stacked nouns, rare word pairs, dropped "that", subjects far from their verbs. Academic prose is already dense, and a draft pushes it further, so each of these slows the reader. In papers the main job is often unpacking, not cutting.

## LaTeX

Edit prose only. Leave math, `\cite`/`\citet`/`\citep`, `\ref`, `\label`, macros, environments, and every number exactly as they are, and keep `\citet` vs `\citep` grammatical after edits. Never add a citation. Never change a number or the scope of a claim (no new "state-of-the-art", no dropped "on ImageNet 256×256"). If a claim lacks evidence in the text, flag it; do not silently soften or strengthen it. Return LaTeX if the input was LaTeX.

## Workflow

1. Section and job. Identify the section and what it must do (abstract: problem, gap, method, main result; method: mechanism, then why).
2. Mark the patterns below, strongest first, including paragraph shape.
3. Rewrite. Keep every supported claim. Do not add a fact, mechanism, number, or citation. If a sentence needs one, write the simpler true sentence and flag the gap.
4. Check pass. Diff facts, numbers, citations, and claim scope against the original. Search again for survivors: contrast framing, closers, triads, dashes, "Notably/Moreover" chains, stacked nouns, animate verbs on inanimate subjects.
5. Return the final text, then a short change list in the user's language (2 to 5 lines), then flagged claims that need a number, a test, or a citation.

## Stock phrasing

Act when these cluster; act on the first five on one sighting.

- Hype openers: "In recent years, X has garnered significant attention", "With the rapid development of". Start with the problem.
- Novelty and destiny: "We propose a novel", "paving the way for", "opens new avenues", "a significant step toward", "unlocks the potential", "sheds light on", "a paradigm shift".
- Empty evidence claims: "Extensive experiments demonstrate the effectiveness/superiority of our method". State the actual result with its number and benchmark.
- Lesson closers after results: "This highlights/underscores the importance of...", "These findings reveal..." when they repeat the result.
- Contrast framing of contributions: "not only X but also Y", "rather than merely X", "This is not just a ... it is a ...".
- Connector chains: "Notably,", "Importantly,", "Crucially,", "Moreover,", "Furthermore,", "Additionally,". Most can go; keep at most one per paragraph, where it marks a real turn.
- Filler frames: "It is worth noting that", "It should be noted that", "In this section, we will discuss". Delete and say the thing.
- Inflation words: plays a crucial/pivotal role, of paramount importance, remarkable, seamlessly, holistic, comprehensive, intricate, nuanced, elegant, delve, harness, underscore, showcase, landscape, realm, tapestry, testament, cornerstone, synergy. Weak alone: leverage (prefer "use"), principled, bridge the gap, To this end, remains largely unexplored.
- Contributions list with bold labels on each item, or "Our contributions are threefold" where the third is "extensive experiments". Use plain sentences or unbolded bullets, as many as there really are.

## Dense sentences

Often the bigger problem in papers.

1. Inanimate subject, animate verb. "the loss punishes", "the tokenizer silently swallows high frequencies", "this asymmetry bites hardest", "the prior fights the condition". If the verb makes the reader picture an agent and a plain mechanism exists, state the mechanism. Field conventions are fine: "Table 2 shows", "results suggest", "the model learns", "the encoder maps", "the model hallucinates".
2. Stacked nouns (3 or more). "discrete visual token reconstruction loss", "video world model action conditioning module". Unpack at first use ("a reconstruction loss on discrete visual tokens"); later uses may shorten once defined. Keep established terms (vision-language model, classifier-free guidance) and defined method names.
3. Rare word pairs and coinages. Invented metaphors such as "token tax", "semantic drift debt", "reasoning surface". Use the field's standard term, or define the new one once and use it consistently.
4. Ad hoc noun-to-verb. "we bucket the frames", "we sandbox the prior". Standard field verbs (ablate, benchmark, tokenize, finetune, distill) are fine.
5. Dropped optional words. Reduced object relatives ("the frames the model attends to most") and missing complementizers ("We find the gap persists across scales."). Restore "that" when the clause is long, starts with a noun that could be misread as an object, or is surprising. Leave short conventional ones; humans vary, so do not restore every one.
6. Long dependencies. Subject separated from the verb by a list or appositive: "Our method, which combines X, Y, and Z with a lightweight adapter trained only on W, achieves..." Split, or move the list after the verb.
7. Nominalizations. "the utilization of", "perform an analysis of", "enables the realization of" become use, analyze, makes possible.

## Other patterns

- Forced triads: "simple, efficient, and effective". Use as many adjectives as the evidence supports, often one.
- Dashes: no em or en dashes in the final prose (math ranges excepted). Use a comma, parentheses, a colon, or two sentences.
- Hedge stacks: "may potentially", "could possibly". One hedge that matches the evidence. Keep honest scope statements.
- Borrowed authority: "it is widely believed", "many works have shown" with no citation. Flag for a citation; do not invent one.
- is/has avoidance: "serves as", "acts as", "stands as" become "is".
- Terminology drift: do not vary terms for elegance (tokenizer / quantizer / encoder for one component). One name per thing.
- Repeated openings: "We ... We ... We ... We". Some is normal in papers; vary when four or more in a row.
- Writing about the paper: "In this section, we..." inside sections. A short roadmap at the end of the intro is conventional; keep it to one or two sentences or drop it if space is tight.
- Paragraph closers that restate the opening, and "Despite these limitations, ..." pivots to optimism.

## What human ML prose looks like

- Plain verbs: use, show, improve, reduce, fail, predict, keep.
- Sentences of mixed length, mostly 10 to 25 words, one idea each.
- Terms defined before use and kept fixed.
- Results stated with numbers and their source: "FID drops from [a] to [b] (Table 2)."
- Hedges matched to evidence; claims scoped to what was tested.
- "We" acting: "We found that X fails when Y."

## Do not overcorrect

No deliberate typos, slang, asides, or mechanical sentence-length variation. Do not replace a banned word with a stranger one; rewrite the sentence. Do not strip standard academic phrasing that a human author would use. When the input already reads well, change as little as possible.

## Section notes

- Abstract: problem (one sentence), gap, what we do, main result with a number, one implication. No "In this paper".
- Introduction: open on the concrete problem or failure case, not field-wide hype. Contributions in plain sentences.
- Related work: group by idea; one plain sentence per group on how this work differs. Avoid repeating "Different from these works, our method...".
- Method: mechanism first, then motivation. Animate verbs and stacked nouns cluster here.
- Experiments: result first, explanation second. "Significantly" only with a statistical test or a stated margin.
- Rebuttal: lead with the answer to each point. Thank the reviewers once at the top, not in every paragraph.

## Examples

Intro
Before: "In recent years, diffusion models have garnered significant attention, showcasing remarkable capabilities across a diverse array of generative tasks. However, their iterative sampling process remains a critical bottleneck — one that quietly erodes their practicality in real-time settings. To address this challenge, we propose a novel training-free acceleration framework that not only reduces latency but also preserves sample fidelity."
After: "Diffusion models generate each sample through many denoising steps, which makes them too slow for real-time use. We propose a training-free method that reduces this latency while keeping sample quality."
Flag: name the mechanism in one clause and give the speedup with its model and benchmark.

Method (density)
Before: "The tokenizer silently swallows high-frequency detail the decoder never recovers, and this asymmetry bites hardest on text-rich images."
After: "The tokenizer discards high-frequency detail that the decoder cannot recover. The loss is largest on images that contain text."

Stacked nouns
Before: "We introduce a discrete visual token reconstruction loss weighting scheme."
After: "We introduce a scheme for weighting the reconstruction loss on discrete visual tokens."

Experiments
Before: "As shown in Table 2, our method consistently and significantly outperforms all baselines across every benchmark, underscoring its robustness and generality."
After: "Our method outperforms all baselines on every benchmark in Table 2."
Flag: give the margin; "significantly" needs a test.
