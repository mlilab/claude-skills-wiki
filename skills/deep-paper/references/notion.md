# Notion backend

One paper = one row of the configured database; the row's page holds the write-up.

## Columns

| column | type | value |
|---|---|---|
| Title | title | paper title |
| Abbr | text | the paper's own short name, empty if none |
| Link | url | arXiv PDF URL |
| Venue | text | from `venue.py` (e.g. `ICLR 2026 (Oral)`, `arXiv 2026.05`) |
| Submitted | date | first arXiv submission date; sort the default view by it, newest first |
| Category | multi-select | usually one; options from the config |
| Tags | multi-select | method/topic keywords |
| Added | created time | automatic |

Extra columns in the user's database are fine; leave them empty unless the user says otherwise.

## Steps

1. Duplicate check: search the database for the arXiv id and the title. Stop if a row exists.
2. `notion_md.py --id <id> --out <tmp>/notion.json` produces `properties`, `icon`, `content`,
   `uploads`.
3. Options: `update`/`create` tools reject multi-select values that are not existing options.
   A new database starts with no Tags options, so add the paper's tags first.
   Use existing Category/Tags options when one fits. If `taxonomy.allow_new_options` is true and
   a new option is needed, add it to the column first with the data-source update tool, keeping
   all existing options in the list.
4. Create the page with `notion-create-pages`: parent `{"type": "data_source_id", "data_source_id":
   <notion.data_source_id>}`, the properties, the icon, and `content` as the body. If a property
   name differs in the user's database, map it.
5. `notion_md.py --id <id> --set-url <url of the new page>` records the link locally.
6. `uploads`: figures that have no public image URL (PDF-only papers) appear in the page as
   `[[upload Figure N]]`. With a token: `notion_upload.py --id <id> --page <url>` replaces each
   placeholder by the uploaded image. Without a token: delete the placeholder lines and report
   the missing figures. SVG figures keep their arXiv URL; if they do not display, upload the PNG
   copy the same way.

## Format notes

`notion_md.py` already converts the write-up conventions:

- `> [!KEY]` / `[!RESULT]` / `[!LIMIT]` callouts → `<callout>` with 📌 yellow, ✅ green, ⚖️ gray.
- `<details><summary>` toggles → Notion toggles; `<u>` → underline; `####` → bold paragraph.
- Pipe tables → `<table>` blocks; figures → images with captions from the arXiv HTML URLs.

If the Notion tool rejects part of the content, read the Notion MCP Markdown spec resource and
fix only that construct. Do not fall back to plain text for the whole page.
