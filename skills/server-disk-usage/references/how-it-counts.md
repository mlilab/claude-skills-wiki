# How diskusage.py counts

Read this when you explain a number, a difference from `du`, an attribution, or a caveat.

## Contents
1. Owners
2. Shared items: direct and estimated
3. Sizes
4. Columns in the brief
5. Whom to ask (`--need`)
6. What is not measured
7. Why not plain `du` (measured)
8. Caveats

## 1. Owners

- `<name>`: the outermost folder named `<name>_workspace`, where `<name>` looks like a
  person (`[A-Za-z][A-Za-z0-9._-]*`) and no ancestor is hidden or a tmp dir. Tool folders
  such as `.local/share/sourcery/workspaces/%home%..._workspace` or bazel's `another_workspace`
  are not owners. Nested workspaces belong to the outer one.
- `@<account>`: the home of another Unix login account (uid 1000 or above) that the account
  owns, for example `/home/alice` on a server where alice has a separate login. This is a
  direct mapping by uid.
- Anything else is "shared, unattributed" unless a shared-item rule below claims it.

## 2. Shared items: direct and estimated

The script looks at these outside every workspace: conda envs (any `envs/*`, and any folder with
`conda-meta`), Hugging Face hub repos (`models--org--name`, `datasets--...`, `spaces--...`)
and the `datasets` library cache, docker containers, images and volumes, and files hardlinked
from a workspace into a shared cache.

