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
        """/fuel without args should return ODOMETER state to start conversation."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        result = await fuel_command(update, context)

        assert result == FUEL_ODOMETER
        # Verify a prompt message was sent
        update.message.reply_text.assert_called_once()

    async def test_fuel_without_args_prompts_odometer(self) -> None:
        """/fuel without args should prompt user for odometer reading."""
        update, context = _make_update_and_context(text="/fuel", args=[])

        await fuel_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        # Should contain a prompt for odometer
        assert msg  # Non-empty response

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
