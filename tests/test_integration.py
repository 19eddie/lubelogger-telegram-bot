"""Integration tests for end-to-end command flows.

Tests verify full command flows using mock objects for Telegram and LubeLogger APIs.

Validates: Requirements 1.1, 4.9, 4.10, 8.1, 8.2, 8.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.exceptions import LubeLoggerUnreachableError
from bot.handlers.fuel import fuel_command
from bot.handlers.vehicle import vehicle_callback, vehicle_command
from bot.middleware.auth import create_auth_filter
from bot.services.config_store import ConfigStore
from bot.services.database import init_db
from bot.services.queue_service import QueueService


def _make_update_and_context(
    text: str = "",
    args: list[str] | None = None,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context for integration testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = args if args is not None else []
    context.user_data = {}

    return update, context


class TestFuelCommandEndToEnd:
    """Test full fuel command → mock LubeLogger → verify confirmation."""

    async def test_fuel_command_inline_args_success(self, tmp_path: object) -> None:
        """Full flow: /fuel 45000 42.5 78.90 → LubeLogger success → confirmation message.

        Validates: Requirements 4.9, 4.10
        """
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)

        config_store = ConfigStore(db_path)
        await config_store.set_active_vehicle(123, 1)

        lubelogger_client = AsyncMock()
        lubelogger_client.add_gas_record = AsyncMock(
            return_value=MagicMock(success=True, message="Gas Record Added")
        )

        queue_service = QueueService(db_path)

        update, context = _make_update_and_context(
            text="/fuel 45000 42.5 78.90",
            args=["45000", "42.5", "78.90"],
            user_id=123,
        )
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": lubelogger_client,
            "queue_service": queue_service,
        }

        from telegram.ext import ConversationHandler

        result = await fuel_command(update, context)

        assert result == ConversationHandler.END

        # Verify LubeLogger client was called
        lubelogger_client.add_gas_record.assert_called_once()
        call_args = lubelogger_client.add_gas_record.call_args
        assert call_args[0][0] == 1  # vehicle_id

        # Verify confirmation message was sent with expected data
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "42.5" in msg
        assert "78.9" in msg
        assert "45000" in msg


class TestOfflineQueueFlow:
    """Test offline flow: command → unreachable → queue → flush → verify send.

    Validates: Requirements 8.1, 8.2, 8.4
    """

    async def test_fuel_queued_then_flushed(self, tmp_path: object) -> None:
        """Full offline flow: fuel command → unreachable → queued → flush → sent."""
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)

        config_store = ConfigStore(db_path)
        await config_store.set_active_vehicle(123, 1)

        # Client raises unreachable on first call
        lubelogger_client = AsyncMock()
        lubelogger_client.add_gas_record = AsyncMock(
            side_effect=LubeLoggerUnreachableError("Connection refused")
        )

        queue_service = QueueService(db_path)

        update, context = _make_update_and_context(
            text="/fuel 45000 42.5 78.90",
            args=["45000", "42.5", "78.90"],
            user_id=123,
        )
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": lubelogger_client,
            "queue_service": queue_service,
        }

        from telegram.ext import ConversationHandler

        result = await fuel_command(update, context)

        assert result == ConversationHandler.END

        # Verify "queued" message was sent to user
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "offline" in msg.lower() or "locally" in msg.lower() or "sync" in msg.lower()

        # Verify queue has 1 pending item
        pending = await queue_service.get_pending()
        assert len(pending) == 1
        assert pending[0].record_type == "gas"
        assert pending[0].status == "pending"

        # Now mock client to succeed for flush
        flush_client = AsyncMock()
        flush_client.add_gas_record = AsyncMock(
            return_value=MagicMock(success=True, message="Gas Record Added")
        )

        # Flush the queue
        flush_result = await queue_service.flush(flush_client)

        assert flush_result.sent == 1
        assert flush_result.failed == 0
        assert flush_result.remaining == 0

        # Verify queue has 0 pending items
        pending_after = await queue_service.get_pending()
        assert len(pending_after) == 0


class TestVehicleSelectionFlow:
    """Test vehicle selection: /vehicle → mock API → select → verify persistence.

    Validates: Requirements 3.1, 3.2, 3.4
    """

    async def test_vehicle_command_shows_keyboard(self, tmp_path: object) -> None:
        """/vehicle should show inline keyboard with vehicles from LubeLogger."""
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)

        config_store = ConfigStore(db_path)

        vehicles_data = [
            MagicMock(id=1, display_name="2020 Toyota Yaris"),
            MagicMock(id=2, display_name="2018 Fiat Punto"),
        ]

        lubelogger_client = AsyncMock()
        lubelogger_client.get_vehicles = AsyncMock(return_value=vehicles_data)

        update, context = _make_update_and_context(text="/vehicle", user_id=123)
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": lubelogger_client,
        }

        await vehicle_command(update, context)

        # Verify reply_text was called with an inline keyboard
        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        reply_markup = call_kwargs[1]["reply_markup"] if call_kwargs[1] else None
        assert reply_markup is not None

        # Check that the keyboard has buttons for both vehicles
        buttons = reply_markup.inline_keyboard
        assert len(buttons) == 2
        assert buttons[0][0].callback_data == "vehicle:1"
        assert buttons[1][0].callback_data == "vehicle:2"

    async def test_vehicle_callback_persists_selection(self, tmp_path: object) -> None:
        """Selecting a vehicle via callback persists to ConfigStore."""
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)

        config_store = ConfigStore(db_path)

        vehicles_data = [
            MagicMock(id=1, display_name="2020 Toyota Yaris"),
            MagicMock(id=2, display_name="2018 Fiat Punto"),
        ]

        lubelogger_client = AsyncMock()
        lubelogger_client.get_vehicles = AsyncMock(return_value=vehicles_data)

        # Create a mock callback query (simulates user pressing "vehicle:1")
        update = MagicMock()
        update.effective_user.id = 123
        update.callback_query.data = "vehicle:1"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": lubelogger_client,
        }

        await vehicle_callback(update, context)

        # Verify ConfigStore was updated
        active_vehicle = await config_store.get_active_vehicle(123)
        assert active_vehicle == 1

        # Verify confirmation message was sent
        update.callback_query.edit_message_text.assert_called_once()
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Toyota" in msg or "Vehicle" in msg or "vehicle" in msg


class TestUnauthorizedUser:
    """Test that unauthorized users are silently dropped.

    Validates: Requirements 1.1, NF-3.3
    """

    def test_auth_filter_rejects_unauthorized_user(self) -> None:
        """Users not in the whitelist are not included in the filter's user_ids."""
        auth_filter = create_auth_filter([100, 200])

        # The filter's user_ids set should contain only authorized users
        assert 100 in auth_filter.user_ids
        assert 200 in auth_filter.user_ids
        assert 999 not in auth_filter.user_ids

    def test_auth_filter_allows_authorized_user(self) -> None:
        """Users in the whitelist are included in the filter's user_ids."""
        auth_filter = create_auth_filter([100, 200, 300])

        assert 100 in auth_filter.user_ids
        assert 200 in auth_filter.user_ids
        assert 300 in auth_filter.user_ids
