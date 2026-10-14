# Writing the deep read (`summary.md`)

A deep read is for a reader who must understand the whole paper: to build on it, reproduce it,
or cite it in related work. It is **not** an abstract-level summary. It follows the paper section
by section, keeps the meaning of every paragraph, places the key figures where they belong, and
links every cited model or method to its source.

Write one file: `<paper dir>/summary.md`. Both backends (HTML site and Notion) are generated from
it, so use only the conventions below.

## Inputs

| file | use |
|---|---|
| `content.md` | Full text in reading order. Paragraph ids `[S3.2.p1]`, citations `[@bib.bib12 Smith et al. (2024)]`, figure and table positions `[[Figure 3]]`, table cells as pipe tables. Read **all** of the main body, not the first pages only. |
| `outline.json` | Section numbers, titles, levels, appendix flag, PDF page, characters per section. |
| `figures.json` | Figures and tables: `number`, `caption`, `section`/`top_section` (nearest numbered section), `in_appendix`, `page`, `files` (local images, may be SVG), `png_files` (raster copies), `image_urls` (verified arXiv URLs). |
| `refs.json` | Bibliography: `label`, `title`, `url` (arXiv abs URL or another source URL, or null). |
| `meta.json` | Title, authors, links, submission date, `venue` from `venue.py`. |
| `figures/` | Image files. Open the figures you feature with an image-capable tool before you describe them. |

## File layout

```markdown
---
abbr: "<ShortName>"          # the paper's own name for its method/system/benchmark; omit if none
category: ["<Category>"]     # 1 item normally; 2 only if the paper is half-and-half
tags: ["<keyword>", "<keyword>", "<keyword>"]   # 3-6 method/topic keywords
icon: "📄"                   # one emoji for the page (Notion icon, HTML index)
survey: false                # true for surveys (relaxes the citation rule)
tldr:                        # exactly 3 lines: problem, method, result. Quote each line:
  - "<the problem and why it matters>"         # an unquoted "e.g.: x" becomes a YAML mapping
  - "<what the paper does>"
  - "<the main result, with a number>"
---

## 1 Introduction

...
```

Do not write the title, authors, links, venue or the TL;DR again in the body: the backends add
them from `meta.json` and the front matter.

`category` must come from `taxonomy.categories` in the config (with Notion: the database's
existing options). Add `Survey` or `Benchmark` as a second category when the paper is one.
Tags are free keywords unless the Notion database restricts them.

## Structure: follow the paper

- One heading per section and subsection of the main body, **in the paper's order**, with the
  **original English title and number**: `## 3 Method`, `### 3.2 Multi-View Verification`.
  Do not translate headings, and do not add a translation in parentheses.
- Titled paragraphs without a number (`#####` lines in `content.md`, e.g. "Problem Setup") become
  `####` headings or a bold lead line inside their numbered section; never give them a number.
- Every paragraph of the main body must be represented. Go paragraph by paragraph through
  `content.md`. Merging two short paragraphs is fine; dropping one is not. Do not compress a
  section into a sentence: a section of the paper usually becomes several bullets or a table.
- Explain enough that a reader new to the subfield can follow: define terms on first use, say what
  each symbol means, and keep the paper's motivation-before-mechanism order.
- Appendix: optional. If it holds material a reader needs (proofs, extra results, prompts,
  implementation details), add `## Appendix highlights` at the end with short bullets per part.

## Visual structure, not translated prose

The page must be easy to scan. Rules (checked by `check.py`):

- **Prose paragraphs are for framing only: 1-3 sentences.** A paragraph of 4+ sentences, or one
  that lists "A does x, B does y, C does z", becomes a list.
- Lists, steps, conditions, components, definitions, comparisons and numbers go into bullet or
  numbered lists, or tables. Target: plain prose is **at most 30%** of the body text.
- Numbers from results tables go into Markdown tables with the paper's exact values, baselines and
  benchmarks. Bold the best value as the paper does.
- Emphasis: `**bold**` for key terms and claims, `<u>underline</u>` sparingly for the one point
  of a section.
- Long derivations or secondary detail: a toggle

  ```markdown
  <details><summary>Derivation of the calibration loss</summary>

  ...

  </details>
  ```

- Callouts, only three kinds, and only for real takeaways:

  ```markdown
  > [!KEY] Core idea or definition
  > text

  > [!RESULT] Main finding
  > text

  > [!LIMIT] Limitation, or contrast with prior work
  > text
  ```

- Math: `$...$` inline and `$$...$$` on its own lines, copied from `content.md` (LaTeX).

## Figures

- Feature the main-body figures that carry the paper: overview/architecture, method details, main
  results, revealing analyses. **6-8 figures** (all of them if the paper has fewer than 6 main
  figures). Do not use appendix figures unless one is essential.
- Refer to a figure by its **number from `figures.json`**, never by file name or order:

  ```markdown
  ![Figure 2: caption in the write-up language — what to look at](fig:2)
  ```

  Captions here are yours, in the write-up language: say what the figure shows and what to notice.
- Placement: directly after the paragraph that first mentions it (see `mentions` in
  `outline.json` and `[[Figure N]]` in `content.md`); otherwise under its own section's heading.
  Never collect figures at the end.
- Tables are not embedded as images: transcribe the rows that matter into a Markdown table and
  name the source (`Table 2`).

## Citations: link every cited model or method

- Wherever the paper cites a model, method, dataset or benchmark, in **any** section, write its
  name as a bold link to the source: `[**MethodName**](<url from refs.json>)`.
- Take the URL from `refs.json` for that citation key. If the entry's `url` is null, write the
  name in bold without a link. **Never invent or guess a URL**; `check.py` rejects arXiv links
  that are not in `refs.json` or `meta.json` and warns about any other unknown link.
- Name the thing, not the author list: link "MethodName", not "Smith et al.". If a citation has no
  short name, link a short descriptive phrase.
- Surveys (`survey: true`): link the works the text discusses; a full reference sweep is not
  required.

## Language

- `language: en`: plain technical English. One idea per sentence.
- `language: ko`: Korean sentences, with technical terms, model names, method names, dataset and
  metric names in English (e.g. "여러 view의 verification 신호를 aggregate한다"). Only the
  sentence structure is Korean. Headings stay in English.
- Faithfulness: every number, claim and comparison must come from the paper. Mark your own
  interpretation as such ("해석:" / "Note:"). Do not add hype words.

## Check your work

```bash
python3 <skill_dir>/scripts/check.py --id <paper id>
```

Fix every `error`. Treat `warning`s as a review list: each one is either fixed or you can say why
it does not apply (for example a section that is only a one-line pointer).
