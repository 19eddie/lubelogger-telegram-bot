"""Tests for the /help command handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from telegram.constants import ParseMode

from bot.command_catalog import COMMAND_CATALOG
from bot.handlers.help import build_help_message, help_command


def _make_update_and_context(language: str = "en") -> tuple[MagicMock, MagicMock]:
    """Create minimal Telegram mocks for help handler tests."""
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value=language)

    context = MagicMock()
    context.bot_data = {"config_store": config_store}
    return update, context


class TestHelpCommand:
    """Tests for catalog-generated localized /help output."""

    def test_help_message_is_formatted_for_telegram(self) -> None:
        """Commands stay readable while arguments use compact monospace markup."""
        message = build_help_message("en")

        assert message.startswith("<b>Available commands:</b>\n\n<b>General</b>")
        assert "<b>Recording</b>" in message
        assert "<b>History and status</b>" in message
        for command in COMMAND_CATALOG:
            if command.show_in_help:
                assert f"/{command.name}" in message
        assert (
            "<code>&lt;odo&gt; &lt;liters&gt; &lt;cost&gt; [--date YYYY-MM-DD] [--missed]</code>"
        ) in message

    def test_help_message_escapes_html_placeholders(self) -> None:
        """Usage placeholders are escaped so Telegram does not parse them as tags."""
        message = build_help_message("en")

        assert "<odo>" not in message
        assert "&lt;odo&gt;" in message

    async def test_help_lists_available_commands(self) -> None:
        update, context = _make_update_and_context()

        await help_command(update, context)

        message = update.message.reply_text.call_args[0][0]
        assert message == build_help_message("en")
        assert update.message.reply_text.call_args.kwargs["parse_mode"] == ParseMode.HTML
        context.bot_data["config_store"].get_language.assert_awaited_once_with(123)

    async def test_help_uses_italian_translation(self) -> None:
        update, context = _make_update_and_context(language="it")

        await help_command(update, context)

        message = update.message.reply_text.call_args[0][0]
        assert message == build_help_message("it")
        assert "<b>Comandi disponibili:</b>" in message
        assert "<b>Registrazione</b>" in message
        assert "<code>&lt;odo&gt; &lt;litri&gt; &lt;costo&gt;" in message
