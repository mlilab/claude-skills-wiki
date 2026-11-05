from __future__ import annotations

import pytest

from meeting_bot import formatting
from meeting_bot.config import MB, SlackSettings, SummarizerSettings
from meeting_bot.errors import ConfigError, UserError
from meeting_bot.files import InputFile, Kind, classify, decode_text, load_local, validate

# -------------------------------------------------------------------- files


@pytest.mark.parametrize(
    ("name", "mimetype", "expected"),
    [
        ("week.PDF", None, (Kind.MATERIAL, "application/pdf")),
        ("fig.jpeg", None, (Kind.MATERIAL, "image/jpeg")),
        ("notes.md", "application/octet-stream", (Kind.BACKGROUND, "text/plain")),
        ("Untitled", "text/plain", (Kind.BACKGROUND, "text/plain")),
        ("scan", "image/png; charset=binary", (Kind.MATERIAL, "image/png")),
    ],
)
def test_classify(name, mimetype, expected):
    assert classify(name, mimetype) == expected


def test_classify_rejects_slides():
    with pytest.raises(UserError, match="slides.pptx"):
        classify("slides.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")


def test_decode_text():
    assert decode_text("﻿피드백".encode()) == "피드백"
    assert decode_text("피드백".encode("cp949")) == "피드백"
    assert decode_text(b"\xff\xfe\xfa") != ""  # never raises


def test_validate():
    pdf = InputFile("a.pdf", Kind.MATERIAL, "application/pdf", b"x" * 10)
    md = InputFile("b.md", Kind.BACKGROUND, "text/plain", b"y" * 10)
    validate([pdf, md], max_file_bytes=10, max_total_bytes=20)
    with pytest.raises(UserError, match="미팅자료"):
        validate([md], max_file_bytes=10, max_total_bytes=20)
    with pytest.raises(UserError, match="a.pdf"):
        validate([pdf], max_file_bytes=9, max_total_bytes=20)
    with pytest.raises(UserError, match="합계"):
        validate([pdf, md], max_file_bytes=10, max_total_bytes=19)


def test_load_local(tmp_path):
    path = tmp_path / "w.pdf"
    path.write_bytes(b"%PDF")
    assert load_local(path) == InputFile("w.pdf", Kind.MATERIAL, "application/pdf", b"%PDF")


# ------------------------------------------------------------------- config
def test_summarizer_settings_defaults():
    s = SummarizerSettings.from_env({"ANTHROPIC_API_KEY": "sk-ant-x"})
    assert (s.model, s.effort, s.fallback, s.max_total_bytes) == ("claude-sonnet-5-5", "medium", True, 20 * MB)


def test_summarizer_settings_overrides():
    s = SummarizerSettings.from_env(
        {
            "ANTHROPIC_API_KEY": "k",
            "SUMMARY_MODEL": "claude-opus-5-5",
            "SUMMARY_EFFORT": "HIGH",
            "SUMMARY_FALLBACK": "off",
            "MAX_FILE_MB": "5",
        }
    )
    assert (s.model, s.effort, s.fallback, s.max_file_bytes) == ("claude-opus-5-5", "high", False, 5 * MB)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"ANTHROPIC_API_KEY": "k", "SUMMARY_EFFORT": "extreme"},
        {"ANTHROPIC_API_KEY": "k", "SUMMARY_FALLBACK": "yes"},
        {"ANTHROPIC_API_KEY": "k", "MAX_FILE_MB": "0"},
        {"ANTHROPIC_API_KEY": "k", "MAX_TOTAL_MB": "big"},
    ],
)
def test_summarizer_settings_invalid(env):
    with pytest.raises(ConfigError):
        SummarizerSettings.from_env(env)


def test_slack_settings():
    s = SlackSettings.from_env(
        {
            "SLACK_BOT_TOKEN": "xoxb-1",
            "SLACK_APP_TOKEN": "xapp-1",
            "ALLOWED_USER_IDS": "U1, U2,",
            "ALLOWED_CHANNEL_IDS": "C1",
        }
    )
    assert s.allowed_user_ids == {"U1", "U2"}
    assert s.allows("U1", "C1", is_dm=False)
    assert not s.allows("U1", "C2", is_dm=False)
    assert s.allows("U1", "D9", is_dm=True)  # DMs ignore the channel list
    assert not s.allows("U3", "D9", is_dm=True)


