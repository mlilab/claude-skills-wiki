"""Command line.

python -m meeting_bot                      # run the Slack bot (same as `serve`)
python -m meeting_bot summarize a.pdf b.md # summarize local files without Slack
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import anthropic
from dotenv import find_dotenv, load_dotenv

from . import formatting
from .config import SlackSettings, SummarizerSettings
from .errors import ConfigError, UserError
from .files import Kind, load_local, validate
from .summarizer import Summarizer


def _summarizer(settings: SummarizerSettings) -> Summarizer:
    return Summarizer(anthropic.Anthropic(), settings)


def cmd_serve() -> int:
    from .slack_app import SummaryBot, serve

    summarizer_settings = SummarizerSettings.from_env()
    slack_settings = SlackSettings.from_env()
    bot = SummaryBot(
        slack_settings,
        _summarizer(summarizer_settings),
        max_file_bytes=summarizer_settings.max_file_bytes,
        max_total_bytes=summarizer_settings.max_total_bytes,
    )
    serve(slack_settings, bot)
    return 0


def cmd_summarize(paths: list[str], note: str, new_topic: bool) -> int:
    settings = SummarizerSettings.from_env()
    files = [load_local(Path(p)) for p in paths]
    validate(files, max_file_bytes=settings.max_file_bytes, max_total_bytes=settings.max_total_bytes)
    summary = _summarizer(settings).summarize(files, note, new_topic=new_topic)
    link = next(f.name for f in files if f.kind is Kind.MATERIAL)
    print(formatting.summary_text(summary.lines, link, for_slack=False))
    if summary.notes:
        print(f"\n참고: {summary.notes}")
    print(f"\n[model={summary.model} usage={summary.usage}]", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meeting-bot", description="Weekly 3-line meeting summary bot")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the Slack bot (default)")
    p = sub.add_parser("summarize", help="summarize local files without Slack (prompt testing)")
    p.add_argument("files", nargs="+", help="PDF/image material, plus optional .md/.txt background notes")
    p.add_argument("--note", default="", help="extra memo, like the text of the Slack message")
    p.add_argument("--new-topic", action="store_true", help="this meeting starts a new topic")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "summarize":
            return cmd_summarize(args.files, args.note, args.new_topic)
        return cmd_serve()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except (UserError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
