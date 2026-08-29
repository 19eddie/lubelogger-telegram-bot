"""Handler for the Latest menu — last fuel and last odometer (Requirements 10.1-10.5).

Sends one message offering the two choices. Each selection edits in place, keeping a back button.
Empty records and unreachable instance both render as notices with back button preserved.
What is read folds into the odometer tracker.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from bot.callbacks import CallbackAction, decode
from bot.exceptions import LubeLoggerUnreachableError
from bot.formatters import render_latest_fuel, render_latest_odometer
from bot.i18n import get_text
from bot.keyboards import LatestTarget, latest_menu_keyboard, latest_record_keyboard
from bot.services.card_service import CardService
from bot.services.consumption import FuelPoint, resolve
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.odometer_tracker import OdometerTracker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def open_latest_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the Latest menu from a Menu_Label tap or from a confirmation (Requirements 10.1, 6.10).

    Sends one message offering last fuel and last odometer with back button.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    query = update.callback_query
    msg = update.effective_message

    if user is None or chat_id is None or msg is None:
        return

    user_id = user.id
    config_store = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)

    # Open new message carrying the Latest menu (Requirement 10.1).
    text = get_text("card_latest_menu_title", lang)
    markup = latest_menu_keyboard(lang)

    card_service: CardService = context.bot_data["card_service"]
    message_id = await card_service.open(chat_id, text, markup)

    # Store message_id in context so subsequent callbacks edit this message.
    if "latest_menu_message_id" not in context.user_data:
        context.user_data["latest_menu_message_id"] = {}
    context.user_data["latest_menu_message_id"][chat_id] = message_id

    if query:
        await query.answer()


async def handle_latest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a tap on the Latest menu or its child screens.

    Edits the same message in place with back button preserved.
    Requirements 10.2, 10.3.
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None

    if query is None or user is None or chat_id is None:
        return

    await query.answer()

    user_id = user.id
    config_store = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)

    # Decode the callback.
    try:
        cb = decode(query.data)
    except (ValueError, IndexError):
        logger.warning(f"Invalid callback_data: {query.data}")
        return

    # Get card_service and message_id.
    card_service: CardService = context.bot_data["card_service"]
    msg_id_map = context.user_data.get("latest_menu_message_id", {})
    message_id = msg_id_map.get(chat_id)

    if message_id is None:
        # Shouldn't happen, but fall back to the current message.
        message_id = query.message.message_id if query.message else None

    if message_id is None:
        return

    # Route to the target.
    if cb.action == CallbackAction.LATEST_OPEN:
        target = LatestTarget(cb.arg or 0)

        if target == LatestTarget.FUEL:
            # Show last fuel record (Requirement 10.2).
            await _show_latest_fuel(
                query, context, user_id, chat_id, message_id, lang
            )

        elif target == LatestTarget.ODOMETER:
            # Show last odometer record (Requirement 10.2).
            await _show_latest_odometer(
                query, context, user_id, chat_id, message_id, lang
            )

    elif cb.action == CallbackAction.LATEST_BACK:
        # Back button → return to Latest menu.
        # Requirement 10.3.
        text = get_text("card_latest_menu_title", lang)
        markup = latest_menu_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        msg_id_map[chat_id] = message_id


async def _show_latest_fuel(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show the latest fuel record with back button (Requirements 10.2, 10.3)."""
    config_store = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    tracker: OdometerTracker = context.bot_data["tracker"]
    card_service: CardService = context.bot_data["card_service"]

    # Get active vehicle.
    vehicle_id = await config_store.get_active_vehicle(user_id)
    vehicle_name = await config_store.get_active_vehicle_name(user_id)

    if vehicle_id is None:
        text = get_text("card_latest_no_vehicle", lang)
        markup = latest_record_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id
        return

    try:
        # Fetch records (Requirement 10.1 — fold into tracker).
        records = await client.get_gas_records(vehicle_id)
    except LubeLoggerUnreachableError:
        # Unreachable instance → show notice with back button (Requirement 10.5).
        text = get_text("card_latest_unreachable", lang)
        markup = latest_record_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id
        return

    # Fold records into tracker (Requirement 10.1, 5.4).
    if records:
        await tracker.observe_records(vehicle_id, gas=records)

    # Show the latest fuel record (Requirement 10.2).
    record = records[0] if records else None

    # Compute consumption if available (Requirement 6.5).
    consumption = None
    if record:
        previous = records[1] if len(records) > 1 else None
        if record.fuel_consumed and record.odometer and previous:
            consumption = resolve(
                record.fuel_economy,
                current=FuelPoint(
                    odometer=record.odometer,
                    liters=record.fuel_consumed,
                    is_fill_to_full=record.is_fill_to_full or False,
                    missed_fuel_up=record.missed_fuel_up or False,
                ),
                previous=FuelPoint(
                    odometer=previous.odometer or 0,
                    liters=previous.fuel_consumed or 0,
                    is_fill_to_full=previous.is_fill_to_full or False,
                    missed_fuel_up=previous.missed_fuel_up or False,
                ),
            )

    text = render_latest_fuel(record, vehicle_name, consumption, lang)
    markup = latest_record_keyboard(lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id


async def _show_latest_odometer(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show the latest odometer record with back button (Requirements 10.2, 10.3)."""
    config_store = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    tracker: OdometerTracker = context.bot_data["tracker"]
    card_service: CardService = context.bot_data["card_service"]

    # Get active vehicle.
    vehicle_id = await config_store.get_active_vehicle(user_id)
    vehicle_name = await config_store.get_active_vehicle_name(user_id)

    if vehicle_id is None:
        text = get_text("card_latest_no_vehicle", lang)
        markup = latest_record_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id
        return

    try:
        # Fetch records (Requirement 10.1 — fold into tracker).
        records = await client.get_odometer_records(vehicle_id)
    except LubeLoggerUnreachableError:
        # Unreachable instance → show notice with back button (Requirement 10.5).
        text = get_text("card_latest_unreachable", lang)
        markup = latest_record_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id
        return

    # Fold records into tracker (Requirement 10.1, 5.4).
    if records:
        await tracker.observe_records(vehicle_id, odometer=records)

    # Show the latest odometer record (Requirement 10.2).
    # Empty result renders as notice with back button (Requirement 10.4).
    record = records[0] if records else None

    text = render_latest_odometer(record, vehicle_name, lang)
    markup = latest_record_keyboard(lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("latest_menu_message_id", {})[chat_id] = message_id
