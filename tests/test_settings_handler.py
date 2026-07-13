"""Tests for the settings handler: /start and /lang commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.handlers.settings import (
    SUPPORTED_LANGUAGES,
    lang_callback,
    lang_command,
    start_command,
    start_vehicle_callback,
)
from bot.models.responses import Vehicle


def _make_vehicles() -> list[Vehicle]:
    """Create a list of mock vehicles."""
    return [
        Vehicle(id=1, year=2020, make="Toyota", model="Corolla"),
        Vehicle(id=2, year=2019, make="Honda", model="Civic"),
    ]


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

    client = AsyncMock()
    client.get_vehicles = AsyncMock(return_value=_make_vehicles())

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": client,
        "allowed_user_ids": [],
    }

    return update, context


def _make_callback_update_and_context(
    callback_data: str,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context for callback query testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = 456
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.set_language = AsyncMock()
    config_store.set_active_vehicle = AsyncMock()

    client = AsyncMock()
    client.get_vehicles = AsyncMock(return_value=_make_vehicles())

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": client,
        "allowed_user_ids": [],
    }

    return update, context


class TestStartCommand:
    """Tests for the /start command handler."""

    async def test_start_with_active_vehicle_shows_welcome_back(self) -> None:
        """/start with an active vehicle shows the welcome-back message with main keyboard."""
        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=1)

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Welcome back" in msg
        assert "2020 Toyota Corolla" in msg
        # Verify main keyboard is attached
        kwargs = update.message.reply_text.call_args[1]
        assert kwargs.get("reply_markup") is not None

    async def test_start_without_vehicle_shows_vehicle_inline_keyboard(self) -> None:
        """/start without an active vehicle shows vehicle selection inline keyboard."""
        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Welcome to LubeLogger Bot" in msg
        # Verify inline keyboard with vehicles
        kwargs = update.message.reply_text.call_args[1]
        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is not None
        buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        assert len(buttons) == 2
        assert buttons[0].callback_data == "start_vehicle:1"
        assert buttons[1].callback_data == "start_vehicle:2"

    async def test_start_api_unreachable_shows_error(self) -> None:
        """/start when API is unreachable shows error message."""
        from bot.exceptions import LubeLoggerUnreachableError

        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(
            side_effect=LubeLoggerUnreachableError("Connection error")
        )

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Can't reach LubeLogger" in msg

    async def test_start_returning_user_api_unreachable_uses_vehicle_id(self) -> None:
        """/start for returning user when API is unreachable falls back to Vehicle #ID."""
        from bot.exceptions import LubeLoggerUnreachableError

        update, context = _make_update_and_context()
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=42)
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(
            side_effect=LubeLoggerUnreachableError("Connection error")
        )

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Vehicle #42" in msg


class TestStartVehicleCallback:
    """Tests for the onboarding vehicle selection callback."""

    async def test_vehicle_selection_sets_active_vehicle(self) -> None:
        """Selecting a vehicle from onboarding sets it as active."""
        update, context = _make_callback_update_and_context("start_vehicle:1")

        await start_vehicle_callback(update, context)

        config_store = context.bot_data["config_store"]
        config_store.set_active_vehicle.assert_called_once_with(123, 1)

    async def test_vehicle_selection_shows_confirmation(self) -> None:
        """Selecting a vehicle edits message and sends main keyboard."""
        update, context = _make_callback_update_and_context("start_vehicle:1")

        await start_vehicle_callback(update, context)

        # Check the inline message was edited
        query = update.callback_query
        query.edit_message_text.assert_called_once()
        edit_msg = query.edit_message_text.call_args[0][0]
        assert "2020 Toyota Corolla" in edit_msg

        # Check the follow-up message with main keyboard
        context.bot.send_message.assert_called_once()
        send_kwargs = context.bot.send_message.call_args[1]
        assert send_kwargs.get("reply_markup") is not None

    async def test_vehicle_selection_unauthorized_user_ignored(self) -> None:
        """Unauthorized user callback is silently ignored."""
        update, context = _make_callback_update_and_context("start_vehicle:1", user_id=999)
        context.bot_data["allowed_user_ids"] = [123]

        await start_vehicle_callback(update, context)

        config_store = context.bot_data["config_store"]
        config_store.set_active_vehicle.assert_not_called()


class TestLangCommand:
    """Tests for the /lang command handler."""

    async def test_lang_shows_keyboard(self) -> None:
        """/lang presents language options as inline keyboard."""
        update, context = _make_update_and_context()

        await lang_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get("reply_markup")
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
        reply_markup = call_kwargs.kwargs.get("reply_markup") or call_kwargs[1].get("reply_markup")
        callback_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
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
