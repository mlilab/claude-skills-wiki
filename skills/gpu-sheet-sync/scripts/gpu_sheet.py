#!/usr/bin/env python3
"""Check the lab's GPU servers listed in the GPU sheet and clear the names of idle GPUs.

    python3 gpu_sheet.py login                     # once: sign in with your lab Google account
    python3 gpu_sheet.py check --json plan.json    # report only, nothing is written
    python3 gpu_sheet.py apply --plan plan.json    # after the user agrees: clear those idle names
    python3 gpu_sheet.py setup-keys                # add your SSH key where it is rejected

login opens a browser for one sign-in with your @mli.kaist.ac.kr Google account. The
sign-in is kept in this skill's own gcloud folder (~/.config/gpu-sheet-sync), so your
default gcloud account stays as it is, and later runs reuse it without asking. The
script also finds or creates a small GCP project of yours with the Sheets API on and no
billing account (so it costs nothing), which Google requires for API quota.

check reads the sheet with the gws CLI, logs in to every server in it with key
authentication only, samples nvidia-smi a few times, and lists every GPU cell with what
it would do. A GPU is idle when no process runs on it and its memory use and utilization
stay under the thresholds in every sample. With --apply, the names of idle GPUs are
cleared after the sheet is read again, so a cell that someone changed in the meantime is
left alone. Servers that cannot be checked are reported and left as they are.

setup-keys is for a person at a terminal. For each server where key login fails, it runs
one interactive ssh login. Once the account password is typed, it appends your public key
to that account's ~/.ssh/authorized_keys, so later logins need no password.

Server NN is reached as serverNN@<proxy> on port 100NN with "IdentitiesOnly yes". The
proxy addresses are read from the sheet's "Proxy Servers IP" cells; only rows whose PORT
is 100NN are checked. Needs Python 3.8+, ssh, gcloud and gws; only the standard library.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SHEET_ID = "100Rey7X-AJ-XCnjUKuKrno7Ku04Q_TYBPz6YYkFZIT4"
SHEET_GID = 339844279                # the "info" tab
LAB_DOMAIN = "mli.kaist.ac.kr"       # every sheet access goes through a Google account of this domain
MEM_LIMIT_MIB = 500                  # an idle GPU uses less memory than this in every sample
UTIL_LIMIT_PCT = 5                   # and less utilization than this
SAMPLES = 3                          # nvidia-smi samples, one second apart
# The lab proxies refuse every connection from a computer for several minutes once it opens
# too many too fast, and retrying keeps the block going. So new connections are paced (both
# proxies together, as they seem to share one limit), a server that is down is not retried
# through the other proxy, and a proxy that keeps refusing is left alone for the rest of the run.
PROXY_INTERVAL_S = 3                 # seconds between any two new SSH connections
REFUSALS_BEFORE_STOP = 3

# Cell values that already mean "nobody": never cleared, and a busy GPU with one is flagged.
FREE_MARKS = {"", "-", "–", "—", "x", "n/a", "na", "free", "idle", "empty", "none"}

GPU_HEAD = re.compile(r"^\s*gpu\s*[#_-]?\s*(\d{1,2})\s*$", re.I)
PORT_HEAD = re.compile(r"^\s*port\s*$", re.I)
PROXY_LABEL = re.compile(r"proxy", re.I)
SERVER_CELL = re.compile(r"server\s*[-_#]?\s*0*(\d{1,3})(?!\d)", re.I)
IP = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])")


class SheetError(Exception):
    pass


class AccountError(Exception):
    pass


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def run(cmd, env=None, timeout=300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SheetError(f"{Path(cmd[0]).name} timed out")


# ---------------------------------------------------------------- Google sign-in
#
# The user's only step is `gpu_sheet.py login`: one browser sign-in with the lab account
# (`gcloud auth login --enable-gdrive-access`; Google blocks gcloud's other sign-in from
# asking for Sheets access). It lives in this skill's own gcloud folder. Everything else
# is automatic: a GCP project of the user's for API quota, the Sheets API turned on there,
# and a short-lived token handed to gws for each run.

STATE_DIR = Path(os.environ.get("GPU_SHEET_SYNC_HOME") or Path.home() / ".config" / "gpu-sheet-sync")
GCLOUD_DIR = STATE_DIR / "gcloud"
CONFIG_FILE = STATE_DIR / "config.json"
PROJECT_PREFIX = "gpu-sheet-sync-"


@dataclass
class Auth:
    account: str
    env: Dict[str, str]   # added to the environment of every gws call
    via: str              # "login" (this skill's sign-in) or "gws" (gws's own sign-in)


_AUTH: Optional[Auth] = None


def gcloud_env() -> Dict[str, str]:
    GCLOUD_DIR.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, CLOUDSDK_CONFIG=str(GCLOUD_DIR))


def gcloud_exe() -> str:
    exe = shutil.which("gcloud")
    if not exe:
        raise AccountError("gcloud is not installed. Install the Google Cloud CLI "
                           "(https://cloud.google.com/sdk/docs/install), then run the login step.")
    return exe


def gcloud(*args, timeout=300) -> subprocess.CompletedProcess:
    """gcloud with this skill's own config folder, as the account signed in there."""
    return run([gcloud_exe()] + list(args), env=dict(gcloud_env(), CLOUDSDK_CORE_DISABLE_PROMPTS="1"),
               timeout=timeout)


