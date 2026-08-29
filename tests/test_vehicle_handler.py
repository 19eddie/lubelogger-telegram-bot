"""Tests for vehicle handler — single fetch and fallback label.

Requirements: 13.3, 13.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.vehicle import vehicle_callback, vehicle_command
from bot.services.config_store import ConfigStore
from bot.services.database import init_db


def _make_snapshot(vehicle_id: int, name: str) -> MagicMock:
    """Build a mock VehicleSnapshot."""
    snap = MagicMock()
    snap.vehicle.id = vehicle_id
    snap.vehicle.display_name = name
    return snap


def _make_update_and_context(
    text: str = "/vehicle",
    user_id: int = 123,
) -> tuple[MagicMock, MagicMock]:
    """Create mock Update and Context."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    return update, context


class TestVehicleHandler:
    """Tests for /vehicle command and callback."""

    @pytest.mark.asyncio
    async def test_single_vehicle_snapshots_call(self, tmp_path: object) -> None:
        """/vehicle + selection callback issues exactly one get_vehicle_snapshots call.

        Requirement 13.3: resolve vehicle names without a second call.
        """
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)
        config_store = ConfigStore(db_path)

        snapshots = [
            _make_snapshot(1, "Toyota Yaris"),
            _make_snapshot(2, "Fiat Punto"),
        ]
        client = AsyncMock()
        client.get_vehicle_snapshots = AsyncMock(return_value=snapshots)

        # Step 1: /vehicle command
        update, context = _make_update_and_context()
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": client,
        }

        await vehicle_command(update, context)

        # Step 2: Selection callback
        cb_update = MagicMock()
        cb_update.effective_user.id = 123
        cb_update.callback_query.data = "vehicle:1"
        cb_update.callback_query.answer = AsyncMock()
        cb_update.callback_query.edit_message_text = AsyncMock()

        cb_context = MagicMock()
        cb_context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": client,
            "allowed_user_ids": [],
        }
        # The mapping was stored by vehicle_command in the same user_data
        cb_context.user_data = context.user_data

        await vehicle_callback(cb_update, cb_context)

        # Verify: exactly one API call total
        assert client.get_vehicle_snapshots.call_count == 1

        # Verify the name was resolved from the mapping
        active_name = await config_store.get_active_vehicle_name(123)
        assert active_name == "Toyota Yaris"

    @pytest.mark.asyncio
    async def test_unnameable_vehicle_renders_fallback(self, tmp_path: object) -> None:
        """A vehicle with empty display_name uses the localized fallback label.

        Requirement 13.6: localized fallback instead of 'Vehicle #<id>'.
        """
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)
        config_store = ConfigStore(db_path)

        # Vehicle with empty name
        snapshots = [_make_snapshot(1, "")]
        client = AsyncMock()
        client.get_vehicle_snapshots = AsyncMock(return_value=snapshots)

        update, context = _make_update_and_context()
        context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": client,
        }

        await vehicle_command(update, context)

        # Check the keyboard button text
        call_kwargs = update.message.reply_text.call_args
        reply_markup = call_kwargs[1]["reply_markup"]
        button_text = reply_markup.inline_keyboard[0][0].text

        # Should NOT be "Vehicle #1" or empty
        assert button_text != ""
        assert "Vehicle #" not in button_text
        # Should be the localized fallback (from locale file)
        assert button_text == "Unnamed vehicle"

    @pytest.mark.asyncio
    async def test_callback_without_mapping_uses_fallback(self, tmp_path: object) -> None:
        """When the mapping is gone (e.g. bot restarted), use localized fallback.

        Requirement 13.6: never use 'Vehicle #<id>'.
        """
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        await init_db(db_path)
        config_store = ConfigStore(db_path)

        cb_update = MagicMock()
        cb_update.effective_user.id = 123
        cb_update.callback_query.data = "vehicle:1"
        cb_update.callback_query.answer = AsyncMock()
        cb_update.callback_query.edit_message_text = AsyncMock()

        cb_context = MagicMock()
        cb_context.bot_data = {
            "config_store": config_store,
            "lubelogger_client": AsyncMock(),
            "allowed_user_ids": [],
        }
        # No mapping available (simulates bot restart)
        cb_context.user_data = {}

        await vehicle_callback(cb_update, cb_context)

        # The name persisted should be the fallback (not "Vehicle #1")
        active_name = await config_store.get_active_vehicle_name(123)
        assert active_name is not None
        assert "Vehicle #" not in active_name
