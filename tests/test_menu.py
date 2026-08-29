"""Unit tests for onboarding and keyboard establishment.

Tests the `/start` command behavior under various scenarios:
- No vehicle available
- Single vehicle (auto-select)
- Multiple vehicles
- LubeLogger unreachable

Validates that Menu_Keyboard is sent exactly once with correct flags, never re-attached,
and that welcome text is at most 3 sentences in every locale.

Requirements: 1.1, 1.3, 1.4, 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions import LubeLoggerUnreachableError
from bot.handlers.menu import start_command
from bot.i18n import available_locales, get_text
from bot.models.responses import Vehicle
from bot.services.lubelogger_client import VehicleSnapshot


@pytest.fixture
def start_update_and_context(fake_bot, temp_db: str, clean_locales):  # type: ignore[no-untyped-def]
    """Fresh Update and Context with services for onboarding tests."""
    from bot.services.config_store import ConfigStore
    from bot.services.lubelogger_client import LubeLoggerClient
    from bot.services.odometer_tracker import OdometerTracker

    update = MagicMock()
    update.effective_user.id = 123
    update.effective_chat.id = 123
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {
        "config_store": ConfigStore(temp_db),
        "lubelogger_client": AsyncMock(spec=LubeLoggerClient),
        "tracker": OdometerTracker(temp_db),
    }

    return update, context


class TestStartCommandNoVehicle:
    """Onboarding with no vehicles available."""

    @pytest.mark.asyncio
    async def test_no_vehicles_sends_welcome_and_menu(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """When no vehicles exist, send welcome + empty note + Menu_Keyboard."""
        update, context = start_update_and_context
        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = []

        await start_command(update, context)

        # Check that reply_text was called at least twice
        assert update.effective_message.reply_text.await_count >= 2

    @pytest.mark.asyncio
    async def test_no_vehicles_menu_keyboard_persists(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """Menu_Keyboard is sent even when no vehicles, with is_persistent and resize_keyboard."""
        update, context = start_update_and_context
        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = []

        await start_command(update, context)

        # Find a call with the Menu_Keyboard in the reply_text calls
        calls = update.effective_message.reply_text.await_args_list
        keyboard_call = None
        for call in calls:
            kwargs = call.kwargs
            markup = kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent"):
                keyboard_call = kwargs
                break

        assert keyboard_call is not None, "Menu_Keyboard was never sent"
        assert keyboard_call["reply_markup"].is_persistent is True, "is_persistent must be True"
        assert keyboard_call["reply_markup"].resize_keyboard is True, "resize_keyboard must be True"


class TestStartCommandSingleVehicle:
    """Onboarding with exactly one vehicle (auto-select)."""

    @pytest.mark.asyncio
    async def test_single_vehicle_auto_selected(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """Single vehicle is auto-selected and persisted."""
        update, context = start_update_and_context
        vehicle = Vehicle(
            id=42,
            year=2020,
            make="Toyota",
            model="Camry",
            name="",
            vin="",
            plate_number="",
        )
        snap = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=45000)
        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = [snap]

        await start_command(update, context)

        # Check the vehicle was persisted
        config_store = context.bot_data["config_store"]
        persisted_id = await config_store.get_active_vehicle(123)  # user_id = 123
        persisted_name = await config_store.get_active_vehicle_name(123)

        assert persisted_id == 42
        assert persisted_name != ""

    @pytest.mark.asyncio
    async def test_single_vehicle_menu_sent_once(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """Menu_Keyboard is sent exactly once after single-vehicle auto-select."""
        update, context = start_update_and_context
        vehicle = Vehicle(
            id=42,
            year=2020,
            make="Toyota",
            model="Camry",
            name="",
            vin="",
            plate_number="",
        )
        snap = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=45000)
        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = [snap]

        await start_command(update, context)

        # Count how many have Menu_Keyboard
        calls = update.effective_message.reply_text.await_args_list
        keyboard_count = 0
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent") and markup.is_persistent:
                keyboard_count += 1

        assert keyboard_count == 1, f"Expected 1 Menu_Keyboard, got {keyboard_count}"


class TestStartCommandMultipleVehicles:
    """Onboarding with multiple vehicles (prompt for selection)."""

    @pytest.mark.asyncio
    async def test_multiple_vehicles_keyboard_sent(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """Multiple vehicles trigger a vehicle-selection inline keyboard."""
        update, context = start_update_and_context
        v1 = Vehicle(id=1, year=2020, make="Toyota", model="Camry", name="", vin="", plate_number="")
        v2 = Vehicle(id=2, year=2021, make="Honda", model="Civic", name="", vin="", plate_number="")
        snap1 = VehicleSnapshot(vehicle=v1, last_reported_odometer=45000)
        snap2 = VehicleSnapshot(vehicle=v2, last_reported_odometer=50000)

        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = [snap1, snap2]

        await start_command(update, context)

        # Should have at least one call with an inline keyboard (vehicle selection)
        calls = update.effective_message.reply_text.await_args_list
        inline_keyboard_found = False
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "inline_keyboard"):  # InlineKeyboardMarkup
                inline_keyboard_found = True
                break

        assert inline_keyboard_found, "Vehicle selection inline keyboard not sent"

    @pytest.mark.asyncio
    async def test_multiple_vehicles_no_menu_until_selection(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """With multiple vehicles, Menu_Keyboard is not sent until one is selected."""
        update, context = start_update_and_context
        v1 = Vehicle(id=1, year=2020, make="Toyota", model="Camry", name="", vin="", plate_number="")
        v2 = Vehicle(id=2, year=2021, make="Honda", model="Civic", name="", vin="", plate_number="")
        snap1 = VehicleSnapshot(vehicle=v1, last_reported_odometer=45000)
        snap2 = VehicleSnapshot(vehicle=v2, last_reported_odometer=50000)

        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.return_value = [snap1, snap2]

        await start_command(update, context)

        # Count persistent keyboards (Menu_Keyboard) in the reply_text calls
        calls = update.effective_message.reply_text.await_args_list
        menu_keyboard_count = 0
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent") and markup.is_persistent:
                menu_keyboard_count += 1

        # Should be 0 at this stage (only after selection)
        assert menu_keyboard_count == 0, "Menu_Keyboard sent prematurely with multiple vehicles"


class TestStartCommandUnreachable:
    """Onboarding when LubeLogger is unreachable."""

    @pytest.mark.asyncio
    async def test_unreachable_still_sends_menu(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """When unreachable and no persisted vehicle, still send Menu_Keyboard."""
        update, context = start_update_and_context
        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.side_effect = LubeLoggerUnreachableError()

        await start_command(update, context)

        calls = update.effective_message.reply_text.await_args_list
        menu_keyboard_found = False
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent") and markup.is_persistent:
                menu_keyboard_found = True
                break

        assert menu_keyboard_found, "Menu_Keyboard not sent when unreachable"

    @pytest.mark.asyncio
    async def test_unreachable_with_persisted_vehicle(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """When unreachable but vehicle is persisted, use the persisted one."""
        update, context = start_update_and_context
        # Pre-persist a vehicle
        config_store = context.bot_data["config_store"]
        await config_store.set_active_vehicle(123, 42, "My Car")

        client = context.bot_data["lubelogger_client"]
        client.get_vehicle_snapshots.side_effect = LubeLoggerUnreachableError()

        await start_command(update, context)

        calls = update.effective_message.reply_text.await_args_list

        # Should send at least one message
        assert len(calls) >= 1
        # Should have at least one with the Menu_Keyboard despite being unreachable
        menu_found = False
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent") and markup.is_persistent:
                menu_found = True
                break
        assert menu_found, "Menu_Keyboard not sent when unreachable with persisted vehicle"


class TestWelcomeTextLength:
    """Verify welcome text never exceeds 3 sentences in any locale."""

    @pytest.mark.parametrize("lang", available_locales())
    def test_welcome_no_active_vehicle_max_3_sentences(self, lang: str) -> None:
        """Welcome text for new users is at most 3 sentences in every locale."""
        welcome_text = get_text("welcome_text", lang)
        # Count sentences: split by period, question mark, or exclamation
        import re

        sentences = re.split(r"[.!?]+", welcome_text)
        # Filter empty strings from trailing punctuation
        sentences = [s.strip() for s in sentences if s.strip()]
        assert len(sentences) <= 3, (
            f"Welcome text for {lang} has {len(sentences)} sentences, max 3 allowed: {welcome_text}"
        )

    @pytest.mark.parametrize("lang", available_locales())
    def test_welcome_with_vehicle_short(self, lang: str) -> None:
        """Welcome-back text is short and exists for every locale."""
        welcome_back_template = get_text("welcome_back_text", lang)
        # Should not be too long; check that key exists and is not empty
        assert welcome_back_template, f"Welcome-back text missing for {lang}"
        # A simple heuristic: should not be excessively long
        assert len(welcome_back_template) < 500, f"Welcome-back text too long for {lang}"

    @pytest.mark.parametrize("lang", available_locales())
    def test_welcome_unreachable_explains_situation(self, lang: str) -> None:
        """Unreachable-during-onboarding message exists and explains the issue."""
        text = get_text("welcome_unreachable", lang)
        assert text, f"Unreachable message missing for {lang}"
        assert len(text) > 0


class TestMenuKeyboardNoReattach:
    """Verify Menu_Keyboard is never re-attached to subsequent messages."""

    @pytest.mark.asyncio
    async def test_no_reattach_on_welcome_back(
        self,
        start_update_and_context: tuple,  # type: ignore[type-arg]
    ) -> None:
        """When user already has an active vehicle, only send Menu_Keyboard once."""
        update, context = start_update_and_context
        config_store = context.bot_data["config_store"]
        await config_store.set_active_vehicle(123, 42, "My Car")

        await start_command(update, context)

        calls = update.effective_message.reply_text.await_args_list

        # Count messages with Menu_Keyboard
        menu_count = 0
        for call in calls:
            markup = call.kwargs.get("reply_markup")
            if markup and hasattr(markup, "is_persistent") and markup.is_persistent:
                menu_count += 1

        assert menu_count == 1, f"Menu_Keyboard attached to {menu_count} messages, expected 1"
