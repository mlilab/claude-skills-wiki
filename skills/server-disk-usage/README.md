# Server Disk Usage

Server Disk Usage is a Claude Code skill for shared lab servers, where one Unix account is used
by several people and each person works in a `<name>_workspace` folder. It measures who uses how
much of the disk, finds what can be tidied, and drafts the messages that ask the right people to
tidy it. It never deletes anything: the owners clean their own data.

## What it does

| Feature | What you get |
| --- | --- |
| Per-person totals | One metadata-only pass over the disk (about 15 s for 3.6 M files). Each inode is counted once, so hardlinks are not double-counted. Each person gets a total and 30- and 90-day unmodified shares. |
| Shared items | Shared conda envs, Hugging Face models and datasets, docker images, containers and volumes, and hardlinked caches are added to people. Each is marked **direct** (symlink, hardlink, bind mount or install record) or **estimated** (name match only). |
| Whom to ask | Given a target such as "free 100G", it orders people the way the lab does. General users come first, for their whole share. If that is not enough, people on the usage sheet and then priority holders follow, for old data and caches only. People under 20G are left out. |
| Messages | Ready-to-paste Korean messages for each person, and a server-state notice with a deadline. The skill never sends them. |
| Folder mode | For tidying one folder: its largest subfolders, their unmodified and unused (cold) shares, and cleanup candidates. |
| Reports | A Korean Markdown report and an HTML view in `results/`, and a short English brief that Claude reads. |

## Requirements

- Claude Code, or another agent that reads `SKILL.md` skills.
- Linux and Python 3.6+ (tested with 3.9). Only the standard library is used, so there is
  nothing to install.
- Optional: access to the `docker` CLI, for docker images, containers and volumes. Without it,
  docker storage is reported as "not measured".

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/server-disk-usage" "$HOME/.claude/skills/server-disk-usage"
```

On a shared account, the account's `~/.claude` belongs to everyone. Keep the clone and the link
in your own Claude setup instead, for example under `<name>_workspace/.claude_env` when you
start Claude with `HOME` set to that folder.

## Use

Ask in plain words. The skill triggers on disk questions, for example:

- "서버 디스크가 거의 다 찼대. 100G 정도 더 확보해야 하는데 누구한테 정리 부탁하면 될까?"
- "내 workspace 정리 좀 하고 싶은데, 어떤 폴더가 큰지랑 오래된 게 뭔지 보여줘."
- "공용 huggingface cache랑 conda envs, docker 이미지가 누구 건지 알 수 있어?"

It first shows each disk's free space. Then it asks at most three questions: which part of the
server to scan, how much space to free, and whether the saved priority and sheet lists are still
current. Then it scans and answers with whom to ask, the messages, a per-person table and the
report paths.

The script can also be run by hand:

```bash
python3 scripts/diskusage.py free                      # disks and saved lists (instant)
python3 scripts/diskusage.py scan --need 100G          # per person, with whom to ask
python3 scripts/diskusage.py scan --mode folder --root PATH
python3 scripts/diskusage.py show PATH --files         # largest subfolders or files
python3 scripts/diskusage.py messages                  # drafted requests and notice
```

## Notes

- **Read-only.** It never deletes, moves, truncates, `chmod`s or `chown`s anything, even when
  asked. When someone asks how to clean, it gives them a command to run themselves.
- **Metadata only.** Everything is `stat()`ed. The only files it opens are small metadata
  files: conda env registries and history, and editable-install records. Docker data comes
  from the `docker` CLI. It never opens data files in a workspace.
- **No sudo.** Root-owned folders and container storage show up as "not measured". Run
  `sudo python3 scripts/diskusage.py scan` yourself if that share matters, then ask Claude to
  use `report`.
- **Local state.** The priority and sheet lists are saved per host in `roles/<host>.json`, and
  reports and snapshots go to `results/`. Both are git-ignored.
- `references/how-it-counts.md` explains how each number is computed and why it differs from
  `du`.
