"""Everything the bot says in Slack: conversation texts, buttons, and the summary card."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# --------------------------------------------------------------------------- conversation
NEW_TOPIC_ACTION = "new_topic"
SKIP_ACTION = "skip_notes"
RESTART_ACTION = "restart"
NEW_TOPIC_LABEL_BUTTON = "🆕 새 주제예요"
SKIP_LABEL = "📄 노트 없이 진행"
SKIP_NOW_LABEL = "⚡ 노트 없이 바로 요약"
RESTART_LABEL = "🔄 새 요약 시작하기"

# Slack renders *bold* only when the closing * is followed by a space or line end, so bold
# spans never touch a Korean particle or "(" (e.g. "*새 주제*라면" shows literal asterisks).
GREETING_TEXT = """\
👋 안녕하세요! 이번 주 미팅 3줄 요약을 도와드릴게요.

*1단계* 지난 미팅들의 피드백 노트(.md / .txt)를 보내 주세요.
이번 주부터 새 주제라면 아래 버튼을 누르거나, "새 주제: (한두 줄 설명)"처럼 보내 주세요.
*2단계* 이번 주 미팅자료(PDF 또는 이미지)를 보내 주세요.

두 파일을 한 번에 보내셔도 돼요. 처음부터 다시 하려면 "처음부터"라고 보내 주세요."""

RESET_PREFIX = "🔄 처음부터 다시 시작할게요.\n\n"
NEED_MATERIAL_TEXT = "*2단계* 이번 주 미팅자료(PDF 또는 이미지)를 보내 주세요 📄"
NEED_CONTEXT_TEXT = "요약하기 전에 지난 미팅들의 피드백 노트를 보내 주시거나, 새 주제라면 알려 주세요."
WORKING_TEXT = (
    "🙌 자료를 모두 받았어요! 지금 읽고 3줄 요약을 쓰고 있어요.\n보통 30초~1분 정도 걸려요. 잠시만 기다려 주세요 ⏳"
)
DONE_TEXT = "✨ 요약을 마쳤어요. 다른 미팅 자료도 요약하려면 아래 버튼을 눌러 주세요."
BUSY_TEXT = "지금 요약을 쓰고 있어요. 끝난 뒤에 다시 보내 주세요 🙏"
NOT_ALLOWED_TEXT = "이 채널이나 계정에서는 요약 봇을 쓸 수 없어요. 관리자에게 문의해 주세요."
INTERNAL_ERROR_TEXT = (
    "죄송해요, 알 수 없는 오류로 요약하지 못했어요. 잠시 후 다시 시도해 주시고, 계속되면 관리자에게 알려 주세요."
)


def ack_lines(
    *,
    notes: Sequence[str] = (),
    materials: Sequence[str] = (),
    new_topic: bool = False,
    skip_notes: bool = False,
    memo: bool = False,
) -> list[str]:
    """One confirmation line per thing the student just gave us."""
    lines = []
    if notes:
        lines.append(f"✅ 피드백 노트를 확인했어요: {_names(notes)}")
    if new_topic:
        lines.append("✅ 새 주제로 기록했어요. 새 주제를 한두 줄로 설명해 주시면 1번 줄에 반영할게요. (선택)")
    if skip_notes:
        lines.append("✅ 피드백 노트 없이 진행할게요.")
    if materials:
        lines.append(f"📄 미팅자료를 받았어요: {_names(materials)}")
    if memo:
        lines.append("📝 보내 주신 메모도 요약할 때 함께 참고할게요.")
    return lines


def choice_text(action_id: str) -> str:
    """Shown on a clicked message in place of its buttons."""
    return {
        NEW_TOPIC_ACTION: f"→ {NEW_TOPIC_LABEL_BUTTON}",
        SKIP_ACTION: "→ 피드백 노트 없이 진행",
        RESTART_ACTION: f"→ {RESTART_LABEL}",
    }[action_id]


def chosen_blocks(message: dict[str, Any], action_id: str) -> tuple[str, list[dict[str, Any]]]:
    """The clicked message redrawn without its buttons, with the choice underneath.

    The original text comes from the message's own section blocks: the payload's flat
    `text` field has its line breaks collapsed, so reusing it would squash the message.
    """
    sections = [b for b in message.get("blocks") or [] if b.get("type") == "section" and b.get("text")]
    original = "\n\n".join(b["text"]["text"] for b in sections) or message.get("text", "")
    choice = choice_text(action_id)
    return f"{original}\n\n{choice}", [_mrkdwn(original), _mrkdwn(choice)]


def choice_blocks(text: str, *, skip_label: str) -> list[dict[str, Any]]:
    """`text` with the two step-1 buttons under it."""
    return [
        _mrkdwn(text),
        {
            "type": "actions",
            "elements": [
                _button(NEW_TOPIC_LABEL_BUTTON, NEW_TOPIC_ACTION),
                _button(skip_label, SKIP_ACTION),
            ],
        },
    ]


def restart_blocks(text: str) -> list[dict[str, Any]]:
    """`text` with a "start a new summary" button under it (after a summary or an error)."""
    return [_mrkdwn(text), {"type": "actions", "elements": [_button(RESTART_LABEL, RESTART_ACTION)]}]


def notes_post(notes: str) -> str:
    return f"💡 참고: {escape(notes)}"


def error_post(message: str) -> str:
    return f"⚠️ {escape(message)}"


# --------------------------------------------------------------------------- summary card
INTRO = "오늘 미팅 자료에 대한 3줄 요약은 다음과 같습니다."
LABELS = ("지난 미팅", "이번 결과", "논의 · Todo")
NEW_TOPIC_LABEL = "새 주제"


def escape(text: str) -> str:
    """Escape the three characters Slack treats as control sequences."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def labels(new_topic: bool) -> tuple[str, str, str]:
    return (NEW_TOPIC_LABEL if new_topic else LABELS[0], LABELS[1], LABELS[2])


def summary_text(lines: Sequence[str], material: str, *, for_slack: bool = True) -> str:
    """The lab's plain template: notification fallback in Slack, and the CLI output."""
    clean = escape if for_slack else str
    body = "\n".join(f"{i}. {clean(line)}" for i, line in enumerate(lines, 1))
    return f"미팅 자료: {material}\n---\n{INTRO}\n\n{body}"


def summary_blocks(lines: Sequence[str], *, new_topic: bool, file_name: str, link: str | None) -> list[dict[str, Any]]:
    """The summary card: same template, with each line under a bold numbered label."""
    name = escape(file_name).replace("|", "¦")
    material = f"<{link}|{name}>" if link else name
    blocks: list[dict[str, Any]] = [_mrkdwn(f"미팅 자료: {material}"), {"type": "divider"}, _mrkdwn(INTRO)]
    for i, (label, line) in enumerate(zip(labels(new_topic), lines, strict=True), 1):
        blocks.append(_mrkdwn(f"*{i}. {label}*\n{escape(line)}"))
    return blocks


# --------------------------------------------------------------------------- helpers
def _names(names: Sequence[str]) -> str:
    return ", ".join(escape(n) for n in names)


def _mrkdwn(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(label: str, action_id: str) -> dict[str, Any]:
    return {"type": "button", "text": {"type": "plain_text", "text": label, "emoji": True}, "action_id": action_id}
