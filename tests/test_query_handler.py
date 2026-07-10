"""Tests for the query handler: /last, /status, /queue commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.exceptions import LubeLoggerUnreachableError
from bot.handlers.query import last_command, queue_command, status_command


def _make_update_and_context(
    args: list[str] | None = None,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context objects for handler testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = args

    # Set up bot_data with mock services
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


class TestLastCommand:
    """Tests for the /last command handler."""

    async def test_last_fuel_displays_record(self) -> None:
        """'/last fuel' should display the latest gas record."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["lubelogger_client"].get_latest_gas_record = AsyncMock(
            return_value={
                "date": "2024-01-15",
                "fuelConsumed": "42.5",
                "cost": "78.90",
                "odometer": "45000",
            }
        )

        await last_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "42.5" in msg
        assert "78.90" in msg
        assert "45000" in msg
        assert "2024-01-15" in msg

    async def test_last_fuel_empty(self) -> None:
        """'/last fuel' with no records shows empty message."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["lubelogger_client"].get_latest_gas_record = AsyncMock(
            return_value=None
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "No fuel records found" in msg

    async def test_last_km_displays_record(self) -> None:
        """'/last km' should display the latest odometer record."""
        update, context = _make_update_and_context(args=["km"])
        context.bot_data["lubelogger_client"].get_latest_odometer = AsyncMock(
            return_value={
                "date": "2024-01-15",
                "odometer": "45000",
            }
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "45000" in msg
        assert "2024-01-15" in msg

    async def test_last_km_empty(self) -> None:
        """'/last km' with no records shows empty message."""
        update, context = _make_update_and_context(args=["km"])
        context.bot_data["lubelogger_client"].get_latest_odometer = AsyncMock(
            return_value=None
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "No odometer records found" in msg

    async def test_last_no_args_shows_usage(self) -> None:
        """'/last' without subcommand shows usage hint."""
        update, context = _make_update_and_context(args=[])

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "/last fuel" in msg or "Usage" in msg

    async def test_last_invalid_subcommand_shows_usage(self) -> None:
        """'/last xyz' with invalid subcommand shows usage hint."""
        update, context = _make_update_and_context(args=["xyz"])

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "/last fuel" in msg or "Usage" in msg

    async def test_last_no_vehicle_prompts_selection(self) -> None:
        """'/last fuel' without active vehicle prompts user to select one."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "/vehicle" in msg

    async def test_last_fuel_unreachable_shows_error(self) -> None:
        """'/last fuel' when LubeLogger is unreachable shows user-friendly message."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["lubelogger_client"].get_latest_gas_record = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "unreachable" in msg.lower() or "unavailable" in msg.lower()

    async def test_last_km_unreachable_shows_error(self) -> None:
        """'/last km' when LubeLogger is unreachable shows user-friendly message."""
        update, context = _make_update_and_context(args=["km"])
        context.bot_data["lubelogger_client"].get_latest_odometer = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "unreachable" in msg.lower() or "unavailable" in msg.lower()


class TestStatusCommand:
    """Tests for the /status command handler."""

    async def test_status_reachable_no_queue(self) -> None:
        """'/status' when LubeLogger reachable and queue empty."""
        update, context = _make_update_and_context()
        context.bot_data["lubelogger_client"].health_check = AsyncMock(return_value=True)
        context.bot_data["queue_service"].get_pending_count = AsyncMock(return_value={})

        await status_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "reachable" in msg.lower()
        assert "no pending" in msg.lower() or "0" in msg.lower() or "empty" in msg.lower()

    async def test_status_reachable_with_queue(self) -> None:
        """'/status' when LubeLogger reachable with pending items."""
        update, context = _make_update_and_context()
        context.bot_data["lubelogger_client"].health_check = AsyncMock(return_value=True)
        context.bot_data["queue_service"].get_pending_count = AsyncMock(
            return_value={"gas": 2, "odometer": 1}
        )

        await status_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "reachable" in msg.lower()
        assert "3" in msg

    async def test_status_offline(self) -> None:
        """'/status' when LubeLogger is unreachable."""
        update, context = _make_update_and_context()
        context.bot_data["lubelogger_client"].health_check = AsyncMock(return_value=False)
        context.bot_data["queue_service"].get_pending_count = AsyncMock(return_value={})

        await status_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "unreachable" in msg.lower()


class TestQueueCommand:
    """Tests for the /queue command handler."""

    async def test_queue_empty(self) -> None:
        """'/queue' with no pending records shows empty message."""
        update, context = _make_update_and_context()
        context.bot_data["queue_service"].get_pending_count = AsyncMock(return_value={})

        await queue_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "no pending" in msg.lower() or "empty" in msg.lower()

    async def test_queue_with_items(self) -> None:
        """'/queue' with pending records shows count and types."""
        update, context = _make_update_and_context()
        context.bot_data["queue_service"].get_pending_count = AsyncMock(
            return_value={"gas": 3, "service": 1}
        )

        await queue_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "4" in msg
        assert "gas" in msg
        assert "service" in msg

    async def test_queue_single_type(self) -> None:
        """'/queue' with a single pending type shows correctly."""
        update, context = _make_update_and_context()
        context.bot_data["queue_service"].get_pending_count = AsyncMock(
            return_value={"odometer": 2}
        )

        await queue_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "2" in msg
        assert "odometer" in msg
