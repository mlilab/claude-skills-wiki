from __future__ import annotations

from typing import Any

import pytest
import requests
from slack_sdk.errors import SlackApiError

from meeting_bot import formatting, slack_app
from meeting_bot.config import SlackSettings
from meeting_bot.errors import UserError
from meeting_bot.slack_app import SummaryBot, download_slack_file, parse_event
from meeting_bot.summarizer import Summary

PDF = {
    "id": "F1",
    "name": "week.pdf",
    "mimetype": "application/pdf",
    "url_private_download": "https://files/F1",
    "permalink": "https://slack/F1",
}
NOTES = {"id": "F2", "name": "notes.md", "mimetype": "text/plain", "url_private_download": "https://files/F2"}
LINES = ("지난 피드백 반영", "결과 <5% 상승", "다음 할 일")


# ------------------------------------------------------------------------------- fakes
class FakeSlack:
    def __init__(self, files_info: dict[str, dict] | None = None, history: list | None = None):
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.files_info_map = files_info or {}
        self.history = history or []

    def chat_postMessage(self, *, channel, text, thread_ts=None, blocks=None):  # noqa: N802 (Slack SDK name)
        ts = f"100.{len(self.posts)}"
        self.posts.append({"channel": channel, "text": text, "thread_ts": thread_ts, "blocks": blocks, "ts": ts})
        return {"ts": ts}

    def chat_update(self, *, channel, ts, text, blocks=None):
        self.updates.append({"channel": channel, "ts": ts, "text": text, "blocks": blocks})

    def files_info(self, *, file):
        return {"file": self.files_info_map[file]}

    def conversations_history(self, *, channel, limit):
        return {"messages": self.history[:limit]}

    @property
    def last(self) -> str:
        return self.posts[-1]["text"]


class FakeSummarizer:
    def __init__(self, result: Summary | BaseException | None = None):
        self.result = result or Summary(lines=LINES)
        self.calls: list[dict[str, Any]] = []

    def summarize(self, files, note="", *, new_topic=False):
        self.calls.append({"files": [f.name for f in files], "note": note, "new_topic": new_topic})
        if isinstance(self.result, BaseException):
            raise self.result
        return Summary(lines=self.result.lines, notes=self.result.notes, new_topic=self.result.new_topic or new_topic)


class SyncExecutor:
    def submit(self, fn, *args):
        fn(*args)


class HeldExecutor:
    """Keeps jobs pending so a message can arrive while a summary is running."""

    def __init__(self):
        self.jobs: list = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))

    def run_all(self):
        for fn, args in self.jobs:
            fn(*args)


class FakeDownloader:
    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url, token, max_bytes):
        self.urls.append(url)
        return b"%PDF fake" if url.endswith("F1") else "지난 피드백".encode()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_bot(summarizer=None, executor=None, clock=None, **settings):
    downloader = FakeDownloader()
    bot = SummaryBot(
        SlackSettings(bot_token="xoxb-test", app_token="xapp-test", **settings),
        summarizer or FakeSummarizer(),
        max_file_bytes=1024,
        max_total_bytes=4096,
        downloader=downloader,
        executor=executor or SyncExecutor(),
        clock=clock or FakeClock(),
    )
    return bot, downloader


_ts = iter(range(1, 10_000))


def dm(files=(), text="", **extra) -> dict[str, Any]:
    return {
        "type": "message",
        "channel_type": "im",
        "subtype": "file_share" if files else None,
        "user": "U1",
        "channel": "D1",
        "ts": f"{next(_ts)}.0",
        "text": text,
        "files": list(files),
        **extra,
    }


def mention(files=(), text="<@UBOT>", **extra) -> dict[str, Any]:
    return {"type": "app_mention", "user": "U1", "channel": "C1", "ts": f"{next(_ts)}.0", "text": text,
            "files": list(files), **extra}  # fmt: skip


def click(action_id: str, *, user="U1", channel="D1", text="(버튼 메시지)") -> dict[str, Any]:
    return {
        "type": "block_actions",
        "user": {"id": user},
        "channel": {"id": channel},
        "container": {"type": "message", "message_ts": "50.0"},
        "message": {"ts": "50.0", "text": text},
        "actions": [{"action_id": action_id}],
    }


def button_ids(post: dict[str, Any]) -> list[str]:
    actions = [b for b in post["blocks"] or [] if b["type"] == "actions"]
    return [e["action_id"] for e in actions[0]["elements"]] if actions else []


