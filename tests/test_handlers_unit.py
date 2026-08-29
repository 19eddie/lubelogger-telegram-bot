"""Unit tests for handler inline-argument and flow-delegation paths.

After task 16.1, /fuel, /service, /km with args submit inline (return END),
without args delegate to start_flow (return COLLECT).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

from bot.handlers.fuel import fuel_command
from bot.handlers.odometer import km_command
from bot.handlers.record_flow import COLLECT
from bot.handlers.service import service_command

END = ConversationHandler.END


def _make_update_and_context(
    text: str = "",
    args: list[str] | None = None,
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context objects for handler testing."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = 999
    update.message.text = text
    update.message.chat_id = 999
    update.message.reply_text = AsyncMock()
    update.effective_message = update.message

    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    context.bot = AsyncMock()

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle = AsyncMock(return_value=1)
    config_store.get_active_vehicle_name = AsyncMock(return_value="Test Car")

    tracker = AsyncMock()
    tracker.get_reference = AsyncMock(return_value=None)

    submitter = AsyncMock()
    submitter.submit = AsyncMock(
        return_value=MagicMock(status="saved", consumption=None, vehicle_name="Test Car")
    )

    client = AsyncMock()
    client.get_vehicle_snapshots = AsyncMock(return_value=[])

    card_service = AsyncMock()
    card_service.open = AsyncMock(return_value=100)
    card_service.update = AsyncMock(return_value=100)

    context.bot_data = {
        "config_store": config_store,
        "lubelogger_client": client,
        "queue_service": AsyncMock(),
        "tracker": tracker,
        "record_submitter": submitter,
        "card_service": card_service,
    }

    return update, context


class TestFuelInlinePath:
    """Tests for /fuel inline-argument submission (Requirement 12.1)."""

    async def test_fuel_with_args_submits_and_returns_end(self) -> None:
        """/fuel 45000 42.5 78.90 should submit inline and return END."""
        update, context = _make_update_and_context(
            text="/fuel 45000 42.5 78.90", args=["45000", "42.5", "78.90"]
        )

        result = await fuel_command(update, context)

        assert result == END
        context.bot_data["record_submitter"].submit.assert_called_once()

    async def test_fuel_with_args_renders_confirmation(self) -> None:
        """/fuel with args should reply with rich confirmation."""
        update, context = _make_update_and_context(
            text="/fuel 45000 42.5 78.90", args=["45000", "42.5", "78.90"]
        )

        await fuel_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args[1]
        assert call_kwargs.get("parse_mode") == "HTML"

    async def test_fuel_with_bad_args_returns_end_with_usage(self) -> None:
        """/fuel with invalid args should show usage and return END."""
        update, context = _make_update_and_context(
            text="/fuel abc", args=["abc"]
        )

        result = await fuel_command(update, context)

        assert result == END

    async def test_fuel_no_vehicle_returns_end(self) -> None:
        """/fuel without active vehicle should inform user and return END."""
        update, context = _make_update_and_context(
            text="/fuel 45000 42.5 78.90", args=["45000", "42.5", "78.90"]
        )
        context.bot_data["config_store"].get_active_vehicle = AsyncMock(return_value=None)

        result = await fuel_command(update, context)

        assert result == END


class TestFuelFlowDelegation:
    """Tests for /fuel without args delegating to start_flow."""

    @patch("bot.handlers.fuel.start_flow", new_callable=AsyncMock)
    async def test_fuel_without_args_delegates_to_start_flow(
        self, mock_start_flow: AsyncMock
    ) -> None:
        """/fuel without args should call start_flow with kind=FUEL."""
        mock_start_flow.return_value = COLLECT
        update, context = _make_update_and_context(text="/fuel", args=[])

        result = await fuel_command(update, context)

        assert result == COLLECT
        mock_start_flow.assert_called_once()
        call_kwargs = mock_start_flow.call_args[1]
        from bot.flows.definitions import FlowKind

        assert call_kwargs["kind"] == FlowKind.FUEL

    @patch("bot.handlers.fuel.start_flow", new_callable=AsyncMock)
    async def test_fuel_vehicle_override_passed_to_start_flow(
        self, mock_start_flow: AsyncMock
    ) -> None:
        """/fuel --vehicle 5 without data args should pass override to start_flow."""
        mock_start_flow.return_value = COLLECT
        update, context = _make_update_and_context(
            text="/fuel --vehicle 5", args=["--vehicle", "5"]
        )

        await fuel_command(update, context)

        call_kwargs = mock_start_flow.call_args[1]
        assert call_kwargs["vehicle_override"] == 5


class TestServiceInlinePath:
    """Tests for /service inline-argument submission (Requirement 12.1)."""

    async def test_service_with_args_submits_and_returns_end(self) -> None:
        """/service 50000 "Oil change" 45.50 should submit inline and return END."""
        update, context = _make_update_and_context(
            text='/service 50000 "Oil change" 45.50', args=["50000", '"Oil', 'change"', "45.50"]
        )

        result = await service_command(update, context)

        assert result == END
        context.bot_data["record_submitter"].submit.assert_called_once()


class TestServiceFlowDelegation:
    """Tests for /service without args delegating to start_flow."""

    @patch("bot.handlers.service.start_flow", new_callable=AsyncMock)
    async def test_service_without_args_delegates_to_start_flow(
        self, mock_start_flow: AsyncMock
    ) -> None:
        """/service without args should call start_flow with kind=SERVICE."""
        mock_start_flow.return_value = COLLECT
        update, context = _make_update_and_context(text="/service", args=[])

        result = await service_command(update, context)

        assert result == COLLECT
        mock_start_flow.assert_called_once()
        from bot.flows.definitions import FlowKind

        call_kwargs = mock_start_flow.call_args[1]
        assert call_kwargs["kind"] == FlowKind.SERVICE


class TestOdometerInlinePath:
    """Tests for /km inline-argument submission (Requirement 12.1)."""

    async def test_km_with_args_submits_and_returns_end(self) -> None:
        """/km 45000 should submit inline and return END."""
        update, context = _make_update_and_context(text="/km 45000", args=["45000"])

        result = await km_command(update, context)

        assert result == END
        context.bot_data["record_submitter"].submit.assert_called_once()

    async def test_km_with_bad_args_returns_end(self) -> None:
        """/km with non-numeric arg should return END."""
        update, context = _make_update_and_context(text="/km abc", args=["abc"])

        result = await km_command(update, context)

        assert result == END


class TestOdometerFlowDelegation:
    """Tests for /km without args delegating to start_flow."""

    @patch("bot.handlers.odometer.start_flow", new_callable=AsyncMock)
    async def test_km_without_args_delegates_to_start_flow(
        self, mock_start_flow: AsyncMock
    ) -> None:
        """/km without args should call start_flow with kind=ODOMETER."""
        mock_start_flow.return_value = COLLECT
        update, context = _make_update_and_context(text="/km", args=[])

        result = await km_command(update, context)

        assert result == COLLECT
        mock_start_flow.assert_called_once()
        from bot.flows.definitions import FlowKind

        call_kwargs = mock_start_flow.call_args[1]
        assert call_kwargs["kind"] == FlowKind.ODOMETER
