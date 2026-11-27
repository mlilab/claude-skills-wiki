# Best-Paper Writing

Draft or revise the title, abstract, introduction, method, and experiments of an ML or computer vision paper. The skill maps claims to author evidence, plans figures, and marks missing results and citations with TODOs. Its writing guidance comes from an analysis of CVPR, ICCV, and NeurIPS award papers. [Upstream project](https://github.com/gulucaptain/Best-Paper-Writing-Skill)

## Install and use

From a clone of this wiki, link `skills/bestpaper-writing` into `~/.claude/skills/` for Claude Code or `~/.agents/skills/` for Codex. Restart the agent if needed so it discovers the skill.

> Use bestpaper-writing to draft a title, abstract, and introduction from these research notes and bibliography. List any missing evidence in the author report.

You can also provide a draft abstract or export an intake JSON from the [offline intake form](assets/intake_form.html). The form interface is in Chinese. The skill can write Markdown or fill a copy of your LaTeX template. See the [LaTeX workflow](references/latex-output.md).

The intake converter and checkers use Python 3 with no third-party packages. The optional Python plot helper uses Matplotlib. LaTeX compilation requires a local TeX toolchain.

```bash
python3 skills/bestpaper-writing/scripts/check_draft.py paper/abstract.md
python3 skills/bestpaper-writing/scripts/style_metrics.py paper/abstract.md
python3 skills/bestpaper-writing/scripts/check_figures.py paper/main.tex
```

## Optional paper examples and CVPR template

The default install includes the writing guides, aggregate corpus statistics, and figure assets. For the quotation bank, exact wording overlap check, or the CVPR 2027 kit, fetch the pinned upstream revision in the ignored `.upstream` directory. Run these commands from the wiki root.

```bash
upstream=skills/bestpaper-writing/.upstream
git init -q "$upstream"
git -C "$upstream" fetch --depth 1 https://github.com/gulucaptain/Best-Paper-Writing-Skill.git f10ba78efb1f9b6c79799acd884e73ef4d4e1145
git -C "$upstream" checkout --detach FETCH_HEAD
```

The scripts discover the example bank there. Set `BESTPAPER_EXEMPLAR_DIR` to the `references/exemplars/` directory of an existing upstream copy to reuse it. When the bank is absent, the draft checker reports that it skipped wording overlap and still runs its other checks. The author kit is at `.upstream/template/CVPR2027/`. Copy it to a new working folder before editing.

## Attribution

This package adapts [Best-Paper-Writing-Skill at `f10ba78`](https://github.com/gulucaptain/Best-Paper-Writing-Skill/tree/f10ba78efb1f9b6c79799acd884e73ef4d4e1145). The wiki copy includes the upstream CC BY 4.0 license and MIT base-skill notice. It uses local references for the upstream quotation bank and author kit and omits verbatim block quotes from the method and experiments guides. The quoted papers retain their own copyrights. [License](LICENSE) · [Notices](NOTICE.md) · [Corpus bibliography](PAPER_LIST.md)