# ------------------------------------------------------------------------- greeting
def test_first_message_without_files_gets_the_greeting_with_buttons():
    bot, _ = make_bot()
    slack = FakeSlack()
    bot.handle(dm(text="안녕하세요"), slack, is_dm=True)
    assert slack.last == formatting.GREETING_TEXT
    assert button_ids(slack.posts[-1]) == [formatting.NEW_TOPIC_ACTION, formatting.SKIP_ACTION]
    assert slack.posts[-1]["thread_ts"] is None  # DMs are answered at top level


def test_opening_an_empty_dm_greets_once():
    bot, _ = make_bot()
    slack = FakeSlack()
    bot.greet_if_new({"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"}, slack)
    assert slack.last == formatting.GREETING_TEXT
    busy = FakeSlack(history=[{"ts": "1.0"}])
    bot.greet_if_new({"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"}, busy)
    bot.greet_if_new({"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "home"}, busy)
    assert busy.posts == []


def test_help_and_reset_words():
    bot, _ = make_bot()
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES]), slack, is_dm=True)
    bot.handle(dm(text="도움말"), slack, is_dm=True)
    assert slack.last == formatting.GREETING_TEXT
    bot.handle(dm(text="처음부터"), slack, is_dm=True)
    assert slack.last == formatting.RESET_PREFIX + formatting.GREETING_TEXT
    bot.handle(dm(files=[PDF]), slack, is_dm=True)  # the notes were dropped by the reset
    assert formatting.NEED_CONTEXT_TEXT in slack.last


# --------------------------------------------------------------- the two-step flow
def test_notes_then_material():
    summarizer = FakeSummarizer()
    bot, downloader = make_bot(summarizer)
    slack = FakeSlack()

    bot.handle(dm(files=[NOTES]), slack, is_dm=True)
    assert slack.last == "✅ 피드백 노트를 확인했어요: notes.md\n" + formatting.NEED_MATERIAL_TEXT
    assert downloader.urls == []  # nothing is downloaded until the summary runs

    bot.handle(dm(files=[PDF]), slack, is_dm=True)
    waiting, done = slack.posts[-2], slack.posts[-1]
    assert waiting["text"] == formatting.WORKING_TEXT
    assert summarizer.calls == [{"files": ["week.pdf", "notes.md"], "note": "", "new_topic": False}]
    card = slack.updates[-1]
    assert card["ts"] == waiting["ts"]  # the waiting message turns into the card
    assert card["text"] == formatting.summary_text(LINES, "https://slack/F1")
    assert card["blocks"] == formatting.summary_blocks(
        LINES, new_topic=False, file_name="week.pdf", link="https://slack/F1"
    )
    assert done["text"] == formatting.DONE_TEXT  # followed by the restart button
    assert button_ids(done) == [formatting.RESTART_ACTION]


def test_restart_button_brings_back_the_greeting():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(files=[PDF]), slack, is_dm=True)  # a half-finished session...
    bot.handle_action(formatting.RESTART_ACTION, click(formatting.RESTART_ACTION, text="끝"), slack)
    assert slack.updates[-1] == {"channel": "D1", "ts": "50.0", "text": "끝\n\n→ 🔄 새 요약 시작하기", "blocks": []}
    assert slack.last == formatting.GREETING_TEXT
    assert button_ids(slack.posts[-1]) == [formatting.NEW_TOPIC_ACTION, formatting.SKIP_ACTION]
    bot.handle(dm(files=[NOTES]), slack, is_dm=True)  # ...is dropped: only the notes are there now
    assert slack.last.endswith(formatting.NEED_MATERIAL_TEXT)


def test_new_topic_by_text_then_material():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(text="새 주제입니다: 의료 VLM hallucination"), slack, is_dm=True)
    assert slack.last.startswith("✅ 새 주제로 기록했어요.")
    assert slack.last.endswith(formatting.NEED_MATERIAL_TEXT)

    bot.handle(dm(text="finding 단위로 보려고 합니다"), slack, is_dm=True)  # extra description
    assert slack.last.startswith("📝 보내 주신 메모도")

    bot.handle(dm(files=[PDF]), slack, is_dm=True)
    call = summarizer.calls[0]
    assert call["new_topic"] is True
    assert call["note"] == "새 주제입니다: 의료 VLM hallucination\nfinding 단위로 보려고 합니다"
    assert "*1. 새 주제*" in slack.updates[-1]["blocks"][3]["text"]["text"]


def test_new_topic_button_from_the_greeting():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(text="hi"), slack, is_dm=True)
    bot.handle_action(formatting.NEW_TOPIC_ACTION, click(formatting.NEW_TOPIC_ACTION, text="인사"), slack)
    assert slack.updates[-1] == {  # buttons removed, choice shown on the clicked message
        "channel": "D1",
        "ts": "50.0",
        "text": "인사\n\n→ 🆕 새 주제예요",
        "blocks": [],
    }
    assert slack.last.endswith(formatting.NEED_MATERIAL_TEXT)
    bot.handle(dm(files=[PDF]), slack, is_dm=True)
    assert summarizer.calls[0]["new_topic"] is True


