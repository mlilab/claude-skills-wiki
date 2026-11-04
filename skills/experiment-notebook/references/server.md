# Server, observations, and existing notebooks

`serve` runs in the foreground. Start it through the environment's background-process support
when the user asks to keep it running. Use the notebook's recorded server or a free port. The
default is 8782. Do not restart an existing research service to preview a skill.

The server binds only to loopback. It accepts GET/HEAD, has no mutation endpoint, and serves only
HTML/CSS/JS paths recorded in `.site-manifest.json`. Directory listings, source JSON, arbitrary
filesystem paths, symlink escapes, and raw log downloads are not served. Treat this as a private
local viewer. It is not an authenticated public hosting service.

The dashboard polls `/api/status` every 20 seconds for state, phase, progress, and elapsed time.
It preserves the search text. Rebuild after
editing report text or registering artifacts. Observations do not rebuild reports or rewrite
study state. Publication, service installation, messaging, and conducting research require
their own user request and are not part of the default pipeline.

## Optional read-only observation

Set a record's `watch` object only from known evidence:

```json
{
  "state_file": "/path/to/recorded-state.json",
  "state_map": {"finished": "completed", "cancelled": "stopped", "error": "failed"},
  "field_paths": {
    "state": "run.status",
    "phase": "run.phase",
    "completed": "progress.done",
    "total": "progress.total",
    "last_activity_at": "run.last_activity_at"
  },
  "pid": 12345,
  "pid_start_ticks": "123456789"
}
```

For a long-running experiment, attach the available state file or recorded process identity.
If no observation source is configured, the UI explicitly displays recorded status only.
It does not claim live monitoring. A state file must be an explicitly selected JSON file.
Without selectors, the monitor reads top-level `state`/`status`, `phase`, `last_activity_at`, and
`progress.completed`/`progress.total`. The optional `field_paths` selects nested values through
dotted dictionary keys. Relative paths resolve from the experiment directory. `state_map`
translates project-specific states. Unknown states stay unknown. Observation never infers
research success. A malformed, missing, or oversized state file produces an observation warning.
The monitor reads actual progress counters and does not estimate missing counts.
Last activity is reported without treating inactivity alone as failure.

The dashboard's SVG diagram draws only explicit research-parent edges, including branches.
Click a node to open its report. An expandable text outline provides the same relationships.
Reference-source and restart links remain separate metadata and do not imply inheritance.

Linux `/proc/<pid>/stat` field 22 identifies process start time. The recorded start tick is
required to treat a matching PID as the same process. A live process with a terminal state is
shown as cleaning up. A vanished/reused PID on a running record is shown as needing attention,
not automatically declared failed. Inactivity alone does not prove failure. Without a recorded
start tick, process identity is unconfirmed. On other operating systems, omit PID observation.

## Existing reports and migrations

For an existing project, inspect its live reporting guide and service first. Preserve the
existing report semantics, numbering, feedback, historical scores, and protected artifact
boundaries. Do not run project reporting code just to discover it: imports or status helpers can
write caches, indexes, notification state, or files.

This package creates new notebook records. It does not automatically convert arbitrary HTML or
attach to a project's database. Reconstruct records from authorized sources, recording provenance
and unknowns. Keep original reports. To convert old documents, first inventory them and compare
text, code blocks, links, tables, and source hashes in an isolated destination. Do not delete or
replace originals unless the user authorizes that step after lossless conversion is verified.

For a read-only source project, point artifacts at selected original files and keep `<book>`
outside it. Never register a whole repository, credentials folder, or hidden evaluation tree.
