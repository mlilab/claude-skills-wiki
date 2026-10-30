#!/usr/bin/env python3
"""Disk usage on a shared server, per owner or per folder, from one metadata-only pass.

  diskusage.py scan [--mode user|folder] [--target PATH | --all] [--root PATH] [--users A,B]
                    [--days 30,90] [--min-size SIZE] [--chunk-min SIZE] [--top N]
                    [--need SIZE] [--margin 30G] [--priority A,B] [--sheet C,D]
                    [--min-user 20G] [--deadline YYYY-MM-DD] [--full]
  diskusage.py report [SNAPSHOT] [--full]   reprint the latest snapshot of each scanned root
  diskusage.py show PATH [SNAPSHOT] [--files] largest subfolders (snapshot) or files (live)
  diskusage.py free [PATH]                  size, used and free of each disk, saved roles (instant)
  diskusage.py messages [SNAPSHOT]          drafted requests and server-state notice

Owners
  <name>      the outermost <name>_workspace folder (no hidden or tmp ancestor)
  @<account>  the home folder of another Unix account, owned by that uid
Shared items outside workspaces (conda envs, Hugging Face models and datasets, docker
images, containers and volumes, hardlinked files) are added to an owner as
  direct     a workspace symlinks into it, bind-mounts it or hardlinks it, or the env's
             registry, editable installs or conda history name the workspace
  estimated  only names point to the owner (the owner's name in the item's name, or the
             item's name in the owner's folder names)
Only small metadata files are opened (conda env registries and history, editable-install
records); everything else is stat()ed. Standard library only, Python >= 3.6.
"""
import argparse
import datetime
import glob
import gzip
import heapq
import json
import os
import pwd
import re
import resource
import shutil
import socket
import stat
import subprocess
import sys
import time

WS_RE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*)_workspace$")
WS_PATH_RE = re.compile(r"/([A-Za-z][A-Za-z0-9._-]*?)_workspace(?=[/\"'\s]|$)")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_TOKENS = {"env", "envs", "test", "new", "old", "python", "conda", "base", "copy", "main",
               "cuda", "torch", "data", "runs", "model", "models", "train", "eval", "latest"}
TMP_DIRS = ("/tmp", "/var/tmp", "/dev/shm")
WEIGHT_EXT = (".pt", ".pth", ".ckpt", ".safetensors", ".bin", ".onnx", ".gguf")
CACHE_NAMES = {"huggingface", "pip", "uv", "torch", "wandb", "conda", "pkgs", "npm", "bazel",
               "pypoetry", "_cacache", "triton", "torch_extensions", "vllm", "modelscope", "Trash"}
CACHE_PARENTS = {".cache", "anaconda3", "miniconda3", "miniforge3", ".npm", "share"}
OUTPUT_NAMES = {"checkpoints", "checkpoint", "ckpt", "ckpts", "outputs", "output", "runs",
                "logs", "wandb", "lightning_logs", "mlruns", "saved_models", "exports"}
# Unreadable folders that usually hold bulk data (container images, VM disks, snaps).
HEAVY_UNREADABLE = {"docker", "containerd", "containers", "libvirt", "lxd", "snapd", "flatpak"}
DISK_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "ntfs",
           "ntfs3", "fuseblk", "exfat", "vfat"}
NET_FS = {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs", "glusterfs", "ceph", "fuse.rclone", "9p",
          "lustre", "beegfs", "gpfs", "fuse.s3fs", "fuse.juicefs"}
TREE_MIN = 64 << 20  # folders at least this large are kept in tree.tsv.gz
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# snapshots stay with the skill, never in the shared account's home
SNAP_BASE = os.environ.get("DISK_USAGE_DIR") or os.path.join(SKILL_DIR, "results", "snapshots")
RANK = {"direct": 0, "estimated": 1, "unknown": 2}


def human(n):
    sign = "-" if n < 0 else ""
    n = float(abs(n))
    for u in "BKMGTP":
        if n < 1024 or u == "P":
            return f"{sign}{n:.0f}{u}" if u in "BK" else f"{sign}{n:.1f}{u}"
        n /= 1024


def parse_size(s):
    units = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
    s = s.strip().upper().rstrip("B")
    return int(float(s[:-1]) * units[s[-1]]) if s[-1] in units else int(s)


