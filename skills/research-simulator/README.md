# Research Simulator

Research Simulator is a Claude Code skill that puts your current research at the centre of a
zoomable map of related papers and lets you play out next steps. Each move changes the research
status, re-maps the neighbourhood of papers, and leaves the experiments it needs as TODO items
with blank results. Numbers are never invented.

## What it does

| Feature | What you get |
| --- | --- |
| n-hop map | The research is a glowing dot in the centre. Hop 1 holds the papers most related to it, hop 2 the papers most related to each hop-1 paper, and so on. You set n on the page. |
| Edges | Each paper links to the dot it was reached from. Edges get thicker and brighter as relatedness (0-100) grows. Clicking a dot opens its paper card. |
| Moves | Numbered next moves (keys 1-9) plus a custom-move box. A move updates the status, moves dots in and out, shows score changes as +n / −n, and asks the agent for the next moves. The trail at the top goes back to any step. |
| Layouts | Free (the default), or grouped by problem or method cluster. |
| Output | A claude.ai artifact, where moves call Claude inside the page, or a standalone HTML file that uses your own API key (kept in tab memory only) or copy/paste with any Claude chat. |

Agents write text and tags only. Relatedness, hops and edges are computed by
`assets/sim-core.js` and `scripts/simcore.py`, and tests check that the two agree. Relatedness
measures how much the facets written for each paper overlap. It does not judge paper quality.

## Requirements

- Claude Code, or another agent that reads `SKILL.md` skills.
- Python 3 (standard library only). Papers are fetched from OpenAlex, or gathered with the web
  tool.
- For tests: node (`tests/run_tests.py`), and playwright with Chrome (`tests/ui_smoke.py`).

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/research-simulator" "$HOME/.claude/skills/research-simulator"
```

## Use

Ask Claude for a research simulator, a research map, or "what if I change the method / problem /
data", for example "연구 시뮬레이터 만들어줘". Claude reads your research status from the
conversation, the repo, another chat, or your notes, collects 30-50 related papers, and builds
the page.

`examples/tabular-compression/` is a real example. Run `rebuild.sh` there to regenerate
`simulator.html`.