**Direct** (counted in the owner's Total) means at least one of these:
- a symlink inside the workspace points into the item, for example a venv's `bin/python`
  pointing into a shared env, or a link into an HF snapshot
- a file in the workspace is a hardlink of the item's file, for example a uv venv and the
  uv cache
- a running process whose working directory is in the workspace has a file of the item open
  or mapped. Models are mmapped. This is read from `/proc`, and processes of other uids,
  including container processes running as root, are not visible.
- `~/.conda/environments.txt` under a HOME inside the workspace lists the env, which conda
  writes when someone creates an env or installs into it
- an editable install in the env (`direct_url.json`, `.egg-link`, `__editable__*.pth`), or
  the env's `conda-meta/history`, names the workspace path
- a docker container bind-mounts the workspace. Its volumes inherit the owner, and so does
  its image when only that owner's containers use the image.

**Estimated** (added only in the Total (+ estimated) column) means only names point to the
owner:
- the owner's name appears in the item's name, for example `alice_vision`,
  `datasets--Alice--...` or the container `exp_bob_1`
- the item's name appears in the owner's folder names at least twice, and at least twice as
  often as for anyone else. Otherwise the item is listed as "ambiguous" with the counts.

When several owners have direct evidence, the item is split equally between them. Items with
no evidence stay unattributed and appear in the item list with `?`.

## 3. Sizes

- Allocated blocks (`st_blocks`), with symlinks not followed. Each inode is counted once, at
  the deepest folder that holds all of its links. That is the space deleting that folder would
  free.
- A conda env's size excludes files hardlinked with `pkgs` or with other envs. Those stay with
  the conda root.
- An HF repo includes the blobs its snapshots link to. Newer caches keep blobs at the hub level
  (`hub/blobs/`); a blob linked from several repos is split between them.
- Docker sizes are docker's own numbers, in decimal units. They are image unique size,
  container writable layer and volume size. Layers shared by several images are one separate
  item.

## 4. Columns in the brief

- **Total**, 합계 in the report: the workspace plus shared items with direct evidence.
- **Total (+ estimated)**, 합계 (추정 포함): the same plus name-based shares. The report's
  per-person line gives the shared split (공용 확실 …, 추정 …).
- The Unmodified and Cold columns count Total.
- **Unmodified 30 d / 90 d**: bytes with no write in that many days. Change the two
  thresholds with `--days 30,90`.
- **Cold 90 d**: bytes with neither a read nor a write, over the longer threshold. It is based on atime, and directory
  atimes are ignored because the scan's own listing updates them. With `noatime` it falls back
  to mtime.
- **atime spike**: most of an owner's unmodified data was read on one day, which usually means
  a copy, rsync, backup or `grep -r`. Cold undercounts there, so trust Unmodified.
- **Other uid**: bytes inside folders owned by another uid, usually root, written by a container
  that mounts the workspace. The shared account cannot delete them. The owner needs the container
  (`docker exec ... chown -R`) or sudo, and future containers should run with
  `docker run --user $(id -u):$(id -g)`.
- **Cleanup kinds**: cache (pip, uv, HF, conda pkgs, ...), outputs (checkpoints, runs, logs,
  wandb, ...), cold or unmodified (80 % or more of the bytes, over the longer threshold), trash, and docker images that no
  container uses.

## 5. Whom to ask (`--need`)

The lab gives some people a priority grant on a server, and others sign up in an empty slot on
the usage sheet. Both groups are asked last, and only about old data and caches. Everyone else
is asked first, about their whole share.

- **Share**: the workspace, plus shared items with direct evidence, plus estimated shares.
  Estimated items are listed in the message with a request to confirm them.
- **Amount asked**: the whole share for people with neither a grant nor a slot. For sheet users
  and priority holders it is data unmodified for 90 days, plus caches, plus the old part of their
  estimated items.
- **Order**: general users first, then sheet users, then priority holders. Within each group the
  larger amount comes first. People are taken until the amounts reach need + margin (30 G by
  default); the rest are listed as 모자라면.
- **Left out**: anyone under `--min-user` (20 G) in total, and sheet users or priority holders
  whose amount asked is under 20 G.
- **No owner** (the server-state notice): conda envs, Hugging Face models and datasets, and
  docker images and volumes of 1 G or more that nobody could be traced to, plus the items of
  people who have no workspace on this server. Plain cache folders (wandb, pip, poetry, bazel,
  torch hub, ...) are not cleanup targets and are never listed. The deadline defaults to
  tomorrow.
- **Lists**: `--priority` and `--sheet` are saved with the date in
  `<skill dir>/roles/<host>.json`, one file per server.

The tool drafts requests only. Owners tidy their own data, and any removal after the notice's
deadline is done by a person.

## 6. What is not measured

"Not measured" is the device's `used` minus what the scan saw, minus docker's numbers when
docker storage is unreadable. It contains:
- container storage (`/var/lib/docker`, containerd) when docker cannot be queried
- folders that cannot be listed, usually root-owned `700` or `500`, written by containers
- files that were deleted while a process still holds them open
- files hidden under mount points, and filesystem overhead

The root reserve (5 % on ext4 by default) is shown on its own. It is why `df` reports 97 % used
while 28 G is still free for root.

## 7. Why not plain `du` (measured on a lab server, 2026-10-29)

- `du` charges a hardlinked file to whichever path it reaches first, and that depends on
  directory order. uv venvs were 90 % hardlinks into the uv cache. `du` showed one folder as
  12.8 G, while deleting it would free 2.3 G.
- `du -x` stats a mount point before it skips it, so a dead NFS or sshfs mount hangs it. The
  script skips mount points by path before any `stat`. `du --exclude` also matches basenames,
  so it can drop unrelated folders that share a mount's name.
- An audit limited to the home folder missed 160 G of `df`'s used space (system trees,
  container storage). The script scans the whole device and reconciles with `df`.
- A conda or pip install keeps its packages' build-time mtimes, so mtime alone calls a live
  env stale. Hence the separate Unmodified and Cold columns.
- `ionice -c3` does nothing on NVMe (the scheduler is `none`), so only `nice` is used.
- Cross-check: the whole-device total matched `du` within 0.3 MB.

## 8. Caveats (state them only when they change a number shown)

- A hardlink whose other link lies outside the scan, or inside an unreadable folder, stays
  charged where it was seen. Links of 1 G or more are listed as "not freeable from here".
- Docker's numbers and the walk's numbers can overlap when the scan runs as root and can read
  docker's storage. In that case docker bytes are taken out of "shared, unattributed".
- Folders under 64 MB are not kept in the snapshot tree. A folder that grew from under 64 MB
  counts as growing from 0.
- Estimates are names, not proof. Never present one as an owner's confirmed usage.
