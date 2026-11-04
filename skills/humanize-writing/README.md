# Humanize Writing

Humanize Writing is a Claude Code skill for everyday and application writing in Korean or English.
It rewrites AI-drafted text, or drafts new text, so that a careful reader accepts it as written by
the applicant. It covers resume and CV bullets, cover letters, research and personal statements,
scholarship and job applications, 자기소개서, emails and posts.

## What it does

| Feature | What you get |
| --- | --- |
| Strong tells | "Not X but Y" contrasts, one-line closers, staged run-ups, application templates and chatbot residue are removed on sight. |
| Clustered tells | Forced triads, uniform rhythm, inflation words and vague outcomes are fixed when they pile up. |
| Density | Inanimate subjects with agent verbs, stacked nouns and long modifiers are unpacked; Korean 번역투 is rewritten into natural sentences. |
| Formatting | Dashes, decorative bold, emoji and the Korean interpunct (·) are replaced. |
| Register rules | Separate rules for resume bullets, statements, Korean formal documents (저/제, active endings) and emails. |
| No invented facts | Nothing is added. Missing numbers or details are asked back as questions. |
| Your voice | A sample of your own writing, if given, overrides the default rules. |

For ML paper prose, use [Humanize Paper](../humanize-paper/README.md).

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/humanize-writing" "$HOME/.claude/skills/humanize-writing"
```

No other dependencies.

## Use

| Ask | Result |
| --- | --- |
| "이 자소서 AI 같아?" | A verdict with the sentences that read as AI and why, then a rewrite |
| "Rewrite these resume bullets" | Plain past-tense bullets with one result each, plus questions for missing numbers |
| "Draft a cover letter for this position from my CV" | A draft, then the details it could not fill without inventing |
| "Make this email shorter and more natural" | The rewritten email that leads with the ask |

## References

- [blader/humanizer](https://github.com/blader/humanizer) (MIT), built on Wikipedia's "Signs of AI writing".
- Clark, Martin and Mahowald, "Why is AI-generated language so hard to understand?", [arXiv 2610.29162](https://arxiv.org/abs/2610.29162).
