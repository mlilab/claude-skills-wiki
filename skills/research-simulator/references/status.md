# Research status: getting it from anywhere

The simulator starts from one research status. It can come from any source; what matters is that it ends up in this shape:

```json
{
  "title": "short project title",
  "problem": "2-3 sentences: what is solved, in which setting, under which constraints",
  "method": "2-3 sentences: the current approach",
  "problem_tags": ["5-7 lowercase-hyphenated tags"],
  "method_tags": ["5-7 lowercase-hyphenated tags"],
  "status": [
    {"kind": "done", "text": "finding with its number, metric and dataset", "result": "optional"},
    {"kind": "todo", "text": "experiment still to run: what, on what, which metric"},
    {"kind": "note", "text": "context that is neither"}
  ]
}
```
Facet text and tags in English (relatedness is computed from them). Status text in the user's language is fine.

## Sources, and how to read them

| source | what to read | watch out for |
|---|---|---|
| **This conversation** | what the user said about goals, method, results, next steps | separate what was run from what was planned |
| **Claude Code / a repo** | README, configs, experiment scripts, result logs or CSVs, recent commits, TODO/issue notes | results only from logs or files that report them; a config is a plan, not a result |
| **Another Claude chat or project** | ask the user to run the export prompt below there and paste the JSON; or read artifacts that chat produced (Artifact list → read) | artifacts are snapshots: newest wins, older ones may be superseded |
| **Notes, a draft, an abstract** | the text as given | abstracts overstate; drafts may describe planned experiments in past tense |
| **Inside the page** | ⇅ Import: paste any of the above; JSON is used directly, plain text is converted by the agent | the agent in the page cannot see files, only what is pasted |

Rules for every source: copy numbers exactly with metric and dataset; a result without a source is a todo, not done; record where the status came from (`sim.py init --status-source "..."`) and say it to the user.

## Export prompt (paste into Claude Code or any Claude chat)

```text
Summarise the current state of this research project as ONE JSON object for a research simulator. Use only what this
conversation / repository actually shows; do not invent results. Shape:
{"title": "...", "problem": "2-3 sentences: what is solved, setting, constraints",
 "method": "2-3 sentences: the current approach",
 "problem_tags": ["5-7 lowercase-hyphenated English tags"], "method_tags": ["5-7 tags"],
 "status": [{"kind": "done", "text": "result with its number, metric and dataset"},
            {"kind": "todo", "text": "experiment or step still open"},
            {"kind": "note", "text": "anything else that matters"}]}
Write problem, method and tags in English. Give 4-10 status items, newest first. Reply with the JSON only.
```
In Claude Code, add: "Read the README, configs, result files and recent commits first."