@pytest.mark.parametrize(
    "env",
    [
        {"SLACK_APP_TOKEN": "xapp-1"},
        {"SLACK_BOT_TOKEN": "xapp-1", "SLACK_APP_TOKEN": "xapp-1"},
        {"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_APP_TOKEN": "xoxb-1"},
    ],
)
def test_slack_settings_invalid(env):
    with pytest.raises(ConfigError):
        SlackSettings.from_env(env)


# --------------------------------------------------------------- formatting
def test_summary_text_template():
    assert formatting.summary_text(["a", "b <c>", "d & e"], "https://slack/F1") == (
        "미팅 자료: https://slack/F1\n---\n오늘 미팅 자료에 대한 3줄 요약은 다음과 같습니다.\n\n"
        "1. a\n2. b &lt;c&gt;\n3. d &amp; e"
    )
    assert formatting.summary_text(["a", "<b>", "c"], "w.pdf", for_slack=False).endswith("2. <b>\n3. c")


def test_summary_blocks():
    blocks = formatting.summary_blocks(["a", "b <c>", "c"], new_topic=False, file_name="w|k.pdf", link="https://s/F1")
    texts = [b["text"]["text"] for b in blocks if b["type"] == "section"]
    assert texts == [
        "미팅 자료: <https://s/F1|w¦k.pdf>",
        "오늘 미팅 자료에 대한 3줄 요약은 다음과 같습니다.",
        "*1. 지난 미팅*\na",
        "*2. 이번 결과*\nb &lt;c&gt;",
        "*3. 논의 · Todo*\nc",
    ]
    assert blocks[1] == {"type": "divider"}
    new = formatting.summary_blocks(["a", "b", "c"], new_topic=True, file_name="w.pdf", link=None)
    assert new[0]["text"]["text"] == "미팅 자료: w.pdf"
    assert new[3]["text"]["text"] == "*1. 새 주제*\na"


def test_error_and_notes_are_escaped():
    assert formatting.error_post("<!channel>") == "⚠️ &lt;!channel&gt;"
    assert formatting.notes_post("a<b") == "💡 참고: a&lt;b"
    assert formatting.ack_lines(notes=["a<b.md"]) == ["✅ 피드백 노트를 확인했어요: a&lt;b.md"]


def test_ack_lines_and_choice_blocks():
    assert formatting.ack_lines(notes=["a.md"], materials=["w.pdf"], memo=True) == [
        "✅ 피드백 노트를 확인했어요: a.md",
        "📄 미팅자료를 받았어요: w.pdf",
        "📝 보내 주신 메모도 요약할 때 함께 참고할게요.",
    ]
    assert formatting.ack_lines(new_topic=True)[0].startswith("✅ 새 주제로 기록했어요")
    blocks = formatting.choice_blocks("질문", skip_label=formatting.SKIP_NOW_LABEL)
    assert blocks[0]["text"]["text"] == "질문"
    labels = [(e["text"]["text"], e["action_id"]) for e in blocks[1]["elements"]]
    assert labels == [
        (formatting.NEW_TOPIC_LABEL_BUTTON, formatting.NEW_TOPIC_ACTION),
        (formatting.SKIP_NOW_LABEL, formatting.SKIP_ACTION),
    ]


def test_bold_spans_render_in_slack():
    """Slack shows literal asterisks when a closing * touches a letter or "(" (e.g. "*새 주제*라면")."""
    import re

    card = formatting.summary_blocks(["a", "b", "c"], new_topic=True, file_name="w", link=None)
    texts = [
        formatting.GREETING_TEXT,
        formatting.NEED_MATERIAL_TEXT,
        formatting.NEED_CONTEXT_TEXT,
        formatting.WORKING_TEXT,
        formatting.DONE_TEXT,
        *formatting.ack_lines(notes=["a.md"], materials=["b.pdf"], new_topic=True, skip_notes=True, memo=True),
        *(b["text"]["text"] for b in card if b["type"] == "section"),
    ]
    for text in texts:
        for m in re.finditer(r"\*[^*\n]+\*", text):
            after = text[m.end() : m.end() + 1]
            assert after in ("", " ", "\n"), f"bold span {m.group()!r} is followed by {after!r} in {text!r}"
