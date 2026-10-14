# MLI Lab Claude Skills Wiki

This repository collects Claude Code and Codex skills shared by the team. **Each skill has its own `skills/<skill-name>/` directory**, with `SKILL.md` at the root of that directory. Keep any code, reference material, and example configuration needed by a skill in the same directory. Do not commit personal configuration, generated data, tokens, or passwords.

| Skill | Description |
| --- | --- |
| [Daily Papers](skills/daily-papers/README.md) | Collects and summarizes research papers in selected areas and builds an English and Korean digest. |
| [Chain-of-Evidence](skills/chain-of-evidence/README.md) | Connects claims in papers and reports to supporting evidence when writing, or audits completed documents against code, logs, and references. |

## Installation

Clone this repository and link the skill directory into the skills folder used by Claude Code or Codex. For example, to use Daily Papers in both:

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills"
ln -s "$HOME/claude-skills-wiki/skills/daily-papers" "$HOME/.claude/skills/daily-papers"
ln -s "$HOME/claude-skills-wiki/skills/daily-papers" "$HOME/.codex/skills/daily-papers"
```

See each skill's README for its dependencies and setup. If a skill with the same name is already installed, check that installation before creating a link.

## Duty credits

The target is **2 duties per account every 2 weeks (4 duties per month)**.

| Activity | Duty credit |
| --- | ---: |
| First publication of a skill | 1 |
| Feedback on a skill | 0.5 |
| Republishing a skill after incorporating feedback | 0.5 or 1, depending on the scope of the changes |

## Publication and feedback rules

1. Publish each skill in its own `skills/<skill-name>/` directory in this repository.
2. Submit feedback through [this repository's Issues](https://github.com/mlilab/claude-skills-wiki/issues). Identify the skill and describe the requested change.
3. The person who first published a skill must incorporate feedback and republish it. That person decides when to republish.
4. When republishing, announce the changes and the duty credit applied to that update (0.5 or 1) in the relevant channel.