def si_bytes(s):
    """docker prints decimal units: '40.71GB', '1.05GB (virtual 41.8GB)', '0B'."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGTP]?B)", s or "")
    units = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15}
    return int(float(m.group(1)) * units[m.group(2).upper()]) if m else 0


def account():
    """(uid, gid, home) of the account, also under sudo."""
    if os.geteuid() == 0 and os.environ.get("SUDO_UID"):
        p = pwd.getpwuid(int(os.environ["SUDO_UID"]))
    else:
        p = pwd.getpwuid(os.getuid())
    return p.pw_uid, p.pw_gid, p.pw_dir


def other_accounts(acct_uid, acct_home):
    """{home: "@name"} for other login accounts whose home that uid owns."""
    out = {}
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and p.pw_uid != acct_uid and p.pw_dir not in ("/", acct_home):
            try:
                if os.lstat(p.pw_dir).st_uid == p.pw_uid:
                    out[os.path.realpath(p.pw_dir)] = "@" + p.pw_name
            except OSError:
                pass
    return out


def read_mounts():
    def unescape(s):  # mountinfo encodes space, tab, newline, backslash as \ooo
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)
    mounts = []
    with open("/proc/self/mountinfo") as f:
        for line in f:
            pre, post = line.rstrip("\n").split(" - ", 1)
            p, q = pre.split(), post.split()
            mounts.append({"target": unescape(p[4]), "options": p[5],
                           "fstype": q[0], "source": unescape(q[1])})
    return mounts


def mount_of(path, mounts):
    best = None
    for m in mounts:
        t = m["target"]
        if path == t or path.startswith(t.rstrip("/") + "/"):
            if best is None or len(t) >= len(best["target"]):
                best = m
    return best


def devices(mounts):
    """One row per disk or network filesystem, at its shortest mount point."""
    by_src = {}
    for m in mounts:
        t = m["fstype"]
        net = t in NET_FS
        if t not in DISK_FS and not net:
            continue
        d = by_src.get(m["source"])
        if d is None:
            by_src[m["source"]] = d = {"source": m["source"], "fstype": t, "mount": m["target"],
                                       "network": net, "mounts": 0}
        elif len(m["target"]) < len(d["mount"]):
            d["mount"] = m["target"]
        d["mounts"] += 1
    for d in by_src.values():
        if d["network"]:
            continue                 # statvfs on a dead server blocks; report it unmeasured
        try:
            sv = os.statvfs(d["mount"])
        except OSError:
            continue
        d.update(size=sv.f_blocks * sv.f_frsize, used=(sv.f_blocks - sv.f_bfree) * sv.f_frsize,
                 avail=sv.f_bavail * sv.f_frsize)
    return sorted(by_src.values(), key=lambda d: d["mount"])


def ws_allowed(path):
    """May a folder at `path` start a workspace? No hidden or tmp ancestor."""
    if any(path == t or path.startswith(t + "/") for t in TMP_DIRS):
        return False
    return not any(c.startswith(".") for c in path.split("/")[:-1])


def owner_from_path(path, acct_homes):
    parts = path.split("/")
    for k, comp in enumerate(parts):
        prefix = "/".join(parts[:k + 1])
        if prefix in acct_homes:
            return acct_homes[prefix]
        m = WS_RE.match(comp)
        if m and ws_allowed(prefix):
            return m.group(1)
    return None


# --------------------------------------------------------------------------- scan

def walk(root, skip, cutoff, cutoff_s, use_atime, acct_uid, now, explicit_root, acct_homes):
    """Single pass over one filesystem. Returns per-folder own counters."""
    rst = os.lstat(root)
    root_dev = rst.st_dev
    future = now + 86400
    tz = time.localtime(now).tm_gmtoff
    owners, owner_id = [None], {}     # owner id 0 = outside every workspace

    def oid(name):
        if name not in owner_id:
            owner_id[name] = len(owners)
            owners.append(name)
        return owner_id[name]

    o0 = owner_from_path(root, acct_homes)
    parent, name, depth = [-1], [root], [0]
    owner, can_ws, foreign = [oid(o0) if o0 else 0], [explicit_root or ws_allowed(root + "/x")], [rst.st_uid != acct_uid]
    own_b, own_m, own_s, own_c, own_n, own_w, own_f = [rst.st_blocks * 512], [0], [0], [0], [1], [0], [0]
    newest = [0.0]
    athist = {}    # owner id -> {local atime day: bytes} of unmodified files only; most of
                   # them read on one day means a bulk read (copy, rsync, backup) reset atime
    links = {}     # ino -> [blocks, nlink, seen, lca, unmodified, cold, mask, mtime, weight, unmodified_short]
    registries, wslinks = [], []      # conda env registries; symlinks inside workspaces
    unreadable, skipped, vanished, errors, entries = [], [], 0, 0, 1
    stack = [(0, root)]

    def lca(a, b):
        while depth[a] > depth[b]:
            a = parent[a]
        while depth[b] > depth[a]:
            b = parent[b]
        while a != b:
            a, b = parent[a], parent[b]
        return a

    while stack:
        di, path = stack.pop()
        try:
            it = os.scandir(path)
        except PermissionError:
            unreadable.append(di)
            continue
        except FileNotFoundError:
            vanished += 1
            continue
        except OSError:
            errors += 1
            continue
        ob = om = osh = oc = nn = ow = 0
        nw = newest[di]
        dow, dd, dws = owner[di], depth[di] + 1, can_ws[di]
        ah = athist.setdefault(dow, {})
        in_dotconda = name[di] == ".conda"
        with it:
            for e in it:
                entries += 1
                try:
                    if e.is_dir(follow_symlinks=False):
                        p = e.path
                        if p in skip:      # never stat a mount point: a dead NFS/sshfs hangs here
                            skipped.append(p)
                            continue
                        st = e.stat(follow_symlinks=False)
                        if st.st_dev != root_dev:
                            skipped.append(p)
                            continue
                        n = e.name
                        o = dow
                        if dow == 0:
                            if p in acct_homes:
                                o = oid(acct_homes[p])
                            elif dws:
                                m = WS_RE.match(n)
                                if m:
                                    o = oid(m.group(1))
                        stack.append((len(parent), p))
                        parent.append(di)
                        name.append(n)
                        depth.append(dd)
                        owner.append(o)
                        can_ws.append(dws and not n.startswith(".") and p not in TMP_DIRS)
                        foreign.append(st.st_uid != acct_uid)
                        own_b.append(st.st_blocks * 512)
                        own_m.append(0)
                        own_s.append(0)
                        own_c.append(0)
                        own_n.append(1)
                        own_w.append(0)
                        own_f.append(0)
                        newest.append(0.0)
                        continue
                    st = e.stat(follow_symlinks=False)
                    if st.st_dev != root_dev:
                        continue
                    b = st.st_blocks * 512
                    mt, at = st.st_mtime, st.st_atime
                    last = max(mt, at) if use_atime else mt
                    if st.st_nlink > 1:
                        rec = links.get(st.st_ino)
                        if rec is None:
                            links[st.st_ino] = [b, st.st_nlink, 1, di, mt < cutoff, last < cutoff,
                                                1 << dow, mt, e.name.endswith(WEIGHT_EXT), mt < cutoff_s]
                            if mt < cutoff:
                                k = int((at + tz) // 86400)
                                ah[k] = ah.get(k, 0) + b
                        else:
                            rec[2] += 1
                            rec[3] = lca(rec[3], di)
                            rec[6] |= 1 << dow
                        continue
                    nn += 1
                    ob += b
                    if mt < cutoff:
                        om += b
                        k = int((at + tz) // 86400)
                        ah[k] = ah.get(k, 0) + b
                    if mt < cutoff_s:
                        osh += b
                    if last < cutoff:
                        oc += b
                    if nw < mt < future:
                        nw = mt
                    n = e.name
                    if b >= 1048576 and n.endswith(WEIGHT_EXT):
                        ow += b
                    elif in_dotconda and n == "environments.txt":
                        registries.append((di, e.path))
                    elif dow and stat.S_ISLNK(st.st_mode) and len(wslinks) < 500000:
                        try:
                            wslinks.append((dow, os.path.normpath(os.path.join(path, os.readlink(e.path)))))
                        except OSError:
                            pass
                except FileNotFoundError:
                    vanished += 1
                except OSError:
                    errors += 1
        own_b[di] += ob
        own_m[di] += om
        own_s[di] += osh
        own_c[di] += oc
        own_n[di] += nn
        own_w[di] += ow
        if foreign[di]:
            own_f[di] += ob
        newest[di] = nw

    # Hardlinked inodes: charge each once, to the deepest folder holding every link seen.
    shared, outside = {}, {}
    for b, nlink, seen, at, unmod, cold, mask, mt, weight, unmod_s in links.values():
        own_b[at] += b
        own_n[at] += 1
        if unmod:
            own_m[at] += b
        if unmod_s:
            own_s[at] += b
        if cold:
            own_c[at] += b
        if weight:
            own_w[at] += b
        if newest[at] < mt < future:
            newest[at] = mt
        if mask & (mask - 1):
            shared[mask] = shared.get(mask, 0) + b
        if seen < nlink:                   # a link lives outside the scan or in an unreadable dir
            outside[at] = outside.get(at, 0) + b
    return {"parent": parent, "name": name, "depth": depth, "owner": owner, "owners": owners,
            "b": own_b, "m": own_m, "s": own_s, "c": own_c, "n": own_n, "w": own_w, "f": own_f,
            "newest": newest, "athist": athist, "unreadable": unreadable, "skipped": skipped,
            "vanished": vanished, "errors": errors, "entries": entries, "links": len(links),
            "shared": shared, "outside": outside, "registries": registries, "wslinks": wslinks}


def rollup(W):
    parent, owner = W["parent"], W["owner"]
    tot = {k: list(W[k]) for k in ("b", "m", "s", "c", "n", "w", "f")}
    newest = list(W["newest"])
    ua = [W["b"][i] if owner[i] == 0 else 0 for i in range(len(parent))]   # outside workspaces
    children = [[] for _ in parent]
    for i in range(len(parent) - 1, 0, -1):    # a child is always indexed after its parent
        p = parent[i]
        children[p].append(i)
        for k in tot:
            tot[k][p] += tot[k][i]
        if newest[i] > newest[p]:
            newest[p] = newest[i]
        if owner[i] == 0:
            ua[p] += ua[i]
    return tot, newest, ua, children


def chunks(start, size, children, eligible, top, min_size):
    """Largest non-overlapping folders under start: split the biggest until `top` rows."""
    heap, out = [(-size[start], start)], []
    while heap and len(out) + len(heap) < top:
        s, i = heapq.heappop(heap)
        kids = [c for c in children[i] if eligible(c) and size[c] >= min_size]
        if not kids:
            out.append((i, -s, False))
            continue
        rest = -s - sum(size[c] for c in kids)
        for c in kids:
            heapq.heappush(heap, (-size[c], c))
        if rest >= min_size:
            out.append((i, rest, True))
    out += [(i, -s, False) for s, i in heap]
    return sorted(out, key=lambda x: -x[1])[:top]


def read_small(path, limit, counter):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            counter[0] += 1
            return f.read(limit)
    except OSError:
        return ""


def deleted_open_files(dev):
    """Files deleted while a process holds them open: counted by df, invisible to a walk."""
    seen, total, rows, denied, fds = set(), 0, [], 0, []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                fds += [f"/proc/{pid}/fd/{n}" for n in os.listdir(f"/proc/{pid}/fd")]
            except PermissionError:
                denied += 1
            except OSError:
                pass
    for fd in fds:
        try:
            tgt = os.readlink(fd)
            if not tgt.endswith(" (deleted)") or not tgt.startswith("/"):
                continue
            st = os.stat(fd)
        except OSError:
            continue
        if st.st_dev != dev or st.st_nlink != 0 or st.st_ino in seen:
            continue
        seen.add(st.st_ino)
        total += st.st_blocks * 512
        pid = fd.split("/")[2]
        try:
            comm = open(f"/proc/{pid}/comm").read().strip()
        except OSError:
            comm = "?"
        rows.append((st.st_blocks * 512, pid, comm, tgt[:-10]))
    rows.sort(reverse=True)
    return total, rows[:10], denied


# ------------------------------------------------------------------ shared items

def item(kind, name, path, bytes_, **kw):
    d = {"kind": kind, "name": name, "path": path, "bytes": int(bytes_), "ev": {}, "match": [],
         "links": [], "detail": "", "owners": [], "certainty": "unknown", "basis": ""}
    d.update(kw)
    return d


def find_items(W, tot, newest, children, P, day, opened):
    """Conda envs and Hugging Face caches outside every workspace, plus hardlink groups."""
    name, parent, owner, owners = W["name"], W["parent"], W["owner"], W["owners"]
    N = len(parent)
    items, installs = [], []
    known = set(o for o in owners if o)

    def age(i):          # (unmodified long, unmodified short, cold) bytes of the item's folder
        return [tot["m"][i], tot["s"][i], tot["c"][i]]

    def who(nm, why):
        """Owner named by a path inside metadata; flag workspaces that no longer exist here."""
        if nm in known:
            return nm, why
        if "@" + nm in known:
            return "@" + nm, why
        return nm, f"{why} (no {nm}_workspace on this server)"

    reg = {}
    for di, path in W["registries"]:
        o = owners[owner[di]]
        if o:            # a registry under someone's HOME: they created or installed into the env
            for line in read_small(path, 1 << 20, opened).split():
                reg.setdefault(os.path.normpath(line), set()).add(o)
    prefixes = {parent[i] for i in range(N) if name[i] == "conda-meta"}
    bases = {e for e in prefixes if any(name[c] == "envs" for c in children[e])}
    for i in range(N):   # envs/* counts even without conda-meta (half-removed envs)
        if name[i] == "envs" and (parent[i] in bases or name[parent[i]] == ".conda"):
            prefixes.update(children[i])
    for e in prefixes:
        pp = P(e)
        if owner[e] or e in bases:
            installs.append({"path": pp, "owner": owners[owner[e]], "bytes": tot["b"][e],
                             "last_change": day(newest[e]), "base": e in bases})
            continue
        hist = read_small(os.path.join(pp, "conda-meta", "history"), 2 << 20, opened)
        m = re.search(r"==> (\d{4}-\d\d-\d\d)", hist)
        it = item("conda env", name[e], pp, tot["b"][e], detail="created " + m.group(1) if m else "", age=age(e),
                  newest=day(newest[e]))
        for o in reg.get(pp, ()):
            it["ev"].setdefault(o, set()).add("env registry in their HOME")
        for nm in set(WS_PATH_RE.findall(hist)):
            o, why = who(nm, "conda history")
            it["ev"].setdefault(o, set()).add(why)
        files = []
        for pat in ("lib/python*/site-packages/*.dist-info/direct_url.json",
                    "lib/python*/site-packages/*.egg-link", "lib/python*/site-packages/__editable__*.pth"):
            files += glob.glob(os.path.join(pp, pat))
        for f in files[:300]:
            for nm in set(WS_PATH_RE.findall(read_small(f, 1 << 16, opened))):
                o, why = who(nm, "editable install")
                it["ev"].setdefault(o, set()).add(why)
        low = name[e].lower()
        it["match"] = sorted({t for t in TOKEN_RE.findall(low) if len(t) >= 4 and not t.isdigit()}
                             - STOP_TOKENS | ({low} if len(low) >= 4 else set()))
        items.append(it)

    # Hugging Face hub repos (models--org--name) and the datasets library cache (org___name).
    hubs = {}
    for i in range(N):
        if not owner[i] and name[i].startswith(("models--", "datasets--", "spaces--")):
            hubs.setdefault(parent[i], []).append(i)
    for h, repos in hubs.items():
        hp = P(h).rstrip("/") + "/blobs/"
        refs = {}        # newer caches keep blobs at hub level; follow snapshot links to them
        if any(name[c] == "blobs" for c in children[h]):
            for r in repos:
                for dp, _, fns in os.walk(os.path.join(P(r), "snapshots")):
                    for f in fns:
                        try:
                            t = os.path.normpath(os.path.join(dp, os.readlink(os.path.join(dp, f))))
                        except OSError:
                            continue
                        if t.startswith(hp):
                            refs.setdefault(t, set()).add(r)
        extra = {}
        for t, rs in refs.items():
            try:
                b = os.lstat(t).st_blocks * 512
            except OSError:
                continue
            for r in rs:
                extra[r] = extra.get(r, 0) + b / len(rs)
        for r in repos:
            kind, _, rest = name[r].partition("--")
            org, _, rn = rest.partition("--")
            items.append(item("hf " + kind.rstrip("s"), f"{org}/{rn}" if rn else rest, P(r),
                              tot["b"][r] + extra.get(r, 0), newest=day(newest[r]), age=age(r),
                              match=[rn.lower()] if len(rn) >= 4 else [],
                              blobs=[t for t, rs in refs.items() if r in rs],
                              detail=f"{human(extra[r])} in shared blobs" if extra.get(r) else ""))
    for i in range(N):
        if not owner[i] and name[i] == "datasets" and name[parent[i]] == "huggingface":
            for c in children[i]:
                n = name[c]
                if n == "downloads" or n.startswith(("_", ".")) or tot["b"][c] < 1 << 20:
                    continue
                dn = n.partition("___")[2] or n
                items.append(item("hf dataset cache", n, P(c), tot["b"][c], newest=day(newest[c]), age=age(c),
                                  match=[dn.lower()] if len(dn) >= 4 else []))

    for mask, b in W["shared"].items():
        ws = [owners[k] for k in range(1, len(owners)) if mask >> k & 1]
        if ws:
            it = item("hardlinked files", "linked into " + " + ".join(ws), None, b)
            for o in ws:
                it["ev"][o] = {"hardlinks in the workspace"}
            items.append(it)
    return items, sorted(installs, key=lambda x: -x["bytes"])


def docker_items(dev, acct_homes):
    """Docker images, containers and volumes as docker reports them (decimal units)."""
    if not shutil.which("docker"):
        return None

    def run(args, timeout):
        p = subprocess.run(["docker"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    try:
        rc, out, err = run(["info", "--format", "{{.DockerRootDir}}"], 15)
        droot = out.strip()
        if rc or not droot:
            msg = "permission denied (needs the docker group or sudo)" if "permission denied" in err.lower() \
                else (err.strip().splitlines() or ["docker info failed"])[-1][:160]
            return {"error": msg}
        rc, out, err = run(["system", "df", "-v", "--format", "{{json .}}"], 180)
        df = json.loads(out) if rc == 0 else {}
        rc, out, _ = run(["system", "df", "--format", "{{json .}}"], 180)
        totals = {r.get("Type", ""): si_bytes(r.get("Size"))
                  for r in (json.loads(x) for x in out.splitlines() if x.strip())} if rc == 0 else {}
        rc, out, _ = run(["ps", "-aq", "--no-trunc"], 15)
        ids = out.split()
        ins = json.loads(run(["inspect"] + ids, 60)[1]) if ids else []
    except (OSError, ValueError, subprocess.SubprocessError) as ex:
        return {"error": str(ex)[:160]}
    try:
        on_dev = os.stat(droot).st_dev == dev
    except OSError:
        on_dev = False
    cont = {}
    for c in ins:
        ev = {}
        mounts = c.get("Mounts") or []
        for m in mounts:
            if m.get("Type") == "bind":
                o = owner_from_path(os.path.normpath(m.get("Source", "")), acct_homes)
                if o:
                    ev.setdefault(o, set()).add("bind-mounts the workspace")
        cont[c.get("Name", "").lstrip("/")] = {"image": c.get("Image", ""), "ev": ev,
                                               "vols": [m.get("Name") for m in mounts if m.get("Type") == "volume"]}
    items = []
    for c in df.get("Containers") or []:
        nm = c.get("Names", "")
        items.append(item("docker container", nm, None, si_bytes(c.get("Size")),
                          ev=dict(cont.get(nm, {}).get("ev", {})),
                          detail=f"{c.get('Image', '')} · {c.get('Status', '')}"))
    uniq = 0
    for im in df.get("Images") or []:
        users = [n for n, v in cont.items() if v["image"] == im.get("ID")]
        b = si_bytes(im.get("UniqueSize"))
        uniq += b
        items.append(item("docker image", f"{im.get('Repository')}:{im.get('Tag')}", None, b, links=users,
                          detail=f"{len(users)} containers, created {str(im.get('CreatedAt', ''))[:10]}"))
    for v in df.get("Volumes") or []:
        nm = v.get("Name", "")
        users = [n for n, info in cont.items() if nm in info["vols"]]
        items.append(item("docker volume", nm, None, si_bytes(v.get("Size")), links=users,
                          detail=f"{len(users)} containers"))
    layers = max(totals.get("Images", 0) - uniq, 0)
    if layers:
        items.append(item("docker image layers", "shared by several images", None, layers))
    if totals.get("Build Cache"):
        items.append(item("docker build cache", "build cache", None, totals["Build Cache"]))
    return {"root": droot, "on_device": on_dev, "items": items,
            "total": sum(totals.values()) or sum(i["bytes"] for i in items)}


def name_hits(owner_names, text):
    low = text.lower()
    toks = set(TOKEN_RE.findall(low))
    hits = []
    for o in owner_names:
        n = o.lstrip("@").lower()
        if (len(n) >= 4 and n in low) or (len(n) == 3 and n in toks):
            hits.append(o)
    return hits


def process_paths(acct_homes):
    """(owner, path) for files that running processes started in a workspace hold open or
    mapped (models are mmapped), read from /proc; other uids' processes are not visible."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            o = owner_from_path(os.readlink(f"/proc/{pid}/cwd"), acct_homes)
        except OSError:
            continue
        if not o:
            continue
        paths = set()
        try:
            paths.add(os.readlink(f"/proc/{pid}/exe"))
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    paths.add(os.readlink(f"/proc/{pid}/fd/{fd}"))
                except OSError:
                    pass
            with open(f"/proc/{pid}/maps") as f:
                for line in f:
                    i = line.find("/")
                    if i > 0:
                        paths.add(line[i:].rstrip("\n"))
        except OSError:
            pass
        out += [(o, p) for p in paths if p.startswith("/")]
    return out


def attribute(items, W, procs):
    """Fill owners / certainty / basis for each shared item."""
    owners, owner, name = W["owners"], W["owner"], W["name"]
    by_path = {it["path"]: it for it in items if it["path"]}
    blob_of = {}
    for it in items:
        for t in it.pop("blobs", ()):
            blob_of.setdefault(t, []).append(it)
    evidence = [(owners[o], t, "symlink from the workspace") for o, t in W["wslinks"]]
    evidence += [(o, t, "open by a running process started in the workspace") for o, t in procs]
    for o, t, why in evidence:
        for it in blob_of.get(t, ()):
            it["ev"].setdefault(o, set()).add(why)
        q = t
        while len(q) > 1:
            it = by_path.get(q)
            if it:
                it["ev"].setdefault(o, set()).add(why)
                break
            q = os.path.dirname(q)
    known = [o for o in owners if o]
    pending = []
    for it in items:
        if it["ev"]:
            it.update(owners=sorted(it["ev"]), certainty="direct",
                      basis="; ".join(f"{o}: {', '.join(sorted(v))}" for o, v in sorted(it["ev"].items())))
            continue
        hits = name_hits(known, it["name"])
        if len(hits) == 1:
            it.update(owners=hits, certainty="estimated", basis="its name contains the owner's name")
        elif it["match"]:
            pending.append(it)
    if pending:   # one regex pass over every workspace folder name
        alts = {}
        for it in pending:
            for m in it["match"]:
                alts.setdefault(m, []).append(it)
        rx = re.compile("|".join(re.escape(m) for m in sorted(alts, key=len, reverse=True)))
        score = {id(it): {} for it in pending}
        for i in range(len(name)):
            o = owner[i]
            if o:
                for mm in set(rx.findall(name[i].lower())):
                    for it in alts[mm]:
                        sc = score[id(it)]
                        sc[owners[o]] = sc.get(owners[o], 0) + 1
        for it in pending:
            sc = sorted(score[id(it)].items(), key=lambda kv: -kv[1])
            if not sc:
                continue
            counts = ", ".join(f"{o} {n}" for o, n in sc[:3])
            if sc[0][1] >= 2 and (len(sc) == 1 or sc[0][1] >= 2 * sc[1][1]):
                it.update(owners=[sc[0][0]], certainty="estimated",
                          basis=f"its name appears in their folder names ({counts})")
            else:
                it["basis"] = f"ambiguous: its name appears in folder names ({counts})"
    cont = {it["name"]: it for it in items if it["kind"] == "docker container"}
    for it in items:   # images and volumes follow the containers that use them
        if it["kind"] in ("docker image", "docker volume") and it["certainty"] != "direct":
            cs = [cont[c] for c in it["links"] if c in cont]
            ows = sorted({o for c in cs for o in c["owners"]})
            if ows:
                cert = "direct" if all(c["certainty"] == "direct" for c in cs) else "estimated"
                it.update(owners=ows, certainty=cert, basis="used by containers of " + ", ".join(ows))
            elif it["kind"] == "docker image" and not it["links"] and it["certainty"] == "unknown":
                it["basis"] = "no container uses it"
    for it in items:
        it.pop("ev", None)
        it.pop("match", None)


