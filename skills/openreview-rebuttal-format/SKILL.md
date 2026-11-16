---
name: openreview-rebuttal-format
description: Write or convert rebuttal replies, reviewer responses and end-of-discussion summaries as OpenReview Markdown in the style of strong published rebuttals - a bold heading per reviewer point with its label in red, `---` between points, bold for what changed and the key result, red for short identifiers, italics for reviewer quotes. Use when the user asks for "md code" for OpenReview, wants a draft reply formatted, or needs tables, math, reviewer quotes or case studies to display properly in an OpenReview comment. It keeps the author's words; for rewording the prose itself, use humanize-paper first.
---

# OpenReview rebuttal format

This format copies the markup of published OpenReview rebuttals. Each reviewer point opens with a bold heading whose label is red, `---` lines separate the points, and a few markers show a skimming reader what matters. The section "Where each marker goes" says where to put red, bold and italics.

This skill changes structure and markup, not wording. If the user also wants the prose to read less AI-written, run `humanize-paper` on the text first, then format the result here. Its rule against decorative bold is about paper prose. The markers below belong to this format, so keep them.

## How OpenReview renders a comment

These rules come from OpenReview's frontend source and its Markdown library (marked, GitHub style).

- **Line breaks:** single line breaks are ignored. Consecutive lines join into one paragraph, so put a blank line between paragraphs, lists, quotes and headings. A table may sit directly under its caption line.
- **No HTML or images:** raw HTML and images (`![](...)`) appear as literal text, so you can't choose colors. To point at a figure, link to its page of the PDF: `[Fig. 3](https://openreview.net/pdf?id=<forum-id>#page=7)`.
- **Sizes and colors:**
  - `#` and `##` headings are large; `###` is only slightly larger than normal text.
  - `####` and smaller headings are smaller than normal text.
  - `**bold**` stays at normal size and shows in dark blue.
  - Text in backticks shows in red, monospaced. Backticks are the only way to make text red. Markdown and math inside them don't render.
- **Math:** MathJax renders `$...$` and `$$...$$`, but Markdown processes the text first.
  - A backslash before punctuation is removed, so `\,` arrives as `,` and `\{` as `{`. Double the backslash: `\\,`, `\\;`, `\\!`, `\\{`, `\\}`.
  - A LaTeX line break needs four backslashes: `\\\\`.
  - A pair of `*` turns into italics. Write `\*`, or use `\ast` or `\times`. If a `_` causes italics, write `\_`.

## The format

```markdown
We thank the reviewer for <what they noted>. Below, we address each point.

---

### **`W1 – <topic>` – We <answer>.**

<paragraph>. **We added <what changed> in <Appendix X>.** As shown in **Table R1**, **<the key result>**.

**Table R1**: <caption>
| Setting | Baseline | Ours |
|---|---:|---:|
| <row> | 0.00 | **0.00** |

<paragraph>. **In the revision, we will <commitment>.**

---

### **`W2, Q1 – <topic>` – We <answer>.**

<paragraph>, as discussed around `L120 - 135`.

> Input: <text>\
> **Baseline output:** <text> // `<verdict>` because <why>\
> **Our output:** <text> // <why it works>

---

[1] <reference cited as [1] above>
```

- **Heading:** a `###` heading holding one bold line: the red label, a dash, and a one-sentence answer.
  - The label is the point ID and its topic. Points that share one answer share one heading: `W2, Q1 – <topic>`.
  - Write the answer in active voice ("We provide ...", not "... are provided").
  - When you write the answer, start with the stance, then the action: "Sure, we now added ...", "True. However, ...", "Fair point, we now ...".
  - Don't use a semicolon in the answer. End the stance with a period or a comma: "We agree. We will ...", not "We agree; we will ...".
- **Larger headings:** use `##` and end the label with a colon: ``## **`W1 - <topic>:` <answer>.**``. Use one heading style throughout a reply.

`examples/draft.md` and `examples/reply.md` in this skill's directory are a short draft and its converted version.

## Where each marker goes

**Red (backticks)** marks short identifiers only:
- the label and topic in each heading;
- reviewer IDs: `` `AbC1` ``;
- line numbers in the paper: `` `L120` ``, `` `L120 - 135` ``;
- literal names in an example, such as the entity or relation a system looks up;
- the short verdict in a case study: `` `Wrong fact retrieved` ``;
- a note added after posting, in bold and red: ``**`Update: we now also added <X>.`**``

Never put a whole paragraph, numbers or math in backticks.

**Bold** marks what a skimming reader must see:
- the whole heading line;
- the sentence that says what changed and where: "We now added a section on X in Appendix H." If the sentence thanks the reviewer first, the bold starts there;
- promises for the final version: "we will report ... in the camera-ready version";
- the one key result of a point;
- references to rebuttal tables in the text: `As shown in **Table R1**, ...`;
- the table label in a caption, and the best value in each table column;
- labels in case studies and in summaries.

