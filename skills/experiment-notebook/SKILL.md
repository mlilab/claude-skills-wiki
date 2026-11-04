---
name: experiment-notebook
description: >-
  Connect research to Git provenance, monitor experiments with Slack lifecycle alerts, draw inheritance diagrams, and
  write HTML reports with execution commits, purpose and hypotheses, parent differences,
  results, and required fixes. Preserve evidence and separate plans from actual execution.
  Use for 실험 보고서, 연구 노트, 연구 계보, experiment dashboards, and recording research
  findings or revisions. Supports computational, laboratory, field, and qualitative research.
  Non-code studies can use protocol or data versions instead of Git. Not for
  daily activity diaries, paper digests, or running the experiments themselves.
---

# Experiment Notebook

Turn existing research evidence into a notebook. A record can describe an experiment,
observational study, simulation, analysis, or literature-based investigation. Keep the report
concise and link supporting detail. This skill does not conduct or rerun the research itself.

The core workflow is **connect Git → prepare the report and parent relationship → record
execution provenance → monitor and notify → report results and required changes**. Preserve these
capabilities when adapting the notebook to another field. Domain roles, models, reward formulas,
budgets, and artifact paths belong to the user's project, not this skill's defaults.

`<skill>` means this directory. Python 3.10+ is sufficient. There are no package dependencies.
`<book>` is the user's chosen notebook directory. Always pass it as `--root`.

## Establish the destination and evidence

1. Read project instructions and the existing reporting guide. Read the current guide again
   before each report edit. A remembered summary cannot replace it.
2. Reuse a configured notebook. Otherwise choose a separate notebook directory with the user,
   or use a destination the user already authorized. Respect read-only project directories.
3. Read the relevant research question, methods or protocol, observations, analysis, and source
   materials. Use logs, configuration, and cost receipts when available and relevant.
   A file's mtime does not establish execution order or successful completion.
4. When session history is relevant and authorized, use [references/evidence.md](references/evidence.md).
   Match sessions to their recorded working directory before reading their contents.

Create a new notebook only when needed:

```bash
python3 <skill>/scripts/notebook.py init --root <book> --title "Research notebook" --language en --timezone UTC
```

This creates `notebook.json` and an editable `GUIDE.md`. It does not change project files,
configure Git, start a service, or send notifications. Keep this private directory out of a
public repository. Do not replace an existing reporting guide with the default.

## Connect the source repository

For code-based work, associate the actual source checkout with the notebook:

```bash
python3 <skill>/scripts/notebook.py connect-git --root <book> --repository <project>
python3 <skill>/scripts/notebook.py git-status --root <book>
```

This records the association in the notebook and reads the branch, full commit, dirty state,
changed paths, and sanitized remotes. It does not change the repository, fetch, push, or commit.
For non-code work, record the actual protocol/data/instrument provenance instead.
Read [references/git.md](references/git.md) for capture stages and historical-run limits.

## Prepare or update a study

Read `<book>/GUIDE.md`, [references/report-guide.md](references/report-guide.md), and
[references/schema.md](references/schema.md) before writing.
Apply [vendor/asd-ste100/SKILL.md](vendor/asd-ste100/SKILL.md) to the report's prose.
For languages other than English, use its clarity principles without claiming English dictionary compliance.

```bash
python3 <skill>/scripts/notebook.py new --root <book> --slug pilot-study --title "Pilot study" --parent none
```

`new` reserves the next number and writes `experiments/001-pilot-study/report.json`. It does not
mark the study as started. For a branch, use the actual parent ID. Use `unknown` when no
source records the parent. Record order, research parent, reference source, and restarted study
are separate fields. A continuation keeps the same number.

Edit that `report.json` from evidence. The default sections are:

1. Previous experiment, research parent, and context.
2. Differences from that parent and the study methods.
3. Purpose, hypotheses, and assessment criteria.
4. Observations and results.
5. Interpretation and limitations.
6. Required fixes, completed revisions, reasons, and follow-up.

Adapt `sections` in `notebook.json` to the discipline and the project's guide while retaining the
meaning of these report items. State none or not applicable where appropriate.
Use `--language ko` for Korean interface labels and set the appropriate timezone.

Use `hypotheses` for statements and assessment criteria, `comparisons` for before/after conditions
and reasons, and `follow_up` for required changes and their implementation/validation status.
Distinguish a needed fix from an implemented fix and a tested fix.