TIER_KO = ("일반", "시트 사용", "우선권")
NOTICE_KINDS = {"conda env", "hf model", "hf dataset", "hf space", "hf dataset cache", "docker image", "docker volume"}


def ko_date(d):
    return f"{d.month}월 {d.day}일({'월화수목금토일'[d.weekday()]})"


def contact_plan(summary, by_owner, hints, items, installs, rest, a, home, short_days, long_days):
    """Whom to ask, in the lab's order: people with neither a priority grant nor a sheet slot
    first (their whole share), then sheet users, then priority holders (old data and caches
    only). People under --min-user in total are left out. Items no one could be traced to go
    into a server-state notice. This drafts requests only; nothing is deleted."""
    need, margin, min_user = parse_size(a.need), parse_size(a.margin), parse_size(a.min_user)
    target = need + margin
    norm = lambda o: o.lstrip("@").lower()
    pri = {norm(x) for x in a.roles.get("priority", [])}
    sheet = {norm(x) for x in a.roles.get("sheet", [])}
    deadline = (datetime.datetime.strptime(a.deadline, "%Y-%m-%d").date() if a.deadline
                else datetime.date.today() + datetime.timedelta(days=1))
    sh = lambda p: "~" + p[len(home):] if p.startswith(home + "/") else p

    rows, small, few, gone = [], [], [], []
    for o, v in by_owner.items():
        mine = [it for it in items if o in it["owners"] and it["bytes"] >= 1 << 30]
        est = [it for it in mine if it["certainty"] == "estimated"]
        if not v["workspaces"] and not o.startswith("@"):
            gone += [(o, it) for it in mine]         # no workspace here: nobody to write to
            continue
        total = owner_total(v) + v.get("shared_est", 0)
        if total < min_user:
            small.append((o, total))
            continue
        tier = 2 if norm(o) in pri else 1 if norm(o) in sheet else 0
        caches = sum(h["bytes"] for h in hints if h["owner"] == o and h["kind"] in ("cache", "trash"))
        est_old = sum((it.get("age") or [0])[0] / len(it["owners"]) for it in est)
        ask = total if tier == 0 else min(v["unmodified"] + caches + est_old, total)
        if ask < min_user:                           # a sheet or priority user with little old data
            few.append((o, int(ask), tier))
            continue
        kinds = None if tier == 0 else ("cache", "trash", "cold", "unmodified")
        folders = [(h["path"], h["bytes"], h["unmodified"]) for h in hints
                   if h["owner"] == o and (kinds is None or h["kind"] in kinds)][:4]
        if not folders and v["workspaces"] and tier == 0:
            folders = [(q, b, None) for b, q in v["top"][:3] if "(files at top" not in q]
        rel = lambda q: next((os.path.relpath(q, w) for w in v["workspaces"] if q.startswith(w.rstrip("/") + "/")), sh(q))
        rows.append({"owner": o, "tier": tier, "total": int(total), "ask": int(ask),
                     "unmodified": v["unmodified"], "unmodified_short": v.get("unmodified_short", 0),
                     "no_workspace": not v["workspaces"],
                     "folders": [(rel(q), b, u) for q, b, u in folders],
                     "direct": [(it["kind"], it["name"], it["bytes"]) for it in mine if it["certainty"] == "direct"][:3],
                     "check": [(it["kind"], it["name"], it["bytes"]) for it in est[:4]]})
    rows.sort(key=lambda r: (r["tier"], -r["ask"]))
    acc = 0
    for r in rows:
        r["now"] = acc < target
        if r["now"]:
            acc += r["ask"]

    # No owner found: envs, models, datasets and docker data nobody could be traced to. Plain
    # cache folders (wandb, pip, torch hub, ...) are not cleanup targets and stay out.
    unknown = [{"kind": it["kind"], "name": it["name"], "bytes": it["bytes"], "newest": it.get("newest", ""),
                "path": it["path"] or ""} for it in items
               if not it["owners"] and it["bytes"] >= 1 << 30 and it["kind"] in NOTICE_KINDS]
    for o, it in gone:
        unknown.append({"kind": it["kind"], "name": f"{it['name']} ({o}_workspace에서 설치, 이 서버에 그 workspace 없음)",
                        "bytes": it["bytes"], "newest": it.get("newest", ""), "path": it["path"] or ""})
    unknown.sort(key=lambda x: -x["bytes"])

    d = summary["device"]
    host = account_label()
    used_pct = round(100 * d["used"] / max(d["used"] + d["avail"], 1))
    msgs = {}
    for r in rows:
        name = r["owner"].lstrip("@")
        M = [f"[{host} 디스크 정리 요청]",
             f"{name}님, 안녕하세요. {host} 디스크가 {used_pct}% 찼고 남은 공간이 {human(d['avail'])}뿐이라, "
             f"연구실 전체로 {human(target)} 정도를 확보하려고 합니다.",
             f"지금 {name}님 몫으로 집계된 공간은 {human(r['total'])}입니다"
             + (" (공용 항목 추정 포함)." if r["check"] else ".")]
        if r["tier"] == 0:
            M.append("지금은 우선권이나 시트 사용 기간이 아니시니, 필요 없는 데이터는 정리하고 "
                     "보관할 것은 다른 저장소로 옮겨 주시면 좋겠습니다.")
        else:
            M.append(("우선권이 있으시니" if r["tier"] == 2 else "시트에 이름을 올리고 쓰고 계시니")
                     + f" workspace를 다 비우실 필요는 없고, {long_days}일 넘게 손대지 않은 데이터와 캐시 위주로 부탁드립니다.")
        if r["folders"] or r["direct"]:
            M.append("먼저 보시면 좋을 곳:")
            M += [f"- {q} {human(b)}" + (f" ({long_days}일 넘게 수정 없음 {100 * u // max(b, 1)}%)" if u else "")
                  for q, b, u in r["folders"]]
            M += [f"- {KO_KIND.get(k, k)} {n} {human(b)}" for k, n, b in r["direct"]]
        if r["check"]:
            M.append("아래는 이름으로 보아 {}님 것으로 추정됩니다. 맞는지 알려 주세요:".format(name))
            M += [f"- {KO_KIND.get(k, k)} {n} {human(b)}" for k, n, b in r["check"]]
        M.append(f"{ko_date(deadline)}까지 정리해 주시거나, 어려우시면 답장 부탁드립니다. 감사합니다.")
        msgs[r["owner"]] = "\n".join(M)
    notice = ""
    if unknown:
        N = [f"[{host} 디스크: 주인 확인 요청]",
             f"{host} 디스크 공간을 확보하는 중인데, 아래 항목의 주인을 찾지 못했습니다.",
             f"본인 것이면 {ko_date(deadline)}까지 정리하시거나 이 글에 댓글로 알려 주세요. "
             "그때까지 연락이 없으면 정리(삭제)하겠습니다."]
        for u in unknown[:15]:
            label = u["name"] if u["kind"] == "folder" else f"{KO_KIND.get(u['kind'], u['kind'])} {u['name']}"
            N.append(f"- {label} {human(u['bytes'])}"
                     + (f" (마지막 수정 {u['newest']})" if u["newest"] not in ("", "-") else ""))
        notice = "\n".join(N)
    return {"need": need, "margin": margin, "target": target, "min_user": min_user,
            "deadline": deadline.isoformat(), "roles": a.roles, "rows": rows, "now_sum": acc,
            "small": sorted(small, key=lambda x: -x[1]), "few": few, "unknown": unknown,
            "messages": msgs, "notice": notice}


def account_label():
    """What the lab calls this server: the shared account's name when it is serverNN."""
    name = pwd.getpwuid(account()[0]).pw_name
    return name if re.match(r"server\d+$", name) else socket.gethostname().split(".")[0]


