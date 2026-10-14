#!/usr/bin/env python3
"""Upload local figures into a Notion page where notion_md.py left "[[upload Figure N]]" lines.

usage: notion_upload.py --id PAPER_ID --page NOTION_PAGE_ID_OR_URL

Needs a Notion internal integration token that can access the database (Settings -> Connections
on the database page): env NOTION_TOKEN, or the file named by notion.token_file in the config.
The token is read at run time and never printed. For each placeholder line the script uploads the
figure file (POST /v1/file_uploads), inserts an image block with the caption right after the
placeholder, and deletes the placeholder. SVG figures with a public URL are replaced by their PNG
copy only if --replace-svg is given.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import requests

from common import load_config, out, paper_dir, read_json

API = "https://api.notion.com/v1"
NV = "2022-06-28"


def token(cfg) -> str:
    t = os.environ.get("NOTION_TOKEN")
    if t:
        return t.strip()
    tf = (cfg.get("notion") or {}).get("token_file")
    if tf and Path(os.path.expanduser(tf)).exists():
        return Path(os.path.expanduser(tf)).read_text().strip()
    raise SystemExit("no Notion token: set NOTION_TOKEN or notion.token_file (see references/notion.md)")


def page_id(s: str) -> str:
    m = re.findall(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", s.lower())
    if not m:
        raise SystemExit(f"not a Notion page id or URL: {s}")
    return m[-1].replace("-", "")


def blocks(h, bid):
    cur = None
    while True:
        r = requests.get(f"{API}/blocks/{bid}/children", headers=h, params={"page_size": 100,
                         **({"start_cursor": cur} if cur else {})}, timeout=60)
        r.raise_for_status()
        d = r.json()
        for b in d["results"]:
            yield b
            if b.get("has_children") and b["type"] not in ("child_page", "child_database"):
                yield from blocks(h, b["id"])
        if not d.get("has_more"):
            return
        cur = d["next_cursor"]


def text_of(b) -> str:
    rt = (b.get(b["type"]) or {}).get("rich_text") or []
    return "".join(x.get("plain_text", "") for x in rt)


def upload(h, path: Path) -> str:
    r = requests.post(f"{API}/file_uploads", headers={**h, "Content-Type": "application/json"},
                      json={"mode": "single_part", "filename": path.name}, timeout=60)
    r.raise_for_status()
    up = r.json()
    with open(path, "rb") as f:
        r2 = requests.post(up["upload_url"], headers=h, files={"file": (path.name, f)}, timeout=180)
    r2.raise_for_status()
    return up["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--page", required=True)
    args = ap.parse_args()
    cfg = load_config()
    h = {"Authorization": f"Bearer {token(cfg)}", "Notion-Version": NV}
    pdir = paper_dir(cfg, args.id)
    figs = {f["number"]: f for f in read_json(pdir / "figures.json", {"figures": []})["figures"]}
    pid = page_id(args.page)
    done, missing = [], []
    for b in list(blocks(h, pid)):
        m = re.search(r"\[\[upload Figure ([A-Za-z]?\d+[a-z]?)\]\]", text_of(b))
        if not m:
            continue
        f = figs.get(m.group(1))
        files = (f or {}).get("png_files") or (f or {}).get("files") or []
        if not files:
            missing.append(m.group(1))
            continue
        parent = b["parent"].get("page_id") or b["parent"].get("block_id")
        after = b["id"]
        for k, fl in enumerate(files):
            fid = upload(h, pdir / fl)
            cap = [{"type": "text", "text": {"content": f"Figure {m.group(1)}: {f['caption'][:1800]}"}}] if k == 0 else []
            r = requests.patch(f"{API}/blocks/{parent}/children", headers={**h, "Content-Type": "application/json"},
                               json={"children": [{"type": "image", "image": {"type": "file_upload",
                                     "file_upload": {"id": fid}, "caption": cap}}], "after": after}, timeout=60)
            r.raise_for_status()
            after = r.json()["results"][0]["id"]
        requests.delete(f"{API}/blocks/{b['id']}", headers=h, timeout=60).raise_for_status()
        done.append(m.group(1))
    out({"uploaded": done, "no_file": missing})


if __name__ == "__main__":
    main()
