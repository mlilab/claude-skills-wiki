from __future__ import annotations

import anthropic
import httpx2
import pytest

from meeting_bot.config import SummarizerSettings
from meeting_bot.errors import UserError
from meeting_bot.files import InputFile, Kind
from meeting_bot.summarizer import (
    FALLBACK_BETA,
    INSTRUCTION,
    LINE_FIELDS,
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    Summarizer,
    build_content,
    clean_line,
)
from tests.fakes import GOOD, FakeAnthropic, api_response


def make(*responses, **settings) -> tuple[Summarizer, FakeAnthropic]:
    client = FakeAnthropic(*responses)
    return Summarizer(client, SummarizerSettings(**settings)), client


def status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


# ------------------------------------------------------------------ request
def test_request_shape_with_fallback(pdf):
    summarizer, _ = make()
    req = summarizer.build_request([pdf])
    assert req["model"] == "claude-sonnet-5-5"
    assert req["system"] == SYSTEM_PROMPT
    assert req["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    assert req["betas"] == [FALLBACK_BETA]
    assert req["fallbacks"] == "default"
    assert "thinking" not in req  # adaptive thinking is the default; "disabled" would be a 400


def test_request_without_fallback(pdf):
    summarizer, _ = make(fallback=False, effort="low", model="claude-opus-5-5")
    req = summarizer.build_request([pdf])
    assert "betas" not in req and "fallbacks" not in req
    assert req["output_config"]["effort"] == "low"
    assert req["model"] == "claude-opus-5-5"


def test_schema_has_exactly_the_three_lines_and_notes():
    assert OUTPUT_SCHEMA["required"] == [*LINE_FIELDS, "new_topic", "notes"]
    assert OUTPUT_SCHEMA["properties"]["new_topic"]["type"] == "boolean"
    assert OUTPUT_SCHEMA["additionalProperties"] is False
    for name in LINE_FIELDS:
        assert name in SYSTEM_PROMPT  # the prompt explains every field it asks for


def test_content_order_and_encoding(pdf):
    png = InputFile("fig.png", Kind.MATERIAL, "image/png", b"\x89PNG")
    note_cp949 = InputFile('a"b.txt', Kind.BACKGROUND, "text/plain", "피드백".encode("cp949"))
    blocks = build_content([note_cp949, pdf, png], note="  새 주제입니다 ")
    assert [b["type"] for b in blocks] == ["document", "image", "text", "text", "text"]
    assert blocks[0]["title"] == "week.pdf"
    assert blocks[0]["source"]["media_type"] == "application/pdf"
    assert blocks[2]["text"] == '<background file="a&quot;b.txt">\n피드백\n</background>'
    assert blocks[3]["text"] == "<user_note>\n새 주제입니다\n</user_note>"
    assert blocks[4]["text"] == INSTRUCTION


def test_empty_note_is_omitted(pdf):
    assert [b["type"] for b in build_content([pdf], note="   ")] == ["document", "text"]


# ----------------------------------------------------------------- response
def test_parse_success(pdf, notes_md):
    payload = {**GOOD, "notes": "  자료 부족:\n표 수치 없음 "}
    summarizer, client = make(api_response(payload, model="claude-sonnet-5"))
    summary = summarizer.summarize([pdf, notes_md], note="memo")
    assert summary.lines == ("지난 피드백 반영", "결과 <5% 상승", "다음 할 일")
    assert summary.notes == "자료 부족: 표 수치 없음"
    assert summary.model == "claude-sonnet-5"  # served by the fallback model
    assert summary.usage == {"input_tokens": 1200, "output_tokens": 300}
    assert len(client.calls) == 1


def test_refusal_is_not_retried(pdf):
    refusal = api_response(text="", stop_reason="refusal", stop_details=type("D", (), {"category": "cyber"})())
    summarizer, client = make(refusal)
    with pytest.raises(UserError, match="거절"):
        summarizer.summarize([pdf])
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        api_response(text="not json"),
        api_response({**GOOD, "this_week": "  "}),
        api_response(GOOD, stop_reason="max_tokens"),
    ],
)
def test_unusable_output_is_retried_once(pdf, bad):
    summarizer, client = make(bad, api_response(GOOD))
    assert summarizer.summarize([pdf]).lines[2] == "다음 할 일"
    assert len(client.calls) == 2


def test_unusable_output_twice_fails(pdf):
    summarizer, client = make(api_response(text="x"), api_response(text="y"))
    with pytest.raises(UserError, match="읽지 못했습니다"):
        summarizer.summarize([pdf])
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (status_error(anthropic.AuthenticationError, 401), "API key"),
        (status_error(anthropic.RateLimitError, 429), "사용량 제한"),
        (status_error(anthropic.BadRequestError, 400), "처리하지 못했습니다: boom"),
        (status_error(anthropic.InternalServerError, 500), "HTTP 500"),
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
            "연결하지 못했습니다",
        ),
    ],
)
def test_api_errors_become_user_errors(pdf, error, message):
    summarizer, client = make(error)
    with pytest.raises(UserError, match=message):
        summarizer.summarize([pdf])
    assert len(client.calls) == 1  # the SDK already retries 429/5xx/connection errors


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("1. 첫 줄", "첫 줄"),
        ("(2) 둘째", "둘째"),
        ("• 셋째", "셋째"),
        ("3.5% 올랐습니다", "3.5% 올랐습니다"),
        ("-5% 하락했습니다", "-5% 하락했습니다"),
        ("10x 빨라졌습니다", "10x 빨라졌습니다"),
        ("줄\n바꿈  공백", "줄 바꿈 공백"),
    ],
)
def test_clean_line(raw, clean):
    assert clean_line(raw) == clean


def test_bad_request_shows_the_api_message_not_the_sdk_dump(pdf):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "PDF exceeds page limit"}}
    error = anthropic.BadRequestError(
        f"Error code: 400 - {body}", response=httpx2.Response(400, request=request), body=body
    )
    summarizer, _ = make(error)
    with pytest.raises(UserError) as info:
        summarizer.summarize([pdf])
    assert str(info.value) == "첨부한 자료를 처리하지 못했습니다: PDF exceeds page limit"


def test_new_topic_flag(pdf):
    summarizer, _ = make(api_response({**GOOD, "new_topic": True}))
    assert summarizer.summarize([pdf]).new_topic is True


def test_declared_new_topic_is_sent_and_fixes_the_label(pdf, notes_md):
    summarizer, client = make(api_response({**GOOD, "new_topic": False}))
    summary = summarizer.summarize([pdf, notes_md], "새 주제: 의료 VLM", new_topic=True)
    texts = [b.get("text") for b in client.calls[0]["messages"][0]["content"] if b["type"] == "text"]
    assert "<new_topic>" in texts[1] and texts[2] == "<user_note>\n새 주제: 의료 VLM\n</user_note>"
    assert summary.new_topic is True  # the student's word wins over the model's flag


def test_no_new_topic_notice_by_default(pdf):
    assert all("<new_topic>" not in b.get("text", "") for b in build_content([pdf]))
