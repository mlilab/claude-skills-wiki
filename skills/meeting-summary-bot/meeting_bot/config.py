"""Settings read from environment variables (`__main__` loads `.env` first)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ConfigError

DEFAULT_MODEL = "claude-sonnet-5-5"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
MB = 1024 * 1024


def _get(env: Mapping[str, str], name: str, default: str = "") -> str:
    return (env.get(name) or default).strip()


def _require(env: Mapping[str, str], name: str) -> str:
    value = _get(env, name)
    if not value:
        raise ConfigError(f"{name} is not set (see .env.example)")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(env, name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < 1:
        raise ConfigError(f"{name} must be >= 1, got {value}")
    return value


def _id_set(env: Mapping[str, str], name: str) -> frozenset[str]:
    return frozenset(part.strip() for part in _get(env, name).split(",") if part.strip())


@dataclass(frozen=True)
class SummarizerSettings:
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    fallback: bool = True  # server-side refusal fallback ("default" routing)
    max_tokens: int = 16000
    max_file_bytes: int = 20 * MB
    max_total_bytes: int = 20 * MB  # base64 adds ~33%; the API request limit is 32 MB

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SummarizerSettings:
        env = os.environ if env is None else env
        _require(env, "ANTHROPIC_API_KEY")  # read by the SDK itself; checked here to fail fast
        effort = _get(env, "SUMMARY_EFFORT", "medium").lower()
        if effort not in EFFORT_LEVELS:
            raise ConfigError(f"SUMMARY_EFFORT must be one of {', '.join(EFFORT_LEVELS)}, got {effort!r}")
        fallback = _get(env, "SUMMARY_FALLBACK", "default").lower()
        if fallback not in ("default", "off"):
            raise ConfigError(f"SUMMARY_FALLBACK must be 'default' or 'off', got {fallback!r}")
        return cls(
            model=_get(env, "SUMMARY_MODEL", DEFAULT_MODEL),
            effort=effort,
            fallback=fallback == "default",
            max_file_bytes=_positive_int(env, "MAX_FILE_MB", 20) * MB,
            max_total_bytes=_positive_int(env, "MAX_TOTAL_MB", 20) * MB,
        )


@dataclass(frozen=True)
class SlackSettings:
    bot_token: str
    app_token: str
    allowed_user_ids: frozenset[str] = frozenset()  # empty = everyone in the workspace
    allowed_channel_ids: frozenset[str] = frozenset()  # empty = any channel the bot is in
    max_concurrent_jobs: int = 2

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SlackSettings:
        env = os.environ if env is None else env
        bot_token = _require(env, "SLACK_BOT_TOKEN")
        app_token = _require(env, "SLACK_APP_TOKEN")
        if not bot_token.startswith("xoxb-"):
            raise ConfigError("SLACK_BOT_TOKEN must be a bot token (xoxb-...)")
        if not app_token.startswith("xapp-"):
            raise ConfigError("SLACK_APP_TOKEN must be an app-level token (xapp-...)")
        return cls(
            bot_token=bot_token,
            app_token=app_token,
            allowed_user_ids=_id_set(env, "ALLOWED_USER_IDS"),
            allowed_channel_ids=_id_set(env, "ALLOWED_CHANNEL_IDS"),
            max_concurrent_jobs=_positive_int(env, "MAX_CONCURRENT_JOBS", 2),
        )

    def allows(self, user: str, channel: str, *, is_dm: bool) -> bool:
        if self.allowed_user_ids and user not in self.allowed_user_ids:
            return False
        return is_dm or not self.allowed_channel_ids or channel in self.allowed_channel_ids