def test_material_first_asks_for_step_one_then_skip_button_summarizes():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(files=[PDF]), slack, is_dm=True)
    assert slack.last == "📄 미팅자료를 받았어요: week.pdf\n" + formatting.NEED_CONTEXT_TEXT
    assert button_ids(slack.posts[-1]) == [formatting.NEW_TOPIC_ACTION, formatting.SKIP_ACTION]
    assert summarizer.calls == []

    bot.handle_action(formatting.SKIP_ACTION, click(formatting.SKIP_ACTION), slack)
    assert summarizer.calls == [{"files": ["week.pdf"], "note": "", "new_topic": False}]


def test_material_first_then_notes():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(files=[PDF]), slack, is_dm=True)
    bot.handle(dm(files=[NOTES]), slack, is_dm=True)
    assert summarizer.calls[0]["files"] == ["week.pdf", "notes.md"]


def test_everything_in_one_message_goes_straight_to_the_summary():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(mention(files=[PDF, NOTES], text="<@UBOT> 이번 주 요약"), slack, is_dm=False)
    assert slack.posts[0]["text"] == formatting.WORKING_TEXT
    assert slack.posts[0]["thread_ts"] is not None  # channels: answered in a thread
    assert summarizer.calls == [{"files": ["week.pdf", "notes.md"], "note": "이번 주 요약", "new_topic": False}]


def test_session_expires_and_is_per_user():
    summarizer, clock = FakeSummarizer(), FakeClock()
    bot, _ = make_bot(summarizer, clock=clock)
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES]), slack, is_dm=True)
    bot.handle(dm(files=[PDF], user="U2"), slack, is_dm=True)  # another student: own session
    assert formatting.NEED_CONTEXT_TEXT in slack.last
    clock.now += slack_app.SESSION_TTL_SECONDS + 1
    bot.handle(dm(files=[PDF]), slack, is_dm=True)  # U1's notes have expired
    assert formatting.NEED_CONTEXT_TEXT in slack.last
    assert summarizer.calls == []


def test_session_is_cleared_after_a_summary():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES, PDF]), slack, is_dm=True)
    bot.handle(dm(files=[PDF]), slack, is_dm=True)  # next week: starts over
    assert formatting.NEED_CONTEXT_TEXT in slack.last
    assert len(summarizer.calls) == 1


def test_notes_go_in_a_separate_message():
    bot, _ = make_bot(FakeSummarizer(Summary(lines=LINES, notes="자료 부족")))
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES, PDF]), slack, is_dm=True)
    assert [p["text"] for p in slack.posts[-2:]] == ["💡 참고: 자료 부족", formatting.DONE_TEXT]


# ---------------------------------------------------------------------- guard rails
@pytest.mark.parametrize(
    ("settings", "channel", "allowed"),
    [
        ({"allowed_user_ids": frozenset({"U9"})}, "C1", False),
        ({"allowed_channel_ids": frozenset({"C2"})}, "C1", False),
        ({"allowed_channel_ids": frozenset({"C2"})}, "D1", True),  # DM channel ids start with D
    ],
)
def test_access_control(settings, channel, allowed):
    bot, _ = make_bot(**settings)
    slack = FakeSlack()
    bot.handle(mention(channel=channel), slack, is_dm=False)
    assert (slack.posts[0]["text"] != formatting.NOT_ALLOWED_TEXT) is allowed


def test_unsupported_file_is_rejected_on_arrival():
    bot, downloader = make_bot()
    slack = FakeSlack()
    pptx = {"id": "F3", "name": "slides.pptx", "mimetype": "application/vnd.ms-powerpoint",
            "url_private_download": "https://files/F3"}  # fmt: skip
    bot.handle(dm(files=[pptx]), slack, is_dm=True)
    assert "지원하지 않는 파일 형식" in slack.last
    assert downloader.urls == []


def test_partial_and_external_files():
    bot, _ = make_bot()
    slack = FakeSlack(files_info={"F1": PDF, "F4": {"id": "F4", "name": "drive.pdf", "mimetype": "application/pdf"}})
    bot.handle(dm(files=[{"id": "F1", "file_access": "check_file_info"}]), slack, is_dm=True)
    assert slack.last.startswith("📄 미팅자료를 받았어요: week.pdf")
    bot.handle(dm(files=[{"id": "F4", "file_access": "check_file_info"}]), slack, is_dm=True)
    assert "내려받을 수 없습니다: drive.pdf" in slack.last


