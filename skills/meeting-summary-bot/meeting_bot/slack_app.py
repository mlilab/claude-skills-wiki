"""Slack front end (Socket Mode): a short guided conversation that ends in a 3-line summary card.

  greeting   the bot says hello when a student first opens its DM (or writes without files)
  step 1     the student sends past feedback notes (.md/.txt), or says it is a new topic
  step 2     the student sends this week's material (PDF/image)
  summary    the bot posts a friendly "working on it" message and replaces it with the card
  restart    a "새 요약 시작하기" button after the card (or an error) brings back the greeting

Steps can arrive in one message or in either order; the bot asks for whatever is still
missing. Conversation state lives in memory per (user, channel) for SESSION_TTL_SECONDS.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from . import formatting
from .config import MB, SlackSettings
from .errors import UserError
from .files import InputFile, Kind, classify, validate
from .summarizer import Summarizer

log = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 2 * 60 * 60
_MENTION = re.compile(r"<@[A-Z0-9]+>")
_NEW_TOPIC = re.compile(r"새\s*주제|new\s*topic", re.IGNORECASE)
_HELP_WORDS = {"도움말", "사용법", "help", "?"}
_RESET_WORDS = {"처음부터", "리셋", "취소", "reset"}
_ACCEPTED_SUBTYPES = {None, "file_share", "thread_broadcast"}
_SEEN_LIMIT = 1000

Downloader = Callable[[str, str, int], bytes]


@dataclass(frozen=True)
class Request:
    """Where a message (or button click) came from and where replies go."""

    user: str
    channel: str
    ts: str
    thread_ts: str | None  # None = top level (plain DM)
    is_dm: bool
    files: tuple[dict[str, Any], ...] = ()
    note: str = ""


@dataclass(frozen=True)
class SlackFile:
    """An attachment that has been classified but not downloaded yet."""

    id: str
    name: str
    kind: Kind
    media_type: str
    url: str
    link: str | None


@dataclass(frozen=True)
class Turn:
    """What one message or button click contributed to the conversation."""

    files: tuple[SlackFile, ...] = ()
    memo: str = ""
    new_topic: bool = False
    skip_notes: bool = False

    @property
    def is_progress(self) -> bool:
        return bool(self.files) or self.new_topic or self.skip_notes


@dataclass
class Session:
    notes: list[SlackFile] = field(default_factory=list)
    materials: list[SlackFile] = field(default_factory=list)
    memos: list[str] = field(default_factory=list)
    new_topic: bool = False
    skip_notes: bool = False
    touched_at: float = 0.0

    @property
    def has_context(self) -> bool:  # step 1 done
        return bool(self.notes) or self.new_topic or self.skip_notes

    @property
    def ready(self) -> bool:
        return self.has_context and bool(self.materials)

    def apply(self, turn: Turn, now: float) -> None:
        for f in turn.files:
            target = self.materials if f.kind is Kind.MATERIAL else self.notes
            if all(existing.id != f.id for existing in target):
                target.append(f)
        if turn.memo:
            self.memos.append(turn.memo)
        self.new_topic = self.new_topic or turn.new_topic
        self.skip_notes = self.skip_notes or turn.skip_notes
        self.touched_at = now


def parse_event(event: dict[str, Any], *, is_dm: bool) -> Request | None:
    """Return the request in a user message, or None for events the bot should ignore."""
    if event.get("bot_id") or event.get("subtype") not in _ACCEPTED_SUBTYPES or not event.get("user"):
        return None
    channel = event["channel"]
    is_dm = is_dm or channel.startswith("D")
    return Request(
        user=event["user"],
        channel=channel,
        ts=event["ts"],
        thread_ts=event.get("thread_ts") or (None if is_dm else event["ts"]),
        is_dm=is_dm,
        files=tuple(event.get("files") or ()),
        note=_MENTION.sub("", event.get("text") or "").strip(),
    )


def _keyword(text: str) -> str:
    return text.strip().strip(".!~ ").lower()


def download_slack_file(url: str, token: str, max_bytes: int) -> bytes:
    try:
        with requests.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=60) as r:
            r.raise_for_status()
            if r.headers.get("Content-Type", "").startswith("text/html"):  # login page = missing scope
                raise UserError("Slack에서 파일을 받지 못했습니다. 봇의 files:read 권한을 확인해 주세요.")
            chunks: list[bytes] = []
            size = 0
            for chunk in r.iter_content(chunk_size=1 << 16):
                size += len(chunk)
                if size > max_bytes:
                    raise UserError(f"파일이 너무 큽니다 (최대 {max_bytes // MB}MB)")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as e:
        log.warning("file download failed: %s", type(e).__name__)
        raise UserError("Slack에서 파일을 내려받지 못했습니다. 잠시 후 다시 시도해 주세요.") from None


class SummaryBot:
    def __init__(
        self,
        settings: SlackSettings,
        summarizer: Summarizer,
        *,
        max_file_bytes: int,
        max_total_bytes: int,
        downloader: Downloader = download_slack_file,
        executor: Executor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.summarizer = summarizer
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.downloader = downloader
        self._executor = executor or ThreadPoolExecutor(
            max_workers=settings.max_concurrent_jobs, thread_name_prefix="summary"
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._busy_users: set[str] = set()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._sessions: dict[tuple[str, str], Session] = {}

    # ---------------------------------------------------------------- entry points
    def handle(self, event: dict[str, Any], client: WebClient, *, is_dm: bool) -> None:
        """A message (DM, or a channel message that mentions the bot)."""
        req = parse_event(event, is_dm=is_dm)
        if req is None or not self._first_delivery(f"{req.channel}:{req.ts}"):
            return
        if not self.settings.allows(req.user, req.channel, is_dm=req.is_dm):
            self._reply(client, req, formatting.NOT_ALLOWED_TEXT)
            return
        if self._is_busy(req.user):
            self._reply(client, req, formatting.BUSY_TEXT)
            return
        word = _keyword(req.note)
        if not req.files and word in _HELP_WORDS:
            self._greet(client, req)
            return
        if not req.files and word in _RESET_WORDS:
            with self._lock:
                self._sessions.pop((req.user, req.channel), None)
            self._greet(client, req, reset=True)
            return
        try:
            files = tuple(self._resolve_file(client, meta) for meta in req.files)
        except UserError as e:
            self._reply(client, req, formatting.error_post(str(e)))
            return
        self._advance(client, req, Turn(files=files, memo=req.note, new_topic=bool(_NEW_TOPIC.search(req.note))))

    def handle_action(self, action_id: str, body: dict[str, Any], client: WebClient) -> None:
        """A click on one of the bot's buttons (new topic / continue without notes / restart)."""
        channel = body["channel"]["id"]
        message = body.get("message") or {}
        message_ts = body["container"]["message_ts"]
        is_dm = channel.startswith("D")
        req = Request(
            user=body["user"]["id"],
            channel=channel,
            ts=message_ts,
            thread_ts=message.get("thread_ts") or (None if is_dm else message_ts),
            is_dm=is_dm,
        )
        if not self.settings.allows(req.user, req.channel, is_dm=is_dm):
            return
        if self._is_busy(req.user):
            self._reply(client, req, formatting.BUSY_TEXT)
            return
        choice = formatting.choice_text(action_id)
        self._update(client, req, message_ts, f"{message.get('text', '')}\n\n{choice}", blocks=[])
        if action_id == formatting.RESTART_ACTION:
            with self._lock:
                self._sessions.pop((req.user, req.channel), None)
            self._greet(client, req)
            return
        turn = Turn(new_topic=action_id == formatting.NEW_TOPIC_ACTION, skip_notes=action_id == formatting.SKIP_ACTION)
        self._advance(client, req, turn)

    def greet_if_new(self, event: dict[str, Any], client: WebClient) -> None:
        """app_home_opened: say hello the first time a student opens the bot's DM."""
        if event.get("tab") != "messages" or not event.get("channel"):
            return
        req = Request(user=event["user"], channel=event["channel"], ts="", thread_ts=None, is_dm=True)
        if not self.settings.allows(req.user, req.channel, is_dm=True):
            return
        try:
            if client.conversations_history(channel=req.channel, limit=1).get("messages"):
                return
        except SlackApiError as e:
            log.warning("conversations.history failed: %s", e.response.get("error"))
            return
        self._greet(client, req)

    # ---------------------------------------------------------------- conversation
    def _advance(self, client: WebClient, req: Request, turn: Turn) -> None:
        now = self._clock()
        key = (req.user, req.channel)
        with self._lock:
            for stale in [k for k, s in self._sessions.items() if now - s.touched_at > SESSION_TTL_SECONDS]:
                del self._sessions[stale]
            session = self._sessions.get(key)
            if session is None and not turn.is_progress:  # small talk before anything else
                session_state = None
            else:
                session = session or Session()
                session.apply(turn, now)
                session_state = session
                if session.ready:
                    self._sessions.pop(key, None)
                else:
                    self._sessions[key] = session
        if session_state is None:
            self._greet(client, req)
        elif session_state.ready:
            self._start_summary(client, req, session_state)
        else:
            self._post_progress(client, req, turn, session_state)

    def _post_progress(self, client: WebClient, req: Request, turn: Turn, session: Session) -> None:
        lines = formatting.ack_lines(
            notes=[f.name for f in turn.files if f.kind is Kind.BACKGROUND],
            materials=[f.name for f in turn.files if f.kind is Kind.MATERIAL],
            new_topic=turn.new_topic,
            skip_notes=turn.skip_notes,
            memo=bool(turn.memo) and not turn.new_topic,
        )
        if session.has_context:  # step 1 done -> ask for the material
            self._reply(client, req, "\n".join([*lines, formatting.NEED_MATERIAL_TEXT]))
        else:  # material came first -> ask for step 1, with buttons
            text = "\n".join([*lines, formatting.NEED_CONTEXT_TEXT])
            self._reply(client, req, text, blocks=formatting.choice_blocks(text, skip_label=formatting.SKIP_NOW_LABEL))

    def _greet(self, client: WebClient, req: Request, *, reset: bool = False) -> None:
        text = (formatting.RESET_PREFIX if reset else "") + formatting.GREETING_TEXT
        self._reply(client, req, text, blocks=formatting.choice_blocks(text, skip_label=formatting.SKIP_LABEL))

    # ---------------------------------------------------------------- summary job
    def _start_summary(self, client: WebClient, req: Request, session: Session) -> None:
        if not self._acquire(req.user):
            self._reply(client, req, formatting.BUSY_TEXT)
            return
        try:
            placeholder_ts = self._reply(client, req, formatting.WORKING_TEXT)
            self._executor.submit(self._run, client, req, session, placeholder_ts)
        except BaseException:
            self._release(req.user)
            raise

    def _run(self, client: WebClient, req: Request, session: Session, placeholder_ts: str) -> None:
        started = time.monotonic()
        try:
            try:
                files = self._download([*session.materials, *session.notes])
                validate(files, max_file_bytes=self.max_file_bytes, max_total_bytes=self.max_total_bytes)
                summary = self.summarizer.summarize(files, "\n".join(session.memos), new_topic=session.new_topic)
            except UserError as e:
                log.info("user error user=%s: %s", req.user, e)
                self._fail(client, req, placeholder_ts, str(e))
                return
            except Exception:
                log.exception("job crashed user=%s", req.user)
                self._fail(client, req, placeholder_ts, formatting.INTERNAL_ERROR_TEXT)
                return
            # Delivery: a Slack failure from here on must not turn a finished summary into an error.
            material = session.materials[0]
            self._update(
                client,
                req,
                placeholder_ts,
                formatting.summary_text(summary.lines, material.link or material.name),
                blocks=formatting.summary_blocks(
                    summary.lines, new_topic=summary.new_topic, file_name=material.name, link=material.link
                ),
            )
            try:
                if summary.notes:
                    self._reply(client, req, formatting.notes_post(summary.notes))
                text = formatting.DONE_TEXT
                self._reply(client, req, text, blocks=formatting.restart_blocks(text))
            except SlackApiError:
                log.exception("posting follow-up messages failed user=%s", req.user)
            log.info("done user=%s files=%d in %.1fs", req.user, len(files), time.monotonic() - started)
        finally:
            self._release(req.user)

    def _fail(self, client: WebClient, req: Request, placeholder_ts: str, message: str) -> None:
        text = formatting.error_post(message)
        self._update(client, req, placeholder_ts, text, blocks=formatting.restart_blocks(text))

    def _download(self, files: Sequence[SlackFile]) -> list[InputFile]:
        token = self.settings.bot_token
        return [
            InputFile(f.name, f.kind, f.media_type, self.downloader(f.url, token, self.max_file_bytes), link=f.link)
            for f in files
        ]

    # ---------------------------------------------------------------- slack helpers
    def _resolve_file(self, client: WebClient, meta: dict[str, Any]) -> SlackFile:
        if "url_private_download" not in meta:  # partial file object ("check_file_info")
            try:
                meta = client.files_info(file=meta["id"])["file"]
            except SlackApiError as e:
                log.warning("files.info failed: %s", e.response.get("error"))
                raise UserError("Slack에서 파일 정보를 가져오지 못했습니다. 다시 올려 주세요.") from None
        name = meta.get("name") or meta.get("title") or meta["id"]
        if "url_private_download" not in meta:  # e.g. a Google Drive file shared into Slack
            raise UserError(f"이 파일은 내려받을 수 없습니다: {name} (Slack에 직접 업로드해 주세요)")
        if meta.get("size", 0) > self.max_file_bytes:
            raise UserError(f"파일이 너무 큽니다: {name} (최대 {self.max_file_bytes // MB}MB)")
        kind, media_type = classify(name, meta.get("mimetype"))
        return SlackFile(meta["id"], name, kind, media_type, meta["url_private_download"], meta.get("permalink"))

    @staticmethod
    def _reply(client: WebClient, req: Request, text: str, *, blocks: list[dict[str, Any]] | None = None) -> str:
        kwargs: dict[str, Any] = {"channel": req.channel, "thread_ts": req.thread_ts, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks
        return client.chat_postMessage(**kwargs)["ts"]

    @staticmethod
    def _update(
        client: WebClient, req: Request, ts: str, text: str, *, blocks: list[dict[str, Any]] | None = None
    ) -> None:
        kwargs: dict[str, Any] = {"channel": req.channel, "ts": ts, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks  # [] removes the old blocks (e.g. clicked buttons)
        try:
            client.chat_update(**kwargs)
        except SlackApiError:
            log.exception("chat.update failed user=%s", req.user)

    def _first_delivery(self, key: str) -> bool:
        """Slack can deliver the same message twice (retries, mention + DM); handle it once."""
        with self._lock:
            if key in self._seen:
                return False
            self._seen[key] = None
            if len(self._seen) > _SEEN_LIMIT:
                self._seen.popitem(last=False)
            return True

    def _is_busy(self, user: str) -> bool:
        with self._lock:
            return user in self._busy_users

    def _acquire(self, user: str) -> bool:
        with self._lock:
            if user in self._busy_users:
                return False
            self._busy_users.add(user)
            return True

    def _release(self, user: str) -> None:
        with self._lock:
            self._busy_users.discard(user)


def create_app(settings: SlackSettings, bot: SummaryBot, *, verify_token: bool = True) -> App:
    app = App(token=settings.bot_token, token_verification_enabled=verify_token)

    @app.event("app_mention")
    def on_mention(event: dict[str, Any], client: WebClient) -> None:
        bot.handle(event, client, is_dm=False)

    @app.event("message")
    def on_message(event: dict[str, Any], client: WebClient) -> None:
        if event.get("channel_type") == "im":  # channel messages are handled via app_mention
            bot.handle(event, client, is_dm=True)

    @app.event("app_home_opened")
    def on_home_opened(event: dict[str, Any], client: WebClient) -> None:
        bot.greet_if_new(event, client)

    buttons = (formatting.NEW_TOPIC_ACTION, formatting.SKIP_ACTION, formatting.RESTART_ACTION)

    @app.action(re.compile(f"^({'|'.join(buttons)})$"))
    def on_button(ack: Callable[[], None], body: dict[str, Any], action: dict[str, Any], client: WebClient) -> None:
        ack()
        bot.handle_action(action["action_id"], body, client)

    return app


def serve(settings: SlackSettings, bot: SummaryBot) -> None:
    app = create_app(settings, bot)
    log.info("starting Socket Mode (max %d concurrent jobs)", settings.max_concurrent_jobs)
    SocketModeHandler(app, settings.app_token).start()
