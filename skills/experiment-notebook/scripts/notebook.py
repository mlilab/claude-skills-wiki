#!/usr/bin/env python3
"""Private experiment reports and a local, read-only dashboard. Python 3.10+."""

import argparse
import copy
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from views import artifact_view, dump, esc, fields, prose, read_source, redact, toggle
from labels import SECTION_TITLES, text
from git_provenance import snapshot as repository_snapshot, connect as connect_repository, capture as capture_code
from lineage import diagram
import notifications


SKILL = Path(__file__).resolve().parents[1]
SECTIONS = SECTION_TITLES["en"]
STATES = {"planned", "running", "completed", "stopped", "failed", "unknown"}
TERMINAL = {"completed", "stopped", "failed"}
ID = re.compile(r"[0-9]{3,}-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def confined(root, path):
    path = Path(path)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Output path escapes the notebook directory.")
    return path


def write(root, relative, value):
    path = confined(root, root / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".notebook-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(root, relative, data):
    write(root, relative, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def config(root):
    data = load(root / "notebook.json")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported notebook schema.")
    if type(data.get("max_artifact_bytes")) is not int or data["max_artifact_bytes"] < 1:
        raise ValueError("max_artifact_bytes must be a positive integer.")
    data.setdefault("timezone", "UTC")
    data.setdefault("language", "en")
    if data["language"] not in SECTION_TITLES:
        raise ValueError("language must be en or ko.")
    data.setdefault("sections", SECTION_TITLES[data["language"]].copy())
    if not isinstance(data["sections"], dict) or not data["sections"] or any(
        not re.fullmatch(r"[a-z][a-z0-9_]*", key) or not isinstance(value, str) or not value.strip()
        for key, value in data["sections"].items()
    ):
        raise ValueError("sections must map section keys to nonempty titles.")
    if type(data.get("request_feedback", False)) is not bool:
        raise ValueError("request_feedback must be boolean.")
    if data.get("repository") is not None and not isinstance(data["repository"], str):
        raise ValueError("repository must be a local path or null.")
    ZoneInfo(data["timezone"])
    notifications.settings(data)
    return data


def reports(root):
    rows = []
    folder = confined(root, root / "experiments")
    for path in sorted(folder.glob("*/report.json")):
        confined(root, path)
        data = load(path)
        if not isinstance(data, dict):
            raise ValueError("An experiment record must be an object.")
        rows.append((path.parent, data))
    return sorted(rows, key=lambda item: (int(item[0].name.split("-", 1)[0]) if item[0].name.split("-", 1)[0].isdigit() else -1, item[0].name), reverse=True)


def blank_record(identifier, number, title, parent, cfg=None):
    cfg = cfg or {}
    return {
        "schema_version": 1, "id": identifier, "number": number, "title": title,
        "status": "planned", "research_outcome": None,
        "parent": parent, "parent_evidence": "", "reference_source": None, "restart_of": None,
        "started_at": None, "ended_at": None, "execution": [],
        "code_snapshots": [], "hypotheses": [], "comparisons": [], "follow_up": [],
        "sections": dict.fromkeys(cfg.get("sections", SECTIONS), ""),
        "scope": {}, "configuration": {}, "timing": {},
        "usage": {},
        "quality": {}, "metrics": [],
        "feedback": {"status": "pending" if cfg.get("request_feedback") else "not_applicable",
                     "verdict": None, "interpretation": None, "rules": []},
        "iterations": [], "artifacts": [], "watch": {},
    }


def reserve(root, slug, title, parent):
    cfg = config(root)
    if not SLUG.fullmatch(slug) or not title.strip():
        raise ValueError("Use a nonempty title and a lowercase slug with single hyphens.")
    lock = confined(root, root / ".reservation-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError("Another reservation is active. Check .reservation-lock before retrying.") from None
    try:
        rows = reports(root)
        if parent not in {"none", "unknown"} and parent not in {r["id"] for _, r in rows}:
            raise ValueError("Parent experiment does not exist.")
        folder = confined(root, root / "experiments")
        reserved = [int(d.name.split("-", 1)[0]) for d in folder.iterdir() if d.is_dir() and ID.fullmatch(d.name)] if folder.exists() else []
        number = max(reserved + [0]) + 1
        identifier = f"{number:03d}-{slug}"
        destination = confined(root, folder / identifier)
        destination.mkdir(parents=True, exist_ok=False)
        write_json(root, f"experiments/{identifier}/report.json", blank_record(identifier, number, title, parent, cfg))
        return {"id": identifier, "record": str(destination / "report.json"), "status": "planned"}
    finally:
        lock.rmdir()


def validate(root):
    cfg = config(root)
    rows = reports(root)
    errors, warnings = [], []
    index = {r.get("id"): r for _, r in rows if isinstance(r.get("id"), str)}
    for directory, record in rows:
        identifier = record.get("id")
        prefix = directory.name + ": "
        local = []
        if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier != directory.name:
            local.append("id must match the numbered experiment directory")
        if record.get("schema_version") != 1:
            local.append("unsupported record schema")
        number = record.get("number")
        if type(number) is not int or (isinstance(identifier, str) and str(number).zfill(3) != identifier.split("-", 1)[0]):
            local.append("number must match id")
        if not isinstance(record.get("title"), str) or not record["title"].strip():
            local.append("title is required")
        if record.get("status") not in STATES:
            local.append("unsupported status")
        for name in ("sections", "scope", "configuration", "timing", "usage", "quality", "feedback", "watch"):
            if not isinstance(record.get(name), dict):
                local.append(name + " must be an object")
        for name in ("execution", "metrics", "iterations", "artifacts"):
            if not isinstance(record.get(name), list):
                local.append(name + " must be a list")
        for name in ("code_snapshots", "hypotheses", "comparisons", "follow_up"):
            if not isinstance(record.get(name, []), list):
                local.append(name + " must be a list")
        if local:
            errors += [prefix + e for e in local]
            continue
        for key in dict.fromkeys([*cfg["sections"], *record["sections"]]):
            if not isinstance(record["sections"].get(key), str):
                errors.append(prefix + "section must be a string: " + key)
            elif not record["sections"][key].strip():
                warnings.append(prefix + "section unrecorded: " + key)
        for name in ("parent", "reference_source", "restart_of"):
            value = record.get(name)
            special = {"none", "unknown"} if name == "parent" else {None}
            if not isinstance(value, (str, type(None))) or value not in special and value not in index:
                errors.append(prefix + "unknown relationship target: " + name)
            if value == identifier:
                errors.append(prefix + "self relationship: " + name)
        if record.get("parent") not in {"none", "unknown"} and not record.get("parent_evidence"):
            warnings.append(prefix + "parent evidence unrecorded")
        parsed_times = {}
        for key in ("started_at", "ended_at"):
            value = record.get(key)
            if value is not None:
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if dt.utcoffset() is None:
                        raise ValueError()
                    parsed_times[key] = dt
                except (ValueError, TypeError, AttributeError):
                    errors.append(prefix + key + " must include an ISO timezone")
        if len(parsed_times) == 2 and parsed_times["ended_at"] < parsed_times["started_at"]:
            errors.append(prefix + "end precedes start")
        if record["status"] == "planned" and record.get("started_at"):
            errors.append(prefix + "planned experiment cannot have an actual start")
        if record["status"] != "planned" and not record.get("started_at"):
            warnings.append(prefix + "actual start time unrecorded")
        for entry in record["execution"]:
            if not isinstance(entry, dict):
                errors.append(prefix + "execution entries must be objects")
                continue
            if entry.get("commit") is not None and not re.fullmatch(r"[0-9a-f]{40}", str(entry["commit"])):
                errors.append(prefix + "execution commit must be a full 40-character hash or null")
            if entry.get("dirty") is not None and type(entry["dirty"]) is not bool:
                errors.append(prefix + "execution dirty must be boolean or null")
        for entry in record.get("code_snapshots", []):
            if not isinstance(entry, dict) or entry.get("stage") not in {"preparation", "execution", "reporting"}:
                errors.append(prefix + "code snapshot needs an explicit preparation/execution/reporting stage")
            elif not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("commit", ""))) or type(entry.get("dirty")) is not bool:
                errors.append(prefix + "code snapshot needs a full commit and boolean dirty state")
            elif entry["dirty"]:
                warnings.append(prefix + "dirty code snapshot: preserve its corresponding diff and untracked inputs for reproducibility")
        if cfg.get("repository") and record["status"] != "planned" and not any(entry.get("commit") for entry in record["execution"] if isinstance(entry, dict)):
            warnings.append(prefix + "linked repository has no recorded actual execution commit")
        for hypothesis in record.get("hypotheses", []):
            if not isinstance(hypothesis, dict) or not isinstance(hypothesis.get("statement"), str) or not isinstance(hypothesis.get("criteria"), str):
                errors.append(prefix + "hypothesis needs a statement and assessment criteria")
        for comparison in record.get("comparisons", []):
            if not isinstance(comparison, dict) or not isinstance(comparison.get("item"), str) or not isinstance(comparison.get("reason"), str):
                errors.append(prefix + "comparison needs an item and reason")
        for change in record.get("follow_up", []):
            if not isinstance(change, dict) or not isinstance(change.get("change"), str) or not isinstance(change.get("reason"), str) or change.get("status") not in {"needed", "implemented", "validated", "deferred"}:
                errors.append(prefix + "follow-up needs a change, reason, and explicit implementation status")
        feedback = record["feedback"]
        if feedback.get("status") not in {"pending", "received", "not_applicable"}:
            errors.append(prefix + "unsupported feedback status")
        if feedback.get("status") == "received" and not feedback.get("verdict"):
            errors.append(prefix + "received feedback needs a verdict")
        for key in ("verdict", "interpretation"):
            if feedback.get(key) is not None and not isinstance(feedback[key], str):
                errors.append(prefix + "feedback." + key + " must be a string or null")
        if not isinstance(feedback.get("rules"), list) or any(not isinstance(rule, str) for rule in feedback.get("rules", [])):
            errors.append(prefix + "feedback.rules must be a list of strings")
        if record["status"] in TERMINAL and feedback.get("status") == "pending":
            warnings.append(prefix + "user verdict pending; request feedback after saving facts")
        artifact_ids = set()
        for artifact in record["artifacts"]:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("id"), str) or not KEY.fullmatch(artifact["id"]):
                errors.append(prefix + "artifact needs a lowercase slug id")
                continue
            if artifact["id"] in artifact_ids:
                errors.append(prefix + "duplicate artifact id")
            artifact_ids.add(artifact["id"])
            if artifact.get("kind") not in {"text", "json", "trajectory"} or not isinstance(artifact.get("path"), str):
                errors.append(prefix + "artifact needs path and supported kind")
                continue
            try:
                raw = read_source(artifact, directory, cfg["max_artifact_bytes"])
                if artifact["kind"] == "json":
                    json.loads(raw)
            except (OSError, ValueError) as error:
                errors.append(prefix + str(error))
        attempts = set()
        for iteration in record["iterations"]:
            if not isinstance(iteration, dict):
                errors.append(prefix + "iteration entries must be objects")
                continue
            if not isinstance(iteration.get("group"), str) or type(iteration.get("iteration")) is not int or iteration.get("iteration", 0) < 1:
                errors.append(prefix + "iteration needs a group and a positive integer index")
                continue
            key = (iteration["group"], iteration["iteration"])
            if key in attempts:
                errors.append(prefix + "duplicate iteration within a group")
            attempts.add(key)
            if iteration.get("description") is not None and not isinstance(iteration["description"], str):
                errors.append(prefix + "iteration description must be a string or null")
            if not isinstance(iteration.get("result"), str):
                errors.append(prefix + "iteration result must be a string")
            for field in ("document", "evidence"):
                if iteration.get(field) is not None and (not isinstance(iteration[field], str) or iteration[field] not in artifact_ids):
                    errors.append(prefix + "iteration references unknown artifact: " + field)
        for metric in record["metrics"]:
            if not isinstance(metric, dict) or not isinstance(metric.get("name"), str) or metric.get("kind") not in {"measured", "estimated", "unknown", "not_applicable"}:
                errors.append(prefix + "metric needs name and measurement kind")
            elif metric.get("kind") in {"measured", "estimated"} and metric.get("value") is None:
                errors.append(prefix + "measured/estimated metric needs a value")
        watch = record["watch"]
        if watch.get("state_file") is not None and not isinstance(watch["state_file"], str):
            errors.append(prefix + "watch.state_file must be a string")
        if not isinstance(watch.get("state_map", {}), dict) or any(v not in STATES for v in watch.get("state_map", {}).values()):
            errors.append(prefix + "watch.state_map must map to supported statuses")
        if watch.get("pid") is not None and (type(watch["pid"]) is not int or watch["pid"] < 1):
            errors.append(prefix + "watch.pid must be a positive integer")
        if watch.get("pid_start_ticks") is not None and not re.fullmatch(r"[0-9]+", str(watch["pid_start_ticks"])):
            errors.append(prefix + "watch.pid_start_ticks must be numeric")
        selectors = watch.get("field_paths", {})
        if not isinstance(selectors, dict) or any(
            key not in {"state", "phase", "completed", "total", "last_activity_at"}
            or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value)
            for key, value in selectors.items()
        ):
            errors.append(prefix + "watch.field_paths must select supported observation fields by dotted keys")
    # Follow each parent chain without relying on chronological order.
    for identifier in index:
        seen, current = set(), identifier
        while isinstance(current, str) and current in index:
            if current in seen:
                errors.append(identifier + ": parent cycle")
                break
            seen.add(current)
            current = index[current].get("parent")
    numbers = [r.get("number") for _, r in rows if type(r.get("number")) is int]
    if len(set(numbers)) != len(numbers):
        errors.append("Experiment numbers must be unique.")
    return {"errors": errors, "warnings": warnings, "experiments": len(rows)}


