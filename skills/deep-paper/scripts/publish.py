#!/usr/bin/env python3
"""Publish the HTML site the way onboarding chose (html.mode in the config).

usage: publish.py

  daily-papers  run the daily-papers publisher; the site is its encrypted sub page deep/
  github        site_publish.py push to the site's own GitHub Pages repository
  local         nothing to publish; open <data_dir>/index.html or run serve.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from common import load_config, out


def main():
    cfg = load_config()
    html = cfg.get("html") or {}
    mode = html.get("mode") or "local"
    if mode == "daily-papers":
        dp = html.get("daily_papers") or {}
        script = Path(dp.get("skill_dir", "")) / "scripts" / "publish.py"
        if not script.exists():
            raise SystemExit("daily-papers publisher not found; rerun setup.py html-set --mode daily-papers")
        r = subprocess.run([dp.get("python") or "python3", str(script), "push"], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"daily-papers publish failed: {(r.stderr or r.stdout)[-400:]}")
        try:
            res = json.loads(r.stdout)
        except json.JSONDecodeError:
            res = {"output": r.stdout[-400:]}
        url = (res.get("url") or "").rstrip("/")
        out({"mode": mode, "pushed": res.get("pushed"), "url": f"{url}/deep/" if url else None})
    elif mode == "github":
        import site_publish
        out({"mode": mode, **site_publish.cmd_push(cfg)})
    else:
        out({"mode": "local", "index": str(cfg["data_dir"] / "index.html"),
             "note": "nothing to publish; serve.py serves the folder"})


if __name__ == "__main__":
    main()
