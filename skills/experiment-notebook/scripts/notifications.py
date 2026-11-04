"""Opt-in Slack lifecycle notifications with a durable outbox. No experiment writes."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from views import redact


EVENTS = {"started", "attached", "resumed", "progress", "completed", "stopped", "failed", "attention"}
TERMINAL = {"completed", "stopped", "failed"}
ACTIVE = {"running", "cleaning_up"}
DATABASE = ".notifications.sqlite3"
LABELS = {
    "started": ("Started", "시작"), "attached": ("In progress · monitoring attached", "진행 중 · 감시 시작"),
    "resumed": ("Resumed", "재개"), "progress": ("Progress", "진행"),
    "completed": ("Completed", "완료"), "stopped": ("Stopped", "중단"),
    "failed": ("Failed", "실패"), "attention": ("Needs attention", "활동 확인 필요"),
}


def settings(config):
    container = config.get("notifications", {})
    if not isinstance(container, dict) or not isinstance(container.get("slack", {}), dict):
        raise ValueError("notifications.slack must be an object.")
    cfg = dict(container.get("slack", {}))
    if any(key in cfg for key in ("token", "bot_token", "webhook_url")):
        raise ValueError("Use token_env or token_file references, not literal Slack credentials.")
    cfg.setdefault("enabled", False)
    cfg.setdefault("token_env", "SLACK_BOT_TOKEN")
    cfg.setdefault("progress_interval_seconds", 1800)
    cfg.setdefault("events", sorted(EVENTS))
    cfg.setdefault("max_attempts", 3)
    if type(cfg["enabled"]) is not bool:
        raise ValueError("Slack enabled must be boolean.")
    if type(cfg["progress_interval_seconds"]) is not int or cfg["progress_interval_seconds"] < 0:
        raise ValueError("Slack progress interval must be a nonnegative integer.")
    if type(cfg["max_attempts"]) is not int or not 1 <= cfg["max_attempts"] <= 10:
        raise ValueError("Slack max_attempts must be between one and ten.")
    if not isinstance(cfg["events"], list) or any(not isinstance(e, str) or e not in EVENTS for e in cfg["events"]):
        raise ValueError("Unsupported Slack event selection.")
    if cfg.get("token_file") is not None and not isinstance(cfg["token_file"], str):
        raise ValueError("Slack token_file must be an existing private file path.")
    if not isinstance(cfg["token_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cfg["token_env"]):
        raise ValueError("Slack token_env must name an environment variable.")
    if cfg["enabled"]:
        channel, user = cfg.get("channel"), cfg.get("user")
        if bool(channel) == bool(user):
            raise ValueError("Select exactly one Slack channel or DM user.")
        if channel and (not isinstance(channel, str) or not re.fullmatch(r"[CDG][A-Z0-9]+", channel)):
            raise ValueError("Use a Slack conversation ID for channel.")
        if user and (not isinstance(user, str) or not re.fullmatch(r"[UW][A-Z0-9]+", user)):
            raise ValueError("Use a Slack member ID for user.")
    return cfg


def destination(cfg):
    return "channel:" + cfg["channel"] if cfg.get("channel") else "user:" + cfg.get("user", "")


def token(cfg):
    if cfg.get("token_file"):
        path = Path(cfg["token_file"]).expanduser()
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError("Slack token file must have private permissions (0600).")
        with path.open() as stream:
            value = stream.read(4097).strip()
    else:
        value = os.environ.get(cfg["token_env"], "").strip()
    if len(value) > 4096 or not re.fullmatch(r"xoxb-[A-Za-z0-9_-]+", value):
        raise ValueError("Slack bot token is unavailable or invalid in the configured secret reference.")
    return value


class DeliveryError(Exception):
    def __init__(self, outcome, code, retry_after=30):
        self.outcome = outcome
        self.code = code if re.fullmatch(r"[a-z0-9_]{1,80}", str(code)) else "unrecognized_error"
        self.retry_after = retry_after
        super().__init__(self.code)


class SlackClient:
    def __init__(self, cfg):
        self.secret = token(cfg)

    def call(self, method, payload):
        if method not in {"conversations.open", "chat.postMessage"}:
            raise ValueError("Unsupported Slack method.")
        request = urllib.request.Request(
            "https://slack.com/api/" + method,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + self.secret, "Content-Type": "application/json; charset=utf-8"},
        )
        ambiguous = "uncertain" if method == "chat.postMessage" else "retry"
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read(65537)
                retry = response.headers.get("Retry-After", "30")
        except urllib.error.HTTPError as error:
            try:
                seconds = max(1, int(error.headers.get("Retry-After", "30")))
            except (TypeError, ValueError):
                seconds = 30
            status = error.code
            error.close()
            if status == 429:
                raise DeliveryError("retry", "rate_limited", seconds) from None
            raise DeliveryError("failed" if status in {400, 401, 403, 404, 410, 422} else ambiguous,
                                "http_" + str(status)) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise DeliveryError(ambiguous, "transport_error") from None
        try:
            data = json.loads(body) if len(body) <= 65536 else None
        except (ValueError, UnicodeError):
            data = None
        if not isinstance(data, dict) or type(data.get("ok")) is not bool:
            raise DeliveryError(ambiguous, "malformed_response")
        if data["ok"]:
            return data
        code = data.get("error", "unknown_api_error")
        if code in {"rate_limited", "ratelimited"}:
            try:
                seconds = max(1, int(retry))
            except (TypeError, ValueError):
                seconds = 30
            raise DeliveryError("retry", code, seconds)
        rejected = {"invalid_auth", "not_authed", "token_expired", "token_revoked", "account_inactive",
                    "missing_scope", "channel_not_found", "not_in_channel", "is_archived", "no_permission",
                    "restricted_action", "not_allowed_token_type", "invalid_arguments"}
        outcome = "failed" if code in rejected else ambiguous
        raise DeliveryError(outcome, code)

    def send(self, cfg, message):
        channel = cfg.get("channel")
        if not channel:
            response = self.call("conversations.open", {"users": cfg["user"]})
            conversation = response.get("channel")
            channel = conversation.get("id") if isinstance(conversation, dict) else None
            if not isinstance(channel, str) or not re.fullmatch(r"D[A-Z0-9]+", channel):
                raise DeliveryError("retry", "invalid_dm_response")
        response = self.call("chat.postMessage", {
            "channel": channel, "text": message, "mrkdwn": False, "parse": "none",
            "unfurl_links": False, "unfurl_media": False,
        })
        if not isinstance(response.get("ts"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+", response["ts"]):
            raise DeliveryError("uncertain", "missing_message_receipt")
        return response["ts"]


def private_path(root, name):
    path = root / name
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("Notification state must remain inside the notebook.")
    return path


def private_database(root, name):
    path = private_path(root, name)
    if not path.exists():
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    return path


@contextmanager
def monitor_lock(root):
    connection = sqlite3.connect(private_database(root, ".notifications-lock.sqlite3"), timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError:
        connection.close()
        raise ValueError("A notification monitor is already running for this notebook.") from None
    try:
        yield
    finally:
        connection.rollback()
        connection.close()


def plan(previous, record, observation, cfg, timestamp):
    state = observation["observed_status"]
    tracker = dict(previous or {"generation": 0, "sequence": 0, "last_notice_at": timestamp,
                                "notice_signature": None, "marker": record.get("started_at")})
    signature = redact([state, observation.get("phase"), observation.get("completed"), observation.get("total")])
    old_state = tracker.get("state")
    marker = record.get("started_at")
    new_execution = bool(previous and marker and tracker.get("marker") and marker != tracker["marker"])
    if new_execution or old_state in TERMINAL and state in ACTIVE:
        tracker["generation"] += 1
    kind = None
    if previous is None:
        kind = "attached" if state in ACTIVE else "attention" if state == "attention" else None
    elif new_execution and state in ACTIVE:
        kind = "started"
    elif state in ACTIVE and old_state not in ACTIVE:
        kind = "resumed" if old_state in TERMINAL or old_state == "attention" else "started"
    elif state in TERMINAL and (state != old_state or new_execution):
        kind = state
    elif state == "attention" and old_state != state:
        kind = "attention"
    elif state in ACTIVE and cfg["progress_interval_seconds"] > 0 and signature != tracker["notice_signature"] and timestamp - tracker["last_notice_at"] >= cfg["progress_interval_seconds"]:
        kind = "progress"
    if kind not in cfg["events"]:
        kind = None
    if kind:
        tracker["sequence"] += 1
        tracker["last_notice_at"] = timestamp
        tracker["notice_signature"] = signature
    tracker["state"] = state
    if marker:
        tracker["marker"] = marker
    return tracker, kind


def format_message(record, observation, kind, timestamp, config):
    language = config.get("language", "en")
    label = LABELS[kind][language == "ko"]
    clean = lambda value, limit: str(redact(value)).replace("\n", " ").replace("<", "‹").replace(">", "›")[:limit]
    parts = ["[" + clean(record["id"], 120) + "] " + label, clean(record["title"], 160)]
    if observation.get("completed") is not None:
        parts.append(str(observation["completed"]) + "/" + str(observation.get("total") if observation.get("total") is not None else "?"))
    moment = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo(config.get("timezone", "UTC")))
    parts.append(moment.strftime("%Y-%m-%d %H:%M:%S %Z"))
    return " | ".join(parts)


class Ledger:
    def __init__(self, root):
        self.db = sqlite3.connect(private_database(root, DATABASE))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS trackers (experiment TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, experiment TEXT, generation INTEGER, kind TEXT, message TEXT,
                destination TEXT, created_at REAL, status TEXT, attempts INTEGER DEFAULT 0,
                attempt_limit INTEGER, next_at REAL, receipt TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS attempts (event TEXT, time REAL, outcome TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS resolutions (event TEXT, time REAL, outcome TEXT, note TEXT);
        """)
        # The caller holds the monitor lock. An in-flight row is from a terminated predecessor.
        with self.db:
            self.db.execute("UPDATE events SET status='uncertain', error='interrupted_delivery' WHERE status='sending'")
            self.db.execute("UPDATE attempts SET outcome='uncertain',error='interrupted_delivery' WHERE outcome='sending'")

    def close(self):
        self.db.close()

    def ingest(self, records, config, timestamp):
        cfg = settings(config)
        queued = 0
        for record, observation in records:
            row = self.db.execute("SELECT data FROM trackers WHERE experiment=?", (record["id"],)).fetchone()
            tracker, kind = plan(json.loads(row[0]) if row else None, record, observation, cfg, timestamp)
            with self.db:
                if kind:
                    key = f'{record["id"]}/{tracker["generation"]}/{tracker["sequence"]}/{destination(cfg)}'
                    identifier = hashlib.sha256(key.encode()).hexdigest()[:24]
                    if kind == "progress" or kind in TERMINAL or kind == "attention":
                        self.db.execute("UPDATE events SET status='superseded' WHERE experiment=? AND generation=? AND kind='progress' AND status='pending'", (record["id"], tracker["generation"]))
                    self.db.execute("INSERT OR IGNORE INTO events (id,experiment,generation,kind,message,destination,created_at,status,attempt_limit,next_at) VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                                    (identifier, record["id"], tracker["generation"], kind, format_message(record, observation, kind, timestamp, config), destination(cfg), timestamp, cfg["max_attempts"], timestamp))
                    queued += 1
                self.db.execute("INSERT OR REPLACE INTO trackers VALUES (?,?)", (record["id"], json.dumps(tracker)))
        return queued

    def deliver_one(self, cfg, timestamp, client_factory=SlackClient):
        cooldown = self.db.execute("SELECT value FROM meta WHERE key='next_post_at'").fetchone()
        if cooldown and float(cooldown[0]) > timestamp:
            return {"delivery": "waiting"}
        row = self.db.execute("""SELECT e.* FROM events e WHERE e.status='pending' AND e.next_at<=?
            AND NOT EXISTS (SELECT 1 FROM events earlier WHERE earlier.experiment=e.experiment
                AND earlier.status IN ('pending','sending') AND earlier.rowid<e.rowid)
            ORDER BY e.created_at,e.rowid LIMIT 1""", (timestamp,)).fetchone()
        if not row:
            return {"delivery": "idle"}
        if row["destination"] != destination(cfg):
            with self.db:
                self.db.execute("UPDATE events SET status='failed',error='destination_changed' WHERE id=?", (row["id"],))
            return {"delivery": "failed", "event": row["id"], "error": "destination_changed"}
        try:
            client = client_factory(cfg)
        except (OSError, ValueError):
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('last_error','token_unavailable')")
            return {"delivery": "blocked", "error": "token_unavailable"}
        with self.db:
            self.db.execute("UPDATE events SET status='sending',attempts=attempts+1 WHERE id=?", (row["id"],))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('next_post_at',?)", (str(timestamp + 1.1),))
            attempt_id = self.db.execute("INSERT INTO attempts VALUES (?,?,'sending',NULL)", (row["id"], timestamp)).lastrowid
        outcome, error, receipt, next_at = "sent", None, None, timestamp
        try:
            receipt = client.send(cfg, row["message"])
        except DeliveryError as failure:
            error = failure.code
            outcome = failure.outcome
            if outcome == "retry":
                outcome = "pending" if row["attempts"] + 1 < row["attempt_limit"] else "failed"
                next_at = timestamp + max(1, failure.retry_after)
                # A method-wide rate limit also postpones other queued posts in this notebook.
                if failure.code in {"rate_limited", "ratelimited"}:
                    with self.db:
                        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('next_post_at',?)", (str(next_at),))
        except Exception:
            # Do not print an exception that could include credentials or response bodies.
            outcome, error = "uncertain", "unexpected_delivery_error"
        with self.db:
            self.db.execute("UPDATE events SET status=?,next_at=?,receipt=?,error=? WHERE id=?", (outcome, next_at, receipt, error, row["id"]))
            self.db.execute("UPDATE attempts SET outcome=?,error=? WHERE rowid=?", (outcome, error, attempt_id))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('last_error',?)", (error or "",))
        return {"delivery": outcome, "event": row["id"], "error": error}


def status(root):
    path = private_path(root, DATABASE)
    if not path.exists():
        return {"counts": {}, "recent": [], "last_error": None}
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = dict(connection.execute("SELECT status,count(*) FROM events GROUP BY status").fetchall())
        recent = [dict(row) for row in connection.execute("SELECT id,experiment,kind,status,attempts,error FROM events ORDER BY created_at DESC,rowid DESC LIMIT 20")]
        error = connection.execute("SELECT value FROM meta WHERE key='last_error'").fetchone()
        return {"counts": counts, "recent": recent, "last_error": error[0] if error and error[0] else None}
    finally:
        connection.close()


def preview(root, records, config, timestamp):
    cfg = settings(config)
    previous = {}
    path = private_path(root, DATABASE)
    if path.exists():
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            previous = {identifier: json.loads(data) for identifier, data in connection.execute("SELECT experiment,data FROM trackers")}
        finally:
            connection.close()
    messages = []
    for record, observation in records:
        _, kind = plan(previous.get(record["id"]), record, observation, cfg, timestamp)
        if kind:
            messages.append({"experiment": record["id"], "kind": kind, "text": format_message(record, observation, kind, timestamp, config)})
    return {"dry_run": True, "enabled": cfg["enabled"], "messages": messages}


def resolve(root, identifier, outcome, note, timestamp=None):
    with monitor_lock(root):
        if not private_path(root, DATABASE).exists():
            raise ValueError("No notification ledger exists.")
        ledger = Ledger(root)
        try:
            row = ledger.db.execute("SELECT * FROM events WHERE id=?", (identifier,)).fetchone()
            if not row or row["status"] not in {"uncertain", "failed"}:
                raise ValueError("Resolve only a failed or uncertain event after checking Slack.")
            moment = timestamp if timestamp is not None else time.time()
            with ledger.db:
                if outcome == "sent":
                    ledger.db.execute("UPDATE events SET status='sent',error=NULL WHERE id=?", (identifier,))
                elif outcome == "not-sent":
                    ledger.db.execute("UPDATE events SET status='pending',next_at=?,attempt_limit=max(attempt_limit,attempts+1),error=NULL WHERE id=?", (moment, identifier))
                else:
                    raise ValueError("Resolution must be sent or not-sent.")
                ledger.db.execute("INSERT INTO resolutions VALUES (?,?,?,?)", (identifier, moment, outcome, str(redact(note))[:500]))
            return {"event": identifier, "resolution": outcome}
        finally:
            ledger.close()


def run_monitor(root, load_config, load_records, observe, once=False, dry_run=False,
                interval=20, client_factory=SlackClient):
    if not 1 <= interval <= 60:
        raise ValueError("Monitor interval must be between one and 60 seconds.")
    config = load_config(root)
    def collect(current_config):
        pairs, skipped = [], 0
        for directory, record in load_records(root):
            try:
                pairs.append((record, observe(directory, record, current_config.get("language", "en"))))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
        return pairs, skipped
    if dry_run:
        pairs, skipped = collect(config)
        return dict(preview(root, pairs, config, time.time()), skipped_records=skipped)
    if not settings(config)["enabled"]:
        return {"enabled": False, "delivery": "disabled"}
    with monitor_lock(root):
        ledger = Ledger(root)
        try:
            while True:
                try:
                    config = load_config(root)
                    cfg = settings(config)
                    if not cfg["enabled"]:
                        return {"enabled": False, "delivery": "disabled"}
                    pairs, skipped = collect(config)
                    timestamp = time.time()
                    queued = ledger.ingest(pairs, config, timestamp)
                    result = dict(ledger.deliver_one(cfg, timestamp, client_factory), queued=queued,
                                  skipped_records=skipped, counts=status(root)["counts"])
                except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
                    result = {"error": "monitor_input_unavailable"}
                if once:
                    return result
                print(json.dumps(result, ensure_ascii=False), flush=True)
                time.sleep(interval)
        finally:
            ledger.close()
