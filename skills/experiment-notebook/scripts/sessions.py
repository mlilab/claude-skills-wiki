#!/usr/bin/env python3
"""Find project-bound Codex/Claude sessions and read selected human-facing messages."""

import argparse
from collections import deque
import json
from pathlib import Path
import re

from views import redact


def belongs(cwd, project):
    if not isinstance(cwd, str) or not cwd.startswith("/"):
        return False
    return Path(cwd).resolve().is_relative_to(project.resolve())


def metadata(path, project, provider=None):
    """Read startup metadata only; never scan an unrelated transcript for a matching cwd."""
    if provider is None:
        with path.open(encoding="utf-8") as stream:
            first = json.loads(stream.readline())
        provider = "codex" if first.get("type") == "session_meta" else "claude"
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line_number > (1 if provider == "codex" else 32):
                break
            row = json.loads(line)
            body = row.get("payload", {}) if provider == "codex" else row
            if provider == "codex" and row.get("type") != "session_meta":
                return None
            if "cwd" in body:
                if not belongs(body["cwd"], project):
                    return None
                return {"provider": provider, "path": str(path), "cwd": body["cwd"],
                        "id": body.get("id", body.get("sessionId")),
                        "timestamp": body.get("timestamp", row.get("timestamp")),
                        "bytes": path.stat().st_size}
    return None


def candidates(project, codex_root, claude_root):
    for path in sorted(codex_root.rglob("*.jsonl")):
        yield path, "codex"
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))
    if claude_root.is_dir():
        for directory in sorted(claude_root.iterdir()):
            if directory.is_dir() and (directory.name == encoded or directory.name.startswith(encoded + "-")):
                for path in sorted(directory.glob("*.jsonl")):
                    yield path, "claude"


def messages(path, provider, contains="", max_chars=1800, limit=50):
    selected, total = deque(maxlen=limit), 0
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            if provider == "codex":
                if row.get("type") != "response_item":
                    continue
                body = row.get("payload", {})
            else:
                body = row.get("message", {})
                if not isinstance(body, dict):
                    continue
                body = dict(body, role=body.get("role", row.get("type")))
            role = body.get("role")
            if role not in {"user", "assistant"} or body.get("phase") == "analysis" or body.get("channel") == "analysis":
                continue
            content = body.get("content", [])
            text = content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") in {"text", "input_text", "output_text"})
            if not text.strip() or contains.casefold() not in text.casefold():
                continue
            total += 1
            safe = redact(text)
            selected.append({"line": number, "timestamp": row.get("timestamp"), "role": role,
                             "text": safe[:max_chars], "clipped": len(safe) > max_chars})
    return {"matched": total, "shown": len(selected), "messages": list(selected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "read"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude/projects")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--contains", default="")
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    try:
        if args.max_chars < 1 or args.limit < 1:
            raise ValueError("max-chars and limit must be positive.")
        if not project.is_dir():
            raise ValueError("Project directory does not exist.")
        if args.command == "list":
            found, unreadable = [], 0
            for path, provider in candidates(project, args.codex_root.expanduser(), args.claude_root.expanduser()):
                try:
                    meta = metadata(path, project, provider)
                    if meta:
                        found.append(meta)
                except (OSError, ValueError, TypeError, AttributeError):
                    unreadable += 1
            data = {"sessions": found, "unreadable_metadata": unreadable}
        else:
            if args.session is None:
                raise ValueError("read requires --session.")
            path = args.session.expanduser().resolve()
            meta = metadata(path, project)
            if not meta:
                raise ValueError("Session startup cwd does not match the selected project.")
            data = {"session": meta, **messages(path, meta["provider"], args.contains, args.max_chars, args.limit)}
        print(json.dumps(redact(data), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"error": redact(str(error))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
