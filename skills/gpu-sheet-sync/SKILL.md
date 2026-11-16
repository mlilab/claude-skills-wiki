---
name: gpu-sheet-sync
description: Check every MLI lab GPU server listed in the lab's GPU sheet ("MLILAB Server State", tab "info") over SSH, find which GPUs are idle with nvidia-smi, summarize, and then ask the user whether to clear the names on idle GPUs (GPU 0 to GPU 7) in the Google Sheet; only after a yes, clear them with the gws CLI, keeping the names on busy GPUs. The user only signs in once with their @mli.kaist.ac.kr Google account; everything else is automatic. Also installs the user's SSH key on servers that still ask for a password. Use when the user asks to check or update the lab GPU sheet, see which lab GPUs are free, clean up stale GPU reservations, or says the sheet still shows names on GPUs nobody is using.
---

# GPU sheet sync

Lab members write their name in the GPU sheet when they take a GPU, and often forget to remove it. This skill logs in to every server in the sheet, checks each GPU with `nvidia-smi`, and clears the names on GPUs that are idle. Names on busy GPUs stay.

`scripts/gpu_sheet.py` in this skill's base directory does all of it, written below as `<skill dir>/scripts/gpu_sheet.py`. It needs Python 3.8+, `ssh`, the gcloud CLI and the gws CLI (`npm install -g @googleworkspace/cli`; ask before installing anything). On Windows, use `python` if `python3` is not found.

## 1. Sign in (the user's only step)

Every sheet access goes through the user's **@mli.kaist.ac.kr** Google account. Run `check` directly. If it exits with code 4 ("No @mli.kaist.ac.kr Google sign-in found", or a wrong or expired one), the user signs in once:

```bash
python3 <skill dir>/scripts/gpu_sheet.py login
```

A browser opens. The user chooses their @mli.kaist.ac.kr account and clicks Allow; that's all. Start this command for them in a Terminal tab (desktop app) or ask them to run it with `!` (Claude Code CLI), because only they can sign in. Then run `check` again.

What happens around that sign-in, all automatic:
- The sign-in is a gcloud login with Drive access, kept in the skill's own folder `~/.config/gpu-sheet-sync`. The user's default gcloud account and credentials don't change. Later runs reuse it without asking, and `login` says "Already signed in" when nothing is needed.
- The script finds or creates a GCP project of the user's named `gpu-sheet-sync-…`, turns on the Sheets API there, and remembers it. Google needs a project for API quota. It has no billing account, so it costs nothing.
- If the user signed in with another account, the script refuses to touch the sheet. Run `login --force` and ask them to pick the lab account.

Never sign in for the user, never use another account even if it can open the sheet, and never create sign-in apps or OAuth clients by hand.

## 2. SSH: servers that reject the key need the password once

Server NN is reached as `ssh serverNN@<proxy> -p 100NN -o "IdentitiesOnly yes"`. The proxies are the IPs under "Proxy Servers IP" in the sheet. `check` first tries key login only (`BatchMode`). The lab server accounts share one password, so when servers reject the key:

- **`check` run in a terminal asks once.** It asks for the password one time, then logs in to every server that rejected the key with it. On each, it appends the user's public key (`~/.ssh/id_ed25519.pub`, `id_ecdsa.pub` or `id_rsa.pub`) to `~/.ssh/authorized_keys` and checks the server in the same run. Later runs need no password. If the first server rejects the password, the user may retype it once. If the user has no key, it offers to create one with `ssh-keygen`.
- **When you run `check`, there is no terminal**, so it lists those servers and doesn't ask. Start this in a Terminal tab for the user (desktop app), or ask them to run it with `!` (Claude Code CLI):

  ```bash
  python3 <skill dir>/scripts/gpu_sheet.py setup-keys --servers <the listed numbers>
  ```

  It asks for the password once and adds the key on all of them. Then run `check` again.

The password is the user's to type, into the script's hidden prompt. The script keeps it in memory for that run only and hands it to ssh through ssh's askpass hook (a small helper in `~/.config/gpu-sheet-sync` that reads it from the environment of that one ssh process). It is never shown, written to a file, or put on a command line. Never ask for it in chat, type it yourself, store it, or read the passwords stored in the sheet.

On Windows the script uses the built-in OpenSSH (`C:\Windows\System32\OpenSSH\ssh.exe`), which gets keys from the Windows ssh-agent, so a passphrase-protected key loaded there works. If the user's own ssh works but the script reports "key not accepted", their key probably has a passphrase that isn't loaded into ssh-agent.

## 3. Check, summarize, ask, then clear

Always in this order, even when the user says "update the sheet": the sheet is changed only after the user agrees to the summary.

