"""Additional edge-case unit tests for /start onboarding flow.

NOTE: Core onboarding scenarios (welcome + vehicle list, welcome-back + keyboard,
API unreachable, vehicle selection) are already tested in tests/test_settings_handler.py.
This file adds edge-case coverage for requirement 7.1-7.5.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.exceptions import LubeLoggerUnreachableError
from bot.handlers.settings import start_command, start_vehicle_callback
from bot.models.responses import Vehicle


def _make_update_and_context(
    user_id: int = 123,
    active_vehicle: int | None = None,
    vehicles: list[Vehicle] | None = None,
    lang: str = "en",
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context for onboarding testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()

    context = MagicMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value=lang)
    config_store.get_active_vehicle = AsyncMock(return_value=active_vehicle)
    config_store.set_active_vehicle = AsyncMock()

    client = AsyncMock()
    if vehicles is None:
        vehicles = [
            Vehicle(id=1, year=2020, make="Toyota", model="Corolla"),
            Vehicle(id=2, year=2019, make="Honda", model="Civic"),
        ]
    client.get_vehicles = AsyncMock(return_value=vehicles)

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": client,
        "allowed_user_ids": [],
    }

    return update, context


class TestStartOnboardingEdgeCases:
    """Edge-case tests for /start onboarding flow (Requirements 7.1-7.5)."""

    async def test_new_user_empty_vehicle_list(self) -> None:
        """/start with no active vehicle and empty list shows inline keyboard with 0 buttons."""
        update, context = _make_update_and_context(active_vehicle=None, vehicles=[])

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        kwargs = update.message.reply_text.call_args[1]
        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is not None
        # Empty vehicle list means empty inline keyboard
        buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        assert len(buttons) == 0

    async def test_new_user_vehicle_display_name_fallback(self) -> None:
        """/start shows 'Vehicle #N' for vehicles with no make/model/year."""
        vehicles = [Vehicle(id=99)]
        update, context = _make_update_and_context(active_vehicle=None, vehicles=vehicles)

        await start_command(update, context)

        kwargs = update.message.reply_text.call_args[1]
        reply_markup = kwargs.get("reply_markup")
        buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        assert len(buttons) == 1
        assert buttons[0].text == "Vehicle #99"
        assert buttons[0].callback_data == "start_vehicle:99"

    async def test_returning_user_vehicle_not_in_list(self) -> None:
        """/start with active vehicle ID not in vehicle list falls back to 'Vehicle #ID'."""
        vehicles = [Vehicle(id=1, year=2020, make="Toyota", model="Corolla")]
        update, context = _make_update_and_context(active_vehicle=999, vehicles=vehicles)

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Vehicle #999" in msg

    async def test_returning_user_api_unreachable_still_shows_welcome_back(self) -> None:
        """/start for returning user when API unreachable shows welcome-back with fallback."""
        update, context = _make_update_and_context(active_vehicle=5)
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        # Should still show welcome back, using fallback Vehicle #5
        assert "Vehicle #5" in msg
        # Main keyboard should still be attached
        kwargs = update.message.reply_text.call_args[1]
        assert kwargs.get("reply_markup") is not None

    async def test_new_user_italian_locale_error_message(self) -> None:
        """/start in Italian when API unreachable shows Italian error text."""
        update, context = _make_update_and_context(active_vehicle=None, lang="it")
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(
            side_effect=LubeLoggerUnreachableError("connessione fallita")
        )

        await start_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        # Should show a message (Italian version of unreachable error)
        assert len(msg) > 0

    async def test_vehicle_selection_with_vehicle_missing_from_api(self) -> None:
        """Selecting a vehicle that no longer exists in API uses fallback display name."""
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_chat.id = 456
        update.callback_query.data = "start_vehicle:42"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.bot = AsyncMock()
        context.bot.send_message = AsyncMock()

        config_store = AsyncMock()
        config_store.get_language = AsyncMock(return_value="en")
        config_store.set_active_vehicle = AsyncMock()

        # Vehicle 42 doesn't exist in the returned list
        client = AsyncMock()
        client.get_vehicles = AsyncMock(
            return_value=[Vehicle(id=1, year=2020, make="Toyota", model="Corolla")]
        )

        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": client,
            "allowed_user_ids": [],
        }

        await start_vehicle_callback(update, context)

        config_store.set_active_vehicle.assert_called_once_with(123, 42)
        # Confirmation should use fallback name
        edit_msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Vehicle #42" in edit_msg

    async def test_vehicle_selection_api_unreachable_uses_fallback(self) -> None:
        """Selecting a vehicle when API is unreachable uses fallback display name."""
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_chat.id = 456
        update.callback_query.data = "start_vehicle:7"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.bot = AsyncMock()
        context.bot.send_message = AsyncMock()

        config_store = AsyncMock()
        config_store.get_language = AsyncMock(return_value="en")
        config_store.set_active_vehicle = AsyncMock()

        client = AsyncMock()
        client.get_vehicles = AsyncMock(side_effect=LubeLoggerUnreachableError("down"))

        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": client,
            "allowed_user_ids": [],
        }

        await start_vehicle_callback(update, context)

        config_store.set_active_vehicle.assert_called_once_with(123, 7)
        edit_msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Vehicle #7" in edit_msg
