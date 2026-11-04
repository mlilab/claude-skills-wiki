# Humanize Paper

Humanize Paper is a Claude Code skill for English ML paper prose. It rewrites AI-drafted text, or
drafts new text, so that it reads as written by a person and is easy for a reviewer to parse. It
works on abstracts, introductions, related work, method and experiment sections, captions,
rebuttals and reviews, in plain text or LaTeX.

## What it does

| Feature | What you get |
| --- | --- |
| Stock phrasing | Hype openers, novelty claims, empty "extensive experiments demonstrate" sentences, lesson closers and connector chains are cut and replaced by the specific result. |
| Density | Inanimate subjects with agent verbs, stacked nouns, coinages, ad hoc verbs, dropped "that" and long subject-verb gaps are unpacked, so the sentence reads in one pass. |
| LaTeX safety | Math, citations, references, labels, macros and every number stay exactly as they are; `\citet` and `\citep` stay grammatical. |
| Claim check | No fact, number or citation is added, and claim scope is kept. Claims that need a number, a test or a citation are listed at the end. |
| Two modes | Rewrite pasted prose, or draft new prose with the same rules and a final check pass. |

Your own style guide, if you give one, takes priority over the skill's rules. For resumes,
statements, emails and Korean documents, use [Humanize Writing](../humanize-writing/README.md).

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/humanize-paper" "$HOME/.claude/skills/humanize-paper"
```

No other dependencies.

## Use

| Ask | Result |
| --- | --- |
| "Humanize this abstract: …" | The rewritten abstract, a short change list, and claims that need support |
| "Rewrite our related work section (LaTeX attached)" | The same in LaTeX, citations untouched |
| "Draft the experiments paragraph for Table 2 from these notes" | A draft written under the rules, then checked |
| "Make this rebuttal paragraph less AI-sounding" | A reply that leads with the answer |

## References

- [blader/humanizer](https://github.com/blader/humanizer) (MIT), built on Wikipedia's "Signs of AI writing".
- Clark, Martin and Mahowald, "Why is AI-generated language so hard to understand?", [arXiv 2610.29162](https://arxiv.org/abs/2610.29162).
