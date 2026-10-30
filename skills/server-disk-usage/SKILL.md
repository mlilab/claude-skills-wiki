---
name: server-disk-usage
description: Measures who uses how much disk on a shared lab server (one Unix account shared by several people, each in a `<name>_workspace` folder), or breaks one folder down for tidying, decides whom to ask to tidy up by the lab's priority and sheet rules, and drafts their messages and a server-state notice. Attributes shared conda envs, Hugging Face models and datasets, docker images, containers and volumes, and hardlinked caches to people, marked direct or estimated. Use this whenever someone asks about disk space, storage, "disk full", "용량", "디스크", "누가 많이 써", "정리 부탁", which folders are big, what to delete or clean up, or how big conda envs, HF caches or docker data are on a server, even if they never name this skill.
---

# Server disk usage

`scripts/diskusage.py` (in this skill's base directory) does the measuring. It makes one
metadata-only pass (about 15 s for 3.6 M files) and prints an English brief of about 60 lines
for you. For people it writes a Korean Markdown report (most users are Korean) and an HTML
view, always into `<skill dir>/results/`. Nothing is ever deleted. The skill finds where the
space is and whom to ask, and the owners tidy their own workspaces.

Your part is what the code cannot do: settle what the user wants, read the brief, dig into the
few items where judgment changes the answer, and explain. Keep your own reading small: the
brief plus at most five follow-up commands of up to 30 lines each. A whole run should cost a
few thousand tokens.

## 1. Ask first

Run `python3 <skill dir>/scripts/diskusage.py free` first. It is instant and prints each disk's
size, used and free space, and the saved lists of who holds a priority grant or a sheet slot on
this server. Then ask once with AskUserQuestion, in Korean unless the user writes otherwise.
Skip a question the request already answers, and skip all of them for a follow-up about an
existing report. Do not ask where to save the report.

1. **Top folder**: which part of the server to look at. Offer the whole disk holding the
   account's home *(recommended)*, the account home itself (`/home/<account>`), or another
   path.
2. **Space to free**: "지금 남은 공간은 N G입니다. 얼마나 더 확보해야 하나요?" Offer about
   +50G, +100G and +200G, plus "목표 없음, 현황만".
3. **Priority and sheet** (only with a target): the lab's priority holders and the people who
   signed up on the usage sheet are asked last, for old data and caches only. If lists are
   saved, offer "저장된 명단 그대로 (우선권 …, 시트 …, 기록일)" *(recommended)*, "바뀜" and
   "명단 없음". If none are saved, offer "명단 없음 (모두 일반으로 계산)" and let the user type
   the names.

The answers map to commands like this:

- Whole disk: `scan`. Another top folder: `scan --root PATH`.
- A target: add `--need SIZE`. A margin of 30G is added (`--margin` changes it).
- Lists: `--priority a,b --sheet c,d`. They are saved in `<skill dir>/roles/<host>.json` for
  next time, so pass them only when they changed.
- The messages give tomorrow as the deadline. Use `--deadline YYYY-MM-DD` if the user names another.
- People using under 20G in total are not asked (`--min-user` changes it).
- Someone who only wants to tidy their own folder gets `scan --mode folder --root PATH`, with no
  questions about targets.
- Only specific people: add `--users a,b`.

## 2. Run

```bash
nice -n19 python3 <skill dir>/scripts/diskusage.py scan [options]
```

- Within a day, for the same scope, `diskusage.py report` reprints the last snapshot without
  rescanning.
- If the scan runs longer than a minute, run it in the background. Never start a second scan
  while one is running.
- The brief lists the other filesystems. If one of them is over 90 % full, or the user asks,
  use `scan --all` (each disk separately) or `scan --target MOUNT`.
- Read only the brief. The `.md`, `.html` and `summary.json` files are for the user and for
  later commands.

## 3. Dig where it matters

The brief flags things. You decide what deserves a closer look. Spend follow-ups on items that
are both big and uncertain, in this order, and stop once the user's question is answered.

| Signal in the brief | Follow-up | Conclude |
|---|---|---|
| A shared item of 20 G or more marked `[unknown]`, `ambiguous` or `[estimated]` | an evidence check below | Upgrade to direct only on direct evidence. Otherwise keep it estimated and say on what basis. |
| A "(its own files + smaller subfolders)" row of 10 G or more | `show PATH` | What is in it |
| A cleanup candidate of 50 G or more | `show PATH --files --top 10` | What kind of data it is (checkpoints, datasets, archives) and how old |
| Growth of 20 G or more since the last snapshot | `show PATH` | Where the growth came from |
| "Not measured" at 10 % of used or more | none | The reason (container storage, root-owned dirs); offer the sudo run |

Evidence checks. Each is metadata only and prints at most 30 lines:

- **conda env**: `grep -m5 '^# cmd' ENV/conda-meta/history`. Look for workspace paths or
  env-file paths in the commands.
- **Hugging Face repo**: `ls REPO/refs REPO/snapshots`, and `show` on workspaces with
  folders named like it.
- **docker**: `docker inspect --format '{{.Name}} {{.Config.Image}} {{range .Mounts}}{{.Type}}:{{.Source}}{{.Name}} {{end}}' NAME`
  and `docker ps -a --filter volume=VOL`.
- **A folder of unclear purpose**: `show PATH --files --top 10`.

## 4. Answer

What to ask people to tidy: their own workspace data, models, datasets, conda envs and docker
data. Plain cache folders (`~/.cache/wandb`, pip, uv, poetry, bazel, torch hub and the like) are
not cleanup targets. Never suggest a request or a notice for them, and leave them out of your
answer unless the user asks about them.

Answer briefly, in the user's language (usually Korean). Use the report's terms: 확실, 추정
and 미상 for certainty, and 30일·90일 미수정 and 90일 미사용 for age.

1. **The disk**: one line with used, free, and how much of the used space was measured.
2. **Whom to ask** (when there is a target). The report orders people the way the lab does.
   First come those with neither a priority grant nor a sheet slot, asked about their whole
   share. If that is not enough, sheet users and then priority holders follow, asked only about
   old data and caches. People under 20G, and sheet or priority users with little old data, are
   left out. Show the 이번에 and 모자라면 rows with each person's amount.
3. **The messages** (when there is a target): run `diskusage.py messages` and paste its output
   into the answer unchanged, each message in its own fenced `text` block so it copies cleanly.
   Give the 이번에 people's messages first, then the server-state notice. Name the 모자라면
   people and say their messages are at the end of the report. Never send anything yourself.
4. **The table**: the owner or folder table from the brief. Copy its rows; do not recompute
   them. For owners use the report's columns: 사용자 | 합계 | 합계 (추정 포함) | 30일 미수정 |
   90일 미수정, from Total, Total (+ estimated) and the two Unmodified columns.
5. **Your findings from step 3**: one line per item, with its certainty and the evidence.
6. **Caveats**: only those that change a number shown. The list is in
   `references/how-it-counts.md`.
7. **File paths**: the `.md` report (Korean; reads well in VS Code's Markdown preview) and the
   `.html` view (any browser, for example VS Code's Simple Browser).
8. **Cost**: the script's Cost line.

## Safety

- **Read-only.** Never delete, move, truncate, `chmod` or `chown` anything, even when asked.
  The owners tidy their own data. When they ask how, give them a command to run, for example `conda clean --all --dry-run`,
  `conda env remove -n NAME`, `huggingface-cli scan-cache` and then `delete-cache`,
  `uv cache prune`, `pip cache purge`, or `docker image rm` / `docker volume rm` for an
  admin. Tell them to check `--help` first.
- **Never open files inside anyone's workspace.** The conda, Hugging Face and docker
  metadata above are the only contents read. Quote no deeper path than the answer needs,
  because a folder name can be sensitive.
- **The notice's deadline is the lab's process, not the skill's.** When it says unclaimed
  items will be removed after the deadline, a person does that later. The skill never deletes
  anything, before or after the deadline.
- **Never run sudo or ask for a password.** When container storage or root-owned folders
  hide a large share, ask the user to run
  `sudo python3 <skill dir>/scripts/diskusage.py scan` in a terminal. Then use `report`.

## Reference

Read `references/how-it-counts.md` when you need to explain how a number was computed, why
it differs from `du`, what direct and estimated mean, or which caveats apply.
