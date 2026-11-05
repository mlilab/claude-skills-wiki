"""Exceptions shared across the package."""


class UserError(Exception):
    """An expected failure whose message is safe to show to the Slack user (Korean)."""


class ConfigError(RuntimeError):
    """Missing or invalid configuration; raised at startup."""
