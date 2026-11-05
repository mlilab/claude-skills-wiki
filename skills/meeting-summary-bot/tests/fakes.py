"""Fakes for the Anthropic client: no test talks to the real API or Slack."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def api_response(
    payload: dict[str, Any] | None = None,
    *,
    text: str | None = None,
    stop_reason: str = "end_turn",
    stop_details: Any = None,
    model: str = "claude-sonnet-5-5",
) -> SimpleNamespace:
    """Shape of an Anthropic BetaMessage, with an (empty) thinking block first like the real API."""
    body = json.dumps(payload, ensure_ascii=False) if text is None else text
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=stop_details,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        model=model,
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
        _request_id="req_test",
    )


GOOD = {
    "last_meeting": "1. 지난 피드백 반영",
    "this_week": "결과 <5% 상승",
    "discussion": "다음 할 일",
    "new_topic": False,
    "notes": "",
}


class FakeAnthropic:
    """Replays queued responses (or raises queued exceptions) from client.beta.messages.create."""

    def __init__(self, *responses: Any):
        self.queue = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
