"""Escaped, redacted views. Original evidence is never modified."""

import hashlib
import html
import json
import re


SECRET_KEYS = {
    "authorization", "api_key", "apikey", "access_token", "refresh_token", "token",
    "password", "secret", "client_secret", "signature", "encrypted_content",
    "cookie", "set_cookie", "x_api_key",
}
PATTERNS = [
    (re.compile(r"\b(?:xox[baprs]-|gh[pousr]_|github_pat_|sk-ant-)[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r'''(?im)(\b(?:[A-Z_]*API_KEY|[A-Z_]*ACCESS_TOKEN|PASSWORD|AUTHORIZATION|X-API-KEY)\s*[:=]\s*)[^\r\n,;}]+'''), r"\1[REDACTED]"),
]


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower().replace("-", "_") in SECRET_KEYS else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)) and redact(parsed) != parsed:
                    value = json.dumps(redact(parsed), ensure_ascii=False, indent=2)
            except ValueError:
                pass
        for pattern, replacement in PATTERNS:
            value = pattern.sub(replacement, value)
    return value


def esc(value):
    return html.escape(str(redact(value)), quote=True)


def dump(value):
    return json.dumps(redact(value), ensure_ascii=False, indent=2)


def prose(value):
    return "".join("<p>" + esc(p).replace("\n", "<br>") + "</p>"
                   for p in str(value or "Not recorded").split("\n\n"))


def toggle(title, body, opened=False):
    return f'<details{" open" if opened else ""}><summary>{esc(title)}</summary>{body}</details>'


def fields(value):
    if isinstance(value, dict):
        return "".join(toggle(k, fields(v)) for k, v in value.items()) or "<p>{}</p>"
    if isinstance(value, list):
        return "".join(toggle(str(i + 1), fields(v)) for i, v in enumerate(value)) or "<p>[]</p>"
    return "<pre>" + esc(dump(value)) + "</pre>"


def source_path(entry, directory):
    from pathlib import Path
    p = Path(entry["path"]).expanduser()
    return (p if p.is_absolute() else directory / p).resolve()


def read_source(entry, directory, limit):
    path = source_path(entry, directory)
    if path.name.lower() in {"auth.json", "credentials.json", "config.toml"} or path.name.startswith(".env") or path.suffix.lower() in {".pem", ".key"}:
        raise ValueError("Credential-like files cannot be registered as artifacts.")
    if not path.is_file():
        raise ValueError("Registered artifact is not an existing file: " + entry["id"])
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Artifact exceeds max_artifact_bytes: " + entry["id"])
    return raw


def records(text):
    try:
        data = json.loads(text)
    except ValueError:
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"unparsed_line": line})
        return rows
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "steps"):
            if isinstance(data.get(key), list):
                return data[key]
    return [data]


def normalized(row):
    if not isinstance(row, dict):
        return {}
    if row.get("type") == "response_item":
        return row.get("payload", {})
    if isinstance(row.get("message"), dict):
        return dict(row["message"], role=row.get("role", row.get("type", row["message"].get("role"))))
    if "source" in row and "role" not in row:
        return dict(row, role=row["source"], content=row.get("message", row.get("content", "")))
    return row


def blocks(row):
    content = row.get("content", row.get("message", ""))
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def tool_status(result, claude=False):
    if result is None:
        return "unknown"
    if "is_error" in result:
        flag = result["is_error"]
        return "fail" if flag is True else "success" if flag is False else "unknown"
    if claude:
        return "success"
    output = result.get("output", {})
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            output = {}
    code = result.get("exit_code", output.get("exit_code") if isinstance(output, dict) else None)
    return ("success" if code == 0 else "fail") if type(code) is int else "unknown"


def tool_view(name, arguments, result, claude=False):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            pass
    if isinstance(arguments, dict):
        arguments = {k: arguments[k] for k in ("description", "command") if k in arguments} | {
            k: v for k, v in arguments.items() if k not in {"description", "command"}}
    output = result.get("content", result.get("output", result)) if result is not None else "No result recorded"
    body = toggle("Input", fields(arguments)) + toggle("Output", fields(output))
    return toggle(f"Tool · {name} · {tool_status(result, claude)}", body)


def trajectory(text):
    raw_rows = records(text)
    rows = [normalized(r) for r in raw_rows]
    results = {}
    for row in rows:
        for b in blocks(row):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                results[b["tool_use_id"]] = (b, True)
        if row.get("type") in {"function_call_output", "custom_tool_call_output"} and row.get("call_id"):
            results[row["call_id"]] = (row, False)
    conversation = []
    for row in rows:
        kind, role = row.get("type"), row.get("role")
        if kind in {"function_call", "custom_tool_call"}:
            result, claude = results.get(row.get("call_id"), (None, False))
            conversation.append(tool_view(row.get("name", "unknown"), row.get("arguments", row.get("input", "")), result, claude))
            continue
        if role not in {"user", "assistant", "agent", "system"} or role == "system":
            continue
        parts = []
        for b in blocks(row):
            bt = b.get("type")
            if bt in {"text", "input_text", "output_text"}:
                parts.append(toggle("Message", prose(b.get("text", ""))))
            elif bt == "thinking":
                parts.append(toggle("Thinking", prose(b.get("thinking") or "No thinking returned")))
            elif bt == "tool_use":
                result, claude = results.get(b.get("id"), (None, True))
                parts.append(tool_view(b.get("name", "unknown"), b.get("input", {}), result, claude))
            elif bt != "tool_result":
                parts.append(toggle("Block · " + str(bt or "unknown"), fields(b)))
        if not parts:
            continue
        title = "User" if role == "user" else "Assistant"
        if row.get("model"):
            title += " · " + str(row["model"])
        if row.get("effort"):
            title += " · " + str(row["effort"])
        usage = row.get("usage", {})
        if isinstance(usage, dict) and type(usage.get("output_tokens")) is int:
            title += " · " + str(usage["output_tokens"]) + " output tokens"
        conversation.append(toggle(title, "".join(parts), opened=True))
    return ("".join(conversation) or "<p>No supported conversation records. See the source records below.</p>") + toggle(
        "Source records · redacted", "".join(toggle(f"Record {i + 1}", fields(row)) for i, row in enumerate(raw_rows)))


def artifact_view(entry, directory, limit):
    raw = read_source(entry, directory, limit)
    text = raw.decode("utf-8", errors="replace")
    kind = entry.get("kind", "text")
    if kind == "json":
        value = json.loads(text)
        changed = redact(value) != value
        body = fields(redact(value))
    elif kind == "trajectory":
        value = records(text)
        changed = redact(value) != value
        body = trajectory(text)
    else:
        changed = redact(text) != text
        body = "<pre>" + "\n".join(f'<span id="L{i + 1}">{esc(line)}</span>' for i, line in enumerate(text.splitlines())) + "</pre>"
    replacement = "\ufffd" in text
    notice = (f'<aside>Source SHA-256: <code>{hashlib.sha256(raw).hexdigest()}</code><br>'
              f'{len(raw)} bytes · redacted: {str(changed).lower()} · UTF-8 replacement: {str(replacement).lower()}<br>'
              'The original file remains unchanged. This redacted view is not an archival copy.</aside>')
    return notice + body
