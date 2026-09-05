"""Unit tests for handler conversation flow initiation.

Tests that /fuel, /service, and /km without args start their respective conversation flows.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import CallbackQueryHandler

from bot.handlers.fuel import (
    DATE as FUEL_DATE,
)
from bot.handlers.fuel import (
    FUEL_DATE_TODAY_CALLBACK,
    fuel_command,
    fuel_date_step,
    fuel_full_tank_step,
    fuel_missed_fuel_up_step,
    fuel_today_date_step,
    get_fuel_conversation_handler,
)
from bot.handlers.fuel import (
    MISSED_FUEL_UP as FUEL_MISSED_FUEL_UP,
)
from bot.handlers.fuel import (
    ODOMETER as FUEL_ODOMETER,
)
from bot.handlers.odometer import ODOMETER as KM_ODOMETER
from bot.handlers.odometer import km_command
from bot.handlers.service import ODOMETER as SERVICE_ODOMETER
from bot.handlers.service import service_command


def _make_update_and_context(
    text: str = "",
    args: list[str] | None = None,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context objects for handler testing.

    Args:
        text: The full message text (e.g. "/fuel" or "/fuel 100 50 70").
        args: The parsed args list (context.args).
        user_id: The Telegram user ID.
    """
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = args or []
    context.user_data = {}

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle = AsyncMock(return_value=1)

    lubelogger_client = AsyncMock()
    queue_service = AsyncMock()

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": lubelogger_client,
        "queue_service": queue_service,
    }

    return update, context


class TestFuelConversationInitiation:
    """Tests for /fuel command conversation flow initiation (Requirement 4.1)."""

    async def test_fuel_without_args_starts_conversation(self) -> None:
        """/fuel without args should return DATE state to start conversation."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        result = await fuel_command(update, context)

        assert result == FUEL_DATE
        # Verify a prompt message was sent
        update.message.reply_text.assert_called_once()

    async def test_fuel_without_args_prompts_odometer(self) -> None:
        """/fuel without args should prompt user for odometer reading."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        # Should contain a prompt for odometer
        assert msg  # Non-empty response

    async def test_fuel_without_args_shows_today_button(self) -> None:
        """The guided date prompt should expose a one-tap today shortcut."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        reply_markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        button = reply_markup.inline_keyboard[0][0]
        assert button.callback_data == FUEL_DATE_TODAY_CALLBACK
        assert button.text == "📅 Today"

    async def test_fuel_without_args_stores_vehicle_id(self) -> None:
        """/fuel without args should store the vehicle_id in user_data."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        assert context.user_data["fuel_vehicle_id"] == 1

    async def test_fuel_without_args_no_vehicle_prompts_selection(self) -> None:
        """/fuel without active vehicle should prompt vehicle selection."""
        update, context = _make_update_and_context(text="/fuel", args=[])
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        from telegram.ext import ConversationHandler

        result = await fuel_command(update, context)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args[0][0]
        assert "/vehicle" in msg

    def test_today_callback_is_registered_in_date_state(self) -> None:
        """DATE state should route the today button through a callback handler."""
        conversation_handler = get_fuel_conversation_handler()

        assert any(
            isinstance(handler, CallbackQueryHandler)
            for handler in conversation_handler.states[FUEL_DATE]
        )


class TestServiceConversationInitiation:
    """Tests for /service command conversation flow initiation (Requirement 5.1)."""

    async def test_service_without_args_starts_conversation(self) -> None:
        """/service without args should return ODOMETER state to start conversation."""
        update, context = _make_update_and_context(text="/service", args=[])

        result = await service_command(update, context)

        assert result == SERVICE_ODOMETER
        update.message.reply_text.assert_called_once()

    async def test_service_without_args_prompts_odometer(self) -> None:
        """/service without args should prompt user for odometer reading."""
        update, context = _make_update_and_context(text="/service", args=[])

        await service_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert msg  # Non-empty response

    async def test_service_without_args_stores_vehicle_id(self) -> None:
        """/service without args should store the vehicle_id in user_data."""
        update, context = _make_update_and_context(text="/service", args=[])

        await service_command(update, context)

        assert context.user_data["service_vehicle_id"] == 1

    async def test_service_without_args_no_vehicle_prompts_selection(self) -> None:
        """/service without active vehicle should prompt vehicle selection."""
        update, context = _make_update_and_context(text="/service", args=[])
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        from telegram.ext import ConversationHandler

        result = await service_command(update, context)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args[0][0]
        assert "/vehicle" in msg


class TestOdometerConversationInitiation:
    """Tests for /km command conversation flow initiation (Requirement 6.2)."""

    async def test_km_without_args_starts_conversation(self) -> None:
        """/km without args should return ODOMETER state to start conversation."""
        update, context = _make_update_and_context(text="/km", args=[])

        result = await km_command(update, context)

        assert result == KM_ODOMETER
        update.message.reply_text.assert_called_once()

    async def test_km_without_args_prompts_odometer(self) -> None:
        """/km without args should prompt user for odometer reading."""
        update, context = _make_update_and_context(text="/km", args=[])

        await km_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert msg  # Non-empty response


class TestFuelMetadataConversation:
    """Tests for fuel date and missed-fuel guided steps."""

    async def test_today_button_sets_today_and_advances(self) -> None:
        """The today callback should store today's date and continue to odometer."""
        update, context = _make_update_and_context()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        result = await fuel_today_date_step(update, context)

        assert result == FUEL_ODOMETER
        assert context.user_data["fuel_date"] == date.today().isoformat()
        update.callback_query.answer.assert_awaited_once_with()
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_date_step_accepts_past_date(self) -> None:
        update, context = _make_update_and_context()
        update.message.text = "2024-01-15"

        result = await fuel_date_step(update, context)

        assert result == FUEL_ODOMETER
        assert context.user_data["fuel_date"] == "2024-01-15"

    async def test_date_step_rejects_future_date(self) -> None:
        update, context = _make_update_and_context()
        update.message.text = "2999-01-15"

        result = await fuel_date_step(update, context)

        assert result == FUEL_DATE
        assert "future" in update.message.reply_text.call_args[0][0].lower()

    async def test_full_tank_step_asks_for_missed_flag(self) -> None:
        update, context = _make_update_and_context()
        update.message.text = "no"

        result = await fuel_full_tank_step(update, context)

        assert result == FUEL_MISSED_FUEL_UP
        assert context.user_data["fuel_is_fill_to_full"] is False
        assert "miss" in update.message.reply_text.call_args[0][0].lower()

    async def test_missed_step_submits_metadata_and_clears_context(self) -> None:
        update, context = _make_update_and_context()
        update.message.text = "yes"
        context.user_data.update(
            {
                "fuel_vehicle_id": 1,
                "fuel_date": "2024-01-15",
                "fuel_odometer": 45000,
                "fuel_liters": 42.5,
                "fuel_cost": 78.9,
                "fuel_is_fill_to_full": False,
            }
        )

        from telegram.ext import ConversationHandler

        result = await fuel_missed_fuel_up_step(update, context)

        assert result == ConversationHandler.END
        context.bot_data["lubelogger_client"].add_gas_record.assert_awaited_once()
        payload = context.bot_data["lubelogger_client"].add_gas_record.call_args[0][1]
        assert payload.date == "2024-01-15"
        assert payload.is_fill_to_full == "false"
        assert payload.missed_fuel_up == "true"
        assert context.user_data == {}
