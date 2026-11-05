"""Dispatch Socket Mode payloads through a real Bolt App (no network) to check routing."""

from __future__ import annotations

import threading
import time

import pytest
from slack_bolt.request import BoltRequest
from slack_sdk import WebClient
from slack_sdk.web import SlackResponse

from meeting_bot import formatting
from meeting_bot.config import SlackSettings
from meeting_bot.slack_app import create_app


class RecordingBot:
    def __init__(self):
        self.calls: list[tuple] = []
        self.lock = threading.Lock()

    def _record(self, *call):
        with self.lock:
            self.calls.append(call)

    def handle(self, event, client, *, is_dm):
        self._record("message", event["type"], is_dm, type(client))

    def handle_action(self, action_id, body, client):
        self._record("action", action_id, body["user"]["id"], type(client))

    def greet_if_new(self, event, client):
        self._record("home", event["tab"], type(client))


@pytest.fixture
def app_and_bot(monkeypatch):
    def fake_auth_test(self, **kwargs):
        return SlackResponse(
            client=self,
            http_verb="POST",
            api_url="https://slack.com/api/auth.test",
            req_args={},
            data={"ok": True, "user_id": "UBOT", "bot_id": "B1", "team_id": "T1", "user": "meeting-summary"},
            headers={},
            status_code=200,
        )

    monkeypatch.setattr(WebClient, "auth_test", fake_auth_test)
    bot = RecordingBot()
    return create_app(SlackSettings(bot_token="xoxb-t", app_token="xapp-t"), bot, verify_token=False), bot


def dispatch(app, body: dict) -> int:
    return app.dispatch(BoltRequest(body=body, mode="socket_mode")).status


def wait_for(bot: RecordingBot, n: int) -> list[tuple]:
    deadline = time.monotonic() + 5  # listeners run on Bolt's worker threads
    while len(bot.calls) < n and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)  # give a wrongly routed payload the chance to show up
    return sorted(bot.calls, key=repr)


def event_body(event: dict, event_id: str) -> dict:
    return {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event": event,
            "event_id": event_id, "event_time": 1}  # fmt: skip


def test_events_are_routed(app_and_bot):
    app, bot = app_and_bot
    base = {"user": "U1", "text": "hi", "ts": "1.0", "event_ts": "1.0"}
    events = [
        {**base, "type": "app_mention", "channel": "C1"},
        {**base, "type": "message", "channel": "D1", "channel_type": "im"},
        {**base, "type": "message", "channel": "C1", "channel_type": "channel"},  # ignored
        {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages", "event_ts": "1.0"},
    ]
    for i, event in enumerate(events):
        assert dispatch(app, event_body(event, f"Ev{i}")) == 200
    assert wait_for(bot, 3) == sorted(
        [
            ("home", "messages", WebClient),
            ("message", "app_mention", False, WebClient),
            ("message", "message", True, WebClient),
        ],
        key=repr,
    )


@pytest.mark.parametrize("action_id", [formatting.NEW_TOPIC_ACTION, formatting.SKIP_ACTION, formatting.RESTART_ACTION])
def test_button_clicks_are_acked_and_routed(app_and_bot, action_id):
    app, bot = app_and_bot
    body = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U1"},
        "api_app_id": "A1",
        "channel": {"id": "D1"},
        "container": {"type": "message", "message_ts": "5.0", "channel_id": "D1"},
        "message": {"ts": "5.0", "text": "인사"},
        "trigger_id": "t1",
        "actions": [{"type": "button", "action_id": action_id, "block_id": "b1", "action_ts": "6.0"}],
    }
    assert dispatch(app, body) == 200  # acked
    assert wait_for(bot, 1) == [("action", action_id, "U1", WebClient)]
