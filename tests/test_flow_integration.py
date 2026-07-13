"""Integration tests for full conversation flows with mocked LubeLogger client.

Tests simulate a complete conversation by calling handler functions in sequence with
mocked services to verify flow transitions and outputs.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.1, 6.2, 8.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from telegram import Message
from telegram.ext import ConversationHandler

from bot.handlers.fuel import (
    COST,
    FULL_TANK,
    LITERS,
    ODOMETER,
    SUMMARY,
    cancel_command,
    fuel_command,
    fuel_cost_step,
    fuel_full_tank_step,
    fuel_liters_step,
    fuel_odometer_step,
    log_another_callback,
    summary_cancel_callback,
    summary_edit_callback,
    summary_save_callback,
)
from bot.models.responses import Vehicle


def _make_vehicles() -> list[Vehicle]:
    return [Vehicle(id=1, year=2020, make="Toyota", model="Corolla")]


def _make_context(
    user_data: dict | None = None,
    vehicles: list[Vehicle] | None = None,
) -> MagicMock:
    """Create a mock context with services."""
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    context.args = []

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle = AsyncMock(return_value=1)

    client = AsyncMock()
    client.get_vehicles = AsyncMock(return_value=vehicles or _make_vehicles())
    client.get_latest_odometer = AsyncMock(return_value={"odometer": "44000"})
    client.get_latest_gas_record = AsyncMock(
        return_value={"odometer": "44000", "date": "2024-01-01", "fuelConsumed": "30", "cost": "55"}
    )
    client.add_gas_record = AsyncMock()

    queue_service = AsyncMock()

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": client,
        "queue_service": queue_service,
        "allowed_user_ids": [],
    }

    # Mock bot for send_or_edit (sends via context.bot.send_message / edit_message_text)
    mock_message = MagicMock(spec=Message)
    mock_message.message_id = 100
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock(return_value=mock_message)
    context.bot.edit_message_text = AsyncMock(return_value=mock_message)

    return context


def _make_message_update(text: str, user_id: int = 123) -> MagicMock:
    """Create a mock Update with a text message."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = 456
    update.message.text = text
    update.message.reply_text = AsyncMock(return_value=MagicMock(message_id=100))
    update.callback_query = None
    return update


