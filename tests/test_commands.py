"""Property and unit tests for commands module."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.commands import COMMANDS, build_commands, register_commands


@settings(max_examples=100)
@given(lang=st.sampled_from(["en", "it"]))
def test_property_command_descriptions_completeness(lang: str) -> None:
    """Property 5: Command descriptions completeness.

    # Feature: telegram-ux-improvements, Property 5: Command descriptions completeness
    """
    commands = build_commands(lang)

    assert len(commands) == 9
    for cmd in commands:
        assert cmd.description
        assert len(cmd.description) > 0


class TestBuildCommands:
    """Unit tests for build_commands."""

    def test_returns_nine_commands_en(self) -> None:
        """build_commands('en') returns exactly 9 BotCommand objects."""
        commands = build_commands("en")
        assert len(commands) == 9

    def test_command_names_match(self) -> None:
        """All command names match the COMMANDS list."""
        commands = build_commands("en")
        names = [c.command for c in commands]
        assert names == COMMANDS

    def test_descriptions_are_non_empty(self) -> None:
        """All command descriptions are non-empty strings."""
        commands = build_commands("en")
        for cmd in commands:
            assert isinstance(cmd.description, str)
            assert len(cmd.description) > 0


class TestRegisterCommands:
    """Unit tests for register_commands."""

    async def test_calls_set_my_commands(self) -> None:
        """register_commands calls bot.set_my_commands."""
        app = MagicMock()
        app.bot.set_my_commands = AsyncMock()

        await register_commands(app)

        app.bot.set_my_commands.assert_called_once()

    async def test_logs_warning_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """register_commands logs WARNING when set_my_commands fails."""
        app = MagicMock()
        app.bot.set_my_commands = AsyncMock(side_effect=Exception("API error"))

        with caplog.at_level(logging.WARNING):
            await register_commands(app)

        assert "Failed to register bot commands" in caplog.text

    async def test_does_not_raise_on_failure(self) -> None:
        """register_commands does not crash when set_my_commands raises."""
        app = MagicMock()
        app.bot.set_my_commands = AsyncMock(side_effect=RuntimeError("Network error"))

        # Should not raise
        await register_commands(app)
