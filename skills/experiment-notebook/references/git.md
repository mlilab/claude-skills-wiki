# Git connection and execution provenance

Associate the actual local source checkout with the notebook. These commands read the source
repository and write only the notebook. They do not configure Git, contact a remote, fetch,
push, create a commit, or execute project code. No token is needed for local inspection.

```bash
python3 <skill>/scripts/notebook.py connect-git --root <book> --repository /path/to/source
python3 <skill>/scripts/notebook.py git-status --root <book>
```

The connection stores `repository` in `notebook.json`. Inspection records the full HEAD commit,
branch or detached state, dirty flag, changed paths, and credential-stripped remote URLs.
The repository must already contain a commit. A missing or inaccessible repository does not
authorize creating one or changing its permissions.

## Capture stages

```bash
python3 <skill>/scripts/notebook.py capture-git --root <book> --experiment <id> --stage preparation --phase prepared
```

`preparation` is the default stage. It adds a dated entry to `code_snapshots` and does not add
an actual execution version. Planning does not establish that any research ran.

At actual start or resume, mark the notebook record as `running` and invoke:

```bash
python3 <skill>/scripts/notebook.py capture-git --root <book> --experiment <id> --stage execution --phase initial-run
```

This appends to `code_snapshots` and `execution`. An execution capture requires a running
notebook record. The capture itself does not start research or change its state.
The caller must select the checkout used by the actual run. For worktrees, containers, or
remote workers, verify that relationship from the execution system's evidence.

For later reporting changes:

```bash
python3 <skill>/scripts/notebook.py capture-git --root <book> --experiment <id> --stage reporting --phase report-edit
```

Reporting snapshots do not replace actual execution entries. Multiple starts or resumes can
retain multiple versions with their phase names and capture timestamps.

## Historical runs and dirty trees

A present-day snapshot cannot reconstruct an old execution version. Read the original run
manifest, launcher record, or archived provenance and write its actual commit into `execution`.
If no source establishes it, retain an unknown value. The dashboard's repository panel explicitly
describes the checkout at build time, separately from each experiment's execution versions.

A dirty flag and changed-path list do not archive the changed source. Preserve the corresponding
diff and untracked inputs in an authorized evidence location when reproducibility requires them.
The checker warns about dirty snapshots. It never silently commits or copies source files.

Non-code research does not need Git. Record the protocol, dataset, instrument, or analysis
version actually used. This exception does not weaken Git provenance for code-based studies.
