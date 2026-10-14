# Deep Paper

Deep Paper is a Claude Code skill for reading one research paper in depth. It writes a
section-by-section study of the paper that you can use for related work, reproduction, or a
reading group, and saves it to a **Notion database** or an **HTML site** where the write-up and
the original PDF sit side by side.

## What it does

| Feature | What you get |
| --- | --- |
| Follows the paper | One heading per section and subsection, in the paper's order, with the original titles. Every paragraph is represented; enumerations, numbers and comparisons become lists and tables (prose ≤ 30%). |
| Figures in place | 6-8 main-body figures, each matched to its number through its caption, placed where the text first mentions it. |
| Linked citations | Every cited model, method or dataset links to its source, taken from the paper's bibliography or an arXiv title search. |
| Venue check | The title is matched against official accepted-paper lists (ICLR, ICML, NeurIPS, CVPR, ICCV, ECCV; WACV and others on request) to find where the paper was published. |
| Quality check | `check.py` flags missing sections, over-compressed sections, too much prose, misplaced or unknown figures, and links that are not in the bibliography. |
| Notion backend | One row per paper in a table inside a Notion page you choose (Title, Abbr, Venue, Submitted, Category, Tags, Link, Added), with the write-up as the row's page: callouts, toggles, tables and figures. |
| HTML backend | An index of all papers with the same columns (sort, filter, search) and a split view per paper: the write-up on the left, the PDF on the right, and a `p.N` button on each section and figure that jumps the PDF to that page. |
| Publishing | The HTML site goes to its own GitHub Pages repository (`https://<username>.github.io/<repository>/`), into an existing compatible paper site as a sub page, or stays on your machine. |
| Languages | English, or Korean sentences with English technical terms (other languages work the same way). Say which one when you set it up, or switch at any time. |

## Requirements

- Claude Code (or another agent that reads `SKILL.md` skills).
- Python 3.9+ with `requirements.txt` (`requests`, `pyyaml`, `beautifulsoup4`, `markdown`; `pymupdf`
  is optional and gives PDF page numbers and figures for papers without arXiv HTML).
- Notion backend: the Notion MCP server (`claude mcp add --transport http notion
  https://mcp.notion.com/mcp`). An integration token is needed only to upload figures of
  papers that have no arXiv HTML.
- GitHub Pages publishing: a public repository and a fine-grained token for it.

## Install

Clone the skills wiki (skip if you already have it) and link this skill into Claude Code's skills
folder:

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/deep-paper" "$HOME/.claude/skills/deep-paper"
python3 -m venv "$HOME/.local/share/deep-paper/venv"
"$HOME/.local/share/deep-paper/venv/bin/pip" install -r "$HOME/.claude/skills/deep-paper/requirements.txt"
"$HOME/.local/share/deep-paper/venv/bin/python" "$HOME/.claude/skills/deep-paper/scripts/setup.py" status
```

Check that `SKILL.md` is directly inside the linked folder. If a `deep-paper` skill is already
installed, check that installation before creating the link.

## First run

Ask Claude: **"Set up Deep Paper."** It asks where to save the write-ups and in which language,
then sets up that place once:

- **Notion**: you give the name of a Notion page. Claude creates a `Papers` table inside that page
  (shown as a table on the page, newest first) and adds every later paper to it.
- **HTML**: if you already run a compatible paper site, the write-ups become its sub page.
  Otherwise Claude walks you through a new GitHub Pages site:
  1. Create an empty public repository, for example `papers`.
  2. Create a fine-grained token for that repository with Contents, Pages and Administration
     read/write.
  3. Store the token in your terminal with `scripts/site_publish.py token` (hidden prompt).
  4. Claude runs the first push and turns on Pages.

  You can also keep the site on your machine only and open it with `scripts/serve.py`.
- **Both**: each paper goes to the Notion table and to the site.

The choices are saved in `~/.config/deep-paper/config.yaml` (see
[config.example.yaml](config.example.yaml)). From then on, "read this paper" uses them directly.

## Use

| Ask | Result |
| --- | --- |
| "Read this paper in depth: https://arxiv.org/abs/1706.03762" | A full write-up, saved and published the configured way |
| "Add *Deep Residual Learning for Image Recognition* to my paper DB" | Title search on arXiv, then the same |
| "Deep-read these 6 papers for my related work: …" | One subagent per paper, five at a time |
| "Write the next ones in English" | Switches the saved write-up language (`setup.py language en`) |
| "Open the paper site" | The published URL, or `scripts/serve.py` and http://127.0.0.1:8010/ |

## How it works

```
resolve.py   title / id / URL → one verified arXiv record, duplicate check
fetch.py     arXiv HTML (title-checked) or PDF → content.md, outline, figures (number ↔ caption ↔ image), refs, PDF pages
refs.py      arXiv links for cited works that the bibliography does not link
venue.py     official accepted lists → venue + evidence
(Claude)     reads everything, writes summary.md by references/writing_guide.md
check.py     structure, coverage, prose share, figures, links
render.py    HTML split view + index          notion_md.py  Notion page + row properties
publish.py   uploads the site the configured way (site_publish.py for GitHub Pages)
```

## Notes

- PDFs are shown from arxiv.org in the browser; the published site contains the write-ups and
  figures only. Write-ups include figures from the papers, so keep a public site in line with the
  papers' licenses.
- The venue lists are cached in `~/.cache/deep-paper/` for 14 days.
