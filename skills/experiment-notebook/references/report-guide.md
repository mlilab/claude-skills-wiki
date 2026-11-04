# Experiment report guide

Use the current project guide and the notebook's `GUIDE.md` before every report edit.
This default is editable. Project terminology and scoring policies remain project-specific.

## Evidence and writing

Apply the bundled `asd-ste100` skill. Use clear sentences and consistent terms. Preserve
uncertainty, exact quotations, identifiers, and raw evidence. Do not claim certified STE compliance.

Separate observed results, user interpretation, author interpretation, estimates, and unknowns.
A completed procedure does not establish scientific success or measurement validity.
Do not infer causality from an observed association or an outcome label alone.

Record the research question, scope, methods, comparison or context, and assessment criteria.
Include hypotheses when the research uses them. Exploratory and qualitative studies need not
have a numerical success threshold. Separate planned work from completed work.
Update the report as observations and analyses become available. Never invent a timestamp.

## Default report structure

1. **Previous experiment and context**: actual research parent and report link, plus background.
   Use none for a first experiment and unknown for an unrecorded parent.
2. **Differences and methods**: what differs from the parent, before/after values, reasons, and
   unchanged conditions. Include the research design and analysis procedure.
3. **Purpose and hypotheses**: objectives, hypothesis statements, and assessment criteria.
   Separate plans from observations. Explicitly identify exploratory work without a prior hypothesis.
4. **Results**: observations, measurements, qualitative findings, or analysis outputs. Include
   resource use only when relevant. Link supporting material instead of pasting large data dumps.
5. **Interpretation**: findings, limitations, alternative explanations, and optional review feedback.
6. **Required changes and follow-up**: what must change, why, which changes are implemented,
   what validation exists, unresolved questions, and next steps.

For code-based studies, include actual execution Git commits and phase information in the main
report's provenance table. Keep preparation, execution, and reporting snapshots distinct.
Use `hypotheses`, `comparisons`, and `follow_up` for their structured main-report tables.

These are defaults, not a mandatory scientific method. Configure `sections` in `notebook.json`
to rename, add, remove, or reorder sections while preserving the applicable information above.
Follow the discipline's reporting standards and the
user's existing guide. Keep the `results` key when structured metrics or iteration tables should
appear in the main report. They remain available on the details page with other section layouts.

Long explanations belong in registered supporting files or descriptive details/summary toggles.
Keep the main result visible. Preserve existing detailed reports when introducing a short summary.

## Reproducibility and accounting

Record the provenance that the work actually has: protocol versions, instruments, sample or
source identifiers, data versions, analysis procedures, dates, and measurement windows.
For software-based work, also record actual execution commits, dirty state, environment, and
configuration when available. Git and source code are not prerequisites for a research record.
The reporting commit and execution commit are separate. Current HEAD cannot identify an old run.

Record errors, evidence-supported causes, fixes, retries, reruns, and their additional usage.
Use the units relevant to the study, such as instrument hours, material quantities, participant
time, or compute cost. Separate measured consumption, estimated cost, and account charges.
AI API and subscription use are optional examples, not required fields. Unknown is not zero.
Reused results do not have the same timing or cost window as newly collected observations.

Keep original observations, responses, diagnostics, and historical policies immutable. If recomputing a
metric offline, label it as a later calculation with its policy, inputs, and implementation version.
Never recalculate scores just to make a viewer or terminology change.

## Optional review feedback

When requested by the user or project guide, record review conclusions and follow-up decisions
separately from observations and the author's analysis. Preserve their meaning and do not invent
feedback. Set `request_feedback: true` to request review for each new record. A specific record
can also use `feedback.status: pending`. Save the factual report before requesting feedback.
Otherwise use `not_applicable`. A missing response is not approval. Preserve existing feedback.

## Iterations and explanations

The optional `iterations` table applies to repeated measurements, parameter sweeps, analysis
revisions, or other iterative work. Group rows by the study's own series or phase.
Record the question or change, evidence, and actual result. Do not invent missing observations.
Studies without iterations can leave the list empty.

Explain unfamiliar terms and describe the research objective, inputs or materials, procedure,
and observed result. Where helpful, compare the reference condition with the observation using
a small example. Label illustrations separately from actual collected data. Use the discipline's
terms and quality checks. Distinguish recorded causes from hypotheses about causes.

## Boundaries

Keep raw files immutable. Do not place credentials, authorization headers, protocol signatures,
private account IDs, or held-out evaluation data into shared skill files. Register only intended
evidence in a private notebook. Preserve access restrictions for participants, collaborators,
restricted datasets, and evaluation materials. Do not assume permission to run, retry, publish, or notify.