**Italics** mark:
- reviewer quotes, `*"..."*`, in the thanks line, in a summary, or when you adopt a reviewer's phrase;
- names of sections or terms from the paper: `*Error Analysis*`;
- a single word that carries the point: "cover it *fully*".

**`---`** goes on its own line, with a blank line above it. Without the blank line, the line above turns into a heading. Put one:
- after the opening paragraph;
- between points;
- before a closing note and before the reference list.

**Tables:**
- Put the caption directly above the table: `**Table R1**: <caption>`. When the table is also in the revised paper, a quote line can name it instead: `> <caption> (Table 11)`, then a blank line. Without the blank line, the table is drawn inside the quote.
- Number rebuttal tables R1, R2, … so they don't clash with the paper's tables.
- Right-align number columns with `---:`, and write "—" in empty cells.
- Bold the best value in each column. If the proposed method ties it, bold the method's value too. A caption that explains the bold says "best", not "higher".

**Lists:** use a numbered list for reasons or components ("two reasons: 1. … 2. …"). Use bullets for parallel items, each written `Label: text`. Indent sub-bullets by 4 spaces.

**Case studies:** a block quote with `>` at the start of every line. End each line except the last with `\`, or the lines run together. Bold the labels, put `//` before each explanation, and write the verdict in red.

**References and links:** cite papers as [1], [2] and list them after the last `---`. Link a table or figure of the paper to its PDF page.

## Summary for the area chair

```markdown
We summarize the reviewers' main concerns and how we addressed them.

* **`AbC1` asks for <request> — added.**
    * *"<short quote from the review>"*
    * <what we added, and where in the revision>.
* **`XyZ2` and `AbC1` question <issue> — addressed.**
    * *"<quote>"*
    * <our answer>.
    * **Both reviewers acknowledged our response.**

---

**<one closing sentence>**
```

## Editing rules

When converting a draft:

- **Keep the author's words.** Converting a draft to this format changes only its structure. Don't reword, shorten or polish the author's sentences. If you add, remove or change any word, list each change after the Markdown. A new heading counts as a change.
- **Headings** are short, plain and in active voice. Don't add claims, hedges or apologies the author didn't write.
- **Drop a bold topic that opens a paragraph** when the new heading already names it, and list the removal.
- **Add the markers where this format puts them.** Bold and red only text the author wrote; don't write new sentences to mark. Markers aren't word changes, but list each sentence you made bold, so the author can check the emphasis.
- **Flag claims, don't fix them.** If a claim is wrong or overstated, for example "prove" when the paper has no theorem, say so after the Markdown and leave the text as written. Apart from the markers, leave tone and emphasis to the author.

When writing new text, such as a heading or a summary from notes:

- **Don't make the reply defensive.** Don't add sentences that concede gaps or limitations the author didn't raise.
- **Keep prose short and plain.** State the finding in the text and leave the numbers to the table.
- **Don't use semicolons.** They read as machine-written. Split the sentence or use a comma. Leave the author's own semicolons as they are.

Before returning a reply:

- **Deliver Markdown in a fenced code block**, so it can be copied as source.
- **Don't split a reply** into several comments to fit a length limit unless the author asks. Limits differ by venue.
- **Run the checker.** It is `scripts/check_openreview_md.py` in this skill's base directory, written below as `<skill dir>`. It uses only the Python standard library. On Windows, use `python` if `python3` is not found. Save the reply, and the draft when converting one, to a scratch or temporary directory, not into the user's repository.
  - `python3 <skill dir>/scripts/check_openreview_md.py reply.md` prints the length as OpenReview counts it and any rendering problems. Add `--limit N` when the user gives the venue's comment limit. Fix each problem it reports, or tell the user why it is intended.
  - When converting a draft, also run `python3 <skill dir>/scripts/check_openreview_md.py --diff draft.md reply.md`. It confirms that only the intended words changed. Every change it lists must be in your change list.

## Seeing the Markdown behind someone else's reply

- **Edited comments:** click **Revisions** under the comment, tick two versions and click **View Differences**. The raw text appears, with its line breaks run together.
- **Any comment:** copy the **Revisions** link. Its `id=` value is the comment's note ID. On an openreview.net page, run this in the browser console:

  ```js
  fetch('https://api2.openreview.net/notes?id=<note-id>', {credentials: 'include'})
    .then(r => r.json()).then(d => console.log(d.notes[0].content.comment.value))
  ```

- **From a fetch tool, without a browser:** search for a distinctive phrase of the reply. The result holds the raw Markdown in `content.comment.value`:
  `https://api2.openreview.net/notes/search?term=%22<phrase>%22&content=all&source=reply`