Preserve the distinction between a plan and a completed action. Record relevant provenance:
protocol or instrument versions, data sources, sample identifiers, analysis procedures, and code
revisions where applicable. For software runs, use the actual full commit when recorded.
Current HEAD cannot identify an old run. Mark unavailable data as unknown, not zero.

Capture preparation separately. At actual start/resume, the existing experiment workflow can
capture an execution version while the notebook record is `running`:

```bash
python3 <skill>/scripts/notebook.py capture-git --root <book> --experiment <id> --stage preparation --phase prepared
python3 <skill>/scripts/notebook.py capture-git --root <book> --experiment <id> --stage execution --phase initial-run
```

These are lifecycle examples. Call the execution capture only at the actual execution point
with the checkout the run uses. It does not start a run. For completed historical experiments,
use recorded execution evidence rather than capturing today's checkout.

For repeated measurements or iterative studies, the optional `iterations` table records the
group, repetition number, question or change, evidence, and result. Use the study's terminology
and classification policy. Leave it empty for studies without iterations.

`usage` accepts the resources relevant to the study, such as instrument hours, materials, or
compute costs. AI API or subscription accounting is optional and has no preset fields.

Register only the evidence files the report needs in `artifacts`. The builder reads those exact
files and creates escaped, redacted HTML views. It never edits them. JSON views have field
toggles. Trajectory views match tool results by tool-use ID. Preserve source logs separately.
For supported formats and limits, read [references/evidence.md](references/evidence.md).

Review feedback is optional. Request it when the user or project guide requires it.
Set `request_feedback: true` for that notebook, or mark a particular review as `pending`.
Otherwise use `feedback.status: not_applicable`. Preserve existing feedback and distinguish it
from the report author's interpretation. Do not delay independent reporting while waiting.

## Validate, build, and open

```bash
python3 <skill>/scripts/notebook.py check --root <book>
python3 <skill>/scripts/notebook.py build --root <book>
python3 <skill>/scripts/notebook.py serve --root <book> --port 8782
```

Resolve validation errors. Investigate warnings. Retain truthful unknown values rather than
inventing data to clear a warning. `build` refreshes generated HTML from the JSON records and
registered artifacts. It leaves the JSON, guide, and source artifacts unchanged.

The server binds to `127.0.0.1` and serves only files listed in the generated site manifest.
Use SSH or editor port forwarding for remote viewing. See
[references/server.md](references/server.md) for observation, deployment, and conversion.

The dashboard orders reserved record numbers newest first, supports search, and draws the
recorded parent relationships. Completion uses a green badge. Failure and interruption use red
badges. Research success is a separate field. Never infer unknown parents from numbers.

For running experiments, connect `watch` to the selected state file and/or the actual PID with
its Linux start tick. The dashboard polls status, phase, progress, and elapsed time every 20
seconds. Use `field_paths` to adapt a project's JSON structure. If no live source is available,
label the view as recorded status only. Do not claim that an unconnected experiment is monitored.
The monitor does not change experiment state or restart the process.

## Slack lifecycle notifications

When Slack notifications are requested, read [references/slack.md](references/slack.md).
Configure the user's chosen channel or DM and a bot-token environment/file reference in the
private notebook. Never hardcode a workspace, recipient, or credential in the shared skill.
Do not assume that a request to add this capability authorizes a test message to an unspecified target.

```bash
python3 <skill>/scripts/notebook.py configure-slack --root <book> --channel <channel-id> --token-env SLACK_BOT_TOKEN
python3 <skill>/scripts/notebook.py monitor --root <book> --once --dry-run
python3 <skill>/scripts/notebook.py monitor --root <book>
```

Run the monitor independently of the browser and before the actual experiment when possible.
It sends start/attach/resume, configured progress, completion, stop, failure, and attention events.
Existing historical terminal runs are not replayed. A late attachment is labeled as monitoring
an already active run. Progress defaults to changed observations at 30-minute intervals.

The private outbox preserves delivery and observation state across restarts. Failed Slack
delivery does not stop the research. Uncertain delivery requires an explicit resolution from
the actual Slack conversation before another attempt. See `notification-status` and
`resolve-notification` in the reference.
The web server and `GET` endpoints never send messages.

The SVG inheritance diagram links explicit research parents to children and opens their reports.
Execution order, reference data, and restarts do not create parent edges automatically.

Report the notebook URL, report path, study status, main findings, relevant resource use, and unresolved
evidence gaps. State whether you built a new notebook or only inspected an existing one.
Creating or publishing a skill does not authorize publishing private notebook content.
