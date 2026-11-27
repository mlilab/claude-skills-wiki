"""Locate a local copy of upstream's optional exemplar bank."""

import os
from pathlib import Path


SKILL = Path(__file__).resolve().parent.parent
BANK_FILES = ("moves.jsonl", "paragraphs.jsonl", "phrasebank.csv")
SETUP_GUIDE = "See README.md under Optional paper examples and CVPR template."


def exemplar_dir():
    configured = os.environ.get("BESTPAPER_EXEMPLAR_DIR")
    if configured:
        return Path(configured).expanduser()
    return SKILL / ".upstream/skills/bestpaper-writing/references/exemplars"
