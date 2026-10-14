---
name: deep-paper
description: Deep, section-by-section reading of a research paper, saved to a Notion database or a static HTML site with the PDF side by side. Follows the paper's own section order without dropping paragraphs, places the main figures (number-checked against their captions) in their sections, links every cited model or method to its source, and verifies the venue against official accepted-paper lists. Use when the user wants to read a paper in depth, study it for related work, or add it to their paper database ("이 논문 깊게 읽어줘", "related work로 정리", "add this paper", "논문 DB에 추가"). Not for daily digests or quick one-paragraph summaries.
---

# Deep Paper

Produce a deep read of one paper at a time: a write-up that a researcher can use instead of a
first full pass of the paper, and that keeps exact numbers, structure and citations. The skill
directory is `<skill_dir>` (this file's folder). Below, `python3` means the Python that has the
requirements installed, usually `~/.local/share/deep-paper/venv/bin/python`; `setup.py status`
prints the one in use. The config is `~/.config/deep-paper/config.yaml`, or the file named by
`$DEEP_PAPER_CONFIG`.

Pipeline per paper: **resolve → fetch → refs + venue → read → write → check → publish**.

## Start: setup check

```bash
python3 <skill_dir>/scripts/setup.py status
```

If `configured` is false (or the HTML backend has no `html_mode`), run
[references/onboarding.md](references/onboarding.md) first: the user picks Notion, HTML or both,
and the language; Notion asks for a page, HTML goes into an existing daily-papers site or a new
GitHub Pages repository. Once configured, **do not ask again**: every later request uses the
saved choices.

**Language**: when the user asks for the write-ups in another language at any point ("write it
in English", "영어로 정리해줘"), switch the saved setting and use it from that paper on:

```bash
python3 <skill_dir>/scripts/setup.py language en     # or ko
```

A request that names a language for one paper only ("this one in English") applies to that paper
and leaves the setting unchanged.

## 1. Resolve the paper

```bash
python3 <skill_dir>/scripts/resolve.py "<title | arXiv id | arxiv.org URL>"
```

- A title is matched against arXiv titles. If the result has a `note` (closest match only),
  compare title and authors with what the user gave before going on. Exit code 2: no match;
  ask for a link instead of guessing.
- `duplicate` set: the paper is already written up. Report its page and stop unless the user
  asked to redo it. With the Notion backend, also search the database for the title or arXiv
  id (Notion search/fetch tools) and stop if a row exists.
- A paper that is not on arXiv: write a record JSON (`id`, `title`, `authors`, `abstract`,
  `submitted`, `links`) from the paper itself and use `fetch.py --pdf FILE --record FILE`.

## 2. Fetch

```bash
python3 <skill_dir>/scripts/fetch.py --id <arxiv id>
```

It reads arXiv HTML (checked against the arXiv title, so a stale or wrong page is rejected) and
falls back to the PDF. Output in `<data_dir>/papers/<id>/`: `content.md`, `outline.json`,
`figures.json` (figure number ↔ caption ↔ image, appendix flag, PDF page), `refs.json`,
`meta.json`, `figures/`, `paper.pdf`. Report a PDF-only source: its section split and figure crops
are less reliable, so review them.

## 3. Citation links and venue (run both; refs takes ~2 min)

```bash
python3 <skill_dir>/scripts/refs.py --id <id>      # arXiv links for cited entries that lack one
python3 <skill_dir>/scripts/venue.py --id <id>     # official accepted lists → meta.json["venue"]
```

Start `refs.py` in the background and read the paper meanwhile. `venue.py` sets the venue from
an official list match; a claim that only appears in the arXiv comments comes back with
`"verify": true`: confirm it (project page, proceedings, OpenReview) or use the `fallback`
(`arXiv YYYY.MM`). Details: [references/venue.md](references/venue.md).

## 4. Read, then write `summary.md`

Read **all** of `content.md` (main body completely; skim the appendix), and look at the figures
you will feature. Then write `<data_dir>/papers/<id>/summary.md` exactly as
[references/writing_guide.md](references/writing_guide.md) describes. The essentials:

- Front matter: `abbr`, `category`, `tags`, `icon`, `survey`, and a 3-line `tldr`.
- The paper's sections in order with their original English titles and numbers; every paragraph
  represented; lists and tables instead of long prose (prose at most 30%).
- 6-8 main figures as `![caption](fig:N)`, N from `figures.json`, each placed where the text
  first mentions it.
- Every cited model, method or dataset as a bold link with the URL from `refs.json`; no URL in
  `refs.json` means bold without a link. Never write a URL from memory.
- Write in `language` from the config (`ko`: Korean sentences, English technical terms).

## 5. Check

```bash
python3 <skill_dir>/scripts/check.py --id <id>
```

Fix all `errors`, and fix or justify each `warning`. Re-run until there are no errors.

## 6. Publish to the configured backend

**HTML** (`backend: html` or `both`):

```bash
python3 <skill_dir>/scripts/render.py --id <id>
```

This writes the split-view page (write-up left, original PDF right, page buttons on headings and
figures) and refreshes the index (`<data_dir>/index.html`, a table with the same columns as the
Notion database). Then publish it the way onboarding chose:

```bash
python3 <skill_dir>/scripts/publish.py
```

It prints the site URL (or, for `local`, the index path). See [references/html.md](references/html.md).

**Notion** (`backend: notion` or `both`): follow [references/notion.md](references/notion.md):

```bash
python3 <skill_dir>/scripts/notion_md.py --id <id> --out <tmp>/notion.json
```

Create the row with the Notion MCP `notion-create-pages` tool: parent = the configured data
source, `properties` and `icon` from the JSON, `content` as the page body. Then record the URL:
`notion_md.py --id <id> --set-url <page url>`. If `uploads` is not empty, run
`notion_upload.py` when a token is configured; otherwise tell the user which figures are missing.

## 7. Report

Per paper: where it is (page path or Notion URL), venue and its evidence, category and tags,
figures used, citation links (linked/linkable from `check.py` stats), and anything skipped (PDF-only
source, unresolved citations, figures that could not be uploaded).

## Several papers

Process one paper per subagent, at most 5 at a time. Give each subagent this file and the
writing guide, the paper input, and the backend. Subagents must be able to write files in
`data_dir` (`summary.md`); if a tool blocks writing Markdown files, a shell heredoc works. Never give the same paper to two subagents;
run `resolve.py` first and drop duplicates. After each batch, check the results before the next.

## Changing settings

Edit the config (fields in `config.example.yaml`): language, backend, data directory,
categories, figure counts, venues to check, check thresholds, and `html.home_link` (a link back
to a parent site shown on the index page).
