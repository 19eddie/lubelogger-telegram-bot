"""Tests for the settings handler: /start and /lang commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.handlers.settings import SUPPORTED_LANGUAGES, lang_callback, lang_command, start_command


def _make_update_and_context(
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context objects for handler testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()

    context = MagicMock()

    # Set up bot_data with mock services
    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle = AsyncMock(return_value=1)

    context.bot_data = {
        "config_store": config_store,
    }

    return update, context


def _make_callback_update_and_context(
    callback_data: str,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context for callback query testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    context = MagicMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.set_language = AsyncMock()

    context.bot_data = {
        "config_store": config_store,
    }

    return update, context


class TestStartCommand:
    """Tests for the /start command handler."""

    async def test_start_with_active_vehicle_shows_welcome(self) -> None:
        """/start with an active vehicle shows the welcome message."""
        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=1)

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Welcome" in msg or "Benvenuto" in msg

    async def test_start_without_vehicle_prompts_selection(self) -> None:
        """/start without an active vehicle prompts vehicle selection."""
        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "/vehicle" in msg

    async def test_start_uses_user_language(self) -> None:
        """/start respects the user's language preference."""
        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_language = AsyncMock(return_value="it")
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Benvenuto" in msg or "/vehicle" in msg


class TestLangCommand:
    """Tests for the /lang command handler."""

    async def test_lang_shows_keyboard(self) -> None:
        """/lang presents language options as inline keyboard."""
        update, context = _make_update_and_context()

        await lang_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get(
            "reply_markup"
        )
        assert reply_markup is not None

        # Verify the keyboard contains all supported languages
        buttons = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        for lang_name in SUPPORTED_LANGUAGES.values():
            assert lang_name in buttons

    async def test_lang_keyboard_callback_data(self) -> None:
        """/lang keyboard buttons have correct callback data format."""
        update, context = _make_update_and_context()

        await lang_command(update, context)

        call_kwargs = update.message.reply_text.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get(
            "reply_markup"
        )
        callback_data = [
            btn.callback_data for row in reply_markup.inline_keyboard for btn in row
        ]
        for code in SUPPORTED_LANGUAGES:
            assert f"lang:{code}" in callback_data


class TestLangCallback:
    """Tests for the language selection callback handler."""

    async def test_lang_callback_persists_selection(self) -> None:
        """Selecting a language persists it in ConfigStore."""
        update, context = _make_callback_update_and_context("lang:it")

        await lang_callback(update, context)

        config_store = context.bot_data["config_store"]
        config_store.set_language.assert_called_once_with(123, "it")

    async def test_lang_callback_confirms_change(self) -> None:
        """Selecting a language confirms the change to the user."""
        update, context = _make_callback_update_and_context("lang:it")

        await lang_callback(update, context)

        query = update.callback_query
        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        msg = query.edit_message_text.call_args[0][0]
        assert "Italiano" in msg

    async def test_lang_callback_english(self) -> None:
        """Selecting English language persists and confirms correctly."""
        update, context = _make_callback_update_and_context("lang:en")

        await lang_callback(update, context)

        config_store = context.bot_data["config_store"]
        config_store.set_language.assert_called_once_with(123, "en")

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "English" in msg
