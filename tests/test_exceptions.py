"""Tests for the custom exception hierarchy."""

from __future__ import annotations

import pytest

from bot.exceptions import (
    BotError,
    ConfigurationError,
    LubeLoggerApiError,
    LubeLoggerUnreachableError,
    ParseError,
)


class TestBotErrorHierarchy:
    """All custom exceptions inherit from BotError."""

    def test_configuration_error_is_bot_error(self) -> None:
        with pytest.raises(BotError):
            raise ConfigurationError("missing TOKEN")

    def test_parse_error_is_bot_error(self) -> None:
        with pytest.raises(BotError):
            raise ParseError(command="/refuel", hint="expected a number")

    def test_lubelogger_unreachable_is_bot_error(self) -> None:
        with pytest.raises(BotError):
            raise LubeLoggerUnreachableError("timeout")

    def test_lubelogger_api_error_is_bot_error(self) -> None:
        with pytest.raises(BotError):
            raise LubeLoggerApiError(status_code=500, message="Internal Server Error")


class TestParseError:
    """ParseError carries command and hint attributes."""

    def test_attributes(self) -> None:
        err = ParseError(command="/refuel", hint="liters must be positive")
        assert err.command == "/refuel"
        assert err.hint == "liters must be positive"

    def test_message(self) -> None:
        err = ParseError(command="/refuel", hint="liters must be positive")
        assert str(err) == "Failed to parse /refuel: liters must be positive"


class TestLubeLoggerApiError:
    """LubeLoggerApiError carries status_code and message attributes."""

    def test_attributes(self) -> None:
        err = LubeLoggerApiError(status_code=404, message="Vehicle not found")
        assert err.status_code == 404
        assert err.message == "Vehicle not found"

    def test_message(self) -> None:
        err = LubeLoggerApiError(status_code=404, message="Vehicle not found")
        assert str(err) == "LubeLogger API error 404: Vehicle not found"