def signed_in_account() -> Optional[str]:
    """The account of this skill's sign-in, or None before the first login."""
    p = gcloud("auth", "list", "--filter=status:ACTIVE", "--format=value(account)", timeout=120)
    lines = [l.strip() for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else []
    return lines[0] if lines else None


def access_token() -> Optional[str]:
    p = gcloud("auth", "print-access-token", timeout=120)
    lines = [l.strip() for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else []
    return lines[-1] if lines else None


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ensure_project(account: str) -> str:
    """The user's GCP project for Sheets API quota: found, or created with the Sheets API on."""
    cfg = load_config()
    if cfg.get("account") == account and cfg.get("project"):
        return cfg["project"]
    p = gcloud("projects", "list", f"--filter=projectId:{PROJECT_PREFIX}*", "--format=value(projectId)")
    found = sorted(x.strip() for x in p.stdout.splitlines() if x.strip()) if p.returncode == 0 else []
    if found:
        project = found[0]
    else:
        import secrets
        import string
        project = PROJECT_PREFIX + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        print(f"Creating GCP project {project} for Sheets API quota (no billing account, so it is free)...",
              file=sys.stderr)
        p = gcloud("projects", "create", project, "--name=GPU Sheet Sync")
        if p.returncode != 0:
            raise SheetError(f"could not create a GCP project: {p.stderr.strip()[-400:]}")
    p = gcloud("services", "enable", "sheets.googleapis.com", f"--project={project}")
    if p.returncode != 0:
        raise SheetError(f"could not turn on the Sheets API in {project}: {p.stderr.strip()[-400:]}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"account": account, "project": project}, indent=1), encoding="utf-8")
    return project


def is_lab(account: Optional[str], domain: str = LAB_DOMAIN) -> bool:
    return bool(account) and account.lower().endswith("@" + domain)


def lab_auth(domain: str = LAB_DOMAIN) -> Auth:
    """How this run reaches the sheet, always as an @domain account; otherwise AccountError."""
    global _AUTH
    if _AUTH:
        return _AUTH
    login_hint = (f"Sign in once with `gpu_sheet.py login`: a browser opens, choose your @{domain} "
                  f"account and allow access.")
    account = signed_in_account()
    if account:
        if not is_lab(account, domain):
            raise AccountError(f"the skill is signed in as {account}, not an @{domain} account. {login_hint}")
        token = access_token()
        if not token:
            raise AccountError(f"the sign-in of {account} has expired. {login_hint}")
        project = ensure_project(account)
        _AUTH = Auth(account, {"GOOGLE_WORKSPACE_CLI_TOKEN": token, "GOOGLE_WORKSPACE_PROJECT_ID": project},
                     "login")
        return _AUTH
    account = gws_account()   # gws's own sign-in, if someone set that up instead
    if is_lab(account, domain):
        _AUTH = Auth(account, {}, "gws")
        return _AUTH
    raise AccountError(f"No @{domain} Google sign-in found. {login_hint}")


def cmd_login(args) -> int:
    """The user's one step: a browser sign-in with the lab account. Then everything is set up."""
    global _AUTH
    if not args.force:
        try:
            auth = lab_auth()
            print(f"Already signed in as {auth.account}.")
            return 0
        except AccountError:
            _AUTH = None
    print(f"A browser opens. Sign in with your @{LAB_DOMAIN} account and allow access.\n")
    rc = subprocess.call([gcloud_exe(), "auth", "login", "--enable-gdrive-access"], env=gcloud_env())
    if rc != 0:
        print("Sign-in did not finish.", file=sys.stderr)
        return rc
    auth = lab_auth()   # checks the account, then finds or creates the project
    print(f"\nSigned in as {auth.account}. The GPU sheet is now reachable; nothing else to set up.")
    return 0


# ---------------------------------------------------------------- gws (Google Sheets)

def gws_command() -> List[str]:
    """The gws executable. On Windows the npm shim is a .cmd file, which mangles JSON
    arguments, so the native binary inside the npm package is used instead."""
    if os.environ.get("GWS_BIN"):
        return [os.environ["GWS_BIN"]]
    found = shutil.which("gws")
    if not found:
        raise SheetError("gws not found. Install it with `npm install -g @googleworkspace/cli`.")
    if os.name == "nt":
        pkg = Path(found).parent / "node_modules" / "@googleworkspace" / "cli"
        if (pkg / "bin" / "gws.exe").exists():
            return [str(pkg / "bin" / "gws.exe")]
        if (pkg / "run.js").exists() and shutil.which("node"):
            return [shutil.which("node"), str(pkg / "run.js")]
    return [found]


def gws(*args, params=None, body=None):
    auth = lab_auth()
    cmd = gws_command() + list(args)
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    p = run(cmd, env=dict(os.environ, **auth.env), timeout=120)
    out = p.stdout.strip()
    try:
        data = json.loads(out) if out else {}
    except json.JSONDecodeError:
        data = None
    if p.returncode != 0 or data is None or (isinstance(data, dict) and "error" in data):
        msg = data.get("error", {}).get("message") if isinstance(data, dict) else None
        msg = msg or p.stderr.strip()[:500] or out[:500] or f"gws exited with {p.returncode}"
        if "insufficient" in msg.lower() and "scope" in msg.lower():
            raise AccountError("the sign-in has no access to Google Sheets. Run `gpu_sheet.py login --force` "
                               "and allow access.")
        raise SheetError(msg)
    return data


def gws_account() -> Optional[str]:
    """The Google account of gws's own sign-in, read from `gws auth status`, or None."""
    try:
        p = run(gws_command() + ["auth", "status"], timeout=60)
    except SheetError:
        return None
    try:
        status = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(status, dict) or status.get("auth_method", "none") == "none":
        return None
    for key in ("user", "email", "account", "user_email"):   # the field that names the account
        v = status.get(key)
        if isinstance(v, str) and EMAIL.fullmatch(v.strip()):
            return v.strip()
    found = EMAIL.findall(json.dumps(status))
    return found[0] if found else None


def quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def col_letter(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def a1(r: int, c: int) -> str:
    return f"{col_letter(c)}{r + 1}"


@dataclass
class Sheet:
    title: str
    grid: List[List[str]]
    merges: List[dict]

    def anchor(self, r: int, c: int) -> Tuple[int, int]:
        """Top-left cell of the merged range holding (r, c), or (r, c) itself."""
        for m in self.merges:
            if (m.get("startRowIndex", 0) <= r < m.get("endRowIndex", 0)
                    and m.get("startColumnIndex", 0) <= c < m.get("endColumnIndex", 0)):
                return m.get("startRowIndex", 0), m.get("startColumnIndex", 0)
        return r, c

    def value(self, r: int, c: int) -> str:
        r, c = self.anchor(r, c)
        row = self.grid[r] if r < len(self.grid) else []
        return str(row[c]) if c < len(row) else ""


def read_sheet(sheet_id: str, gid: int) -> Sheet:
    meta = gws("sheets", "spreadsheets", "get",
               params={"spreadsheetId": sheet_id, "fields": "sheets(properties(sheetId,title),merges)"})
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == gid:
            title = s["properties"]["title"]
            data = gws("sheets", "spreadsheets", "values", "get",
                       params={"spreadsheetId": sheet_id, "range": quote_title(title)})
            return Sheet(title, data.get("values", []), s.get("merges", []))
    raise SheetError(f"the spreadsheet has no tab with gid {gid}")


def clear_cells(sheet_id: str, title: str, cells: List[Tuple[int, int]]):
    ranges = [f"{quote_title(title)}!{a1(r, c)}" for r, c in cells]
    gws("sheets", "spreadsheets", "values", "batchClear",
        params={"spreadsheetId": sheet_id}, body={"ranges": ranges})


# ---------------------------------------------------------------- sheet layout

@dataclass
class ServerRow:
    server: int
    row: int                    # 0-based row in the grid
    hosts: List[str]            # SSH addresses to try, in order
    gpu_cols: Dict[int, int]    # GPU index -> 0-based column


def proxy_hosts(grid: List[List[str]]) -> List[str]:
    """The IPs listed in the cells right below the first cell labelled like "Proxy Servers IP".
    Later cells that merely mention a proxy (memos such as "ProxyJump ...") are ignored."""
    for r, line in enumerate(grid):
        for c, v in enumerate(line):
            if not PROXY_LABEL.search(str(v)) or IP.search(str(v)):
                continue
            hosts: List[str] = []
            for below in grid[r + 1:]:
                ips = IP.findall(str(below[c])) if c < len(below) else []
                if not ips:
                    break
                hosts += [h for h in ips if h not in hosts]
            if hosts:
                return hosts
    return []


def find_servers(sheet: Sheet) -> List[ServerRow]:
    """Server rows under each header row that names at least two GPU columns ("GPU 0", ...).
    A row counts when a cell left of the GPU columns says "server NN" and, if the header
    has a PORT column, its port is 100NN (rows of the old layout have other ports)."""
    hosts = proxy_hosts(sheet.grid)
    rows, header, seen = [], None, set()
    for r, line in enumerate(sheet.grid):
        cells = [str(v) for v in line]
        gpu_cols: Dict[int, int] = {}
        for c, v in enumerate(cells):
            m = GPU_HEAD.match(v)
            if m and int(m.group(1)) not in gpu_cols:
                gpu_cols[int(m.group(1))] = c
        if len(gpu_cols) >= 2:
            port_col = next((c for c, v in enumerate(cells) if PORT_HEAD.match(v)), None)
            header = (gpu_cols, port_col, min(gpu_cols.values()))
            continue
        if not header:
            continue
        gpu_cols, port_col, first = header
        num = next((int(m.group(1)) for m in map(SERVER_CELL.search, cells[:first]) if m), None)
        if num is None or num in seen:
            continue
        if port_col is not None and (cells[port_col].strip() if port_col < len(cells) else "") != str(10000 + num):
            continue
        seen.add(num)
        rows.append(ServerRow(num, r, list(hosts), dict(gpu_cols)))
    return rows


# ---------------------------------------------------------------- ssh and nvidia-smi

def ssh_exe() -> str:
    """The ssh client. On Windows, the built-in OpenSSH, which uses the Windows ssh-agent (where a
    passphrase-protected key is usually loaded); Git Bash's ssh can't reach that agent."""
    if os.environ.get("GPU_SHEET_SSH"):
        return os.environ["GPU_SHEET_SSH"]
    if os.name == "nt":
        win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
        if win.exists():
            return str(win)
    return shutil.which("ssh") or "ssh"


def ssh_base(host: str, num: int, batch: bool = True) -> List[str]:
    cmd = [ssh_exe(), "-p", str(10000 + num), "-o", "IdentitiesOnly yes",
           "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
    if batch:
        cmd += ["-o", "BatchMode=yes"]
    return cmd + [f"server{num:02d}@{host}"]


PROBE = """echo "HOST $(hostname)"
command -v nvidia-smi >/dev/null 2>&1 || { echo NO_NVIDIA_SMI; exit 0; }
i=0
while [ "$i" -lt @SAMPLES@ ]; do
  [ "$i" -gt 0 ] && sleep 1
  echo SAMPLE
  nvidia-smi --query-gpu=index,uuid,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>&1
  i=$((i+1))
done
echo APPS
nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>&1
"""


@dataclass
class Gpu:
    index: int
    mem: Optional[int]     # highest MiB used over the samples
    total: Optional[int]
    util: Optional[int]    # highest utilization % over the samples
    procs: int
    idle: bool

    def describe(self) -> str:
        mem = "memory n/a" if self.mem is None else f"{self.mem:,}/{self.total or 0:,} MiB"
        util = "util n/a" if self.util is None else f"{self.util}%"
        procs = f", {self.procs} process{'es' if self.procs != 1 else ''}" if self.procs else ""
        return f"{mem}, {util}{procs}"


@dataclass
class Probe:
    ok: bool
    error: str = ""
    hostname: str = ""
    gpus: Dict[int, Gpu] = field(default_factory=dict)
    host: str = ""         # the address that answered


def number(s: str) -> Optional[int]:
    try:
        return int(float(s))
    except ValueError:
        return None   # "[N/A]", "[Not Supported]"


def parse_probe(text: str, mem_limit: int = MEM_LIMIT_MIB, util_limit: int = UTIL_LIMIT_PCT) -> Probe:
    hostname, section, seen, apps, noise = "", None, {}, Counter(), []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("HOST "):
            hostname = line[5:].strip()
        elif line == "NO_NVIDIA_SMI":
            return Probe(False, "nvidia-smi not found", hostname)
        elif line in ("SAMPLE", "APPS"):
            section = line
        else:
            parts = [p.strip() for p in line.split(",")]
            if section == "SAMPLE" and len(parts) >= 5 and parts[0].isdigit():
                s = seen.setdefault(int(parts[0]), {"uuid": parts[1], "mem": [], "util": [], "total": number(parts[3])})
                s["mem"].append(number(parts[2]))
                s["util"].append(number(parts[4]))
            elif section == "APPS" and parts[0].startswith("GPU-"):
                apps[parts[0]] += 1
            elif section in ("SAMPLE", "APPS") and not line.lower().startswith("no running"):
                noise.append(line)
    if not seen:
        return Probe(False, "nvidia-smi failed: " + (noise[0] if noise else "no output"), hostname)
    gpus = {}
    for idx, s in seen.items():
        mems = [m for m in s["mem"] if m is not None]
        utils = [u for u in s["util"] if u is not None]
        mem = max(mems) if len(mems) == len(s["mem"]) else None   # a missing reading is not "idle"
        util = max(utils) if utils else None
        procs = apps[s["uuid"]]
        idle = procs == 0 and mem is not None and mem < mem_limit and (util is None or util < util_limit)
        gpus[idx] = Gpu(idx, mem, s["total"], util, procs, idle)
    return Probe(True, "", hostname, gpus)


def ssh_error(stderr: str) -> str:
    text = stderr.strip()
    low = text.lower()
    if "permission denied" in low:
        return "key not accepted: run setup-keys once (if your key has a passphrase, load it into ssh-agent)"
    if "host key verification failed" in low or "remote host identification has changed" in low:
        return "host key does not match ~/.ssh/known_hosts"
    for hint in ("timed out", "no route to host", "connection refused", "could not resolve",
                 "network is unreachable", "connection closed", "connection reset", "not responding"):
        if hint in low:
            return "unreachable (" + hint + ")"
    lines = [l for l in text.splitlines() if not l.startswith("Warning: Permanently added")]
    return lines[-1] if lines else "ssh failed"


THROTTLED = ("the proxies are refusing connections from this computer, probably because too many "
             "were opened in a short time; wait about 10 minutes, then run again")


class Proxies:
    """Paces new connections per proxy, and stops using a proxy that is blocking this computer.

    A proxy also refuses connections to a server that is down, and several servers in a row can
    be down. So after a few refusals in a row the proxy is tested with a server that answered
    through it earlier in this run: only if that one is refused too is the proxy left alone."""

    def __init__(self, interval: float = PROXY_INTERVAL_S, max_refusals: int = REFUSALS_BEFORE_STOP):
        self.interval, self.max_refusals = interval, max_refusals
        self.lock = threading.Lock()
        self.next_slot: Dict[str, float] = {}
        self.refusals: Counter = Counter()
        self.alive: Dict[str, int] = {}     # proxy -> a server that answered through it
        self.blocked: set = set()

    def usable(self, host: str) -> bool:
        with self.lock:
            return host not in self.blocked

    def wait_turn(self, host: str):
        """Wait until a new connection may be opened; turns are shared by all proxies."""
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_slot.get("all", 0.0))
            self.next_slot["all"] = start + self.interval
        if start > now:
            time.sleep(start - now)

    def has_answered(self, host: str) -> bool:
        with self.lock:
            return host in self.alive

    def answered(self, host: str, num: int):
        with self.lock:
            self.refusals[host] = 0
            self.alive[host] = num
            self.blocked.discard(host)

    def refused(self, host: str, num: int):
        with self.lock:
            self.refusals[host] += 1
            if self.refusals[host] < self.max_refusals or host in self.blocked:
                return
            self.refusals[host] = 0
            canary = self.alive.get(host)
        if canary is None or canary == num or connection_refused(host, canary):
            with self.lock:
                self.blocked.add(host)


PROXIES = Proxies()


def connection_refused(host: str, num: int) -> bool:
    """One key-only connection: True when the proxy refuses it (not when the server rejects the key)."""
    PROXIES.wait_turn(host)
    try:
        p = subprocess.run(ssh_base(host, num) + ["true"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=40, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return True
    return p.returncode == 255 and ssh_error(p.stderr).startswith("unreachable")


def ssh_try(hosts: List[str], num: int, remote: str, timeout: int) -> Tuple[Optional[subprocess.CompletedProcess], str, str]:
    """Run `remote` over key-only ssh through the first proxy that answers.
    Returns (process or None, error, address)."""
    error, host, tried = "no proxy address in the sheet (use --host)", "", False
    for host in hosts:
        if not PROXIES.usable(host):
            continue
        tried = True
        PROXIES.wait_turn(host)
        try:
            p = subprocess.run(ssh_base(host, num) + [remote], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            p, error = None, "unreachable (timed out)"
        if p is not None and p.returncode != 255:
            PROXIES.answered(host, num)
            return p, "", host
        if p is not None:
            error = ssh_error(p.stderr)
            if not error.startswith("unreachable"):
                PROXIES.answered(host, num)   # the server answered (it rejected the key); another proxy won't help
                return None, error, host
        known_good = PROXIES.has_answered(host)
        PROXIES.refused(host, num)
        if known_good:
            return None, error, host   # this proxy works, so the server itself is down: don't retry elsewhere
    if hosts and not tried:
        error = THROTTLED
    return None, error, host


def probe(hosts: List[str], num: int, samples: int, mem_limit: int, util_limit: int) -> Probe:
    p, error, host = ssh_try(hosts, num, PROBE.replace("@SAMPLES@", str(samples)), 40 + 2 * samples)
    if p is None:
        return Probe(False, error, host=host)
    result = parse_probe(p.stdout, mem_limit, util_limit)
    result.host = host
    return result


# ---------------------------------------------------------------- plan

@dataclass
class Cell:
    server: int
    gpu: int
    row: int
    col: int
    value: str
    status: str      # idle, busy, absent, unknown
    action: str      # clear, keep, flag, none
    note: str = ""


def is_free(value: str) -> bool:
    return value.strip().lower() in FREE_MARKS


def plan(sheet: Sheet, servers: List[ServerRow], probes: Dict[int, Probe]) -> List[Cell]:
    cells = []
    for s in servers:
        p = probes.get(s.server)
        for gpu, col in sorted(s.gpu_cols.items()):
            value = sheet.value(s.row, col).strip()
            if p is None or not p.ok:
                cells.append(Cell(s.server, gpu, s.row, col, value, "unknown", "none",
                                  p.error if p else "not checked"))
                continue
            g = p.gpus.get(gpu)
            if g is None:
                cells.append(Cell(s.server, gpu, s.row, col, value, "absent", "none", "no such GPU on the server"))
            elif g.idle:
                action = "none" if is_free(value) else "clear"
                cells.append(Cell(s.server, gpu, s.row, col, value, "idle", action, g.describe()))
            else:
                action = "flag" if is_free(value) else "keep"
                note = g.describe() + (" (busy, but no name in the sheet)" if action == "flag" else "")
                cells.append(Cell(s.server, gpu, s.row, col, value, "busy", action, note))
    # A merged cell names several GPUs: clear it only if every GPU it covers is idle, and only once.
    groups: Dict[Tuple[int, int], List[Cell]] = {}
    for c in cells:
        groups.setdefault(sheet.anchor(c.row, c.col), []).append(c)
    for group in groups.values():
        if len(group) < 2 or not any(c.action == "clear" for c in group):
            continue
        all_idle = all(c.status == "idle" for c in group)
        first = True
        for c in group:
            if c.action != "clear":
                continue
            if not all_idle:
                c.action, c.note = "keep", c.note + " (merged cell also covers a busy or unchecked GPU)"
            elif not first:
                c.action, c.note = "none", c.note + " (same merged cell)"
            first = False
    return cells


# ---------------------------------------------------------------- commands

def selected(servers: List[ServerRow], only: Optional[str], host: Optional[str]) -> List[ServerRow]:
    if only:
        wanted = {int(x) for x in only.replace(" ", "").split(",") if x}
        servers = [s for s in servers if s.server in wanted]
    if host:
        for s in servers:
            s.hosts = [host]
    return servers


def idle_count(p: Probe) -> int:
    return sum(1 for g in p.gpus.values() if g.idle)


def gpu_ranges(gpus: List[int]) -> str:
    """[0, 1, 2, 3, 6] -> "GPU0-3, GPU6"."""
    spans: List[List[int]] = []
    for g in sorted(gpus):
        if spans and g == spans[-1][1] + 1:
            spans[-1][1] = g
        else:
            spans.append([g, g])
    return ", ".join(f"GPU{a}" if a == b else f"GPU{a}-{b}" for a, b in spans)


def report(servers: List[ServerRow], probes: Dict[int, Probe], cells: List[Cell], details: bool = False):
    """Servers ranked from most to fewest free (idle) GPUs, one line each, then the skipped ones."""
    by_server: Dict[int, List[Cell]] = {}
    for c in cells:
        by_server.setdefault(c.server, []).append(c)
    checked = [s for s in servers if probes.get(s.server) and probes[s.server].ok]
    skipped = [s for s in servers if s not in checked]
    if details:   # every GPU of every checked server
        for s in checked:
            p = probes[s.server]
            print(f"server{s.server:02d}  {p.host}:{10000 + s.server}  sheet row {s.row + 1}  ({p.hostname})")
            for c in by_server.get(s.server, []):
                name = repr(c.value) if c.value else "(empty)"
                act = {"clear": "-> CLEAR", "keep": "keep", "flag": "check", "none": ""}[c.action]
                print(f"  GPU{c.gpu}  {c.status:<6} {name:<16} {act:<8} {c.note}")
        print()

    ranked = sorted(checked, key=lambda s: (-idle_count(probes[s.server]), s.server))
    print("Free GPUs by server, most first:")
    for s in ranked:
        p = probes[s.server]
        names: Dict[str, List[int]] = {}
        for c in by_server.get(s.server, []):
            if c.action == "clear":
                names.setdefault(c.value, []).append(c.gpu)
        flags = [c.gpu for c in by_server.get(s.server, []) if c.action == "flag"]
        notes = []
        if names:
            notes.append("name to clear: " + "; ".join(f"{gpu_ranges(g)} {n!r}" for n, g in names.items()))
        if flags:
            notes.append("busy, no name: " + gpu_ranges(flags))
        line = f"  server{s.server:02d}  {idle_count(p)}/{len(p.gpus)} idle"
        print(line + ("   " + "   ".join(notes) if notes else ""))
    if skipped:
        print("Skipped:")
        for s in skipped:
            p = probes.get(s.server)
            print(f"  server{s.server:02d}  {p.error if p else 'no proxy address in the sheet (use --host)'}")

    free = sum(idle_count(probes[s.server]) for s in checked)
    total = sum(len(probes[s.server].gpus) for s in checked)
    clears = [c for c in cells if c.action == "clear"]
    flags = [c for c in cells if c.action == "flag"]
    print(f"\n{free}/{total} GPUs idle on {len(checked)} checked servers ({len(skipped)} skipped). "
          f"{len(clears)} name(s) on idle GPUs to clear, {len(flags)} busy GPU(s) with no name.")


def key_rejected(p: Optional[Probe]) -> bool:
    return bool(p) and not p.ok and p.error.startswith("key not accepted")


def ask_passwords_and_add_key(servers: List[ServerRow], probes: Dict[int, Probe], args) -> None:
    """For servers that rejected the key: ask once for the lab servers' password (they share one),
    add the user's public key on each of them with it, and check them again."""
    rejected = [s for s in servers if key_rejected(probes.get(s.server))]
    if not rejected:
        return
    numbers = ",".join(str(s.server) for s in rejected)
    names = ", ".join(f"server{s.server:02d}" for s in rejected)
    if args.no_password or not sys.stdin.isatty():
        print(f"\nKey not accepted by {names}. To add your key there (one password for all of them), "
              f"run this in a terminal: gpu_sheet.py setup-keys --servers {numbers}\n")
        return
    key = public_key()
    if not key:
        return
    print(f"\n{names} did not accept your SSH key.")
    added = add_keys([(s.server, [probes[s.server].host] + [h for h in s.hosts if h != probes[s.server].host])
                      for s in rejected], key)
    for num, host in added.items():
        probes[num] = probe([host], num, args.samples, args.mem_mib, args.util)
    print()


def public_key() -> Optional[str]:
    """The user's public key, offering to create one when there is none."""
    pub = find_public_key()
    if pub is None:
        path = Path.home() / ".ssh" / "id_ed25519"
        answer = input(f"No SSH key in {path.parent}. Create {path} with ssh-keygen now? [y/N] ")
        if answer.strip().lower() != "y":
            return None
        path.parent.mkdir(mode=0o700, exist_ok=True)
        if subprocess.call(["ssh-keygen", "-t", "ed25519", "-f", str(path)]) != 0:
            return None
        pub = find_public_key()
    print(f"Key: {pub}")
    return pub.read_text(encoding="utf-8").strip()


def askpass_helper() -> Path:
    """The small program ssh runs to get the password (SSH_ASKPASS). It prints the password from
    the environment of that one ssh process; the password is never written to a file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = STATE_DIR / "askpass.cmd"
        text = ("@echo off\r\n"
                f'"{sys.executable}" -c "import os,sys; sys.stdout.write(os.environ[\'GPU_SHEET_SSH_PASS\'] + chr(10))"\r\n')
    else:
        path = STATE_DIR / "askpass.sh"
        text = "#!/bin/sh\nprintf '%s\\n' \"$GPU_SHEET_SSH_PASS\"\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        with open(path, "w", encoding="utf-8", newline="") as f:   # keep \r\n for cmd, \n for sh
            f.write(text)
    os.chmod(path, 0o700)
    return path


def password_login(host: str, num: int, password: str, remote: str) -> subprocess.CompletedProcess:
    """One password login that runs `remote`. The password reaches ssh through SSH_ASKPASS."""
    env = dict(os.environ, SSH_ASKPASS=str(askpass_helper()), SSH_ASKPASS_REQUIRE="force",
               DISPLAY=os.environ.get("DISPLAY") or "none", GPU_SHEET_SSH_PASS=password, PYTHONIOENCODING="utf-8")
    cmd = [ssh_exe(), "-p", str(10000 + num), "-o", "IdentitiesOnly yes", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "PubkeyAuthentication=no",
           "-o", "PreferredAuthentications=password,keyboard-interactive", "-o", "NumberOfPasswordPrompts=1",
           f"server{num:02d}@{host}", remote]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=60, stdin=subprocess.DEVNULL)


def add_key_with_password(hosts: List[str], num: int, key: str, password: str) -> Tuple[str, Optional[str]]:
    """("added", proxy) | ("wrong password", None) | ("unreachable", None) | ("failed", None)."""
    status = "unreachable"
    for host in hosts:
        if not PROXIES.usable(host):
            continue
        PROXIES.wait_turn(host)
        try:
            p = password_login(host, num, password, install_key_command(key))
        except subprocess.TimeoutExpired:
            PROXIES.refused(host, num)
            continue
        if "KEY_INSTALLED" in p.stdout:
            PROXIES.answered(host, num)
            return "added", host
        error = ssh_error(p.stderr)
        if error.startswith("unreachable"):
            known_good = PROXIES.has_answered(host)
            PROXIES.refused(host, num)
            if known_good:
                return "unreachable", None
            continue
        PROXIES.answered(host, num)
        return ("wrong password", None) if error.startswith("key not accepted") else ("failed", None)
    return status, None


def add_keys(targets: List[Tuple[int, List[str]]], key: str) -> Dict[int, str]:
    """Ask once for the password the lab servers share, then add the key on every target.
    If the first server tried rejects it, the user may type it again once.
    Returns {server: proxy} for the servers where the key was added."""
    import getpass
    print(f"Type the password of the lab server accounts. It is used for these {len(targets)} server(s) "
          f"in this run only and is never shown or saved. (Enter skips.)")
    password = getpass.getpass("Password: ")
    added: Dict[int, str] = {}
    confirmed = False
    for num, hosts in targets:
        name = f"server{num:02d}"
        if not password:
            print(f"{name}: skipped")
            continue
        status, host = add_key_with_password(hosts, num, key, password)
        if status == "wrong password" and not confirmed:
            password = getpass.getpass(f"{name} did not accept that password. Type it again (Enter skips): ")
            if password:
                status, host = add_key_with_password(hosts, num, key, password)
        if status == "added":
            confirmed = True
            added[num] = host
            print(f"{name}: key added")
        elif status == "wrong password":
            print(f"{name}: did not accept the password")
        elif status == "unreachable":
            print(f"{name}: {THROTTLED if not any(PROXIES.usable(h) for h in hosts) else 'unreachable'}")
        else:
            print(f"{name}: could not add the key")
    password = ""
    return added


def probe_servers(servers: List[ServerRow], args) -> Dict[int, Probe]:
    """Check the servers in parallel (paced), printing one progress line per server."""
    probes: Dict[int, Probe] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        # spread servers over the proxies: server i starts with proxy i mod n
        futures = {pool.submit(probe, s.hosts[i % len(s.hosts):] + s.hosts[:i % len(s.hosts)], s.server,
                               args.samples, args.mem_mib, args.util): s
                   for i, s in enumerate(x for x in servers if x.hosts)}
        for f in concurrent.futures.as_completed(futures):
            p = probes[futures[f].server] = f.result()
            state = f"checked, {idle_count(p)}/{len(p.gpus)} GPUs idle" if p.ok else p.error
            print(f"  [{len(probes)}/{len(futures)}] server{futures[f].server:02d}: {state}",
                  file=sys.stderr, flush=True)
    return probes


def cmd_check(args) -> int:
    sheet = read_sheet(args.sheet_id, args.gid)
    servers = selected(find_servers(sheet), args.servers, args.host)
    if not servers:
        print("No server rows found in the sheet (a header row with GPU 0, GPU 1, ... columns, then rows "
              "naming 'server NN' with PORT 100NN).")
        return 1
    probes = probe_servers(servers, args)
    ask_passwords_and_add_key(servers, probes, args)
    cells = plan(sheet, servers, probes)
    report(servers, probes, cells, details=args.details)

    applied, changed = [], []
    clears = [c for c in cells if c.action == "clear"]
    if args.apply and clears:
        fresh = read_sheet(args.sheet_id, args.gid)   # leave alone cells that changed since the first read
        for c in clears:
            (changed if fresh.value(c.row, c.col).strip() != c.value else applied).append(c)
        if applied:
            clear_cells(args.sheet_id, fresh.title, [fresh.anchor(c.row, c.col) for c in applied])
        print(f"\nCleared {len(applied)} cell(s) in tab {fresh.title!r}: "
              + ", ".join(f"server{c.server:02d} GPU{c.gpu} {a1(c.row, c.col)} ({c.value})" for c in applied))
        if changed:
            print("Left alone because the cell changed while checking: "
                  + ", ".join(f"server{c.server:02d} GPU{c.gpu}" for c in changed))
    elif clears:
        print("Nothing was written. To clear these names: "
              + (f"gpu_sheet.py apply --plan {args.json}" if args.json else "run again with --json FILE, then apply --plan FILE"))

    if args.json:
        out = {
            "sheet_tab": sheet.title, "applied": bool(args.apply),
            "servers": [{"server": s.server, "hosts": s.hosts, "port": 10000 + s.server, "row": s.row + 1,
                         "ok": bool(probes.get(s.server) and probes[s.server].ok),
                         "key_rejected": key_rejected(probes.get(s.server)),
                         "error": probes[s.server].error if s.server in probes else "no proxy address",
                         "hostname": probes[s.server].hostname if s.server in probes else ""} for s in servers],
            "cells": [{**c.__dict__, "cell": a1(c.row, c.col),
                       "cleared": c in applied, "changed_meanwhile": c in changed} for c in cells],
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_apply(args) -> int:
    """Clear the cells a `check --json` run planned to clear, after the user agreed. Only the servers
    involved are checked again; a cell is cleared only if every GPU it names is still idle and the
    cell still holds the name the check saw."""
    data = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    cells = data.get("cells", [])
    wanted = [c for c in cells if c.get("action") == "clear" and not c.get("cleared")]
    if not wanted:
        print("Nothing to clear in this plan.")
        return 0
    rows = {s["server"]: s for s in data.get("servers", [])}
    nums = sorted({c["server"] for c in wanted})
    servers = [ServerRow(n, rows[n]["row"] - 1, list(rows[n]["hosts"]), {}) for n in nums]
    print(f"Checking {', '.join(f'server{n:02d}' for n in nums)} again before clearing...", file=sys.stderr)
    probes = probe_servers(servers, args)
    fresh = read_sheet(args.sheet_id, args.gid)

    def still_idle(server: int, gpu: int) -> bool:
        p = probes.get(server)
        return bool(p and p.ok and gpu in p.gpus and p.gpus[gpu].idle)

    by_anchor: Dict[Tuple[int, int], List[dict]] = {}
    for c in cells:
        by_anchor.setdefault(fresh.anchor(c["row"], c["col"]), []).append(c)
    cleared, left = [], []
    for c in wanted:
        group = by_anchor.get(fresh.anchor(c["row"], c["col"]), [c])
        if not all(still_idle(g["server"], g["gpu"]) for g in group):
            left.append((c, "no longer idle" if probes.get(c["server"]) and probes[c["server"]].ok
                         else "could not be checked again"))
        elif fresh.value(c["row"], c["col"]).strip() != c["value"]:
            left.append((c, f"the cell changed to {fresh.value(c['row'], c['col']).strip()!r}"))
        else:
            cleared.append(c)
    if cleared:
        clear_cells(args.sheet_id, fresh.title, sorted({fresh.anchor(c["row"], c["col"]) for c in cleared}))
    print(f"Cleared {len(cleared)} cell(s) in tab {fresh.title!r}"
          + (": " + ", ".join(f"server{c['server']:02d} GPU{c['gpu']} {c['cell']} ({c['value']})" for c in cleared)
             if cleared else "."))
    for c, why in left:
        print(f"Left server{c['server']:02d} GPU{c['gpu']} ({c['value']}): {why}")
    return 0


def find_public_key() -> Optional[Path]:
    d = Path.home() / ".ssh"
    for name in ("id_ed25519", "id_ecdsa", "id_rsa"):   # identities ssh tries with IdentitiesOnly
        if (d / name).exists() and (d / f"{name}.pub").exists():
            return d / f"{name}.pub"
    return None


def install_key_command(key: str) -> str:
    k = shlex.quote(key.strip())
    return ("umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys"
            " && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
            ' && if [ -n "$(tail -c1 ~/.ssh/authorized_keys)" ]; then echo >> ~/.ssh/authorized_keys; fi'
            f" && (grep -qxF {k} ~/.ssh/authorized_keys || echo {k} >> ~/.ssh/authorized_keys)"
            " && echo KEY_INSTALLED")


def cmd_setup_keys(args) -> int:
    if not sys.stdin.isatty():
        print("setup-keys asks for the server password, so it must run in a terminal.")
        return 2
    if args.servers and args.host:
        servers = [ServerRow(int(n), -1, [args.host], {}) for n in args.servers.split(",") if n.strip()]
    else:
        servers = selected(find_servers(read_sheet(args.sheet_id, args.gid)), args.servers, args.host)
    key = public_key()
    if not key:
        return 1
    targets, failed = [], []
    for s in servers:
        name = f"server{s.server:02d}"
        p, why, host = ssh_try(s.hosts, s.server, "true", 40)
        if p is not None and p.returncode == 0:
            print(f"{name}: key login already works")
        elif why.startswith("key not accepted"):
            targets.append((s.server, [host] + [h for h in s.hosts if h != host]))
        else:
            print(f"{name}: {why or 'ssh failed'}, skipped")
            failed.append(name)
    if targets:
        added = add_keys(targets, key)
        failed += [f"server{n:02d}" for n, _ in targets if n not in added]
    print("\nDone." + (f" Not set up: {', '.join(failed)}" if failed else " Every server accepts your key."))
    return 1 if failed else 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # names may be non-ASCII; show progress
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    lp = sub.add_parser("login", help="sign in once with your lab Google account (opens a browser)")
    lp.add_argument("--force", action="store_true", help="sign in again even if already signed in")
    for name in ("check", "apply", "setup-keys"):
        sp = sub.add_parser(name)
        sp.add_argument("--sheet-id", default=SHEET_ID)
        sp.add_argument("--gid", type=int, default=SHEET_GID, help="tab id from the sheet URL (#gid=...)")
        if name != "apply":
            sp.add_argument("--servers", help="only these server numbers, e.g. 24,39")
            sp.add_argument("--host", help="use this SSH address instead of the proxies in the sheet")
        if name == "apply":
            sp.add_argument("--plan", required=True, help="the --json file of a check run")
        if name == "check":
            sp.add_argument("--apply", action="store_true", help="clear the names of idle GPUs right away")
            sp.add_argument("--json", help="also write the full result (the plan for apply) to this file")
            sp.add_argument("--details", action="store_true", help="also list every GPU of every server")
            sp.add_argument("--no-password", action="store_true",
                            help="don't ask for passwords of servers that reject your key; just list them")
        if name in ("check", "apply"):
            sp.add_argument("--mem-mib", type=int, default=MEM_LIMIT_MIB, help="idle below this memory use")
            sp.add_argument("--util", type=int, default=UTIL_LIMIT_PCT, help="idle below this utilization %%")
            sp.add_argument("--samples", type=int, default=SAMPLES)
            sp.add_argument("--workers", type=int, default=4, help="servers checked at once")
        sp.add_argument("--interval", type=float, default=PROXY_INTERVAL_S,
                        help="seconds between new connections through one proxy (the proxies block bursts)")
    args = ap.parse_args(argv)
    global PROXIES
    PROXIES = Proxies(getattr(args, "interval", PROXY_INTERVAL_S))
    try:
        return {"login": cmd_login, "check": cmd_check, "apply": cmd_apply,
                "setup-keys": cmd_setup_keys}[args.command](args)
    except AccountError as e:
        print(f"Not signed in with a lab account: {e}", file=sys.stderr)
        return 4
    except SheetError as e:
        print(f"Google Sheets error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
