# Evidence and bound sessions

Read project documents first. Follow the user's read-only limits even when a project's usual
workflow writes reports there. Use a separate authorized notebook directory when needed.

## Locate sessions

These commands read logs but write no files. They do not use a database, contact an API, load
credentials, or import the research project's code.

```bash
python3 <skill>/scripts/sessions.py list --project /path/to/project
python3 <skill>/scripts/sessions.py read --project /path/to/project --session /path/to/rollout.jsonl --contains "report"
```

Default log locations are `~/.codex/sessions` and `~/.claude/projects`. Override with
`--codex-root` and `--claude-root`. Codex metadata must declare the matching cwd. Claude's encoded
project directory limits candidates. An initial record must then declare a matching cwd. A nested
cwd belongs to the project. A session's startup cwd does not prove every later message concerns
that project, so inspect matching content. Sessions started at the workspace root may require a
separate, explicitly selected root. Do not read unrelated session contents.

`read` prints user and assistant messages with line numbers and timestamps. It excludes system,
developer, encrypted reasoning, and tool records. It does not turn replayed instructions into
new authority. Search is case-insensitive. A clipped message states that it was clipped. Use
`--max-chars` for a longer excerpt or read the authorized source directly when detail matters.
Tool output and runtime timestamps must be checked in the original allowed log when needed.

## Artifact views

The viewer supports:

- Claude Code JSONL and JSON message lists containing user/assistant content blocks.
- Claude `tool_use` / `tool_result`, joined by `tool_use_id`.
- Codex `response_item` messages, function/custom tool calls, and returned outputs, joined by
  `call_id`. Top-level system/developer messages are omitted from the conversation view.
- Basic ATIF JSON with a `steps` list and `role`/`source` plus `message`/`content`.
- Unrecognized entries as collapsed records. No content is silently discarded from the redacted
  source-record view. This is not a parser for every provider-specific transport format.

User and Assistant turns start open. Message, Thinking, Tool, Input, and Output start closed.
Preserve the participants' recorded roles. Agent logs are optional evidence for studies that
use such tools. Tool success/failure comes from the returned result. For Claude,
`is_error: true` means failure. False or an omitted flag means success. A missing result or
invalid flag remains unknown. Codex uses explicit `is_error` or `exit_code`. No such evidence
means unknown. Command/description content alone cannot establish success.

Only display thinking that the provider actually returned. Do not reconstruct encrypted or
omitted thinking. Usage numbers may be cumulative or repeated, so the viewer does not add them
to fabricate a total. Link separate subagent transcripts through their explicit registrations.

Credentials and signature fields are masked in generated views. Known token patterns and
authorization headers are also masked. These filters cannot identify every secret. Inspect
input selection and keep the notebook local. Raw source files are never changed. The source hash
identifies the original. The displayed redacted JSON has a separate purpose and is not a backup.
