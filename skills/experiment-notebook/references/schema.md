# Notebook record schema

Each JSON record lives at `<book>/experiments/<number>-<slug>/report.json`.
`new` creates a complete starting record. `build` generates HTML without rewriting source JSON.
A record can represent an experiment, observation, analysis, or other coherent study.

## Notebook settings

`notebook.json` has these settings:

| Field | Meaning |
| --- | --- |
| `repository` | Local source repository associated by `connect-git`, or absent for non-code studies. |
| `language` | `en` or `ko` interface labels. Default: `en`. |
| `timezone` | IANA timezone for displayed dates. Default: `UTC`. |
| `sections` | Ordered mapping of section keys to display titles. Customize names, order, and selection. |
| `request_feedback` | Whether new records start with review pending. Default: `false`. |
| `max_artifact_bytes` | Maximum source bytes for one evidence view. Default: 16 MiB. |

For example, a qualitative study can use:

```json
{
  "sections": {
    "purpose": "Research question",
    "data_selection": "Source selection",
    "methods": "Coding and analysis procedure",
    "results": "Findings",
    "analysis": "Interpretation and limitations"
  }
}
```

Section keys use lowercase letters, digits, and underscores, starting with a letter. Section
text is plain text with blank lines between paragraphs. Literal Markdown is not interpreted.
Extra sections in a record are preserved after the configured sections. Structured metrics and
iterations appear under `results` and also remain available in the details page.

## Record fields

| Field | Meaning |
| --- | --- |
| `id`, `number`, `title` | Stable directory ID, reserved integer, display title |
| `status` | planned/running/completed/stopped/failed/unknown. Separate from the research conclusion. |
| `research_outcome` | Research interpretation, or null |
| `parent`, `parent_evidence` | Actual predecessor study and source for the relationship. Parent can be `none` or `unknown`. |
| `reference_source`, `restart_of` | Other notebook record IDs or null. Separate from parent. |
| `started_at`, `ended_at` | ISO 8601 timestamps with timezone, or null |
| `sections` | Mapping of section keys to prose strings |
| `scope`, `configuration`, `quality` | Study-specific scope, methods, conditions, and quality checks |
| `execution` | Optional provenance entries. Can include phase, protocol version, instrument, data version, commit, and dirty state. |
| `code_snapshots` | Dated Git snapshots with preparation/execution/reporting stage, phase, commit, dirty state, branch, and sanitized remotes. |
| `hypotheses` | List of `{statement, criteria}` for the experiment's hypotheses and assessment criteria. |
| `comparisons` | List of `{item, before, after, reason}` for explicit differences from the parent. |
| `follow_up` | List of `{change, reason, status, evidence}`. Status: `needed`, `implemented`, `validated`, or `deferred`. |
| `timing`, `usage` | Study-specific measurement windows, durations, resources, and costs. Empty objects when unused. |
| `metrics` | Optional list of `{name, value, kind, evidence}`. Kind: measured/estimated/unknown/not_applicable. |
| `feedback` | Optional review: `{status, verdict, interpretation, rules}`. Status defaults to not_applicable. |
| `iterations` | Optional repeated-measurement or revision rows |
| `artifacts` | Explicit evidence file registrations `{id, label, path, kind}` |
| `watch` | Optional state-file/PID observation. See server.md. |

The record created by `new` includes empty lists/objects for unused features. A research record
does not need a Git repository, AI service, quantitative metric, iterative process, or reviewer.
If a software commit is provided, use its actual full 40-character hash. An absent commit does
not imply missing provenance for studies that do not use code. Unknown values are not zero.
For a linked code repository, a started record without an actual execution commit produces a
warning. Preparation/reporting captures do not satisfy that requirement. Dirty snapshots need
their corresponding diff and untracked inputs preserved separately for full reproducibility.

Git capture commands and historical-run limits are in [git.md](git.md). `hypotheses`,
`comparisons`, and `follow_up` render in the purpose, changes, and follow-up sections respectively.
They are also preserved on the details page when a custom section layout omits those keys.

Illustrative non-software fields (not an actual study result):

```json
{
  "execution": [{"phase": "measurement", "protocol_version": "method-v1", "instrument": "recorded instrument"}],
  "configuration": {"sample_preparation": "recorded procedure"},
  "quality": {"calibration": "see calibration record"},
  "usage": {"instrument_hours": null, "material_quantity": null, "quantity_unit": "record the unit"},
  "metrics": [{"name": "response", "value": null, "kind": "unknown", "evidence": "measurement pending"}],
  "feedback": {"status": "not_applicable", "verdict": null, "interpretation": null, "rules": []},
  "iterations": [
    {
      "group": "measurement series", "iteration": 1,
      "description": "First repeated measurement", "document": null,
      "evidence": "measurement-1", "result": "recorded observation"
    }
  ],
  "artifacts": [
    {"id": "measurement-1", "label": "Measurement data", "path": "evidence/measurement.csv", "kind": "text"}
  ]
}
```

Iteration `document` and `evidence` values reference registered artifact IDs or null. The
iteration number is unique within its `group`. Omit scientific conclusions until evidence
supports them. Feedback becomes pending only when a review is requested.

An artifact path is absolute or relative to the record directory. Register a file, not a
whole directory. The builder reads selected files but writes only inside the notebook.
Kinds are `text`, `json`, and optional `trajectory`. Source hashes and byte sizes identify the
original evidence. Generated pages are redacted views, not byte-identical archival copies.
Register subagent transcripts separately if the study has them. Unsupported or oversized
artifacts fail validation rather than being silently truncated.

The main report is `site/reports/<id>/analysis.html`. Details and evidence pages are siblings.
`site/index.html` is the dashboard. Original JSON and raw evidence files are not served.