def test_oversized_file_is_rejected_on_arrival():
    bot, _ = make_bot()
    slack = FakeSlack()
    bot.handle(dm(files=[{**PDF, "size": 10_000}]), slack, is_dm=True)
    assert "너무 큽니다: week.pdf" in slack.last


def test_duplicate_delivery_is_handled_once():
    summarizer = FakeSummarizer()
    bot, _ = make_bot(summarizer)
    slack = FakeSlack()
    event = mention(files=[PDF, NOTES])
    bot.handle(event, slack, is_dm=False)
    bot.handle({**event, "type": "message", "channel_type": "channel"}, slack, is_dm=False)
    assert len(summarizer.calls) == 1


def test_messages_while_a_summary_runs_get_a_busy_reply():
    executor = HeldExecutor()
    bot, _ = make_bot(executor=executor)
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES, PDF]), slack, is_dm=True)
    bot.handle(dm(text="혹시"), slack, is_dm=True)
    assert slack.last == formatting.BUSY_TEXT
    executor.run_all()
    bot.handle(dm(text="안녕"), slack, is_dm=True)
    assert slack.last == formatting.GREETING_TEXT


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UserError("API 사용량 제한"), "⚠️ API 사용량 제한"),
        (RuntimeError("bug"), formatting.error_post(formatting.INTERNAL_ERROR_TEXT)),
    ],
)
def test_job_errors_replace_the_waiting_message(error, expected):
    bot, _ = make_bot(FakeSummarizer(error))
    slack = FakeSlack()
    bot.handle(dm(files=[NOTES, PDF]), slack, is_dm=True)
    assert slack.updates[-1]["text"] == expected
    assert button_ids(slack.updates[-1]) == [formatting.RESTART_ACTION]
    bot.handle(dm(text="안녕"), slack, is_dm=True)  # the user is released
    assert slack.last == formatting.GREETING_TEXT


def test_notes_failure_does_not_overwrite_a_finished_summary():
    class FlakySlack(FakeSlack):
        def chat_postMessage(self, *, channel, text, thread_ts=None, blocks=None):  # noqa: N802
            if text.startswith("💡 참고:"):
                raise SlackApiError("rate limited", {"ok": False, "error": "ratelimited"})
            return super().chat_postMessage(channel=channel, text=text, thread_ts=thread_ts, blocks=blocks)

    bot, _ = make_bot(FakeSummarizer(Summary(lines=LINES, notes="자료 부족")))
    slack = FlakySlack()
    bot.handle(dm(files=[NOTES, PDF]), slack, is_dm=True)
    assert [u["text"] for u in slack.updates] == [formatting.summary_text(LINES, "https://slack/F1")]


@pytest.mark.parametrize(
    "event",
    [
        {"user": "U1", "channel": "C1", "ts": "1", "bot_id": "B1"},
        {"user": "U1", "channel": "C1", "ts": "1", "subtype": "message_changed"},
        {"channel": "C1", "ts": "1"},
    ],
)
def test_ignored_events(event):
    assert parse_event(event, is_dm=False) is None


def test_parse_event_strips_mentions_and_keeps_thread():
    req = parse_event(mention(text="<@UBOT> 새 주제 <@U2>", thread_ts="0.5"), is_dm=False)
    assert (req.note, req.thread_ts, req.is_dm) == ("새 주제", "0.5", False)


# ------------------------------------------------------------------------- download
class FakeResponse:
    def __init__(self, chunks, content_type="application/pdf", status=200):
        self.chunks, self.headers, self.status = chunks, {"Content-Type": content_type}, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def iter_content(self, chunk_size):
        return iter(self.chunks)


@pytest.mark.parametrize(
    ("response", "result"),
    [
        (FakeResponse([b"ab", b"cd"]), b"abcd"),
        (FakeResponse([b"<html>"], content_type="text/html; charset=utf-8"), "files:read"),
        (FakeResponse([b"x" * 6]), "너무 큽니다"),
        (FakeResponse([], status=403), "내려받지 못했습니다"),
    ],
)
def test_download_slack_file(monkeypatch, response, result):
    seen = {}

    def fake_get(url, headers, stream, timeout):
        seen.update(url=url, auth=headers["Authorization"])
        return response

    monkeypatch.setattr(slack_app.requests, "get", fake_get)
    if isinstance(result, bytes):
        assert download_slack_file("https://files/F1", "xoxb-t", 5) == result
        assert seen == {"url": "https://files/F1", "auth": "Bearer xoxb-t"}
    else:
        with pytest.raises(UserError, match=result):
            download_slack_file("https://files/F1", "xoxb-t", 5)
