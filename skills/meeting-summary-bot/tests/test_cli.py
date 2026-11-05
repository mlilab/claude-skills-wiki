from __future__ import annotations

import pytest

from meeting_bot import __main__ as cli
from meeting_bot.summarizer import Summarizer
from tests.fakes import GOOD, FakeAnthropic, api_response


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # so a developer's real .env is never picked up
    for name in ("ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_summarize_prints_the_template(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = FakeAnthropic(api_response({**GOOD, "notes": "표 수치 없음"}))
    monkeypatch.setattr(cli, "_summarizer", lambda settings: Summarizer(client, settings))
    (tmp_path / "week.pdf").write_bytes(b"%PDF")
    (tmp_path / "notes.md").write_text("지난 피드백", encoding="utf-8")

    assert cli.main(["summarize", "week.pdf", "notes.md", "--note", "새 주제", "--new-topic"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("미팅 자료: week.pdf\n---\n")
    assert "2. 결과 <5% 상승" in out  # not Slack-escaped on the terminal
    assert "참고: 표 수치 없음" in out
    content = client.calls[0]["messages"][0]["content"]
    assert content[-2]["text"] == "<user_note>\n새 주제\n</user_note>"
    assert content[-3]["text"].startswith("<new_topic>")


def test_missing_api_key_is_a_config_error(tmp_path, capsys):
    (tmp_path / "week.pdf").write_bytes(b"%PDF")
    assert cli.main(["summarize", "week.pdf"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_serve_requires_slack_tokens(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cli.main([]) == 2
    assert "SLACK_BOT_TOKEN" in capsys.readouterr().err


def test_user_errors_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    assert cli.main(["summarize", "notes.md"]) == 1
    assert "미팅자료" in capsys.readouterr().err