**a. Check** (writes nothing):

```bash
python3 <skill dir>/scripts/gpu_sheet.py check --no-password --json <scratch dir>/gpu.json
```

Always pass `--no-password` when you run it: your shell may look like a terminal to the script, and without the flag it would sit at a password prompt nobody sees. Servers that reject the key are then listed for step 2 instead. It reads the sheet and checks every server, printing a progress line per server ("checked, 4/8 GPUs idle"). Then it prints the servers ranked from most to fewest free GPUs, one line each:

```
Free GPUs by server, most first:
  server37  6/6 idle   name to clear: GPU0-5 'Kim'
  server24  4/4 idle   name to clear: GPU0-3 'Long'
  server31  4/8 idle   busy, no name: GPU1, GPU3, GPU5, GPU7
  server08  0/4 idle
Skipped:
  server20  unreachable (connection closed)

14/22 GPUs idle on 4 checked servers (1 skipped). 5 name(s) on idle GPUs to clear, 4 busy GPU(s) with no name.
```

`--details` also lists every GPU of every server. The JSON file is the plan for step c. Keep it in a scratch directory, out of the user's repository.

The lab proxies block a computer that opens too many connections in a short time, for 10 minutes or more, and that also blocks the user's own ssh. So the script opens at most one new SSH connection every 3 seconds, across both proxies together; a full run takes about 1.5–2 minutes and prints a progress line per server. It doesn't retry a server that is down through the other proxy, and it stops using a proxy that keeps refusing. Run it once. If it reports "the proxies are refusing connections", tell the user and wait at least 10 minutes before running it again. Never rerun it in a loop, retry servers one by one, or lower `--interval`.

**b. Summarize and ask.** Show the ranking as the script printed it (most free GPUs first), then point out:
- **Names on idle GPUs** ("name to clear"): these are what would be cleared.
- **Busy GPUs with no name** ("busy, no name"): someone is using them without writing it in the sheet.
- **Skipped servers** and why. "key not accepted" means step 2. "unreachable" for a few servers usually means they are down. If every server is unreachable, this computer can't reach the proxies: the user should connect the way they normally reach the lab servers.

Then ask whether to clear the names on those idle GPUs. If there are none, say so and stop.

**c. Clear, only if the user says yes:**

```bash
python3 <skill dir>/scripts/gpu_sheet.py apply --plan <scratch dir>/gpu.json
```

This checks only the servers in the plan again, which takes seconds, not a full run. It clears a cell only if every GPU it names is still idle and the cell still holds the name the check saw. It clears values only, so formatting stays. Then tell the user what was cleared (server, GPU, cell, old name) and what was left and why ("no longer idle", "the cell changed").

If the user says no, or only part ("only server24"), don't clear anything they didn't agree to. For a part, run `check --servers <those> --json …` again and apply that plan.

## How a GPU is judged

A GPU is **idle** when, in each of 3 samples taken 1 second apart, it has no compute process, uses less than 500 MiB of memory, and is under 5% utilization. Anything else is **busy**, including a GPU whose memory is held by a stopped job and a GPU whose readings are missing. Change the limits with `--mem-mib`, `--util` and `--samples` only when the user asks.

What the script never changes:
- names on busy GPUs;
- cells of servers it could not check, and GPU columns the server does not have;
- cells that already mean "free" (empty, `-`, `x`, `n/a`, `free`, `idle`, `none`);
- a merged cell that covers several GPUs, unless every GPU it covers is idle;
- any cell other than the GPU cells of server rows.

## The sheet

Spreadsheet `100Rey7X-AJ-XCnjUKuKrno7Ku04Q_TYBPz6YYkFZIT4`, tab "info" (`gid=339844279`). The header row has `GPU 0` … `GPU 7` and `PORT` columns. A row counts as a server when its server-name cell says "server NN" and its PORT is 100NN. Rows of the old layout, with other ports, are skipped. `--host` overrides the proxies, `--sheet-id` and `--gid` point to another sheet, and `--servers 24,39` limits the run.

The tab also holds server passwords and other private notes. Never print, copy or summarize anything from it except the GPU cells the script reports.

If the script finds no server rows, the sheet layout has changed. Tell the user what you see, and don't edit the sheet by hand.

## Rules

- Change the sheet only through `apply --plan`, after the user agreed to the summary. Never clear, write or format other cells, and never fill in names.
- On the servers, run only what the script runs: `nvidia-smi`, `hostname`, and the key install in `setup-keys`. Never kill processes or change anything else.
- Report what the script printed. Don't call a GPU idle or busy from your own reading of the numbers.