def observe(directory, record, language="en"):
    state = record.get("status", "unknown")
    warning = ""
    watch = record.get("watch", {})
    data = {}
    def selected(key, default=None):
        paths = watch.get("field_paths", {})
        path = paths.get(key) if isinstance(paths, dict) else None
        value = data
        if isinstance(path, str) and path:
            for part in path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        return default
    if watch.get("state_file"):
        try:
            data = json.loads(read_source({"id": "state", "path": watch["state_file"]}, directory, 1024 * 1024))
            raw = selected("state", data.get("state", data.get("status")))
            state = watch.get("state_map", {}).get(raw, raw)
            if state not in STATES:
                state, warning = "unknown", text("unknown_state", language)
        except (OSError, ValueError, AttributeError, TypeError):
            state, warning = "unknown", text("unreadable_state", language)
    pid = watch.get("pid")
    if pid:
        expected = watch.get("pid_start_ticks")
        if expected is None:
            state, warning = "attention", text("missing_tick", language)
        else:
            try:
                stat = Path(f"/proc/{int(pid)}/stat").read_text()
                tail = stat.rsplit(")", 1)[1].split()
                alive = tail[19] == str(expected) and tail[0] not in {"Z", "X"}
            except (OSError, ValueError, IndexError):
                alive = False
            if alive and state in TERMINAL:
                state = "cleaning_up"
            elif not alive and state == "running":
                state, warning = "attention", text("missing_process", language)
    if not isinstance(data, dict):
        data = {}
    progress = data.get("progress", {})
    progress = progress if isinstance(progress, dict) else {}
    completed = selected("completed", progress.get("completed"))
    total = selected("total", progress.get("total"))
    completed = completed if type(completed) is int and completed >= 0 else None
    total = total if type(total) is int and total >= 0 else None
    phase = selected("phase", data.get("phase"))
    phase = phase if isinstance(phase, str) else None
    last_activity = selected("last_activity_at", data.get("last_activity_at"))
    elapsed = None
    try:
        start = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
        if record.get("ended_at"):
            end = datetime.fromisoformat(record["ended_at"].replace("Z", "+00:00"))
        elif state in {"running", "cleaning_up", "attention"}:
            end = datetime.now(timezone.utc)
        else:
            end = None
        if start.utcoffset() is not None and end is not None and end.utcoffset() is not None:
            elapsed = max(0, int((end - start).total_seconds()))
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    summary = [phase] if phase else []
    if completed is not None:
        summary.append(f'{text("progress", language)}: {completed}/{total if total is not None else "?"}')
    if elapsed is not None:
        summary.append(f'{text("elapsed", language)}: {elapsed}')
    if not watch.get("state_file") and not watch.get("pid"):
        summary.append(text("recorded_only", language))
    return {"id": record["id"], "recorded_status": record["status"], "observed_status": state,
            "label": text(state, language), "warning": warning, "phase": phase,
            "completed": completed, "total": total, "elapsed_seconds": elapsed,
            "last_activity_at": last_activity if isinstance(last_activity, str) else None,
            "summary": " · ".join(summary)}


