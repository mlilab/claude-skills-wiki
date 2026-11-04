# Experiment Notebook

[한국어](README.ko.md) | English

A Claude Code and Codex skill for recording research questions, methods, observations, results,
and interpretations in an evidence-backed HTML notebook. Use it for computational experiments,
laboratory measurements, field observations, qualitative studies, or literature-based analyses.
Each record represents a study or a coherent piece of research. Its core is **Git provenance,
experiment monitoring, inheritance diagrams, and reports that connect purpose, hypotheses,
parent differences, results, and required fixes**.

The skill has no project-specific roles, scoring formula, model, budget, or experimental protocol.
Code-based studies connect their source Git repository. Non-code studies can use protocol or
data versions instead. AI services, agent logs, numerical metrics, and iterative optimization
are optional.

## Features

| Feature | What it does |
| --- | --- |
| Git connection | Connects a local source repository and captures its full commit, branch, dirty state, changed paths, and sanitized remotes. Separates preparation, execution, and reporting versions. |
| Experiment monitoring | Polls state, phase, progress, elapsed time, and optional Linux process identity without changing the experiment. Marks unconnected records as recorded-status only. |
| Inheritance diagram | Draws an SVG parent-to-child diagram with branches and report links. Reference sources, restarts, and chronological order remain separate. |
| Report essentials | Keeps actual execution commits, purpose/hypotheses, differences from the parent, results, analysis, and required fixes with their reasons and validation status. |
| Other provenance | Records protocols, instruments, data sources, sample identifiers, or analysis versions for the study. |
| Resources | Accepts study-specific quantities and costs, such as instrument hours, materials, participant time, or compute use. |
| Optional iterations | Links repeated measurements or revisions to their question/change, evidence, and result. |
| Evidence views | Provides field toggles for JSON and readable text views without modifying original files. Agent trajectories are optional adapters. |
| Dashboard | Offers search, newest-first records, live progress and status badges, and a text alternative to the inheritance diagram. |
| Languages | Provides English or Korean interface labels and a configurable timezone. Report content can use the study's language. |
| Optional review | Records review conclusions when requested. Does not require a user verdict after every study. |

## Install

Python 3.10+ is required. No third-party Python packages are needed. Git integration uses the
locally installed Git executable and does not need an API token for local inspection.

From a clone of this repository:

```bash
mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills"
ln -s /path/to/claude-skills-wiki/skills/experiment-notebook "$HOME/.claude/skills/experiment-notebook"
ln -s /path/to/claude-skills-wiki/skills/experiment-notebook "$HOME/.codex/skills/experiment-notebook"
```

Inspect an existing installation before creating a link with the same name. Keep personal
configuration, study data, logs, and credentials outside the shared skill directory.

## Use

Ask the agent, for example:

- “Connect this source repository, monitor the experiment, and show its parent branches and reports.”
- “Record the execution commit, hypothesis, changes from the parent, results, and fixes needed next.”
- “Build a notebook for this measurement study. Keep the source directory read-only.”
- “Record the protocol, observations, and limitations of these field visits.”
- “Compare these simulations and link each conclusion to its recorded results.”
- “Use the sections Question, Data selection, Analysis, Findings, and Limitations for this review.”
- “If available, use the Codex sessions bound to this directory as supporting evidence.”

Or start a notebook directly:

```bash
python3 /path/to/skill/scripts/notebook.py init --root /path/to/private-notebook --title "My research" --language en --timezone UTC
python3 /path/to/skill/scripts/notebook.py connect-git --root /path/to/private-notebook --repository /path/to/source
python3 /path/to/skill/scripts/notebook.py new --root /path/to/private-notebook --slug pilot-study --title "Pilot study" --parent none
python3 /path/to/skill/scripts/notebook.py capture-git --root /path/to/private-notebook --experiment 001-pilot-study --stage preparation --phase prepared
```

For non-code work, skip the Git connection and capture. Fill
`experiments/001-pilot-study/report.json` with actual evidence. At actual launch/resume, use an
execution capture from the checkout used by the run while its notebook status is `running`:

```bash
python3 /path/to/skill/scripts/notebook.py capture-git --root /path/to/private-notebook --experiment 001-pilot-study --stage execution --phase initial-run
```

This does not launch the experiment. For a historical run, use its recorded execution evidence.
Configure `watch` with the actual state file or process identity for live monitoring. Then:

```bash
python3 /path/to/skill/scripts/notebook.py check --root /path/to/private-notebook
python3 /path/to/skill/scripts/notebook.py build --root /path/to/private-notebook
python3 /path/to/skill/scripts/notebook.py serve --root /path/to/private-notebook --port 8782
```

Open `http://127.0.0.1:8782/`. Forward that port when working on a remote server.
The server exposes only generated HTML/CSS/JS in its manifest, not original data or notebook JSON.

## Adapt it to the research

`notebook.json` controls the associated `repository`, `language` (`en` or `ko`), `timezone`, `sections`, `request_feedback`,
and the artifact size limit. Its defaults are English, UTC, six general sections, and no required
review. Rename, reorder, add, or remove sections in its `sections` mapping. Report-specific extra
sections are also preserved. `GUIDE.md` holds the project's writing conventions.

Use `hypotheses`, `comparisons`, and `follow_up` to keep hypotheses and assessment criteria,
before/after conditions and reasons, and needed/implemented/validated fixes in the main report.
Keep preparation, actual execution, and reporting commits distinct. A later code change must
not overwrite the version used by an earlier experiment.

Use `configuration`, `execution`, and `quality` for the provenance and checks that the study
actually has. A lab protocol can have a version without a Git commit. A qualitative study can
have findings without numerical metrics. Leave `usage` empty when resource accounting is not
relevant. No API, subscription, or billing fields are populated by default.

Leave `iterations` and `artifacts` empty when unused. For a running experiment, attach `watch`
to an available state file or PID. Without a live source, the dashboard explicitly shows recorded
status only. Set `request_feedback: true` only
when the project requires review for each record. A specific record can instead mark feedback
as `pending` when review is requested. Observed results and review conclusions remain separate.

See [Git provenance](references/git.md), the [record schema](references/schema.md), [writing guide](references/report-guide.md),
[evidence adapters](references/evidence.md), and [server notes](references/server.md).

## Scope and limits

This skill documents existing or planned research. It does not conduct experiments, rerun analyses,
change source projects, publish externally, send messages, or install recurring jobs.
Optional Linux PID observation requires a recorded process start tick. A completed procedure
and a supported research claim are separate outcomes.

The optional trajectory adapter supports Claude tool messages, Codex response items, and basic
ATIF steps. Unknown records remain available in a collapsed source view. Automatic masking
cannot identify every secret, so inspect inputs before sharing. The server is local-only and
is not an authenticated public hosting service.

Validation from the repository root:

```bash
python3 -B -m unittest discover -s skills/experiment-notebook/tests -v
```

Tests create and remove synthetic files only under this skill's `tests/.tmp/`. They do not use
existing research projects or running services.
