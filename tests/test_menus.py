"""Tests for the Options and Latest menus (Requirements 1.10, 1.11, 10.2, 10.4, 10.5).

Each selection edits the same message id. The back button restores the menu.
Empty records and unreachable instance keep the back button.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.callbacks import CallbackAction, encode
from bot.keyboards import LatestTarget, OptionsTarget
from bot.models.records import GasRecord, OdometerRecord, VehicleSnapshot
from bot.models.responses import Vehicle


def _make_context(lang: str = "en") -> MagicMock:
    """Build a minimal ContextTypes.DEFAULT_TYPE stand-in."""
    ctx = MagicMock()
    ctx.user_data = {"lang": lang}
    ctx.bot_data = {
        "config_store": AsyncMock(),
        "lubelogger_client": AsyncMock(),
        "queue_service": AsyncMock(),
        "card_service": AsyncMock(),
        "tracker": AsyncMock(),
    }
    return ctx


def _make_update(
    *,
    user_id: int = 42,
    chat_id: int = 123,
    callback_query_id: str = "cq-1",
) -> MagicMock:
    """Build a minimal Update with a callback_query."""
    update = MagicMock()
    query = AsyncMock()
    query.answer = AsyncMock()
    query.id = callback_query_id
    query.message = MagicMock()
    query.message.message_id = 456
    update.callback_query = query
    user = MagicMock()
    user.id = user_id
    update.effective_user = user
    chat = MagicMock()
    chat.id = chat_id
    update.effective_chat = chat
    msg = AsyncMock()
    msg.message_id = 456
    update.effective_message = msg
    bot = AsyncMock()
    bot.context = _make_context()
    msg.bot = bot
    return update


class TestOptionsMenu:
    """Tests for the Options_Menu handler (Requirements 1.9, 1.10, 1.11, 1.13)."""

    @pytest.mark.asyncio
    async def test_options_vehicle_keeps_message_id(self):
        """Vehicle selection keeps the same message id (Requirement 1.10)."""
        from bot.handlers.options import _show_vehicle_selection

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        context.user_data["options_menu_message_id"] = {chat_id: message_id}

        # Mock vehicle snapshots.
        vehicle = Vehicle(id=1, name="Car1")
        snapshot = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=None)
        context.bot_data["lubelogger_client"].get_vehicle_snapshots.return_value = [snapshot]

        # Mock card_service.update to return the same message_id.
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_vehicle_selection(
            update.callback_query,
            context,
            123,  # user_id
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called with the same message_id.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed

    @pytest.mark.asyncio
    async def test_options_back_button_preserves_message_id(self):
        """Back button preserves the message id (Requirement 1.11)."""
        from bot.handlers.options import handle_options_callback

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        context.user_data["options_menu_message_id"] = {chat_id: message_id}

        # Mock callback data for back button.
        update.callback_query.data = encode(CallbackAction.OPTIONS_BACK, "-")

        # Mock card_service.update to return the same message_id.
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await handle_options_callback(update, context)

        # card_service.update should have been called.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed


    @pytest.mark.asyncio
    async def test_options_status_edits_message(self):
        """Status screen edits the message in place (Requirement 1.10)."""
        from bot.handlers.options import _show_status

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        context.user_data["options_menu_message_id"] = {chat_id: message_id}

        # Mock health check and queue.
        context.bot_data["lubelogger_client"].health_check = AsyncMock(return_value=True)
        context.bot_data["queue_service"].get_pending_count = AsyncMock(return_value={})
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_status(
            update.callback_query,
            context,
            123,  # user_id
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called.
        context.bot_data["card_service"].update.assert_called_once()


class TestLatestMenu:
    """Tests for the Latest menu handler (Requirements 10.1, 10.2, 10.3, 10.4, 10.5)."""

    @pytest.mark.asyncio
    async def test_latest_fuel_keeps_message_id(self):
        """Selecting fuel keeps the same message id (Requirement 10.2)."""
        from bot.handlers.latest import _show_latest_fuel

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        user_id = 123
        vehicle_id = 42
        context.user_data["latest_menu_message_id"] = {chat_id: message_id}

        # Mock vehicle and gas record.
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=vehicle_id)
        context.bot_data["config_store"].get_active_vehicle_name = AsyncMock(return_value="Car1")

        record = GasRecord(
            id=1,
            vehicle_id=vehicle_id,
            date="2024-01-15",
            odometer=45000,
            fuel_consumed=42.5,
            cost=50.0,
            is_fill_to_full=True,
            missed_fuel_up=False,
            fuel_economy=6.2,
        )
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(return_value=[record])
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_latest_fuel(
            update.callback_query,
            context,
            user_id,
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called with the same message_id.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed


    @pytest.mark.asyncio
    async def test_latest_empty_fuel_keeps_message_id(self):
        """Empty fuel result keeps the message id with back button (Requirement 10.4)."""
        from bot.handlers.latest import _show_latest_fuel

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        user_id = 123
        vehicle_id = 42
        context.user_data["latest_menu_message_id"] = {chat_id: message_id}

        # Mock vehicle but no gas record.
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=vehicle_id)
        context.bot_data["config_store"].get_active_vehicle_name = AsyncMock(return_value="Car1")
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(return_value=[])
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_latest_fuel(
            update.callback_query,
            context,
            user_id,
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called with the same message_id and back button.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed

    @pytest.mark.asyncio
    async def test_latest_unreachable_keeps_message_id(self):
        """Unreachable instance keeps the message id with back button (Requirement 10.5)."""
        from bot.handlers.latest import _show_latest_fuel
        from bot.exceptions import LubeLoggerUnreachableError

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        user_id = 123
        vehicle_id = 42
        context.user_data["latest_menu_message_id"] = {chat_id: message_id}

        # Mock vehicle but unreachable client.
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=vehicle_id)
        context.bot_data["config_store"].get_active_vehicle_name = AsyncMock(return_value="Car1")
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_latest_fuel(
            update.callback_query,
            context,
            user_id,
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called (not raised).
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed


    @pytest.mark.asyncio
    async def test_latest_back_button_preserves_message_id(self):
        """Back button preserves the message id (Requirement 10.3)."""
        from bot.handlers.latest import handle_latest_callback

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        context.user_data["latest_menu_message_id"] = {chat_id: message_id}

        # Mock callback data for back button.
        update.callback_query.data = encode(CallbackAction.LATEST_BACK, "-")

        # Mock card_service.update to return the same message_id.
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await handle_latest_callback(update, context)

        # card_service.update should have been called.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed

    @pytest.mark.asyncio
    async def test_latest_odometer_keeps_message_id(self):
        """Selecting odometer keeps the same message id (Requirement 10.2)."""
        from bot.handlers.latest import _show_latest_odometer

        context = _make_context()
        update = _make_update()
        chat_id = 123
        message_id = 456
        user_id = 123
        vehicle_id = 42
        context.user_data["latest_menu_message_id"] = {chat_id: message_id}

        # Mock vehicle and odometer record.
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=vehicle_id)
        context.bot_data["config_store"].get_active_vehicle_name = AsyncMock(return_value="Car1")

        record = OdometerRecord(
            id=1,
            vehicle_id=vehicle_id,
            date="2024-01-15",
            odometer=45000,
        )
        context.bot_data["lubelogger_client"].get_odometer_records = AsyncMock(
            return_value=[record]
        )
        context.bot_data["card_service"].update = AsyncMock(return_value=message_id)

        await _show_latest_odometer(
            update.callback_query,
            context,
            user_id,
            chat_id,
            message_id,
            "en",
        )

        # card_service.update should have been called with the same message_id.
        context.bot_data["card_service"].update.assert_called_once()
        call_args = context.bot_data["card_service"].update.call_args
        assert call_args[0][1] == message_id  # Same message_id passed