def badge(record, observation=None, language="en"):
    status = (observation or {}).get("observed_status", record["status"])
    return f'<span data-status="{esc(record["id"])}" class="badge {esc(status)}">{esc(text(status, language))}</span>'


def page(title, body, asset_prefix="", nav="", generated=None, language="en"):
    return (f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="stylesheet" href="{asset_prefix}style.css">'
            f'<script src="{asset_prefix}app.js" defer></script></head><body><header>{nav}</header>'
            f'<h1>{esc(title)}</h1>{body}<footer>{esc(text("generated", language))}: {esc(generated or now())} · '
            f'{esc(text("footer", language))}</footer></body></html>')


def table(headers, rows):
    return ('<div class="scroll"><table><thead><tr>' + "".join(f"<th>{esc(h)}</th>" for h in headers)
            + '</tr></thead><tbody>' + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
            + "</tbody></table></div>")


def pretty_time(value, cfg):
    if not value:
        return text("unrecorded", cfg["language"])
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d %H:%M:%S %Z")


def relation_link(identifier, prefix="../", language="en"):
    if identifier in {None, "none", "unknown"}:
        return text("none" if identifier == "none" else "unrecorded", language)
    return f'<a href="{prefix}{esc(identifier)}/analysis.html">{esc(identifier)}</a>'


