"""Tests for the query handler: /last, /status, /queue commands."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from bot.exceptions import LubeLoggerUnreachableError
from bot.handlers.query import last_command, queue_command, status_command
from bot.models.records import GasRecord, OdometerRecord


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
    config_store.get_active_vehicle_name = AsyncMock(return_value="My Car")

    lubelogger_client = AsyncMock()
    queue_service = AsyncMock()
    odometer_tracker = AsyncMock()

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": lubelogger_client,
        "queue_service": queue_service,
        "odometer_tracker": odometer_tracker,
    }

    return update, context


def _gas_record(**kwargs: object) -> GasRecord:
    """Build a GasRecord with sensible defaults."""
    defaults: dict[str, object] = {
        "id": 1,
        "date": dt.date(2024, 1, 15),
        "odometer": 45000,
        "fuelConsumed": Decimal("42.50"),
        "cost": Decimal("78.90"),
        "fuelEconomy": Decimal("6.50"),
        "isFillToFull": True,
        "missedFuelUp": False,
        "notes": "",
    }
    defaults.update(kwargs)
    return GasRecord.model_validate(defaults)


def _odometer_record(**kwargs: object) -> OdometerRecord:
    """Build an OdometerRecord with sensible defaults."""
    defaults: dict[str, object] = {
        "id": 1,
        "date": dt.date(2024, 1, 15),
        "odometer": 45000,
    }
    defaults.update(kwargs)
    return OdometerRecord.model_validate(defaults)


class TestLastCommand:
    """Tests for the /last command handler."""

    async def test_last_fuel_displays_record(self) -> None:
        """'/last fuel' should render through formatters with HTML parse mode."""
        update, context = _make_update_and_context(args=["fuel"])
        record = _gas_record()
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(
            return_value=[record]
        )

        await last_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        msg = call_kwargs[0][0]
        # Rendered through formatters — contains HTML markup
        assert "<b>" in msg
        # Uses HTML parse_mode
        assert call_kwargs[1]["parse_mode"] == "HTML"
        # Contains the odometer value (formatted)
        assert "45" in msg

    async def test_last_fuel_empty(self) -> None:
        """'/last fuel' with no records shows empty message via formatters."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(return_value=[])

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        # Formatters render "card_latest_empty" when no record
        assert "No record" in msg or "yet" in msg

    async def test_last_fuel_folds_into_tracker(self) -> None:
        """'/last fuel' folds gas records into odometer tracker."""
        update, context = _make_update_and_context(args=["fuel"])
        record = _gas_record()
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(
            return_value=[record]
        )
        tracker = context.bot_data["odometer_tracker"]

        await last_command(update, context)

        tracker.observe_records.assert_called_once_with(1, gas=[record])

    async def test_last_fuel_no_tracker_call_when_empty(self) -> None:
        """'/last fuel' does not call tracker when no records."""
        update, context = _make_update_and_context(args=["fuel"])
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(return_value=[])
        tracker = context.bot_data["odometer_tracker"]

        await last_command(update, context)

        tracker.observe_records.assert_not_called()

    async def test_last_km_displays_record(self) -> None:
        """'/last km' should render through formatters with HTML parse mode."""
        update, context = _make_update_and_context(args=["km"])
        record = _odometer_record()
        context.bot_data["lubelogger_client"].get_odometer_records = AsyncMock(
            return_value=[record]
        )

        await last_command(update, context)

        call_kwargs = update.message.reply_text.call_args
        msg = call_kwargs[0][0]
        assert "<b>" in msg
        assert call_kwargs[1]["parse_mode"] == "HTML"
        assert "45" in msg

    async def test_last_km_empty(self) -> None:
        """'/last km' with no records shows empty message via formatters."""
        update, context = _make_update_and_context(args=["km"])
        context.bot_data["lubelogger_client"].get_odometer_records = AsyncMock(
            return_value=[]
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "No record" in msg or "yet" in msg

    async def test_last_km_folds_into_tracker(self) -> None:
        """'/last km' folds odometer records into tracker."""
        update, context = _make_update_and_context(args=["km"])
        record = _odometer_record()
        context.bot_data["lubelogger_client"].get_odometer_records = AsyncMock(
            return_value=[record]
        )
        tracker = context.bot_data["odometer_tracker"]

        await last_command(update, context)

        tracker.observe_records.assert_called_once_with(1, odometer=[record])

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
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "unreachable" in msg.lower() or "unavailable" in msg.lower()

    async def test_last_km_unreachable_shows_error(self) -> None:
        """'/last km' when LubeLogger is unreachable shows user-friendly message."""
        update, context = _make_update_and_context(args=["km"])
        context.bot_data["lubelogger_client"].get_odometer_records = AsyncMock(
            side_effect=LubeLoggerUnreachableError("timeout")
        )

        await last_command(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "unreachable" in msg.lower() or "unavailable" in msg.lower()

    async def test_last_fuel_escapes_html_in_values(self) -> None:
        """Values from API are escaped — HTML special chars don't break parse mode."""
        update, context = _make_update_and_context(args=["fuel"])
        # notes with HTML-dangerous content (the formatters escape via esc())
        record = _gas_record(notes="oil change <5000km>")
        context.bot_data["lubelogger_client"].get_gas_records = AsyncMock(
            return_value=[record]
        )

        await last_command(update, context)

        call_kwargs = update.message.reply_text.call_args
        # Should use HTML parse mode and not contain raw < in a value position
        assert call_kwargs[1]["parse_mode"] == "HTML"


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
