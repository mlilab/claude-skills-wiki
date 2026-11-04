"""Read local Git provenance without modifying the source repository or contacting remotes."""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit

from views import redact


def git(repository, *arguments, optional=False):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repository), *arguments],
            capture_output=True, text=True, env=env, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Local Git inspection timed out. No remote request was made.") from None
    if result.returncode and not optional:
        raise ValueError("Cannot read local Git provenance. Check the repository and its existing commits.")
    return result.stdout.rstrip("\n") if result.returncode == 0 else None


def safe_remote(url):
    """Remove embedded credentials, query strings, and fragments before recording a remote."""
    if "://" in url:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if ":" in host:
            host = "[" + host + "]"
        if parsed.port:
            host += ":" + str(parsed.port)
        return redact(urlunsplit((parsed.scheme, host, parsed.path, "", "")))
    return redact(re.sub(r"^[^/@:]+@(?=[^:]+:)", "", url))


def snapshot(repository):
    repository = Path(repository).expanduser().resolve()
    root = Path(git(repository, "rev-parse", "--show-toplevel")).resolve()
    commit = git(root, "rev-parse", "--verify", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("The repository must have a full recorded commit.")
    changes = git(root, "status", "--porcelain=v1", "--untracked-files=normal").splitlines()
    remotes = {}
    for name in git(root, "remote").splitlines():
        url = git(root, "remote", "get-url", name)
        remotes[name] = safe_remote(url)
    return {
        "repository": str(root), "captured_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit, "branch": git(root, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True),
        "dirty": bool(changes), "changes": redact(changes), "remotes": remotes,
    }


def connect(root, repository, cfg, save_json):
    current = snapshot(repository)
    cfg["repository"] = current["repository"]
    save_json(root, "notebook.json", cfg)
    return {"repository": cfg["repository"], "current_checkout": current,
            "note": "Association only. No source changes, fetch, push, or historical execution claim."}


def capture(root, repository, directory, record, stage, phase, save_json):
    current = snapshot(repository)
    entry = dict(current, stage=stage, phase=phase)
    record.setdefault("code_snapshots", []).append(entry)
    if stage == "execution":
        record["execution"].append(dict(entry))
    save_json(root, str(directory.relative_to(root) / "report.json"), record)
    return {"id": record["id"], "snapshot": entry,
            "note": "Capture is contemporaneous. It does not reconstruct historical execution or run an experiment."}
