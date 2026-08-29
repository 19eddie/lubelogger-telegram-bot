"""Tests for the command registry service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.i18n import available_locales
from bot.services.command_registry import commands_for, COMMANDS


class TestCommandsFor:
    """Tests for the pure commands_for function."""

    def test_commands_for_en(self) -> None:
        """commands_for('en') returns a list of BotCommand objects in English."""
        commands = commands_for("en")
        assert len(commands) == len(COMMANDS)
        assert commands[0].command == "start"
        assert "Start" in commands[0].description

    def test_commands_for_it(self) -> None:
        """commands_for('it') returns a list of BotCommand objects in Italian."""
        commands = commands_for("it")
        assert len(commands) == len(COMMANDS)
        assert commands[0].command == "start"
        # Italian description will differ from English
        assert len(commands[0].description) > 0

    def test_commands_tuple_has_expected_commands(self) -> None:
        """COMMANDS tuple contains all expected command names."""
        command_names = [name for name, _key in COMMANDS]
        expected = [
            "start",
            "fuel",
            "service",
            "km",
            "last",
            "vehicle",
            "status",
            "queue",
            "lang",
            "cancel",
        ]
        assert command_names == expected


@pytest.mark.parametrize("lang", available_locales())
def test_property_commands_complete(lang: str) -> None:
    """Property 8: The registered command list is complete in every locale.

    **Validates: Requirements 2.1, 2.2**

    For each supported locale, commands_for(lang) must return a list of len(COMMANDS) with no
    missing descriptions. The list contains all ten commands (start, fuel, service, km, last,
    vehicle, status, queue, lang, cancel) in that order, each with a non-empty description.
    """
    commands = commands_for(lang)

    # Property: exactly ten commands, one per registered command tuple
    assert len(commands) == len(COMMANDS), (
        f"Expected {len(COMMANDS)} commands for {lang}, got {len(commands)}"
    )

    # Property: command names match COMMANDS in order
    expected_names = [name for name, _ in COMMANDS]
    actual_names = [cmd.command for cmd in commands]
    assert actual_names == expected_names, (
        f"Command order or names mismatch for {lang}. "
        f"Expected {expected_names}, got {actual_names}"
    )

    # Property: each command has a non-empty description
    for cmd in commands:
        assert cmd.description, (
            f"Command '{cmd.command}' in language '{lang}' has empty description"
        )
        assert len(cmd.description) > 0, (
            f"Command '{cmd.command}' in language '{lang}' has zero-length description"
        )

    # Property: all expected commands are present
    expected_set = {"start", "fuel", "service", "km", "last", "vehicle", "status", "queue", "lang", "cancel"}
    actual_set = {cmd.command for cmd in commands}
    assert actual_set == expected_set, (
        f"Command set mismatch for {lang}. "
        f"Expected {expected_set}, got {actual_set}"
    )

