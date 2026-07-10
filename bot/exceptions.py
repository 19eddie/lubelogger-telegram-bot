"""Custom exception hierarchy for the LubeLogger Telegram Bot."""

from __future__ import annotations


class BotError(Exception):
    """Base exception for all bot errors."""


class ConfigurationError(BotError):
    """Raised when required configuration is missing or invalid."""


class ParseError(BotError):
    """Raised when command arguments cannot be parsed."""

    def __init__(self, command: str, hint: str) -> None:
        self.command = command
        self.hint = hint
        super().__init__(f"Failed to parse {command}: {hint}")


class LubeLoggerUnreachableError(BotError):
    """Raised when LubeLogger cannot be reached (timeout or connection error)."""


class LubeLoggerApiError(BotError):
    """Raised when LubeLogger returns a non-success response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"LubeLogger API error {status_code}: {message}")
