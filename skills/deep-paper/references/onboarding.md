# Onboarding (first run only)

Run this once, when `setup.py status` says `configured: false` or the user asks to set the skill
up again. Talk in the user's language. Never ask for a token in chat. After onboarding the choices
live in the config, so a later "summarize this paper" uses them without asking again.

## 1. Ask once

1. **Where to save**: `notion` (a table in a Notion page), `html` (a web page per paper with the
   PDF side by side), or `both`.
2. **Write-up language**: `en`, or `ko` (Korean sentences with English technical terms). Other
   languages follow the Korean rule. If the user wrote the request in English or asks for
   English, use `en`. It can be changed later with `setup.py language en|ko`.
3. Optional: categories (default list in `config.example.yaml`).

Write the answers to a temporary JSON file outside the skill folder and run
`setup.py init --answers FILE` (format: `{"backend": "notion", "language": "ko"}`; for html the
data folder is set in step 3).

## 2. Notion

Ask for the **name of the Notion page** that should hold the paper table, then follow
"Notion database" below. That is all; every later paper is added to that table.

## 3. HTML: where the site lives

Run `setup.py status` and look at `daily_papers`:

- **The user already runs a daily-papers digest site and `supports_deep` is true**: put the
  papers inside that site as its `deep/` sub page, encrypted with the same password:

  ```bash
  python3 <skill_dir>/scripts/setup.py html-set --mode daily-papers
  ```

  The index gets a link back to the digest. `publish.py` runs the digest's own publisher.
- **Otherwise** (no digest site, or one without `deep/` support): a GitHub Pages site of its own.
  Tell the user to:
  1. Create an empty **public** repository on GitHub, for example `papers`; the site will be at
     `https://<username>.github.io/<repository>/`.
  2. Create a fine-grained personal access token limited to that repository with **Contents,
     Pages and Administration: read and write** (GitHub → Settings → Developer settings →
     Fine-grained tokens).
  3. Store it in their own terminal (hidden prompt):
     `python3 <skill_dir>/scripts/site_publish.py token`

  Then run:

  ```bash
  python3 <skill_dir>/scripts/setup.py html-set --mode github --user <username> --repo <repository> --data-dir ~/deep-papers
  python3 <skill_dir>/scripts/site_publish.py setup     # first push and Pages on
  ```

  Open the URL and confirm it loads. The site is public: write-ups and figures can be read by
  anyone with the link. PDFs are never uploaded.
- **The user does not want a public site**: `setup.py html-set --mode local`, then `serve.py`.

## Notion database (first run only)

1. The Notion MCP server must be connected (`claude mcp add --transport http notion
   https://mcp.notion.com/mcp`, then authenticate with `/mcp`).
2. **Ask the user for the name of the Notion page** that should hold the paper database (for
   example "Papers/Reading"). Find it with the Notion search tool; if several pages match, show the
   paths and let the user pick. If the user already has a database for papers, use that instead
   and map its columns (references/notion.md).
3. `setup.py notion-schema` prints the `CREATE TABLE` statement. Create the database with the
   Notion MCP create-database tool, parent = that page, title "Papers" (or the user's name).
   Then make it show **inside the page as a table** (not a separate full page to click into):
   update the data source with `is_inline: true`, and set its default table view to
   `SORT BY "Submitted" DESC; SHOW "Title", "Abbr", "Venue", "Submitted", "Category", "Tags", "Link", "Added"`
   (name it "Newest first").
4. Save it: `setup.py notion-set --data-source <collection id from the result> --database-url
   <database url> --parent-page <page url>`. From then on every paper goes into this database;
   do not ask again.
5. Optional, only for figures of papers without arXiv HTML: an internal integration token
   (notion.so/my-integrations, connected to the database). Store it in a file with mode 600 and
   set `notion.token_file`, or export `NOTION_TOKEN`. Without it those figures are skipped and
   reported.

## Python dependencies

```bash
python3 -m venv ~/.local/share/deep-paper/venv
~/.local/share/deep-paper/venv/bin/pip install -r <skill_dir>/requirements.txt
```

Use that Python for all scripts. PyMuPDF is optional but gives PDF page numbers (page buttons in
the HTML view) and figures for PDF-only papers.
