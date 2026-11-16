# GPU Sheet Sync

GPU Sheet Sync is a Claude Code skill for the lab's GPU sheet ("MLILAB Server State", tab
"info"). Lab members write their name on a GPU when they take it, and often leave it there
after their job ends. One run of this skill logs in to every server listed in the sheet,
checks each GPU with `nvidia-smi`, and clears the names on GPUs that are idle. Names on busy
GPUs stay.

## What it does

| Feature | What you get |
| --- | --- |
| Sign in once | Your only step is one browser sign-in with your @mli.kaist.ac.kr account. The skill sets up the rest itself, and later runs reuse the sign-in. |
| All servers at once | Every current server in the sheet (rows whose PORT is 100NN) is checked over SSH as `serverNN@<proxy> -p 100NN -o "IdentitiesOnly yes"`. The proxies are the "Proxy Servers IP" addresses in the sheet. |
| Careful idle rule | A GPU counts as idle only if it has no process, under 500 MiB of memory and under 5% utilization in each of 3 samples. A job that holds memory, or a missing reading, counts as busy. |
| Ask before writing | You get a summary first: idle GPUs that still carry a name, busy GPUs with no name, and skipped servers. Names are cleared only if you say yes. |
| Safe sheet update | Only GPU cells of idle GPUs are cleared, values only. Just before clearing, those servers are checked again and the sheet is read again; a GPU that became busy or a cell that changed is left alone. Servers that can't be reached are not touched. |
| Report | A progress line per server ("checked, 4/8 GPUs idle"), then the servers ranked from most to fewest free GPUs, with the names that would be cleared, busy GPUs with no name, and skipped servers with the reason. `--details` lists every GPU. |
| One password, typed once | The lab servers share one password. When servers reject your SSH key, the run asks for it once and adds your public key on all of them, so later runs need no password. It is kept in memory for that run only. |
| Gentle on the proxies | The lab proxies block a computer that opens many connections quickly, so connections are paced (one every 3 seconds, about 1.5–2 minutes per run). The run doesn't retry servers that are down, and it stops using a proxy that keeps refusing. |

## Requirements

- Claude Code, or another agent that reads `SKILL.md` skills.
- Python 3.8+ (standard library only) and `ssh`.
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install), used only for the sign-in, and the
  [gws](https://github.com/googleworkspace/cli) CLI for the sheet (`npm install -g @googleworkspace/cli`).
- A network from which the lab proxies are reachable, the same one you use for the lab servers.

## Install

```bash
git clone https://github.com/mlilab/claude-skills-wiki.git "$HOME/claude-skills-wiki"
mkdir -p "$HOME/.claude/skills"
ln -s "$HOME/claude-skills-wiki/skills/gpu-sheet-sync" "$HOME/.claude/skills/gpu-sheet-sync"
npm install -g @googleworkspace/cli
```

Then sign in once. A browser opens; choose your @mli.kaist.ac.kr account and click Allow.

```bash
python3 scripts/gpu_sheet.py login
```

The sign-in is kept in `~/.config/gpu-sheet-sync`, apart from your default gcloud account. The
skill also creates a small GCP project of yours (`gpu-sheet-sync-…`) with the Sheets API on,
which Google requires for API quota. It has no billing account, so it costs nothing.

There is no separate SSH setup. The first `check` in a terminal asks once for the lab servers'
password if some servers don't accept your key yet, then adds your key on all of them.
`setup-keys` does the same without checking GPUs.

## Use

| Ask | Result |
| --- | --- |
| "Update the GPU sheet" | Checks every server, summarizes idle and busy GPUs, then asks whether to clear the names on the idle ones and does it if you say yes |
| "Which lab GPUs are free right now?" | The same check and summary, then the same question |
| "Is anyone actually using server39?" | The check limited to that server |

The sheet is changed only after you agree. Clearing re-checks just the servers involved, so it
takes seconds, and it leaves any GPU that became busy or any cell someone edited meanwhile.

The script can also be run by hand:

```bash
python3 scripts/gpu_sheet.py check --json plan.json    # report only (asks the password once if needed)
python3 scripts/gpu_sheet.py apply --plan plan.json    # clear the idle names that check listed
python3 scripts/gpu_sheet.py check --servers 24,39     # some servers only
python3 scripts/gpu_sheet.py setup-keys                # only add your SSH key where needed
```

`python3 tests/run_tests.py` runs the offline tests (no network, Google account or ssh).

## Notes

- **Read-only on the servers.** It runs only `hostname` and `nvidia-smi`, and adds your
  public key to `~/.ssh/authorized_keys` in `setup-keys`. It never stops or kills jobs.
- **Only GPU cells.** The tab also holds passwords and notes. The skill reads and reports only
  the GPU cells, and never fills in names.
- **Merged cells.** A name merged across several GPUs is cleared only when all of them are idle.
- **Exit codes.** 3 means a Google Sheets error, and 4 means you need to sign in with your lab
  account (`login`).