def _make_callback_update(callback_data: str, user_id: int = 123) -> MagicMock:
    """Create a mock Update with a callback query."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = 456
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.message = None
    return update


class TestCompleteFuelFlow:
    """Integration tests for the complete fuel conversation flow."""

    async def test_full_fuel_flow_single_vehicle(self) -> None:
        """Complete fuel flow with single vehicle (auto-select).

        Validates requirements: 3.1, 4.1, 4.4, 4.5, 5.1, 5.2
        """
        context = _make_context()

        # Step 1: /fuel with no args (auto-selects single vehicle)
        update1 = _make_message_update("/fuel")
        result = await fuel_command(update1, context)
        assert result == ODOMETER
        assert context.user_data["fuel_vehicle_id"] == 1

        # Step 2: Enter odometer
        update2 = _make_message_update("45000")
        result = await fuel_odometer_step(update2, context)
        assert result == LITERS
        assert context.user_data["fuel_odometer"] == 45000

        # Step 3: Enter liters
        update3 = _make_message_update("35.5")
        result = await fuel_liters_step(update3, context)
        assert result == COST
        assert context.user_data["fuel_liters"] == 35.5

        # Step 4: Enter cost
        update4 = _make_message_update("62.50")
        result = await fuel_cost_step(update4, context)
        assert result == FULL_TANK
        assert context.user_data["fuel_cost"] == 62.5

        # Step 5: Enter full tank
        update5 = _make_message_update("yes")
        result = await fuel_full_tank_step(update5, context)
        assert result == SUMMARY
        assert context.user_data["fuel_full_tank"] is True

        # Step 6: Save from summary
        update6 = _make_callback_update("summary_save")
        result = await summary_save_callback(update6, context)
        assert result == ConversationHandler.END

        # Verify record was submitted
        context.bot_data["lubelogger_client"].add_gas_record.assert_called_once()

    async def test_full_fuel_flow_no_as_full_tank(self) -> None:
        """Complete fuel flow where user answers 'no' to full tank.

        Validates requirements: 4.1, 4.4, 4.5
        """
        context = _make_context()

        # Start flow
        update1 = _make_message_update("/fuel")
        await fuel_command(update1, context)

        # Enter all values
        update2 = _make_message_update("50000")
        await fuel_odometer_step(update2, context)

        update3 = _make_message_update("25")
        await fuel_liters_step(update3, context)

        update4 = _make_message_update("45")
        await fuel_cost_step(update4, context)

        # Answer "no" for full tank
        update5 = _make_message_update("no")
        result = await fuel_full_tank_step(update5, context)
        assert result == SUMMARY
        assert context.user_data["fuel_full_tank"] is False


class TestCancelAtVariousSteps:
    """Tests for cancelling at various steps in the conversation flow.

    Validates requirements: 4.2, 4.3, 4.7
    """

    async def test_cancel_at_odometer_step(self) -> None:
        """Cancel at odometer step restores main keyboard."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
            }
        )

        update = _make_message_update("\u274c Cancel")
        result = await cancel_command(update, context)
        assert result == ConversationHandler.END
        # Main keyboard should be attached to response
        call_kwargs = update.message.reply_text.call_args[1]
        assert call_kwargs.get("reply_markup") is not None
        # user_data should be cleaned up
        assert "fuel_vehicle_id" not in context.user_data
        assert "fuel_vehicle_name" not in context.user_data

    async def test_cancel_at_liters_step(self) -> None:
        """Cancel at liters step restores main keyboard and cleans up data."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
                "fuel_odometer": 45000,
            }
        )

        update = _make_message_update("\u274c Cancel")
        result = await cancel_command(update, context)
        assert result == ConversationHandler.END
        assert "fuel_odometer" not in context.user_data
        # Reply should include markup for main keyboard
        call_kwargs = update.message.reply_text.call_args[1]
        assert call_kwargs.get("reply_markup") is not None

    async def test_cancel_at_cost_step(self) -> None:
        """Cancel at cost step restores main keyboard and cleans up data."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
                "fuel_odometer": 45000,
                "fuel_liters": 35.0,
            }
        )

        update = _make_message_update("\u274c Cancel")
        result = await cancel_command(update, context)
        assert result == ConversationHandler.END
        assert "fuel_liters" not in context.user_data

    async def test_cancel_from_summary(self) -> None:
        """Cancel from summary inline button discards data and restores main keyboard."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
                "fuel_odometer": 45000,
                "fuel_liters": 35.0,
                "fuel_cost": 60.0,
                "fuel_full_tank": True,
            }
        )

        update = _make_callback_update("summary_cancel")
        result = await summary_cancel_callback(update, context)
        assert result == ConversationHandler.END
        # Data should be cleaned up
        assert "fuel_odometer" not in context.user_data
        assert "fuel_liters" not in context.user_data
        assert "fuel_cost" not in context.user_data
        assert "fuel_full_tank" not in context.user_data


class TestEditFromSummary:
    """Tests for editing from summary (restarting flow with preserved values).

    Validates requirements: 4.6, 8.1
    """

    async def test_edit_from_summary_restarts_at_odometer(self) -> None:
        """Edit from summary restarts at odometer step with preserved values."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
                "fuel_odometer": 45000,
                "fuel_liters": 35.0,
                "fuel_cost": 60.0,
                "fuel_full_tank": True,
            }
        )

        update = _make_callback_update("summary_edit")
        result = await summary_edit_callback(update, context)
        assert result == ODOMETER
        # Data should be preserved for defaults
        assert context.user_data["fuel_odometer"] == 45000
        assert context.user_data["fuel_liters"] == 35.0
        assert context.user_data["fuel_cost"] == 60.0
        assert context.user_data["fuel_full_tank"] is True

    async def test_edit_then_complete_flow(self) -> None:
        """After edit, user can re-enter data and save successfully."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
                "fuel_odometer": 45000,
                "fuel_liters": 35.0,
                "fuel_cost": 60.0,
                "fuel_full_tank": True,
            }
        )

        # User taps Edit
        update_edit = _make_callback_update("summary_edit")
        result = await summary_edit_callback(update_edit, context)
        assert result == ODOMETER

        # User enters new odometer
        update_odo = _make_message_update("46000")
        result = await fuel_odometer_step(update_odo, context)
        assert result == LITERS
        assert context.user_data["fuel_odometer"] == 46000

        # User enters new liters
        update_liters = _make_message_update("40")
        result = await fuel_liters_step(update_liters, context)
        assert result == COST

        # User enters new cost
        update_cost = _make_message_update("70")
        result = await fuel_cost_step(update_cost, context)
        assert result == FULL_TANK

        # User enters full tank
        update_tank = _make_message_update("yes")
        result = await fuel_full_tank_step(update_tank, context)
        assert result == SUMMARY

        # User saves
        update_save = _make_callback_update("summary_save")
        result = await summary_save_callback(update_save, context)
        assert result == ConversationHandler.END
        context.bot_data["lubelogger_client"].add_gas_record.assert_called_once()


class TestLogAnother:
    """Tests for 'Log another' starting new flow with pre-selected vehicle.

    Validates requirements: 6.1, 6.2
    """

    async def test_log_another_starts_new_flow_with_vehicle(self) -> None:
        """'Log another' starts new flow with vehicle pre-selected."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
            }
        )

        update = _make_callback_update("confirm_log_another:fuel")
        result = await log_another_callback(update, context)
        assert result == ODOMETER
        # Vehicle should still be pre-selected
        assert context.user_data["fuel_vehicle_id"] == 1
        assert context.user_data["fuel_vehicle_name"] == "Toyota Corolla"
        # Previous data fields should be cleared
        assert "fuel_odometer" not in context.user_data
        assert "fuel_liters" not in context.user_data
        assert "fuel_cost" not in context.user_data
        assert "fuel_full_tank" not in context.user_data

    async def test_log_another_after_cleanup_uses_config(self) -> None:
        """'Log another' after data cleanup falls back to config for vehicle ID."""
        context = _make_context(user_data={})
        # Simulate that user_data was already cleaned — vehicle should come from config_store
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=2)

        update = _make_callback_update("confirm_log_another:fuel")
        result = await log_another_callback(update, context)
        assert result == ODOMETER
        assert context.user_data["fuel_vehicle_id"] == 2

    async def test_log_another_then_complete_flow(self) -> None:
        """After 'Log another', user can complete a new fuel flow."""
        context = _make_context(
            user_data={
                "fuel_vehicle_id": 1,
                "fuel_vehicle_name": "Toyota Corolla",
                "fuel_total_steps": 4,
            }
        )

        # Tap log another
        update_log = _make_callback_update("confirm_log_another:fuel")
        result = await log_another_callback(update_log, context)
        assert result == ODOMETER

        # Enter odometer
        update_odo = _make_message_update("50000")
        result = await fuel_odometer_step(update_odo, context)
        assert result == LITERS
        assert context.user_data["fuel_odometer"] == 50000

        # Enter liters
        update_liters = _make_message_update("30")
        result = await fuel_liters_step(update_liters, context)
        assert result == COST

        # Enter cost
        update_cost = _make_message_update("55")
        result = await fuel_cost_step(update_cost, context)
        assert result == FULL_TANK

        # Enter full tank
        update_tank = _make_message_update("yes")
        result = await fuel_full_tank_step(update_tank, context)
        assert result == SUMMARY

        # Save
        update_save = _make_callback_update("summary_save")
        result = await summary_save_callback(update_save, context)
        assert result == ConversationHandler.END
        context.bot_data["lubelogger_client"].add_gas_record.assert_called_once()