def collect(a, root, target, mounts, devs, explicit_root):
    acct_uid, acct_gid, home = account()
    m = mount_of(root, mounts)
    use_atime = "noatime" not in m["options"].split(",")
    skip = {x["target"] for x in mounts if x["target"].startswith(root.rstrip("/") + "/")}
    acct_homes = other_accounts(acct_uid, home)
    now = time.time()
    sv = os.statvfs(root)
    dev = os.lstat(root).st_dev
    t0, r0 = time.time(), resource.getrusage(resource.RUSAGE_SELF)
    folder = a.mode == "folder"

    short_days, long_days = sorted(int(x) for x in a.days.split(","))[:2]
    W = walk(root, skip, now - long_days * 86400, now - short_days * 86400, use_atime, acct_uid, now,
             explicit_root, acct_homes)
    tot, newest, ua, children = rollup(W)
    owners, N = W["owners"], len(W["parent"])
    min_size = parse_size(a.min_size or ("1G" if folder else "10G"))
    paths = {}

    def P(i):
        if i not in paths:
            p = W["parent"][i]
            paths[i] = W["name"][i] if p < 0 else os.path.join(P(p), W["name"][i])
        return paths[i]

    def day(t):
        return datetime.date.fromtimestamp(t).isoformat() if t else "-"

    def blank():
        return {"bytes": 0, "unmodified": 0, "unmodified_short": 0, "cold": 0, "weights": 0, "other_uid": 0,
                "shared_direct": 0, "shared_est": 0, "workspaces": [], "top": []}

    ws_roots = [i for i in range(N) if W["owner"][i] and
                (W["parent"][i] < 0 or W["owner"][W["parent"][i]] != W["owner"][i])]
    by_owner = {}
    for i in ws_roots:
        d = by_owner.setdefault(owners[W["owner"][i]], blank())
        d["bytes"] += tot["b"][i]
        d["unmodified"] += tot["m"][i]
        d["unmodified_short"] += tot["s"][i]
        d["cold"] += tot["c"][i]
        d["weights"] += tot["w"][i]
        d["other_uid"] += tot["f"][i]
        d["workspaces"].append(P(i))
        kids = [(tot["b"][c], P(c)) for c in children[i]]
        loose = tot["b"][i] - sum(b for b, _ in kids)
        if loose >= 1 << 30:
            kids.append((loose, P(i) + "/(files at top + links shared by subfolders)"))
        d["top"] += kids
    for o, d in by_owner.items():
        d["top"] = sorted(d["top"], reverse=True)[:5]
        if o.startswith("@"):
            d["other_uid"] = 0                    # an account's own files are not "other uid"
        h = W["athist"].get(owners.index(o), {})
        if h:
            k, b = max(h.items(), key=lambda kv: kv[1])
            d["atime_peak"] = {"day": (datetime.date(1970, 1, 1) + datetime.timedelta(days=k)).isoformat(),
                               "bytes": b}

    opened = [0]
    items, installs = ([], []) if folder else find_items(W, tot, newest, children, P, day, opened)
    dock = None if folder else docker_items(dev, acct_homes)
    if dock and "items" in dock:
        items += dock["items"]
    if not folder:
        attribute(items, W, process_paths(acct_homes))
    attributed_tree = attributed_docker = docker_unattr = 0
    for it in items:
        dockerish = it["kind"].startswith("docker")
        if it["owners"] and it["certainty"] in ("direct", "estimated"):
            share = it["bytes"] / len(it["owners"])
            for o in it["owners"]:
                d = by_owner.setdefault(o, blank())
                d["shared_direct" if it["certainty"] == "direct" else "shared_est"] += share
                if it["certainty"] == "direct" and it.get("age"):   # direct items count fully
                    for k, v in zip(("unmodified", "unmodified_short", "cold"), it["age"]):
                        d[k] += v / len(it["owners"])
            if dockerish:
                attributed_docker += it["bytes"]
            else:
                attributed_tree += it["bytes"]
        elif dockerish:
            docker_unattr += it["bytes"]
    for d in by_owner.values():
        for k in ("shared_direct", "shared_est", "unmodified", "unmodified_short", "cold"):
            d[k] = int(d[k])
    docker_total = dock["total"] if dock and dock.get("on_device") else 0
    docker_in_tree = bool(dock and dock.get("root") and not any(
        P(i) == dock["root"] for i in W["unreadable"]) and dock.get("on_device") and os.access(dock["root"], os.R_OK))

    rest = [{"bytes": s, "path": P(i), "rest": r, "newest": day(newest[i])}
            for i, s, r in chunks(0, tot["b"] if folder else ua, children,
                                  (lambda c: True) if folder else (lambda c: W["owner"][c] == 0),
                                  a.top, parse_size(a.chunk_min))]

    # Hints only where people keep files (folders holding a workspace, the account home,
    # tmp), never system trees such as /usr; in folder mode anywhere under the root.
    homes = {P(W["parent"][i]) for i in ws_roots if W["parent"][i] >= 0} | {home} | set(TMP_DIRS)
    homes = (root.rstrip("/") + "/",) if folder else tuple(h.rstrip("/") + "/" for h in homes)
    hints = []
    for i in range(1, N):
        s = tot["b"][i]
        if s < min_size or not P(i).startswith(homes):
            continue
        nm = W["name"][i]
        if nm in CACHE_NAMES and (W["name"][W["parent"][i]] in CACHE_PARENTS or nm == "pkgs"):
            kind = "cache" if nm != "Trash" else "trash"
        elif nm in OUTPUT_NAMES:
            kind = "outputs"
        elif tot["c"][i] >= 0.8 * s:
            kind = "cold"
        elif tot["m"][i] >= 0.8 * s:
            kind = "unmodified"
        else:
            continue
        hints.append((W["depth"][i], P(i), i, kind))
    kept = []
    for _, p, i, kind in sorted(hints):          # outermost first; drop nested repeats
        if not any(p.startswith(k["path"] + "/") for k in kept):
            big = sorted(((tot["b"][c], W["name"][c]) for c in children[i]), reverse=True)[:3]
            kept.append({"owner": owners[W["owner"][i]] or "-", "kind": kind, "bytes": tot["b"][i],
                         "unmodified": tot["m"][i], "cold": tot["c"][i], "newest": day(newest[i]),
                         "path": p, "largest": [(n, b) for b, n in big if b >= 1 << 30]})
    kept.sort(key=lambda h: (-h["cold"], -h["unmodified"], -h["bytes"]))
    unused_images = [it for it in items if it["kind"] == "docker image" and it["basis"] == "no container uses it"]

    unread = []
    for i in W["unreadable"]:
        p = P(i)
        try:
            st = os.lstat(p)
            meta = f"uid {st.st_uid} mode {st.st_mode & 0o777:o} mtime {day(st.st_mtime)}"
        except OSError:
            meta = "?"
        unread.append({"path": p, "owner": owners[W["owner"][i]] or "-", "meta": meta,
                       "storage": os.path.basename(p) in HEAVY_UNREADABLE})
    unread.sort(key=lambda u: (not u["storage"], u["path"].count("/"), u["path"]))

    del_total, del_rows, del_denied = deleted_open_files(dev)
    outside = [{"path": P(i), "bytes": b} for i, b in
               sorted(W["outside"].items(), key=lambda kv: -kv[1])[:5]]
    excluded = []                    # filesystems mounted inside the scanned tree
    for p in sorted(set(W["skipped"])):
        mm = mount_of(p, mounts)
        d = next((x for x in devs if x["source"] == mm["source"]), None) if mm else None
        if d:
            excluded.append({"path": p, "fstype": d["fstype"], "source": d["source"],
                             "used": d.get("used"), "size": d.get("size"), "bind": d["source"] == m["source"]})
    folders = []
    if folder:
        kids = sorted(children[0], key=lambda c: -tot["b"][c])
        folders = [{"path": P(c), "bytes": tot["b"][c], "unmodified": tot["m"][c],
                    "unmodified_short": tot["s"][c], "cold": tot["c"][c],
                    "files": tot["n"][c], "newest": day(newest[c]), "owner": owners[W["owner"][c]] or "-"}
                   for c in kids[:40]]
        loose = tot["b"][0] - sum(tot["b"][c] for c in kids)
        if loose > 0:
            folders.append({"path": root.rstrip("/") + "/(files directly here)", "bytes": loose,
                            "unmodified": 0, "unmodified_short": 0, "cold": 0, "files": 0, "newest": "", "owner": "-"})
    used = (sv.f_blocks - sv.f_bfree) * sv.f_frsize
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    summary = {
        "mode": a.mode, "selected": sorted(a.users.split(",")) if a.users else [],
        "host": socket.gethostname(), "time": datetime.datetime.now().isoformat(timespec="minutes"),
        "target": target, "root": root, "entries": W["entries"],
        "cold_days": long_days, "short_days": short_days, "cold_rule": "atime and mtime" if use_atime else "mtime only (noatime)",
        "device": {"source": m["source"], "fstype": m["fstype"], "mount": m["target"],
                   "size": sv.f_blocks * sv.f_frsize, "used": used,
                   "avail": sv.f_bavail * sv.f_frsize, "reserved": (sv.f_bfree - sv.f_bavail) * sv.f_frsize},
        "devices": devs, "excluded_mounts": excluded,
        "measured": tot["b"][0], "owners": by_owner, "folders": folders,
        "no_workspace_bytes": ua[0],
        "unattributed_shared": max(ua[0] - attributed_tree - (attributed_docker + docker_unattr if docker_in_tree else 0), 0),
        "docker": {k: v for k, v in (dock or {}).items() if k != "items"},
        "docker_in_gap": 0 if docker_in_tree else docker_total,
        "docker_unattributed": docker_unattr if dock and dock.get("on_device") else 0,
        "items": sorted(items, key=lambda it: -it["bytes"]), "installs": installs,
        "no_workspace_top": rest, "links_outside_scan": outside, "hardlinked_inodes": W["links"],
        "plan": None,
        "hints": kept[:a.top * 2], "unused_images": [(it["name"], it["bytes"]) for it in unused_images],
        "unreadable": unread, "skipped_mounts": sorted(set(W["skipped"])),
        "deleted_open": {"bytes": del_total, "top": del_rows, "procs_denied": del_denied},
        "vanished": W["vanished"], "errors": W["errors"],
        "cost": {"wall_s": round(time.time() - t0, 1),
                 "cpu_s": round(r1.ru_utime + r1.ru_stime - r0.ru_utime - r0.ru_stime, 1),
                 "peak_rss_mb": r1.ru_maxrss // 1024, "files_opened": opened[0]},
    }
    if a.need and not folder:
        summary["plan"] = contact_plan(summary, by_owner, kept, items, installs, rest, a, home,
                                       short_days, long_days)
    tree = [(tot["b"][i], tot["m"][i], tot["s"][i], tot["c"][i], day(newest[i]), tot["n"][i],
             owners[W["owner"][i]] or "-", P(i)) for i in range(N) if tot["b"][i] >= TREE_MIN]
    return summary, tree


def write_outputs(summary, tree, a):
    acct_uid, acct_gid, home = account()
    host = socket.gethostname().split(".")[0]
    base = a.out_base or SNAP_BASE
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    stem = os.path.join(base, host, stamp)
    snap, k = stem, 1
    while os.path.exists(snap):        # never overwrite an earlier snapshot
        snap, k = f"{stem}.{k}", k + 1
    os.makedirs(snap)
    with gzip.open(os.path.join(snap, "tree.tsv.gz"), "wt", encoding="utf-8", errors="backslashreplace") as f:
        f.write("bytes\tunmodified\tunmod_short\tcold\tnewest\tfiles\towner\tpath\n")
        for row in tree:
            f.write("\t".join(str(x) for x in row) + "\n")
    out_dir = a.out or os.path.join(SKILL_DIR, "results")
    os.makedirs(out_dir, exist_ok=True)
    label = summary["root"].strip("/").replace("/", "_") or "root"
    name = f"{host}_{os.path.basename(snap)}_{summary['mode']}_{label}"
    summary["outputs"] = {"md": os.path.join(out_dir, name + ".md"),
                          "html": os.path.join(out_dir, name + ".html"), "snapshot": snap}
    with open(os.path.join(snap, "summary.json"), "w", encoding="utf-8", errors="backslashreplace") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    psnap, prev = previous(snap, summary)
    growth = grown(psnap, snap) if psnap else []
    with open(summary["outputs"]["md"], "w", encoding="utf-8", errors="backslashreplace") as f:
        f.write(render_md(summary, prev, growth))
    write_html(summary, prev, growth, snap, summary["outputs"]["html"])
    if os.geteuid() == 0 and os.environ.get("SUDO_UID"):   # keep outputs owned by the account
        for p in [snap, os.path.dirname(snap), base, out_dir, summary["outputs"]["md"],
                  summary["outputs"]["html"]] + [os.path.join(snap, f) for f in os.listdir(snap)]:
            os.chown(p, acct_uid, acct_gid)
    return prev, growth


def roles_file():
    """The lab's priority and sheet lists live with the skill, one file per server."""
    return os.path.join(SKILL_DIR, "roles", socket.gethostname().split(".")[0] + ".json")


def load_roles(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_scan(a):
    path = roles_file()
    a.roles = load_roles(path)
    if a.priority is not None or a.sheet is not None:   # the lab's lists change; keep the latest
        for k, v in (("priority", a.priority), ("sheet", a.sheet)):
            if v is not None:
                a.roles[k] = [x.strip() for x in v.split(",") if x.strip()]
        a.roles["saved"] = datetime.date.today().isoformat()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(a.roles, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    mounts = read_mounts()
    devs = devices(mounts)
    if a.all:
        roots = [(d["mount"], d["mount"]) for d in devs if not d["network"] and d.get("size", 0) >= 1 << 30]
    elif a.mode == "folder":
        r = os.path.realpath(a.root or a.target or os.getcwd())
        roots = [(r, r)]
    else:
        target = os.path.realpath(a.target or account()[2])
        roots = [(os.path.realpath(a.root) if a.root else mount_of(target, mounts)["target"], target)]
    for root, target in roots:
        summary, tree = collect(a, root, target, mounts, devs, bool(a.root) or a.mode == "folder")
        prev, growth = write_outputs(summary, tree, a)
        print(render_text(summary, prev, growth, full=a.full))


# ------------------------------------------------------------------------ report

def previous(snap, s):
    for d in sorted(glob.glob(os.path.join(os.path.dirname(snap), "*")), reverse=True):
        pj = os.path.join(d, "summary.json")
        if d < snap and os.path.exists(pj):
            c = json.load(open(pj, encoding="utf-8"))
            if c.get("root") == s["root"] and c.get("mode", "user") == s.get("mode", "user"):
                return d, c
    return None, None


def load_tree(snap):
    """{path: row dict} from tree.tsv.gz; columns come from the header line."""
    t = {}
    with gzip.open(os.path.join(snap, "tree.tsv.gz"), "rt", encoding="utf-8") as f:
        cols = next(f).rstrip("\n").split("\t")
        for line in f:
            row = dict(zip(cols, line.rstrip("\n").split("\t", len(cols) - 1)))
            t[row["path"]] = row
    return t


def grown(old, new, min_delta=1 << 30, top=10):
    """Split the growth into non-overlapping folders, deepest first.

    A folder is listed with the growth its grown subfolders do not explain, so no byte
    is listed twice. Folders under TREE_MIN in a snapshot count as 0 there."""
    a, b = load_tree(old), load_tree(new)
    d = {p: int(r["bytes"]) - int(a[p]["bytes"]) if p in a else int(r["bytes"]) for p, r in b.items()}
    cand = {p for p, v in d.items() if v >= min_delta}
    kids = {}
    for p in cand:
        kids.setdefault(os.path.dirname(p), []).append(p)
    out = []
    for p in cand:
        rest = d[p] - sum(d[c] for c in kids.get(p, []))
        if rest >= min_delta:
            out.append((rest, p, p in kids))
    return sorted(out, reverse=True)[:top]


def owner_total(v):
    return v["bytes"] + v.get("shared_direct", 0)


def composition(s):
    """Device split into ordered (label, bytes) parts that sum to the device size."""
    d = s["device"]
    if s.get("mode") == "folder":
        parts = [("this folder", s["measured"]), ("rest of the device", max(d["used"] - s["measured"], 0))]
    else:
        parts = [(o, owner_total(v)) for o, v in sorted(s["owners"].items(), key=lambda kv: -owner_total(kv[1]))]
        parts.append(("estimated", sum(v.get("shared_est", 0) for v in s["owners"].values())))
        parts.append(("shared, unattributed", s["unattributed_shared"]))
        if s.get("docker_unattributed"):
            parts.append(("docker, unattributed", s["docker_unattributed"]))
        gap = max(d["used"] - s["measured"] - s.get("docker_in_gap", 0), 0)
        parts.append(("outside scan root" if s["root"] != d["mount"] else "not measured", gap))
    parts.append(("root reserve", d["reserved"]))
    parts.append(("free", d["avail"]))
    return parts


def text_bar(s, width=60):
    parts = composition(s)
    total = sum(b for _, b in parts) or 1
    legend, line, k = [], "", 0
    fixed = {"estimated": "e", "shared, unattributed": "s", "docker, unattributed": "d",
             "outside scan root": "o", "not measured": "?", "root reserve": ":", "free": ".",
             "this folder": "#", "rest of the device": "-"}
    for label, b in parts:
        if label in fixed:
            c = fixed[label]
        else:
            k += 1
            c = str(k) if k < 10 else "+"
        line += c * round(width * b / total)
        if b * 100 / total >= 0.5:
            legend.append(f"{c} {label} {100 * b / total:.0f}%")
    return f"[{line[:width].ljust(width, '.')}]\n " + "  ".join(legend)


def share_bar(frac, width=12):
    n = max(frac, 0) * width
    full = int(n)
    return ("█" * full + ("▌" if n - full >= 0.5 else "")).ljust(width)


def header(s, L):
    d = s["device"]
    used, meas = d["used"], s["measured"]
    L.append(f"# Disk usage by {s.get('mode', 'user')} | {s['host']} {s['time']} | {s['root']} on {d['source']} ({d['fstype']})")
    L.append(text_bar(s))
    gap = max(used - meas - s.get("docker_in_gap", 0), 0)
    L.append(f"device used {human(used)} of {human(d['size'])} | free {human(d['avail'])} + root reserve "
             f"{human(d['reserved'])} | scanned {human(meas)} ({100 * meas / used:.1f}% of used)"
             + (f" | docker (by docker) {human(s['docker_in_gap'])}" if s.get("docker_in_gap") else "")
             + (f" | not measured {human(gap)}" if s.get("mode") != "folder" else ""))
    others = [x for x in s["devices"] if x["source"] != d["source"]]
    if others:
        L.append("Other filesystems, not in this audit: " + "; ".join(
            f"{x['mount']} {x['fstype']} " + (f"{human(x['used'])}/{human(x['size'])}" if "size" in x else "network, not queried")
            for x in others[:6]))
    other = [x for x in s["excluded_mounts"] if not x.get("bind")]
    binds = [x["path"] for x in s["excluded_mounts"] if x.get("bind")]
    if other:
        L.append("Other devices mounted inside the scanned tree, excluded: " + "; ".join(
            f"{x['path']} -> {x['source']} ({x['fstype']}" + (f", {human(x['used'])} used" if x.get("used") else "") + ")"
            for x in other[:6]))
    if binds:
        L.append("Bind mounts of this same device, skipped so nothing is counted twice: " + ", ".join(binds[:4]))


def render_folder(s, prev, growth, full, L):
    age = f"{s['cold_days']}d"
    tot = s["measured"] or 1
    L.append(f"\n## Folders in {s['root']} ({human(s['measured'])}; each inode counted once)")
    sd = f"{s.get('short_days', '-')}d"
    L.append(f"| Folder | Size | Share | Unmodified {sd} | Unmodified {age} | Cold {age} | Newest | Files |")
    L.append("|---|---|---|---|---|---|---|---|")
    for f in s["folders"][:(40 if full else 15)]:
        L.append(f"| {os.path.basename(f['path'])} | {human(f['bytes'])} | `{share_bar(f['bytes'] / tot)}` "
                 f"{100 * f['bytes'] / tot:.0f}% | {human(f.get('unmodified_short', 0))} | {human(f['unmodified'])} | "
                 f"{human(f['cold'])} | {f['newest']} | {f['files']:,} |")
    L.append("\n## Largest folders inside (non-overlapping)")
    for r in s["no_workspace_top"][:(len(s["no_workspace_top"]) if full else 8)]:
        L.append(f"  {human(r['bytes']):>7}  newest {r['newest']}  {r['path']}"
                 + ("  (its own files + smaller subfolders)" if r["rest"] else ""))
    out = sum(r["bytes"] for r in s["links_outside_scan"])
    if out:
        L.append(f"Hardlinked with files outside this folder (deleting here frees nothing for these): {human(out)}"
                 + (" — " + "; ".join(f"{human(r['bytes'])} {r['path']}" for r in s["links_outside_scan"][:3]) if full else ""))


def render_user(s, prev, growth, full, L):
    d = s["device"]
    used = d["used"]
    age = f"{s['cold_days']}d"
    ps = prev["owners"] if prev else {}
    sel = set(s.get("selected") or [])
    L.append(f"\n## By owner (Total = workspace + shared items with direct evidence; Total (+ estimated) also adds "
             f"name-matched shared items; unmodified and cold count Total; Δ vs {prev['time'] if prev else '-'})")
    sd = f"{s.get('short_days', '-')}d"
    L.append(f"| Owner | Total | Share of used | Total (+ estimated) | Unmodified {sd} | Unmodified {age} | Cold {age} | Δ | Top folders |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    sweeps, hidden = [], []
    for o, v in sorted(s["owners"].items(), key=lambda kv: -owner_total(kv[1])):
        t = owner_total(v)
        if (sel and o not in sel) or (not sel and not full and t + v.get("shared_est", 0) < 1 << 30):
            hidden.append(o)
            continue
        delta = human(t - owner_total(ps[o])) if o in ps else ("new" if prev else "")
        tops = ", ".join(f"{os.path.relpath(p, v['workspaces'][0]) if len(v['workspaces']) == 1 else p} {human(b)}"
                         for b, p in v["top"][:3 if full else 2])
        L.append(f"| {o} | {human(t)} | `{share_bar(t / used)}` {100 * t / used:.0f}% | "
                 f"{human(t + v.get('shared_est', 0))} | {human(v.get('unmodified_short', 0))} | {human(v['unmodified'])} | "
                 f"{human(v['cold'])} | {delta} | {tops} |")
        pk = v.get("atime_peak")
        if pk and pk["bytes"] >= max(0.5 * v["unmodified"], 10 << 30):
            sweeps.append(f"{o} {human(pk['bytes'])} of {human(v['unmodified'])} unmodified read on {pk['day']}")
    if hidden:
        L.append(f"| {'other owners' if sel else 'under 1G'} | | | | | | | | {', '.join(sorted(hidden))} |")
    us = s["unattributed_shared"]
    L.append(f"| (shared, unattributed) | {human(us)} | `{share_bar(us / used)}` {100 * us / used:.0f}% | | | | | | below |")
    if sweeps:
        L.append("atime spike (copy/rsync/backup reset atime; trust Unmodified there): " + "; ".join(sweeps))
    ro = [(o, v["other_uid"]) for o, v in s["owners"].items() if v["other_uid"] >= 1 << 30 and (not sel or o in sel)]
    if ro:
        L.append("In folders of another uid (usually root, from containers), undeletable without sudo: "
                 + ", ".join(f"{o} {human(b)}" for o, b in sorted(ro, key=lambda x: -x[1])))

    pl = s.get("plan")
    if pl:
        ro = pl["roles"]
        L.append(f"\n## Whom to ask: need {human(pl['need'])} + margin {human(pl['margin'])} = {human(pl['target'])} "
                 f"(free now {human(d['avail'])}); roles {ro.get('saved', 'not set')}: priority "
                 f"{', '.join(ro.get('priority', [])) or '-'}; sheet {', '.join(ro.get('sheet', [])) or '-'}")
        tiers = ("general, whole share", "sheet, old data + caches", "priority, old data + caches")
        for label, now in (("Ask now", True), ("If still short", False)):
            rs = [r for r in pl["rows"] if r["now"] == now]
            if rs:
                L.append(f"{label}: " + "; ".join(f"{r['owner']} [{tiers[r['tier']]}] {human(r['ask'])}"
                                                + (" (no workspace here)" if r["no_workspace"] else "") for r in rs)
                         + (f" = {human(pl['now_sum'])}" + ("" if pl["now_sum"] >= pl["target"] else " (below target)") if now else ""))
        if pl["small"]:
            L.append(f"Left out, under {human(pl['min_user'])} in total: " + ", ".join(o for o, _ in pl["small"]))
        if pl.get("few"):
            L.append(f"Left out, sheet/priority with under {human(pl['min_user'])} of old data or caches: "
                     + ", ".join(f"{o} {human(b)}" for o, b, _ in pl["few"]))
        if pl["unknown"]:
            L.append(f"No owner found ({len(pl['unknown'])} items, {human(sum(u['bytes'] for u in pl['unknown']))}; "
                     "server-state notice drafted): " + ", ".join(f"{u['name']} {human(u['bytes'])}" for u in pl["unknown"][:3]))
        L.append(f"Messages (deadline {pl['deadline']}): in the report, or `diskusage.py messages` prints them.")
    items = [it for it in s["items"] if not sel or set(it["owners"]) & sel or (full and not it["owners"])]
    if items:
        L.append("\n## Shared items (conda envs, Hugging Face caches, docker, hardlinks) and who they go to")
        for it in items[:(len(items) if full else 12)]:
            who = " + ".join(it["owners"]) or "?"
            L.append(f"  {human(it['bytes']):>7}  {it['kind']:<17} {it['name'][:44]:<44} {who} [{it['certainty']}]"
                     + (f" — {it['basis']}" if it["basis"] else "") + (f" ({it['detail']})" if full and it["detail"] else ""))
        if not full and len(items) > 12:
            L.append(f"  ... {len(items) - 12} more in the full report")
    dk = s.get("docker") or {}
    if dk.get("error"):
        L.append(f"docker: not queried ({dk['error']}); its storage is part of 'not measured'.")
    if not sel:
        L.append("\n## Largest folders outside any workspace (owner not guessed)")
        for r in s["no_workspace_top"][:(len(s["no_workspace_top"]) if full else 6)]:
            L.append(f"  {human(r['bytes']):>7}  newest {r['newest']}  {r['path']}"
                     + ("  (its own files + smaller subfolders)" if r["rest"] else ""))
    if full and s.get("installs"):
        L.append("\n## Conda installs, and envs inside workspaces")
        for e in s["installs"][:10]:
            L.append(f"  {human(e['bytes']):>7}  last change {e['last_change']}  [{e['owner'] or '-'}] {e['path']}"
                     + ("  (base: includes pkgs and every env)" if e["base"] else ""))


def render_text(s, prev, growth, full=False):
    L = []
    header(s, L)
    folder = s.get("mode") == "folder"
    (render_folder if folder else render_user)(s, prev, growth, full, L)
    age = f"{s['cold_days']}d"
    sel = set(s.get("selected") or [])
    hints = [h for h in s["hints"] if not sel or h["owner"] in sel]
    L.append(f"\n## Cleanup candidates (owner decides; unmodified = no write in {age}, cold = no read or write)")
    for h in hints[:(len(hints) if full else 6)]:
        pct = lambda k: f"{100 * h[k] / max(h['bytes'], 1):.0f}%"
        L.append(f"  [{h['owner']}] {h['kind']:<10} {human(h['bytes']):>7}  unmod {pct('unmodified'):>4}  "
                 f"cold {pct('cold'):>4}  {h['path']}"
                 + ("  <- " + ", ".join(f"{n} {human(b)}" for n, b in h["largest"]) if full and h["largest"] else ""))
    if s.get("unused_images"):
        L.append("  docker images no container uses: " + ", ".join(f"{n} {human(b)}" for n, b in s["unused_images"][:4]))

    L.append("\n## Not measured")
    heavy = [u["path"] for u in s["unreadable"] if u.get("storage")]
    if heavy:
        L.append(f"  container/snap storage, needs root: {', '.join(heavy)}"
                 + (" (docker's own numbers are used above)" if s.get("docker_in_gap") else ""))
    groups = {}
    for u in s["unreadable"]:
        if not u.get("storage"):
            groups.setdefault(u["owner"], []).append(u)
    if not full:
        L.append("  unreadable dirs (size unknown): " + (", ".join(
            f"{o} {len(r)}" for o, r in sorted(groups.items(), key=lambda kv: kv[0] == "-")) or "none"))
    else:
        for o, rows in sorted(groups.items(), key=lambda kv: kv[0] == "-"):
            tmp = [u for u in rows if u["path"].startswith(tuple(t + "/" for t in TMP_DIRS))]
            rows = [u for u in rows if u not in tmp]
            L.append(f"  unreadable [{o}] {len(rows) + len(tmp)} dirs, size unknown"
                     + (f" ({len(tmp)} under tmp dirs not listed)" if tmp else "") + ":")
            for u in rows[:6]:
                L.append(f"      {u['path']}  ({u['meta']})")
            if len(rows) > 6:
                L.append(f"      ... {len(rows) - 6} more in summary.json")
    do = s["deleted_open"]
    if do["bytes"]:
        L.append(f"  deleted-but-open {human(do['bytes'])}: " + "; ".join(
            f"pid {pid} {comm} {human(b)} {p}" for b, pid, comm, p in do["top"][:3]))
    if growth:
        L.append(f"\n## Grew most since {prev['time']} (non-overlapping)")
        for dlt, p, inner in growth[:(10 if full else 5)]:
            L.append(f"  {human(dlt):>7}  {p}" + ("  (outside the subfolders listed)" if inner else ""))
    if full:
        L.append("\nOwners: <name>_workspace folders; @account = another Unix account's home. Each inode is charged "
                 "once, to the deepest folder holding all its links. Shared items: direct = a workspace symlinks, "
                 "bind-mounts or hardlinks it, or env metadata names the workspace; estimated = names only.")
    c, o = s["cost"], s.get("outputs", {})
    L.append(f"\nReport: {o.get('md', '-')}\nVisual: {o.get('html', '-')}")
    text = "\n".join(L)
    cost = (f"Cost: scan {c['wall_s']} s wall, {c['cpu_s']} s CPU, {c['peak_rss_mb']} MB peak RSS, "
            f"{s['entries']:,} entries stat()ed, {c['files_opened']} metadata files opened; ")
    n = len(text) + len(cost) + 40
    return text + "\n" + cost + f"this text {n:,} chars (~{n // 4:,} tokens)"


# ------------------------------------------------- Korean report (.md and .html)

KO_KIND = {"conda env": "conda env", "hf model": "HF 모델", "hf dataset": "HF 데이터셋",
           "hf space": "HF Space", "hf dataset cache": "HF datasets 캐시",
           "docker container": "docker 컨테이너", "docker image": "docker 이미지",
           "docker volume": "docker 볼륨", "docker image layers": "docker 공유 레이어",
           "docker build cache": "docker 빌드 캐시", "hardlinked files": "hardlink 파일"}
KO_CERT = {"direct": "확실", "estimated": "추정", "unknown": "미상"}
KO_HINT = {"cache": "캐시", "outputs": "실험 산출물", "cold": "오래 안 씀",
           "unmodified": "오래 수정 안 함", "trash": "휴지통"}
KO_PART = {"estimated": "추정", "shared, unattributed": "공용 (주인 미확인)",
           "docker, unattributed": "docker (주인 미확인)", "outside scan root": "스캔 범위 밖",
           "not measured": "측정 못 함", "root reserve": "root 예약 공간", "free": "남은 공간",
           "this folder": "이 폴더", "rest of the device": "디스크의 나머지"}
KO_BASIS = [
    (r"\(no (\S+?)_workspace on this server\)", r"(이 서버에 \1_workspace 없음)"),
    (r"ambiguous: its name appears in folder names \((.*)\)", r"판단 보류: 여러 사람의 폴더 이름에 나옴 (\1)"),
    (r"its name appears in their folder names \((.*)\)", r"폴더 이름에 이 이름이 나옴 (\1)"),
    (r"its name contains the owner's name", "이름에 사용자 이름이 들어 있음"),
    (r"used by containers of ", "사용하는 컨테이너의 주인: "),
    (r"no container uses it", "사용하는 컨테이너 없음"),
    (r"open by a running process started in the workspace", "workspace에서 실행 중인 프로세스가 사용 중"),
    (r"symlink from the workspace", "workspace의 symlink가 가리킴"),
    (r"hardlinks in the workspace", "workspace에 같은 파일이 hardlink로 있음"),
    (r"bind-mounts the workspace", "컨테이너가 workspace를 mount함"),
    (r"env registry in their HOME", "그 사람 HOME의 env 등록 기록"),
    (r"editable install", "editable install 경로"),
    (r"a venv in the workspace is built on it", "workspace의 venv가 이 env 위에 만들어짐"),
]


def ko_basis(text):
    for pat, rep in KO_BASIS:
        text = re.sub(pat, rep, text)
    return text


def ko_item(it):
    name = it["name"]
    if it["kind"] == "hardlinked files":
        name = " + ".join(it["owners"]) + " workspace와 공용 캐시"
    return dict(it, kind_ko=KO_KIND.get(it["kind"], it["kind"]), cert_ko=KO_CERT[it["certainty"]],
                basis_ko=ko_basis(it["basis"]), name_ko=name)


def md_bar(frac, width=16):
    """Bar of full and eighth blocks; plain text so it renders in any Markdown preview."""
    eighths = int(round(max(0.0, min(frac, 1.0)) * width * 8))
    return "█" * (eighths // 8) + ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")[eighths % 8]


def render_md(s, prev, growth):
    """The report people read in VS Code or GitHub: Korean, short columns, real Markdown."""
    d, home = s["device"], account()[2]
    used, folder = d["used"], s.get("mode") == "folder"
    sel = set(s.get("selected") or [])
    age, sdays = s["cold_days"], s.get("short_days", "-")
    sh = lambda p: ("~" + p[len(home):] if p.startswith(home + "/") else "~" if p == home else p).replace(
        "/(files at top", " (files at top").replace("(files at top + links shared by subfolders)", "(최상위 파일과 하위 폴더 간 hardlink)")
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "-"
    cut = lambda t, n=40: t if len(t) <= n else t[:n - 1] + "…"
    mid = lambda t, n=44: t if len(t) <= n else t[:n // 3] + "…" + t[-(n - n // 3 - 1):]
    L = []
    add = L.append
    t = s["time"].replace("T", " ")
    if folder:
        add(f"# 폴더 사용 현황: `{sh(s['root'])}`\n")
    else:
        add(f"# 디스크 사용 현황: {s['host']}\n")
    add(f"{t} 기준. 디스크 `{d['mount']}` ({d['source']}, {d['fstype']}). 경로의 `~`는 `{home}`입니다.\n")

    # The one thing to read first.
    if folder:
        fs = s["folders"]
        top = ", ".join(f"`{os.path.basename(f['path'])}` {human(f['bytes'])}" for f in fs[:3])
        unmod = sum(f["unmodified"] for f in fs)
        unmod_s = sum(f.get("unmodified_short", 0) for f in fs)
        add(f"> **이 폴더 {human(s['measured'])}** (디스크 사용량의 {pct(s['measured'], used)})  ")
        add(f"> 가장 큰 하위 폴더: {top}  ")
        add(f"> 수정하지 않은 지 {sdays}일 넘은 데이터 {human(unmod_s)} ({pct(unmod_s, s['measured'])}), "
            f"{age}일 넘은 데이터 {human(unmod)} ({pct(unmod, s['measured'])})\n")
    else:
        owners = sorted(s["owners"].items(), key=lambda kv: -owner_total(kv[1]))
        top = ", ".join(f"{o} {human(owner_total(v))} ({pct(owner_total(v), used)})" for o, v in owners[:3])
        gap = max(used - s["measured"] - s.get("docker_in_gap", 0), 0)
        add(f"> **디스크 {pct(used, used + d['avail'])} 사용 중 (df 기준), 남은 공간 {human(d['avail'])}**  ")
        add(f"> 가장 많이 쓰는 사람: {top}  ")
        add(f"> 주인을 확인하지 못한 공용 공간 {human(s['unattributed_shared'])}"
            + (f", 측정하지 못한 공간 {human(gap)}" if gap >= 1 << 30 else "") + "\n")

    pl = s.get("plan")
    if pl:
        ro = pl["roles"]
        add("## 정리 요청 대상\n")
        add(f"남은 공간 {human(d['avail'])}. 확보 기준: 목표 {human(pl['need'])} + 여유 {human(pl['margin'])} = "
            f"**{human(pl['target'])}**. 우선권도 시트도 없는 사람(일반)에게 먼저 부탁하고, 시트 사용자와 "
            "우선권 보유자는 오래된 데이터와 캐시만 부탁하는 후순위입니다. "
            "이 보고서는 누구에게 무엇을 부탁할지 정리할 뿐이고, 정리는 각자 합니다.\n")
        add(f"- 우선권: {', '.join(ro.get('priority', [])) or '없음'} / 시트 사용: {', '.join(ro.get('sheet', [])) or '없음'}"
            + (f" (명단 기록 {ro['saved']})" if ro.get("saved") else " (명단 없음: 모두 일반으로 계산)"))
        if pl["small"]:
            add(f"- 전체 사용량 {human(pl['min_user'])} 미만이라 제외: "
                + ", ".join(f"{o} {human(b)}" for o, b in pl["small"]))
        if pl.get("few"):
            add(f"- {TIER_KO[1]}·{TIER_KO[2]} 중 오래된 데이터와 캐시가 {human(pl['min_user'])} 미만이라 제외: "
                + ", ".join(f"{o} {human(b)}" for o, b, _ in pl["few"]))
        add("")
        if pl["rows"]:
            add(f"| 순서 | 사용자 | 구분 | 전체 | 요청 기준 | 먼저 볼 곳 |\n|---|---|---|---:|---:|---|")
            for r in pl["rows"]:
                where = ", ".join(f"`{mid(q)}` {human(b)}" for q, b, _ in r["folders"][:2])
                where = ", ".join(x for x in [where] + [f"{KO_KIND.get(k, k)} `{mid(n)}` {human(b)}"
                                                        for k, n, b in r["direct"][:2]] if x) or "-"
                if r["check"]:
                    where += f"; 추정 {len(r['check'])}건 확인"
                basis = "전체" if r["tier"] == 0 else "오래된 데이터·캐시"
                add(f"| {'이번에' if r['now'] else '모자라면'} | **{r['owner']}**"
                    + (" (이 서버에 workspace 없음)" if r["no_workspace"] else "")
                    + f" | {TIER_KO[r['tier']]} | {human(r['total'])} | {human(r['ask'])} ({basis}) | {where} |")
            add("")
            if pl["now_sum"] < pl["target"]:
                add(f"> 이번 요청 대상의 기준량을 다 합쳐도 {human(pl['now_sum'])}로 목표에 못 미칩니다.\n")
        if pl["unknown"]:
            add(f"주인을 찾지 못한 항목 {len(pl['unknown'])}개, {human(sum(u['bytes'] for u in pl['unknown']))}. "
                "server-state 공지문을 맨 아래에 만들어 두었습니다.\n")
        add(f"사람별 메시지와 공지문은 맨 아래 '보낼 메시지'에 있습니다. 기한은 {pl['deadline']}로 잡았습니다.\n")

    add("## 한눈에 보기\n")
    add("| 구분 | 용량 | 비율 | |\n|---|---:|---:|---|")
    total = sum(b for _, b in composition(s)) or 1
    for label, b in composition(s):
        if b * 1000 / total < 5:
            continue
        add(f"| {KO_PART.get(label, label)} | {human(b)} | {pct(b, total)} | {md_bar(b / total)} |")
    add("")

    if folder:
        add("## 하위 폴더\n")
        add(f"| 폴더 | 용량 | 비율 | {sdays}일 미수정 | {age}일 미수정 | 최근 수정 | 파일 수 |\n|---|---:|---:|---:|---:|---|---:|")
        for f in s["folders"][:30]:
            nm = os.path.basename(f["path"])
            add(f"| `{cut(nm, 36)}` | {human(f['bytes'])} | {pct(f['bytes'], s['measured'])} | "
                f"{pct(f.get('unmodified_short', 0), f['bytes'])} | {pct(f['unmodified'], f['bytes'])} | "
                f"{f['newest'] or '-'} | {f['files']:,} |")
        add("")
        out = sum(r["bytes"] for r in s["links_outside_scan"])
        if out:
            add(f"이 폴더 밖의 파일과 hardlink로 묶인 {human(out)}은 여기서 지워도 공간이 늘지 않습니다.\n")
    else:
        add("## 사용자별\n")
        has_prev = bool(prev)
        head = f"| 사용자 | 합계 | 합계 (추정 포함) | {sdays}일 미수정 | {age}일 미수정 |" + (" 지난번 대비 |" if has_prev else "")
        add(head + "\n|---|---:|---:|---:|---:|" + ("---:|" if has_prev else ""))
        ps = prev["owners"] if prev else {}
        small = []
        for o, v in owners:
            tv = owner_total(v)
            if (sel and o not in sel) or (not sel and tv + v.get("shared_est", 0) < 1 << 30):
                small.append(o)
                continue
            row = (f"| **{o}** | {human(tv)} | {human(tv + v.get('shared_est', 0))} | "
                   f"{human(v.get('unmodified_short', 0))} | {human(v['unmodified'])} |")
            if has_prev:
                dv = tv - owner_total(ps[o]) if o in ps else None
                row += " " + ("새로 생김" if dv is None else "-" if abs(dv) < 100 << 20
                              else ("+" if dv > 0 else "") + human(dv)) + " |"
            add(row)
        add("")
        add("**합계**는 workspace에, symlink·hardlink·mount·설치 기록처럼 확실한 근거로 연결된 공용 항목을 더한 "
            "값입니다. **합계 (추정 포함)** 은 여기에 이름만 일치해 추정한 공용 항목까지 더한 값입니다. "
            "미수정 열은 합계 기준입니다."
            + (f" 1G 미만: {', '.join(sorted(small))}." if small else "") + " `@이름` 은 별도 리눅스 계정입니다.\n")
        for o, v in owners:
            if o in small:
                continue
            parts = [", ".join(f"`{cut(sh(os.path.relpath(p, v['workspaces'][0]) if len(v['workspaces']) == 1 else p), 34)}` {human(b)}"
                               for b, p in v["top"][:3])] if v["top"] else []
            shared = [f"{lab} {human(v[k])}" for k, lab in (("shared_direct", "확실"), ("shared_est", "추정")) if v.get(k)]
            if shared:
                parts.append("공용 " + ", ".join(shared))
            if parts:
                add(f"- **{o}**: " + " · ".join(parts))
        add("")
        notes = []
        for o, v in owners:
            pk = v.get("atime_peak")
            if (not sel or o in sel) and pk and pk["bytes"] >= max(0.5 * v["unmodified"], 10 << 30):
                notes.append(f"{o}의 오래된 데이터 {human(pk['bytes'])}이 {pk['day']} 하루에 한꺼번에 읽혔습니다. "
                             "복사나 백업이 있었던 것으로 보여 '미사용' 수치는 믿기 어렵고, '미수정' 수치를 기준으로 보세요.")
            if (not sel or o in sel) and v["other_uid"] >= 1 << 30:
                notes.append(f"{o}의 {human(v['other_uid'])}은 root(주로 docker 컨테이너)가 만든 폴더 안에 있어 "
                             "sudo 없이는 지울 수 없습니다.")
        for n in notes:
            add(f"> {n}\n")

        every = [ko_item(it) for it in s["items"] if not sel or set(it["owners"]) & sel]
        items = [it for it in every if it["bytes"] >= 100 << 20]
        tiny = [it for it in every if it["bytes"] < 100 << 20]
        if items:
            add("## 공용 항목의 주인\n")
            add("conda env, Hugging Face 캐시, docker 데이터처럼 workspace 밖에 있는 것들입니다. "
                "**확실**은 symlink, hardlink, mount, 설치 기록처럼 직접 근거가 있는 경우이고, "
                "**추정**은 이름만 일치하는 경우입니다.\n")
            add("| 항목 | 종류 | 용량 | 주인 | 근거 |\n|---|---|---:|---|---|")
            for it in items[:20]:
                who = " + ".join(it["owners"]) or "?"
                add(f"| `{cut(it['name_ko'], 38)}` | {it['kind_ko']} | {human(it['bytes'])} | "
                    f"{who} ({it['cert_ko']}) | {cut(it['basis_ko'], 70) or '-'} |")
            add("")
            rest_items = items[20:] + tiny
            if rest_items:
                add(f"<details><summary>나머지 {len(rest_items)}개 항목 (작은 항목 포함)</summary>\n")
                add("| 항목 | 종류 | 용량 | 주인 |\n|---|---|---:|---|")
                for it in rest_items:
                    add(f"| `{cut(it['name_ko'], 38)}` | {it['kind_ko']} | {human(it['bytes'])} | "
                        f"{' + '.join(it['owners']) or '?'} ({it['cert_ko']}) |")
                add("\n</details>\n")

    hints = [h for h in s["hints"] if not sel or h["owner"] in sel]
    if hints or s.get("unused_images"):
        add("## 정리 후보\n")
        add("지울지는 각자 판단합니다. 이 보고서는 아무것도 지우지 않습니다.\n")
        add(f"| 주인 | 종류 | 용량 | {age}일 미수정 | 경로 |\n|---|---|---:|---:|---|")
        for h in hints[:15]:
            add(f"| {h['owner'] if h['owner'] != '-' else '공용'} | {KO_HINT.get(h['kind'], h['kind'])} | "
                f"{human(h['bytes'])} | {pct(h['unmodified'], h['bytes'])} | `{cut(sh(h['path']), 60)}` |")
        for n, b in s.get("unused_images", [])[:5]:
            add(f"| 공용 | 안 쓰는 docker 이미지 | {human(b)} | - | `{cut(n, 60)}` |")
        add("")

    if not folder and not sel and s["no_workspace_top"]:
        add("## workspace 밖의 큰 폴더\n")
        add("주인을 판단하지 않고 크기만 보여줍니다.\n")
        add("| 용량 | 최근 수정 | 경로 |\n|---:|---|---|")
        for r in s["no_workspace_top"][:12]:
            add(f"| {human(r['bytes'])} | {r['newest']} | `{cut(sh(r['path']), 60)}`"
                + (" (직접 든 파일과 작은 하위 폴더)" if r["rest"] else "") + " |")
        add("")

    if growth:
        add(f"## 지난번({prev['time'].replace('T', ' ')})보다 많이 늘어난 곳\n")
        add("| 증가 | 경로 |\n|---:|---|")
        for dlt, p, inner in growth[:10]:
            add(f"| +{human(dlt)} | `{cut(sh(p), 60)}`" + (" (위 하위 폴더 제외)" if inner else "") + " |")
        add("")

    add("## 측정하지 못한 부분\n")
    heavy = [u["path"] for u in s["unreadable"] if u.get("storage")]
    dk = s.get("docker") or {}
    if heavy:
        add(f"- 컨테이너 저장소({', '.join('`' + p + '`' for p in heavy)})는 root 권한이 있어야 읽을 수 있습니다."
            + (" 대신 docker가 알려준 용량을 썼습니다." if s.get("docker_in_gap") else ""))
    if dk.get("error"):
        add(f"- docker 정보를 가져오지 못했습니다: {dk['error']}")
    groups = {}
    for u in s["unreadable"]:
        if not u.get("storage"):
            groups.setdefault(u["owner"], []).append(u)
    if groups:
        add("- 읽을 수 없는 폴더(크기 모름): " + ", ".join(
            f"{'시스템' if o == '-' else o} {len(r)}개" for o, r in sorted(groups.items(), key=lambda kv: kv[0] == "-")))
    if s["deleted_open"]["bytes"]:
        add(f"- 지웠지만 프로세스가 아직 열고 있는 파일: {human(s['deleted_open']['bytes'])}")
    others = [x for x in s["devices"] if x["source"] != d["source"]]
    if others:
        add("- 다른 디스크는 이번 집계에 넣지 않았습니다: " + ", ".join(
            f"`{x['mount']}` ({x['fstype']}" + (f", {human(x['used'])}/{human(x['size'])}" if "size" in x else ", 네트워크") + ")"
            for x in others[:5]))
    add("")
    ws_groups = {o: r for o, r in groups.items() if o != "-"}
    if ws_groups:
        add("<details><summary>읽을 수 없는 workspace 폴더 목록</summary>\n")
        for o, rows in ws_groups.items():
            for u in rows[:10]:
                add(f"- {o}: `{sh(u['path'])}` ({u['meta']})")
        add("\n</details>\n")

    def quote(text):   # a blockquote wraps in any preview and copies as plain text
        return "\n".join("> " + line.replace("- ", "· ", 1) if line.startswith("- ") else "> " + line
                         for line in text.split("\n")).replace("\n", "  \n") + "\n"

    if pl and (pl["messages"] or pl["notice"]):
        add("## 보낼 메시지\n")
        add("미리보기 화면에서 그대로 복사해 보내면 됩니다. 필요하면 고쳐서 쓰세요.\n")
        for r in pl["rows"]:
            add(f"### {r['owner']} ({'이번에' if r['now'] else '모자라면'}, {TIER_KO[r['tier']]})\n")
            add(quote(pl["messages"][r["owner"]]))
        if pl["notice"]:
            add("### server-state 공지 (주인 확인)\n")
            add(quote(pl["notice"]))

    c, o = s["cost"], s.get("outputs", {})
    add("---\n")
    add(f"스캔 {c['wall_s']}초, CPU {c['cpu_s']}초, 메모리 {c['peak_rss_mb']}MB, "
        f"항목 {s['entries']:,}개. 파일 내용은 conda 메타데이터 {c['files_opened']}개 말고는 읽지 않았습니다.  ")
    if o.get("html"):
        add(f"그림으로 보기: `{o['html']}`")
    add("")
    add("<details><summary>숫자를 어떻게 셌나</summary>\n")
    add("- 크기는 실제로 디스크를 차지하는 블록 기준이고, symlink는 따라가지 않습니다.")
    add("- 같은 파일이 hardlink로 여러 곳에 있으면 한 번만 셉니다. 그 링크들을 모두 담은 가장 깊은 폴더에 넣습니다.")
    add("- 사용자는 가장 바깥쪽 `<이름>_workspace` 폴더로 정합니다.")
    add(f"- 미수정은 그 기간({sdays}일, {age}일) 동안 쓰기가 없었다는 뜻입니다. "
        f"미사용은 {age}일 동안 읽기와 쓰기가 모두 없었다는 뜻입니다.")
    add("- 남은 공간은 일반 사용자가 쓸 수 있는 양이고, root 예약 공간은 따로 표시했습니다.")
    add("\n</details>\n")
    return "\n".join(L)


def write_html(s, prev, growth, snap, path):
    tree = load_tree(snap)
    data = {"s": s, "prev": prev["time"] if prev else None, "growth": growth, "parts": composition(s),
            "tree": [[r["path"], int(r["bytes"]), int(r["unmodified"]), int(r["cold"]), r["newest"], r["owner"]]
                     for r in tree.values()]}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8", errors="backslashreplace") as f:
        f.write(HTML.replace("__DATA__", blob))


def latest_snapshots():
    base = SNAP_BASE
    seen, out = set(), []
    for pj in sorted(glob.glob(os.path.join(base, socket.gethostname().split(".")[0], "*", "summary.json")),
                     reverse=True):
        s = json.load(open(pj, encoding="utf-8"))
        key = (s.get("root"), s.get("mode", "user"))
        if key not in seen:
            seen.add(key)
            out.append(os.path.dirname(pj))
    if not out:
        sys.exit(f"no snapshot under {base}; run `scan` first")
    return out


def cmd_free(a):
    """One line per disk, df-style and instant, for asking how much space is needed."""
    path = os.path.realpath(a.path or account()[2])
    mounts = read_mounts()
    here = mount_of(path, mounts)
    for d in devices(mounts):
        if "size" not in d:
            print(f"  {d['mount']} {d['fstype']} (network, not queried)")
            continue
        mark = "*" if d["source"] == here["source"] else " "
        pct = 100 * d["used"] / max(d["used"] + d["avail"], 1)
        print(f"{mark} {d['mount']} ({d['source']}, {d['fstype']}): size {human(d['size'])}, used {human(d['used'])} "
              f"({pct:.0f}%), free {human(d['avail'])}")
    print(f"* = the disk holding {path}")
    ro = load_roles(roles_file())
    print(f"roles in {roles_file()} ({'saved ' + ro['saved'] if ro.get('saved') else 'none saved'}): priority "
          f"{', '.join(ro.get('priority', [])) or '-'}; sheet {', '.join(ro.get('sheet', [])) or '-'}")


def cmd_messages(a):
    for snap in [a.snapshot] if a.snapshot else latest_snapshots():
        pl = json.load(open(os.path.join(snap, "summary.json"), encoding="utf-8")).get("plan")
        if pl:
            for r in pl["rows"]:
                print(f"=== {r['owner']} ({'now' if r['now'] else 'if still short'})\n{pl['messages'][r['owner']]}\n")
            if pl["notice"]:
                print(f"=== server-state notice\n{pl['notice']}\n")
            return
    print("no plan in the latest snapshot; run `scan --need SIZE`")


def cmd_report(a):
    for snap in [a.snapshot] if a.snapshot else latest_snapshots():
        s = json.load(open(os.path.join(snap, "summary.json"), encoding="utf-8"))
        psnap, prev = previous(snap, s)
        print(render_text(s, prev, grown(psnap, snap) if psnap else [], full=a.full))


def show_files(target, top, cold_days):
    """Live, metadata-only look inside one folder: largest files, extensions, age."""
    mounts = read_mounts()
    skip = {m["target"] for m in mounts if m["target"].startswith(target.rstrip("/") + "/")}
    dev, cutoff, now = os.lstat(target).st_dev, time.time() - cold_days * 86400, time.time()
    heap, ext, seen, total, unmod, nfiles, denied = [], {}, set(), 0, 0, 0, 0
    stack = [target]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            denied += 1
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.path not in skip and e.stat(follow_symlinks=False).st_dev == dev:
                            stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_nlink > 1:
                    if st.st_ino in seen:
                        continue
                    seen.add(st.st_ino)
                b = st.st_blocks * 512
                total += b
                nfiles += 1
                if st.st_mtime < cutoff:
                    unmod += b
                x = os.path.splitext(e.name)[1].lower() or "(none)"
                ext[x] = ext.get(x, 0) + b
                item_ = (b, e.path, st.st_mtime, st.st_nlink)
                if len(heap) < top:
                    heapq.heappush(heap, item_)
                elif b > heap[0][0]:
                    heapq.heapreplace(heap, item_)
    day = lambda t: datetime.date.fromtimestamp(t).isoformat()
    print(f"{target}: {human(total)} in {nfiles:,} files, unmodified {cold_days}d {100 * unmod / max(total, 1):.0f}%"
          + (f", {denied} unreadable dirs" if denied else ""))
    print("by extension: " + ", ".join(f"{x} {human(b)}" for x, b in sorted(ext.items(), key=lambda kv: -kv[1])[:8]))
    for b, p, mt, nl in sorted(heap, reverse=True):
        print(f"  {human(b):>7}  mtime {day(mt)}" + (f"  hardlinks {nl}" if nl > 1 else "") + f"  {os.path.relpath(p, target)}")


def cmd_show(a):
    target = os.path.realpath(a.path)
    if a.files:
        return show_files(target, a.top, max(int(x) for x in a.days.split(",")))
    snap = a.snapshot or latest_snapshots()[0]
    rows = sorted(((int(r["bytes"]), r) for p, r in load_tree(snap).items()
                   if p == target or os.path.dirname(p) == target), key=lambda x: -x[0])
    if not rows:
        sys.exit(f"{target}: not in snapshot (only folders >= {human(TREE_MIN)} are kept)")
    for b, r in rows[:a.top + 1]:
        pct = lambda k: f"{100 * int(r[k]) / max(b, 1):3.0f}%"
        print(f"{human(b):>7}  unmodified {pct('unmodified')}  cold {pct('cold')}  newest {r['newest']}  "
              f"{int(r['files']):>9,} files  [{r['owner']}] {r['path']}")
    print(f"(snapshot {snap}; folders under {human(TREE_MIN)} are not kept)")


def main():
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("scan")
    s.add_argument("--mode", choices=("user", "folder"), default="user",
                   help="user: per-owner totals over the device; folder: plain breakdown of one folder")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--target", help="user mode: path whose filesystem is audited (default: the account's home)")
    g.add_argument("--all", action="store_true", help="user mode: every local disk filesystem, each separately")
    s.add_argument("--root", help="scan only this subtree (folder mode: the folder; default: current dir)")
    s.add_argument("--users", help="user mode: report only these owners, e.g. alice,bob")
    s.add_argument("--days", default="30,90", help="two 'unmodified' thresholds in days; cold uses the longer")
    s.add_argument("--min-size", help="smallest cleanup candidate (default 10G, folder mode 1G)")
    s.add_argument("--chunk-min", default="1G", help="smallest folder listed in the drill-down")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--full", action="store_true", help="print the full report instead of the brief")
    s.add_argument("--out", help="directory for the .md and .html reports (default: <skill>/results)")
    s.add_argument("--out-base", help="snapshot base (default: $DISK_USAGE_DIR or <skill>/results/snapshots)")
    s.add_argument("--need", help="space to free, e.g. 100G: adds whom to ask to the report")
    s.add_argument("--margin", default="30G", help="added to --need when choosing whom to ask")
    s.add_argument("--priority", help="people holding a priority grant on this server, e.g. a,b (saved)")
    s.add_argument("--sheet", help="people signed up on the usage sheet, e.g. c,d (saved)")
    s.add_argument("--min-user", default="20G", help="leave out people using less than this in total")
    s.add_argument("--deadline", help="YYYY-MM-DD in the messages (default: tomorrow)")
    ms = sub.add_parser("messages", help="print the drafted requests and notice of the latest plan")
    ms.add_argument("snapshot", nargs="?")
    fr = sub.add_parser("free", help="size, used and free space of each disk (instant)")
    fr.add_argument("path", nargs="?")
    r = sub.add_parser("report")
    r.add_argument("snapshot", nargs="?")
    r.add_argument("--full", action="store_true")
    w = sub.add_parser("show")
    w.add_argument("path")
    w.add_argument("snapshot", nargs="?")
    w.add_argument("--top", type=int, default=20)
    w.add_argument("--files", action="store_true", help="live scan of PATH: largest files and extensions")
    w.add_argument("--days", default="30,90")
    a = ap.parse_args()
    {"scan": cmd_scan, "report": cmd_report, "show": cmd_show, "free": cmd_free, "messages": cmd_messages}.get(
        a.cmd, lambda _: ap.print_help())(a)


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Disk usage</title>
<style>
:root{--bg:#f7f6f2;--fg:#1c1c1a;--muted:#6a6862;--line:#e2dfd6;--card:#fff;--accent:#2f6aa3;
--free:#e7e4da;--reserve:#cfc9ba;--unmeasured:#c4a98f;--shared:#a9a59c;--rest:#ecebe5;--est:#d9d3c3}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ebeae5;--muted:#9b9991;
--line:#34332f;--card:#1f1e1c;--accent:#7eaee0;--free:#2b2a27;--reserve:#45423b;--unmeasured:#6d5947;--shared:#5f5b54;--rest:#272623;--est:#4a463e}}
:root[data-theme=dark]{--bg:#161615;--fg:#ebeae5;--muted:#9b9991;--line:#34332f;--card:#1f1e1c;--accent:#7eaee0;
--free:#2b2a27;--reserve:#45423b;--unmeasured:#6d5947;--shared:#5f5b54;--rest:#272623;--est:#4a463e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:22px 16px 56px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:30px 0 10px}.sub{color:var(--muted);font-size:13px}
.stack{display:flex;height:30px;border-radius:6px;overflow:hidden;border:1px solid var(--line);margin-top:14px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:8px;font-size:12.5px;color:var(--muted)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:18px;font-variant-numeric:tabular-nums}.kpi span{font-size:12px;color:var(--muted)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.hb{display:flex;height:9px;width:150px;border-radius:4px;overflow:hidden;background:var(--rest)}.hb i{display:block;height:100%}
.path{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;word-break:break-all}
.tag{font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.tag.direct{border-color:var(--accent);color:var(--accent)}
#tm{position:relative;height:540px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card)}
.box{position:absolute;border:1px solid var(--card);overflow:hidden;font-size:11.5px;line-height:1.25;padding:3px 5px;color:#141414}
.box.can{cursor:zoom-in}.box .s{opacity:.75}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-bottom:8px}
.crumb a{color:var(--accent);cursor:pointer}.crumb{font-size:13px}
button{font:inherit;font-size:12.5px;padding:3px 10px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
button.on{border-color:var(--accent);color:var(--accent)}
.note{font-size:12.5px;color:var(--muted);margin-top:6px}
@media (max-width:640px){#tm{height:400px}}
</style></head><body><main>
<h1 id="title">Disk usage</h1><div class="sub" id="subtitle"></div>
<div class="stack" id="stack"></div><div class="legend" id="legend"></div>
<div class="kpis" id="kpis"></div>
<div id="ownerSec"><h2>By owner</h2><div class="scroll"><table id="owners"></table></div><div class="note" id="ownernote"></div></div>
<div id="folderSec"><h2>Folders</h2><div class="scroll"><table id="folders"></table></div></div>
<h2>Where the space is</h2>
<div class="bar"><span class="crumb" id="crumb"></span><span style="flex:1"></span>
<span>Color</span><button id="cOwner" class="on">owner</button><button id="cCold">unmodified share</button></div>
<div id="tm"></div><div class="note">Click a box to open it, the path above to go back. Hatched: files and folders under 64 MB. Hover for details.</div>
<div id="itemSec"><h2>Shared items and who they go to</h2><div class="note">direct = a workspace symlinks, bind-mounts or hardlinks it, or env metadata names the workspace (counted in the owner's total); estimated = names only (shown separately).</div><div class="scroll"><table id="items"></table></div></div>
<h2>Cleanup candidates</h2><div class="note">Suggestions only; the owner decides.</div><div class="scroll"><table id="hints"></table></div>
<div id="nowsSec"><h2>Largest folders outside any workspace</h2><div class="scroll"><table id="nows"></table></div></div>
<div id="growSec"><h2>Grew most since the previous snapshot</h2><div class="scroll"><table id="grow"></table></div></div>
<h2>Not measured</h2><div id="unmeasured" class="note"></div>
<div class="note" id="foot"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),S=D.s,dev=S.device,FOLDER=S.mode==='folder';
const fmt=b=>{const u='BKMGTP';let i=0,n=Math.abs(b);while(n>=1024&&i<5){n/=1024;i++}return(b<0?'-':'')+(i<2?n.toFixed(0):n.toFixed(1))+u[i]};
const pct=(a,b)=>b?Math.round(100*a/b)+'%':'';
const PAL=['#7fb2d9','#f2b56b','#9fd49f','#d6a3db','#ef9c9c','#8fd3cf','#e4cf72','#b4ade6','#cfa47d','#a5c99a','#e8a9c4','#9ab8c9'];
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const tot=v=>v.bytes+(v.shared_direct||0);
const owners=Object.entries(S.owners).sort((a,b)=>tot(b[1])-tot(a[1]));
const ocol={};owners.forEach(([o],i)=>ocol[o]=PAL[i%PAL.length]);
const colOf=o=>o==='-'?css('--shared'):(ocol[o]||css('--shared'));
const hatch=c=>`repeating-linear-gradient(45deg,${c},${c} 4px,${css('--card')} 4px,${css('--card')} 6px)`;
const el=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,y]of Object.entries(a)){if(x==='style')e.style.cssText=y;else if(x==='cls')e.className=y;else e.setAttribute(x,y)}for(const c of k)e.append(c);return e};
function table(id,head,rows){const t=document.getElementById(id);t.innerHTML='';const tr=el('tr');head.forEach(h=>tr.append(el('th',h.n?{cls:'n'}:{},h.t)));t.append(el('thead',{},tr));const tb=el('tbody');rows.forEach(r=>{const x=el('tr');r.forEach((c,i)=>{const td=el('td',head[i].n?{cls:'n'}:{});if(c instanceof Node)td.append(c);else td.textContent=c;x.append(td)});tb.append(x)});t.append(tb)}
const show=(id,on)=>document.getElementById(id).style.display=on?'':'none';
document.getElementById('title').textContent=(FOLDER?'Folder usage · ':'Disk usage by owner · ')+S.host;
document.getElementById('subtitle').textContent=`${S.time} · ${S.root} on ${dev.source} (${dev.fstype}) · ${D.prev?'compared with '+D.prev:'no previous snapshot'}`;
const fixed={'estimated':'--est','shared, unattributed':'--shared','docker, unattributed':'--unmeasured','outside scan root':'--rest','not measured':'--unmeasured','root reserve':'--reserve','free':'--free','this folder':'--accent','rest of the device':'--shared'};
const all=D.parts.reduce((a,p)=>a+p[1],0),stack=document.getElementById('stack'),leg=document.getElementById('legend');
D.parts.forEach(([l,b])=>{if(!b)return;const c=fixed[l]?css(fixed[l]):colOf(l);const bg=l==='estimated'||l==='docker, unattributed'?hatch(c):c;
 stack.append(el('div',{style:`width:${100*b/all}%;background:${bg}`,title:`${l}: ${fmt(b)} (${pct(b,all)})`}));
 if(b/all>=.004)leg.append(el('span',{},el('i',{cls:'sw',style:'background:'+bg}),`${l} ${fmt(b)} · ${pct(b,all)}`))});
const gap=Math.max(dev.used-S.measured-(S.docker_in_gap||0),0);
const k=document.getElementById('kpis');[[fmt(dev.used),'used of '+fmt(dev.size)],[fmt(dev.avail),'free for users'],[fmt(S.measured),FOLDER?'in this folder':'scanned ('+pct(S.measured,dev.used)+' of used)']].concat(FOLDER?[]:[[fmt(gap),'not measured'],[fmt(dev.reserved),'root-only reserve']]).forEach(([a,b])=>k.append(el('div',{cls:'kpi'},el('b',{},a),el('span',{},b))));
show('ownerSec',!FOLDER);show('itemSec',!FOLDER&&S.items.length);show('nowsSec',!FOLDER);show('folderSec',FOLDER);
if(!FOLDER){const mx=Math.max(1,...owners.map(([,v])=>tot(v)+(v.shared_est||0)),S.unattributed_shared);
 const bar=(o,v)=>{const b=el('div',{cls:'hb'});b.append(el('i',{style:`width:${150*v.bytes/mx}px;background:${colOf(o)}`}));if(v.shared_direct)b.append(el('i',{style:`width:${150*v.shared_direct/mx}px;background:${colOf(o)};opacity:.7`}));if(v.shared_est)b.append(el('i',{style:`width:${150*v.shared_est/mx}px;background:${hatch(colOf(o))}`}));return b};
 table('owners',[{t:'Owner'},{t:'Total',n:1},{t:''},{t:'Shared, direct',n:1},{t:'Estimated',n:1},{t:'Unmodified '+S.short_days+'d',n:1},{t:'Unmodified '+S.cold_days+'d',n:1},{t:'Cold '+S.cold_days+'d',n:1},{t:'Other uid',n:1},{t:'Top folders'}],
  owners.map(([o,v])=>[o,fmt(tot(v)),bar(o,v),v.shared_direct?fmt(v.shared_direct):'',v.shared_est?fmt(v.shared_est):'',fmt(v.unmodified_short||0),fmt(v.unmodified),fmt(v.cold),v.other_uid?fmt(v.other_uid):'',v.top.slice(0,3).map(([b,p])=>p.split('/').pop()+' '+fmt(b)).join(', ')])
  .concat([['(shared, unattributed)',fmt(S.unattributed_shared),bar('-',{bytes:S.unattributed_shared}),'','','','','','','']]));
 document.getElementById('ownernote').textContent='Owner = the outermost <name>_workspace folder; @name = another Unix account. Bar: workspace (solid), shared items with direct evidence (lighter), estimated (hatched). Each file is counted once, at the deepest folder holding all its hardlinks. Unmodified = no write; cold = no read or write. Other uid = inside folders of another uid (usually root, from a container): cannot be deleted without sudo.';
 table('items',[{t:'Kind'},{t:'Name'},{t:'Size',n:1},{t:'Owner'},{t:'Basis'}],S.items.map(it=>[it.kind,el('span',{cls:'path'},it.name),fmt(it.bytes),el('span',{},(it.owners.join(' + ')||'?')+' ',el('span',{cls:'tag '+(it.certainty==='direct'?'direct':'')},it.certainty)),it.basis+(it.detail?` (${it.detail})`:'')]));
 table('nows',[{t:'Size',n:1},{t:'Newest'},{t:'Path'}],S.no_workspace_top.map(r=>[fmt(r.bytes),r.newest,el('span',{cls:'path'},r.path+(r.rest?'  (own files + smaller subfolders)':''))]));}
else table('folders',[{t:'Folder'},{t:'Size',n:1},{t:'Share',n:1},{t:'Unmodified '+S.short_days+'d',n:1},{t:'Unmodified '+S.cold_days+'d',n:1},{t:'Cold',n:1},{t:'Newest'},{t:'Files',n:1}],S.folders.map(f=>[el('span',{cls:'path'},f.path.split('/').pop()),fmt(f.bytes),pct(f.bytes,S.measured),fmt(f.unmodified_short||0),fmt(f.unmodified),fmt(f.cold),f.newest,f.files.toLocaleString()]));
const nodes=new Map();D.tree.forEach(([p,b,m,c,nw,o])=>nodes.set(p,{p,b,m,c,nw,o,kids:[]}));
const dn=p=>{if(p==='/')return null;const i=p.lastIndexOf('/');return i<=0?'/':p.slice(0,i)};
const up=p=>{let q=dn(p);while(q!==null&&!nodes.has(q))q=dn(q);return q===null?null:nodes.get(q)};
for(const n of nodes.values()){const q=up(n.p);if(q)q.kids.push(n)}
const root=nodes.get(S.root)||[...nodes.values()][0];let cur=root,mode='owner';
while(cur&&cur.kids.length){const k=cur.kids.reduce((a,b)=>b.b>a.b?b:a);if(k.b>=.85*cur.b)cur=k;else break}  // open where the space splits
function squarify(items,x,y,w,h){const out=[],total=items.reduce((a,b)=>a+b.v,0);if(!total)return out;const sc=w*h/total;let i=0;
 while(i<items.length){const sh=Math.min(w,h);let row=[],sum=0,best=Infinity;
  while(i<items.length){const a=items[i].v*sc,s=sum+a,r=row.concat([a]),M=Math.max(...r),m=Math.min(...r),worst=Math.max(sh*sh*M/(s*s),s*s/(sh*sh*m));
   if(row.length&&worst>best)break;row=r;sum=s;best=worst;i++}
  const th=sum/sh;let off=0,j=i-row.length;for(const a of row){const len=a/th,it=items[j++];if(w>=h)out.push({it,x,y:y+off,w:th,h:len});else out.push({it,x:x+off,y,w:len,h:th});off+=len}
  if(w>=h){x+=th;w-=th}else{y+=th;h-=th}}return out}
const coldCol=f=>{const a=[159,212,159],b=[199,140,98];return`rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*f)).join(',')})`};
function render(){const tm=document.getElementById('tm');if(!root){tm.textContent='Nothing over 64 MB.';return}tm.innerHTML='';const W=tm.clientWidth,H=tm.clientHeight;
 const kids=cur.kids.slice().sort((a,b)=>b.b-a.b),items=kids.map(n=>({v:n.b,n}));const rest=cur.b-kids.reduce((a,n)=>a+n.b,0);
 if(rest>cur.b*.003)items.push({v:rest,n:null});items.sort((a,b)=>b.v-a.v);
 for(const r of squarify(items,0,0,W,H)){const n=r.it.n,bx=el('div',{cls:'box'+(n&&n.kids.length?' can':'')});
  bx.style.cssText=`left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;`+(n?`background:${mode==='owner'?colOf(n.o):coldCol(n.b?n.m/n.b:0)}`:`background:repeating-linear-gradient(45deg,${css('--rest')},${css('--rest')} 6px,${css('--line')} 6px,${css('--line')} 7px);color:${css('--muted')}`);
  const nm=n?n.p.split('/').pop()||'/':'(files + small folders)';bx.title=n?`${n.p}\n${fmt(n.b)} · owner ${n.o}\nunmodified ${pct(n.m,n.b)} · cold ${pct(n.c,n.b)} · newest ${n.nw}`:`${fmt(r.it.v)} in files and folders under 64 MB`;
  if(r.w>46&&r.h>16){bx.append(el('div',{},nm));if(r.h>30)bx.append(el('div',{cls:'s'},fmt(r.it.v)+(n&&mode!=='owner'?' · '+pct(n.m,n.b):'')))}
  if(n&&n.kids.length)bx.onclick=()=>{cur=n;render()};tm.append(bx)}
 const cr=document.getElementById('crumb');cr.innerHTML='';const chain=[];for(let q=cur;q;q=q===root?null:up(q.p))chain.unshift(q);
 chain.forEach((n,i)=>{const a=el('a',{},(n.p.split('/').pop()||n.p)+' '+fmt(n.b));a.onclick=()=>{cur=n;render()};cr.append(a);if(i<chain.length-1)cr.append(' / ')})}
document.getElementById('cOwner').onclick=e=>{mode='owner';e.target.classList.add('on');document.getElementById('cCold').classList.remove('on');render()};
document.getElementById('cCold').onclick=e=>{mode='cold';e.target.classList.add('on');document.getElementById('cOwner').classList.remove('on');render()};
addEventListener('resize',()=>render());render();
table('hints',[{t:'Owner'},{t:'Kind'},{t:'Size',n:1},{t:'Unmodified',n:1},{t:'Cold',n:1},{t:'Newest'},{t:'Path'}],S.hints.map(h=>[h.owner,h.kind,fmt(h.bytes),pct(h.unmodified,h.bytes),pct(h.cold,h.bytes),h.newest,el('span',{cls:'path'},h.path)]));
if(D.growth.length)table('grow',[{t:'Growth',n:1},{t:'Path'}],D.growth.map(([d,p,inner])=>[fmt(d),el('span',{cls:'path'},p+(inner?'  (outside the subfolders listed)':''))]));else show('growSec',0);
const un={};S.unreadable.forEach(u=>{if(!u.storage)un[u.owner]=(un[u.owner]||0)+1});
const heavy=S.unreadable.filter(u=>u.storage).map(u=>u.path),dk=S.docker||{};
document.getElementById('unmeasured').textContent=(FOLDER?'':`${fmt(gap)} of used space was not measured. `)+(heavy.length?`Container/snap storage needs root: ${heavy.join(', ')}${S.docker_in_gap?' (docker\'s own numbers are used above)':''}. `:'')+(dk.error?`Docker not queried: ${dk.error}. `:'')+`Unreadable folders (size unknown): ${Object.entries(un).map(([o,n])=>o+' '+n).join(', ')||'none'}. Deleted files still open: ${fmt(S.deleted_open.bytes)}.`+(S.excluded_mounts.some(x=>!x.bind)?` Other devices mounted inside the tree were excluded: ${S.excluded_mounts.filter(x=>!x.bind).map(x=>x.path+' ('+x.source+')').join(', ')}.`:'');
const c=S.cost;document.getElementById('foot').textContent=`Scan: ${c.wall_s} s wall, ${c.cpu_s} s CPU, ${c.peak_rss_mb} MB peak memory, ${S.entries.toLocaleString()} entries; ${c.files_opened} metadata files opened, no other file contents read.`;
</script></main></body></html>
"""

if __name__ == "__main__":
    main()
