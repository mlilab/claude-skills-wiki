"""Shared fixtures."""

from __future__ import annotations

import pytest

from meeting_bot.files import InputFile, Kind


@pytest.fixture
def pdf() -> InputFile:
    return InputFile("week.pdf", Kind.MATERIAL, "application/pdf", b"%PDF-1.7 fake", link="https://slack/F1")


@pytest.fixture
def notes_md() -> InputFile:
    return InputFile("notes.md", Kind.BACKGROUND, "text/plain", "지난 피드백: ablation 더".encode())