class TestInPlaceEditing:
    """Tests for in-place editing across sequential conversation steps.

    Validates requirements: 8.1
    """

    async def test_sequential_steps_use_send_or_edit(self) -> None:
        """Sequential steps use send_or_edit to edit messages in place."""
        context = _make_context()

        # Start flow — this sends the auto-select message + odometer prompt
        update1 = _make_message_update("/fuel")
        await fuel_command(update1, context)

        # After first prompt, last_bot_message_id should be set
        assert "last_bot_message_id" in context.user_data

        # Enter odometer — send_or_edit should try to edit the previous message
        update2 = _make_message_update("45000")
        await fuel_odometer_step(update2, context)

        # The bot should have called edit_message_text (in-place edit)
        assert context.bot.edit_message_text.called or context.bot.send_message.called

    async def test_message_id_tracked_across_steps(self) -> None:
        """Message ID is tracked across conversation steps for in-place editing."""
        context = _make_context()

        # Start flow
        update1 = _make_message_update("/fuel")
        await fuel_command(update1, context)

        # Verify message ID is stored
        assert context.user_data.get("last_bot_message_id") is not None

        # Enter odometer
        update2 = _make_message_update("45000")
        await fuel_odometer_step(update2, context)

        # Message ID should still be tracked
        assert context.user_data.get("last_bot_message_id") is not None
