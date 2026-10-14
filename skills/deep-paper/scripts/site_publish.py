#!/usr/bin/env python3
"""Publish the HTML site to its own GitHub Pages repository (html.mode: github).

usage: site_publish.py token      # store a GitHub token (hidden prompt, or one line on stdin)
       site_publish.py setup      # check or create the public repo, turn on Pages, first push
       site_publish.py push       # publish the current site (one commit, force-pushed)

The site is published at https://<user>.github.io/<repo>/ (html.github in the config). Only the
pages and figures are uploaded: never paper.pdf (the viewer loads arXiv PDFs from arxiv.org), never
content.md, summary.md, refs or the cache. The token needs, for that one repository, Contents,
Pages and Administration read/write (fine-grained token). It is stored in
~/.config/deep-paper/github-token with mode 600 and is never printed or written into the repo.
"""
from __future__ import annotations

import base64
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import config_path, load_config, out, session

API = "https://api.github.com"


def token_path() -> Path:
    return config_path().parent / "github-token"


def token() -> str:
    p = token_path()
    if not p.exists():
        raise SystemExit("no GitHub token: run site_publish.py token in a terminal")
    return p.read_text().strip()


def gh(method, path, **kw):
    h = {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json"}
    return session().request(method, API + path, headers=h, timeout=60, **kw)


def gh_cfg(cfg) -> dict:
    g = (cfg.get("html") or {}).get("github") or {}
    if not (g.get("user") and g.get("repo")):
        raise SystemExit("html.github is not set: setup.py html-set --mode github --user U --repo R")
    return g


def cmd_token():
    tok = (getpass.getpass("GitHub token (hidden): ") if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not tok:
        raise SystemExit("empty token")
    r = session().get(API + "/user", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"GitHub rejected the token (HTTP {r.status_code})")
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    out({"token_stored": True, "login": r.json().get("login")})


def export(cfg, dst: Path) -> int:
    """Copy the publishable files of the site into dst (a git work tree)."""
    root = cfg["data_dir"]
    for item in dst.iterdir():
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    n = 0
    for rel in ["index.html", "index.json"]:
        if (root / rel).exists():
            shutil.copy2(root / rel, dst / rel)
            n += 1
    if (root / "assets").exists():
        shutil.copytree(root / "assets", dst / "assets")
        n += len(list((dst / "assets").iterdir()))
    for pdir in sorted((root / "papers").glob("*")):
        if not (pdir / "index.html").exists():
            continue
        tgt = dst / "papers" / pdir.name
        tgt.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdir / "index.html", tgt / "index.html")
        n += 1
        if (pdir / "figures").exists():
            shutil.copytree(pdir / "figures", tgt / "figures")
            n += len(list((tgt / "figures").iterdir()))
    (dst / ".nojekyll").write_text("")
    return n


def git(repo: Path, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def cmd_push(cfg) -> dict:
    g = gh_cfg(cfg)
    me = gh("GET", "/user").json()
    repo = cfg["data_dir"] / ".publish" / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        git(repo, "init", "-q", "-b", "main")
    n = export(cfg, repo)
    git(repo, "config", "user.name", me["login"])
    git(repo, "config", "user.email", f"{me['id']}+{me['login']}@users.noreply.github.com")
    git(repo, "add", "-A")
    # one commit, force-pushed: old versions do not pile up in the public history
    git(repo, "checkout", "-q", "--orphan", "publish")
    git(repo, "commit", "-q", "-m", "update", check=False)
    git(repo, "branch", "-q", "-D", "main", check=False)
    git(repo, "branch", "-q", "-m", "main")
    auth = base64.b64encode(f"x-access-token:{token()}".encode()).decode()
    url = f"https://github.com/{g['user']}/{g['repo']}.git"
    r = subprocess.run(["git", "-C", str(repo), "-c", f"http.extraheader=Authorization: Basic {auth}",
                        "push", "-q", "-f", url, "main"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"push failed: {(r.stderr or r.stdout).replace(auth, '***')[:300]}")
    return {"pushed": True, "files": n, "url": g.get("url")}


def cmd_setup(cfg):
    g = gh_cfg(cfg)
    r = gh("GET", f"/repos/{g['user']}/{g['repo']}")
    if r.status_code == 404:
        c = gh("POST", "/user/repos", json={"name": g["repo"], "private": False, "has_wiki": False,
                                            "description": "Deep Papers"})
        if c.status_code not in (200, 201):
            raise SystemExit(f"could not create {g['user']}/{g['repo']} (HTTP {c.status_code}); create an "
                             "empty public repository with that name on github.com and run setup again")
    elif r.status_code == 200 and r.json().get("private"):
        print("warning: the repository is private; GitHub Pages on the Free plan needs a public one", flush=True)
    res = cmd_push(cfg)
    p = gh("POST", f"/repos/{g['user']}/{g['repo']}/pages", json={"source": {"branch": "main", "path": "/"}})
    if p.status_code not in (201, 409):
        res["pages"] = (f"turn on Pages by hand: repository Settings -> Pages -> Deploy from branch main / root "
                        f"(API HTTP {p.status_code})")
    else:
        res["pages"] = "enabled"
    out(res)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("token", "setup", "push"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "token":
        return cmd_token()
    cfg = load_config()
    if sys.argv[1] == "setup":
        return cmd_setup(cfg)
    out(cmd_push(cfg))


if __name__ == "__main__":
    main()