def lineage(rows, language="en"):
    index = {r["id"]: r for _, r in rows}
    children = {}
    for _, record in rows:
        children.setdefault(record.get("parent"), []).append(record["id"])
    def branch(identifier):
        record = index[identifier]
        kids = children.get(identifier, [])
        body = f'<a href="reports/{esc(identifier)}/analysis.html">{esc(identifier)} · {esc(record["title"])}</a> {badge(record, language=language)}'
        if kids:
            body += "<ul>" + "".join(branch(k) for k in sorted(kids, key=lambda k: int(k.split("-", 1)[0]))) + "</ul>"
        return "<li>" + body + "</li>"
    roots = [r["id"] for _, r in rows if r.get("parent") not in index]
    outline = '<div class="lineage"><ul>' + "".join(branch(i) for i in sorted(roots, key=lambda k: int(k.split("-", 1)[0]))) + "</ul></div>"
    return diagram(rows, language) + toggle(text("lineage_outline", language), outline)


def main_report(record, cfg):
    language = cfg["language"]
    tr = lambda key: text(key, language)
    content = (f'<aside>{badge(record, language=language)} · {esc(record["id"])} · {tr("outcome")}: '
               + esc(record.get("research_outcome") or tr("unrecorded")) + "<br>" + tr("started") + ": "
               + esc(pretty_time(record.get("started_at"), cfg)) + " · " + tr("ended") + ": "
               + esc(pretty_time(record.get("ended_at"), cfg)) + "</aside><main>")
    if cfg.get("repository") and record["status"] != "planned" and not any(v.get("commit") for v in record["execution"]):
        content += '<aside>' + esc(tr("missing_execution_commit")) + '</aside>'
    versions = list(record.get("code_snapshots", []))
    for version in record["execution"]:
        if version.get("commit") and version not in versions:
            versions.append(dict(version, stage="execution"))
    if versions:
        content += '<h2>' + tr("git_provenance") + '</h2>' + table(
            [tr(k) for k in ("stage", "phase", "captured", "commit", "dirty")],
            [[esc(tr(v.get("stage", "execution"))), esc(v.get("phase") or tr("unrecorded")),
              esc(v.get("captured_at") or tr("unrecorded")), '<code>' + esc(v.get("commit") or tr("unrecorded")) + '</code>',
              esc(v.get("dirty") if v.get("dirty") is not None else tr("unrecorded"))] for v in versions])
    titles = dict(cfg["sections"])
    titles.update({key: key for key in record["sections"] if key not in titles})
    for number, (key, heading) in enumerate(titles.items(), 1):
        content += f'<section><h2>{number}. {esc(heading)}</h2>' + prose(record["sections"].get(key) or tr("unrecorded"))
        if key == "previous":
            content += '<p>' + tr("parent") + ': ' + relation_link(record.get("parent"), language=language) + '<br>' + tr("reference") + ': ' + relation_link(record.get("reference_source"), language=language) + '<br>' + tr("restart") + ': ' + relation_link(record.get("restart_of"), language=language) + '</p>'
        if key == "changes" and record.get("comparisons"):
            content += table([tr(k) for k in ("metric", "before", "after", "reason")],
                             [[esc(c["item"]), esc(c.get("before") if c.get("before") is not None else tr("unrecorded")),
                               esc(c.get("after") if c.get("after") is not None else tr("unrecorded")), esc(c["reason"])]
                              for c in record["comparisons"]])
        if key == "purpose" and record.get("hypotheses"):
            content += table([tr("hypothesis"), tr("criteria")],
                             [[esc(h["statement"]), esc(h["criteria"])] for h in record["hypotheses"]])
        if key == "results":
            if record["timing"]:
                content += '<p>' + tr("elapsed") + ': ' + esc(record["timing"].get("elapsed_seconds") if record["timing"].get("elapsed_seconds") is not None else tr("unrecorded")) + ' · ' + tr("window") + ': ' + esc(record["timing"].get("window") or tr("unrecorded")) + '</p>'
            if record["metrics"]:
                content += table([tr(k) for k in ("metric", "value", "kind", "evidence")], [[esc(m["name"]), esc(m.get("value") if m.get("value") is not None else tr("unrecorded")), esc(m["kind"]), esc(m.get("evidence", tr("unrecorded")))] for m in record["metrics"]])
            usage = record["usage"]
            if usage:
                content += table([tr("resource"), tr("value")], [[esc(k), esc(v if v is not None else tr("unrecorded"))] for k, v in usage.items()])
            groups = {}
            for iteration in record["iterations"]:
                groups.setdefault(iteration["group"], []).append(iteration)
            for group, iterations in groups.items():
                content += f'<h3>{esc(group)}</h3>'
                cells = []
                for row in sorted(iterations, key=lambda row: row["iteration"]):
                    description = row.get("description") or tr("unrecorded")
                    preview = esc(description[:180]) + ("…" if len(description) > 180 else "")
                    if row.get("document"):
                        preview += f' <a href="artifact-{esc(row["document"])}.html">{tr("full")}</a>'
                    elif len(description) > 180:
                        preview += toggle(tr("full"), prose(description))
                    link = f'<a href="artifact-{esc(row["evidence"])}.html">{tr("view")}</a>' if row.get("evidence") else tr("unrecorded")
                    cells.append([str(row["iteration"]), preview, link, esc(row.get("result", tr("unrecorded")))])
                content += table([tr(k) for k in ("iteration", "description", "evidence", "result")], cells)
        if key == "analysis" and record["feedback"]["status"] != "not_applicable":
            feedback = record["feedback"]
            content += '<h3>' + tr("feedback") + '</h3>'
            if feedback["status"] == "pending":
                content += '<p>' + tr("pending") + '</p>'
            for field in ("verdict", "interpretation"):
                if feedback.get(field):
                    content += '<p><strong>' + tr(field) + '</strong>: ' + esc(feedback[field]) + '</p>'
            if feedback.get("rules"):
                content += '<p><strong>' + tr("rules") + '</strong></p>' + prose("\n".join(feedback["rules"]))
        if key == "post_changes" and record.get("follow_up"):
            content += table([tr(k) for k in ("change", "reason", "status", "evidence")],
                             [[esc(c["change"]), esc(c["reason"]), esc(tr(c["status"])),
                               esc(c.get("evidence") or tr("unrecorded"))] for c in record["follow_up"]])
        content += "</section>"
    return content + '<p><a href="details.html">' + tr("details") + '</a></p></main>'


