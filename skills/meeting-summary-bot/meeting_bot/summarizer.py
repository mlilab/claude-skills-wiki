"""Turn this week's meeting material (+ optional background notes) into the 3-line summary.

One Messages API call per request: PDFs/images go in as document/image blocks, background
notes as tagged text, and structured outputs pin the answer to exactly three fields.
"""

from __future__ import annotations

import base64
import dataclasses
import html
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import anthropic

from .config import SummarizerSettings
from .errors import UserError
from .files import InputFile, Kind, decode_text

log = logging.getLogger(__name__)

SYSTEM_PROMPT = resources.files(__package__).joinpath("prompt.md").read_text(encoding="utf-8")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
LINE_FIELDS = ("last_meeting", "this_week", "discussion")
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "last_meeting": {
            "type": "string",
            "description": "1번 줄: 지난 미팅 피드백/계획과 그에 따라 한 일 (새 주제면 출발점)",
        },
        "this_week": {"type": "string", "description": "2번 줄: 이번 실험과 결과, 예상과 다른 점과 원인 가설"},
        "discussion": {"type": "string", "description": "3번 줄: 의견을 받고 싶은 점과 구체적인 next step"},
        "new_topic": {"type": "boolean", "description": "1번 줄을 새 주제 형태로 썼으면 true"},
        "notes": {"type": "string", "description": "학생에게만 보이는 메모. 없으면 빈 문자열"},
    },
    "required": [*LINE_FIELDS, "new_topic", "notes"],
    "additionalProperties": False,
}
INSTRUCTION = "위 자료로 이번 미팅의 3줄 요약을 작성해 주세요."
NEW_TOPIC_NOTICE = "<new_topic>학생이 이번 미팅부터 새 주제를 시작한다고 알려 주었습니다.</new_topic>"
_NUMBERING = re.compile(r"^\s*(?:\(?\d{1,2}[.)\]:]|[①②③④⑤]|[-*•·])(?=\s|$)\s*")
_ATTEMPTS = 2  # one retry when the output is unusable; refusals and API errors are not retried


@dataclass(frozen=True)
class Summary:
    lines: tuple[str, str, str]
    new_topic: bool = False
    notes: str = ""
    model: str = ""  # the model that actually answered (may differ after a fallback)
    usage: dict[str, Any] = field(default_factory=dict)


class _UnusableOutput(UserError):
    pass


def build_content(files: Sequence[InputFile], note: str = "", *, new_topic: bool = False) -> list[dict[str, Any]]:
    """User-turn content blocks: material first, then feedback notes, new-topic notice, memo, instruction."""
    blocks: list[dict[str, Any]] = []
    for f in files:
        if f.kind is not Kind.MATERIAL:
            continue
        data = base64.standard_b64encode(f.data).decode("ascii")
        if f.is_pdf:
            blocks.append(
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": f.media_type, "data": data},
                    "title": f.name,
                }
            )
        else:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": f.media_type, "data": data}})
    for f in files:
        if f.kind is Kind.BACKGROUND:
            text = decode_text(f.data).strip()
            blocks.append({"type": "text", "text": f'<background file="{html.escape(f.name)}">\n{text}\n</background>'})
    if new_topic:
        blocks.append({"type": "text", "text": NEW_TOPIC_NOTICE})
    if note.strip():
        blocks.append({"type": "text", "text": f"<user_note>\n{note.strip()}\n</user_note>"})
    blocks.append({"type": "text", "text": INSTRUCTION})
    return blocks


def clean_line(text: str) -> str:
    """Collapse whitespace and drop a leading "1." / "-" style marker (but not "3.5%")."""
    return _NUMBERING.sub("", " ".join(text.split()), count=1).strip()


def parse_response(response: Any) -> Summary:
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        log.warning("refusal: category=%s request_id=%s", category, getattr(response, "_request_id", None))
        raise UserError("모델이 이 자료의 요약을 거절했습니다. 자료 내용을 확인한 뒤 다시 시도해 주세요.")
    if response.stop_reason == "max_tokens":
        raise _UnusableOutput("응답이 길이 제한에 걸려 잘렸습니다. 다시 시도해 주세요.")
    text = next((block.text for block in response.content if block.type == "text"), None)
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        raise _UnusableOutput("요약 결과를 읽지 못했습니다. 다시 시도해 주세요.") from None
    lines = tuple(clean_line(str(data.get(name, ""))) for name in LINE_FIELDS)
    if not all(lines):
        raise _UnusableOutput("요약 결과에 빈 줄이 있습니다. 다시 시도해 주세요.")
    usage = response.usage
    return Summary(
        lines=lines,  # type: ignore[arg-type]  # exactly three by construction
        new_topic=bool(data.get("new_topic", False)),
        notes=" ".join(str(data.get("notes", "")).split()),
        model=response.model,
        usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    )


def _api_message(error: anthropic.APIStatusError) -> str:
    """The API's own error text (e.g. "PDF exceeds page limit"), not the SDK's "Error code: 400 - {...}"."""
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict) and body["error"].get("message"):
        return str(body["error"]["message"])
    return error.message


def to_user_error(error: anthropic.APIError) -> UserError:
    """Map SDK errors to messages for the Slack user (most specific first)."""
    if isinstance(error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return UserError("서버의 Anthropic API key 설정에 문제가 있습니다. 관리자에게 알려 주세요.")
    if isinstance(error, anthropic.RateLimitError):
        return UserError("API 사용량 제한에 걸렸습니다. 잠시 후 다시 시도해 주세요.")
    if isinstance(error, anthropic.BadRequestError):
        return UserError(f"첨부한 자료를 처리하지 못했습니다: {_api_message(error)}")
    if isinstance(error, anthropic.APIConnectionError):  # includes timeouts
        return UserError("Anthropic API에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    if isinstance(error, anthropic.APIStatusError):
        return UserError(f"Anthropic API 일시 오류입니다 (HTTP {error.status_code}). 잠시 후 다시 시도해 주세요.")
    return UserError("Anthropic API 호출에 실패했습니다. 잠시 후 다시 시도해 주세요.")


class Summarizer:
    def __init__(self, client: anthropic.Anthropic, settings: SummarizerSettings):
        self.client = client
        self.settings = settings

    def build_request(self, files: Sequence[InputFile], note: str = "", *, new_topic: bool = False) -> dict[str, Any]:
        s = self.settings
        request: dict[str, Any] = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_content(files, note, new_topic=new_topic)}],
            "output_config": {
                "effort": s.effort,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        }
        if s.fallback:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def summarize(self, files: Sequence[InputFile], note: str = "", *, new_topic: bool = False) -> Summary:
        """`new_topic`: the student said this meeting starts a new topic (line 1 and its label follow)."""
        request = self.build_request(files, note, new_topic=new_topic)
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                response = self.client.beta.messages.create(**request)
            except anthropic.APIError as e:
                log.warning("API error: %s", e)
                raise to_user_error(e) from e
            try:
                summary = parse_response(response)
            except _UnusableOutput as e:
                log.warning("unusable output (attempt %d/%d): %s", attempt, _ATTEMPTS, e)
                if attempt == _ATTEMPTS:
                    raise
                continue
            log.info(
                "summary ok: model=%s usage=%s request_id=%s",
                summary.model,
                summary.usage,
                getattr(response, "_request_id", None),
            )
            # The student's own word decides the label; the model only decides when they said nothing.
            return dataclasses.replace(summary, new_topic=True) if new_topic else summary
        raise AssertionError("unreachable")
