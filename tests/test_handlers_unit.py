"""Unit tests for handler conversation flow initiation.

Tests that /fuel, /service, and /km without args start their respective conversation flows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.handlers.fuel import ODOMETER as FUEL_ODOMETER
from bot.handlers.fuel import fuel_command
from bot.handlers.odometer import ODOMETER as KM_ODOMETER
from bot.handlers.odometer import km_command
from bot.handlers.service import ODOMETER as SERVICE_ODOMETER
from bot.handlers.service import service_command
from bot.models.responses import Vehicle


def _make_vehicle(vehicle_id: int = 1, make: str = "Toyota", model: str = "Corolla") -> Vehicle:
    """Create a test Vehicle instance."""
    return Vehicle(id=vehicle_id, year=2020, make=make, model=model)


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
    update.effective_chat.id = 123
    update.message.text = text
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.edit_message_text = AsyncMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle = AsyncMock(return_value=1)

    lubelogger_client = AsyncMock()
    # Default: single vehicle for auto-select
    lubelogger_client.get_vehicles = AsyncMock(return_value=[_make_vehicle()])
    lubelogger_client.get_latest_odometer = AsyncMock(return_value=None)

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
        """/fuel without args should return ODOMETER state to start conversation."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        result = await fuel_command(update, context)

        assert result == FUEL_ODOMETER

    async def test_fuel_without_args_prompts_odometer(self) -> None:
        """/fuel without args should prompt user for odometer reading."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        # With auto-select, it sends auto-select message + odometer prompt via send_or_edit
        # The bot sends a message via context.bot.send_message (from send_or_edit)
        assert context.bot.send_message.called or update.message.reply_text.called

    async def test_fuel_without_args_stores_vehicle_id(self) -> None:
        """/fuel without args should store the vehicle_id in user_data."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        assert context.user_data["fuel_vehicle_id"] == 1

    async def test_fuel_without_args_no_vehicle_prompts_selection(self) -> None:
        """/fuel without active vehicle should prompt vehicle selection."""
        update, context = _make_update_and_context(text="/fuel", args=[])
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(return_value=[])

        from telegram.ext import ConversationHandler

        result = await fuel_command(update, context)

        assert result == ConversationHandler.END


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
        """/service without active vehicle should end conversation when no vehicles."""
        update, context = _make_update_and_context(text="/service", args=[])
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)
        context.bot_data["lubelogger_client"].get_vehicles = AsyncMock(return_value=[])

        from telegram.ext import ConversationHandler

        result = await service_command(update, context)

        assert result == ConversationHandler.END


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