def build(root):
    result = validate(root)
    if result["errors"]:
        return result
    cfg, rows = config(root), reports(root)
    language = cfg["language"]
    tr = lambda key: text(key, language)
    generated = now()
    manifest = []
    def output(relative, text):
        write(root, "site/" + relative, text)
        manifest.append(relative)
    for name in ("style.css", "app.js"):
        output(name, (SKILL / "assets" / name).read_text(encoding="utf-8"))
    cards = []
    for directory, original in rows:
        record = redact(copy.deepcopy(original))
        identifier = record["id"]
        nav = '<a href="../../index.html">' + tr("dashboard") + '</a><a href="analysis.html">' + tr("report") + '</a>'
        output(f"reports/{identifier}/analysis.html", page(record["title"], main_report(record, cfg), "../../", nav, generated, language))
        details = "<main>" + fields({k: v for k, v in record.items() if k not in {"sections", "artifacts"}})
        details += '<h2>' + tr("artifacts") + '</h2><ul>'
        for artifact in original["artifacts"]:
            link = "artifact-" + artifact["id"] + ".html"
            details += f'<li><a href="{esc(link)}">{esc(artifact.get("label", artifact["id"]))}</a></li>'
            body = artifact_view(artifact, directory, cfg["max_artifact_bytes"])
            output(f"reports/{identifier}/{link}", page(artifact.get("label", artifact["id"]), "<main>" + body + "</main>", "../../", nav, generated, language))
        details += "</ul></main>"
        output(f"reports/{identifier}/details.html", page(record["title"] + " · " + tr("detail_suffix"), details, "../../", nav, generated, language))
        observation = observe(directory, original, language)
        summary = record["sections"].get("purpose") or next((v for v in record["sections"].values() if v.strip()), tr("unrecorded"))
        cards.append(f'<article class="card" data-search="{esc((identifier + " " + record["title"] + " " + " ".join(record["sections"].values())).lower())}">'
                     + badge(record, observation, language) + f'<span class="muted">{esc(identifier)}</span><h2><a href="reports/{esc(identifier)}/analysis.html">{esc(record["title"])}</a></h2>'
                     + '<p>' + esc(summary[:240]) + '</p><div class="muted">' + tr("started") + ': '
                     + esc(pretty_time(record.get("started_at"), cfg)) + '</div><div class="muted" data-observation="'
                     + esc(identifier) + '">' + esc(observation["summary"]) + '</div></article>')
    git_panel = ""
    if cfg.get("repository"):
        try:
            git_panel = '<aside><strong>' + tr("repository_now") + '</strong>' + fields(repository_snapshot(cfg["repository"])) + '</aside>'
        except (OSError, ValueError) as error:
            result["warnings"].append(str(error))
    slack_enabled = notifications.settings(cfg)["enabled"]
    notification_panel = '<aside><strong>Slack</strong><p id="notification-status">' + esc(tr("slack_enabled") if slack_enabled else tr("slack_disabled")) + '</p></aside>'
    body = notification_panel + '<p class="muted">' + tr("order_note") + '</p><input id="search" aria-label="' + tr("search") + '" placeholder="' + tr("search") + '"><div class="grid">' + "".join(cards) + '</div><main><h2>' + tr("lineage") + '</h2>' + lineage([(d, redact(r)) for d, r in rows], language) + '</main><p id="observed-at" class="muted"></p>'
    output("index.html", page(cfg.get("title", "Experiment notebook"), git_panel + body, generated=generated, language=language))
    write_json(root, ".site-manifest.json", {"generated_at": generated, "files": manifest})
    return dict(result, site=str(root / "site" / "index.html"), generated_at=generated)


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, root, **kwargs):
        self.root = root
        super().__init__(*args, **kwargs)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        route = unquote(urlsplit(self.path).path)
        try:
            if route == "/api/status":
                language = config(self.root)["language"]
                data = {"observed_at": now(), "observed_label": text("observed", language), "experiments": [observe(d, r, language) for d, r in reports(self.root)]}
                content, mime = dump(data).encode(), "application/json; charset=utf-8"
            elif route == "/api/notifications":
                cfg = config(self.root)
                enabled = notifications.settings(cfg)["enabled"]
                summary = notifications.status(self.root)
                data = {"enabled": enabled, "label": text("slack_enabled" if enabled else "slack_disabled", cfg["language"]),
                        "counts": summary["counts"], "last_error": summary["last_error"]}
                content, mime = dump(data).encode(), "application/json; charset=utf-8"
            else:
                relative = "index.html" if route == "/" else route.lstrip("/")
                manifest = load(self.root / ".site-manifest.json")
                if relative not in manifest["files"] or ".." in Path(relative).parts:
                    self.send_error(404)
                    return
                site = (self.root / "site").resolve()
                confined(self.root, site)
                path = site / relative
                if path.is_symlink() or not path.resolve().is_relative_to(site):
                    self.send_error(404)
                    return
                suffix = path.suffix
                mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}.get(suffix)
                if mime is None:
                    self.send_error(404)
                    return
                content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            if not head:
                self.wfile.write(content)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            self.send_error(503, "Notebook cannot be read. Check the local records and build.")

    def log_message(self, *_):
        pass  # Do not persist request paths or query parameters.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "new", "connect-git", "git-status", "capture-git", "configure-slack",
                    "monitor", "notification-status", "resolve-notification", "check", "build", "serve"):
        child = sub.add_parser(command)
        child.add_argument("--root", type=Path, required=True)
        if command == "init":
            child.add_argument("--title", default="Experiment notebook")
            child.add_argument("--timezone", default="UTC")
            child.add_argument("--language", choices=("en", "ko"), default="en")
        if command == "new":
            child.add_argument("--slug", required=True)
            child.add_argument("--title", required=True)
            child.add_argument("--parent", default="unknown")
        if command == "connect-git":
            child.add_argument("--repository", type=Path, required=True)
        if command == "capture-git":
            child.add_argument("--experiment", required=True)
            child.add_argument("--stage", choices=("preparation", "execution", "reporting"), default="preparation")
            child.add_argument("--phase", required=True)
        if command == "configure-slack":
            targets = child.add_mutually_exclusive_group(required=True)
            targets.add_argument("--channel")
            targets.add_argument("--user")
            secrets = child.add_mutually_exclusive_group()
            secrets.add_argument("--token-env", default="SLACK_BOT_TOKEN")
            secrets.add_argument("--token-file", type=Path)
            child.add_argument("--progress-interval", type=int, default=1800)
        if command == "monitor":
            child.add_argument("--once", action="store_true")
            child.add_argument("--dry-run", action="store_true")
            child.add_argument("--interval", type=float, default=20)
        if command == "resolve-notification":
            child.add_argument("--event", required=True)
            child.add_argument("--outcome", choices=("sent", "not-sent"), required=True)
            child.add_argument("--note", required=True)
        if command == "serve":
            child.add_argument("--port", type=int, default=8782)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    try:
        if args.command == "init":
            if (root / "notebook.json").exists():
                raise ValueError("Notebook already exists. Reuse its guide and records.")
            ZoneInfo(args.timezone)
            root.mkdir(parents=True, exist_ok=True)
            write_json(root, "notebook.json", {"schema_version": 1, "title": args.title, "timezone": args.timezone,
                       "language": args.language, "sections": SECTION_TITLES[args.language].copy(),
                       "request_feedback": False, "max_artifact_bytes": 16 * 1024 * 1024})
            if not (root / "GUIDE.md").exists():
                write(root, "GUIDE.md", (SKILL / "references" / "report-guide.md").read_text(encoding="utf-8"))
            result = {"root": str(root), "guide": str(root / "GUIDE.md")}
        elif args.command == "new":
            result = reserve(root, args.slug, args.title, args.parent)
        elif args.command in {"connect-git", "git-status", "capture-git"}:
            cfg = config(root)
            if args.command == "connect-git":
                result = connect_repository(root, args.repository, cfg, write_json)
            else:
                if not cfg.get("repository"):
                    raise ValueError("Use connect-git to associate a local source repository first.")
                if args.command == "git-status":
                    result = {"current_checkout": repository_snapshot(cfg["repository"])}
                else:
                    matches = [(d, r) for d, r in reports(root) if r["id"] == args.experiment]
                    if not matches:
                        raise ValueError("Experiment does not exist.")
                    directory, record = matches[0]
                    if args.stage == "execution" and record["status"] != "running":
                        raise ValueError("Execution capture requires a running record. Use historical evidence for past execution commits.")
                    result = capture_code(root, cfg["repository"], directory, record, args.stage, args.phase, write_json)
        elif args.command == "configure-slack":
            cfg = config(root)
            slack = {"enabled": True, "token_env": args.token_env, "progress_interval_seconds": args.progress_interval}
            slack["channel" if args.channel else "user"] = args.channel or args.user
            if args.token_file:
                slack["token_file"] = str(args.token_file.expanduser().resolve())
            cfg.setdefault("notifications", {})["slack"] = slack
            notifications.settings(cfg)
            write_json(root, "notebook.json", cfg)
            result = {"enabled": True, "target_kind": "channel" if args.channel else "user",
                      "note": "Configuration saved. Start monitor to send lifecycle notifications. No Slack call was made."}
        elif args.command == "monitor":
            result = notifications.run_monitor(root, config, reports, observe, args.once, args.dry_run, args.interval)
        elif args.command == "notification-status":
            config(root)
            result = notifications.status(root)
        elif args.command == "resolve-notification":
            config(root)
            result = notifications.resolve(root, args.event, args.outcome, args.note)
        elif args.command == "check":
            result = validate(root)
        elif args.command == "build":
            result = build(root)
        else:
            config(root)
            if not (root / ".site-manifest.json").is_file():
                raise ValueError("Build the notebook before starting the server.")
            server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, root=root))
            print(f"http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
            return 0
        print(json.dumps(redact(result), ensure_ascii=False, indent=2))
        return 1 if result.get("errors") or result.get("error") else 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(json.dumps({"error": redact(str(error))}, ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        return 0
    except sqlite3.Error:
        print(json.dumps({"error": "Notification ledger is unavailable."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
