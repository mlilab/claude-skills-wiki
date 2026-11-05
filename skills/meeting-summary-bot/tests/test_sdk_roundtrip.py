"""Run the real `anthropic` SDK against a mocked HTTP transport (no network, no key).

Checks what the fakes cannot: that the SDK accepts our request kwargs, what goes over the
wire (beta header, fallbacks, structured output, PDF block), and that the parser reads a
real BetaMessage object.
"""

from __future__ import annotations

import json

import anthropic
import httpx2

from meeting_bot.config import SummarizerSettings
from meeting_bot.summarizer import FALLBACK_BETA, Summarizer
from tests.fakes import GOOD


def test_request_over_the_wire_and_response_parsing(pdf, notes_md):
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["beta"] = request.headers.get("anthropic-beta", "")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            headers={"request-id": "req_mock"},
            json={
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": json.dumps(GOOD, ensure_ascii=False)},
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 2048, "output_tokens": 256},
            },
        )

    client = anthropic.Anthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    summary = Summarizer(client, SummarizerSettings()).summarize([pdf, notes_md], note="memo")

    assert seen["path"] == "/v1/messages"
    assert FALLBACK_BETA in seen["beta"]
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "medium"
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert "betas" not in body  # sent as a header, not in the body

    assert summary.lines == ("지난 피드백 반영", "결과 <5% 상승", "다음 할 일")
    assert summary.usage == {"input_tokens": 2048, "output_tokens": 256}
