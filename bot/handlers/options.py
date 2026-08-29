"""Handler for the Options_Menu — vehicle, language, status and queue (Requirements 1.9-1.13).

Every selection edits the same message in place, keeping a back button.
Vehicle and language selections avoid going into the Menu_Keyboard per Requirement 1.13.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from bot.callbacks import CallbackAction, decode
from bot.exceptions import LubeLoggerUnreachableError
from bot.formatters import render_welcome
from bot.i18n import available_locales, get_text
from bot.keyboards import (
    OptionsTarget,
    VehicleChoice,
    language_keyboard,
    options_back_keyboard,
    options_menu_keyboard,
    vehicle_keyboard,
)
from bot.services.card_service import CardService
from bot.services.command_registry import register_for_chat
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)


async def open_options_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the Options_Menu from a Menu_Label tap or from /options.

    Sends one message carrying the menu: vehicle, language, status, queue.
    Requirement 1.9.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    query = update.callback_query
    msg = update.effective_message

    if user is None or chat_id is None or msg is None:
        return

    user_id = user.id
    config_store: ConfigStore = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)

    # Open new message carrying the Options_Menu (Requirement 1.9).
    # We send a new message here. Every subsequent tap will edit it.
    text = get_text("card_options_menu_title", lang)
    markup = options_menu_keyboard(lang)

    card_service: CardService = context.bot_data["card_service"]
    message_id = await card_service.open(chat_id, text, markup)

    # Store message_id in context so subsequent callbacks edit this message.
    if "options_menu_message_id" not in context.user_data:
        context.user_data["options_menu_message_id"] = {}
    context.user_data["options_menu_message_id"][chat_id] = message_id

    if query:
        await query.answer()


async def handle_options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a tap on the Options_Menu or its child screens.

    Edits the same message in place with back button preserved.
    Requirement 1.10, 1.11.
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None

    if query is None or user is None or chat_id is None:
        return

    await query.answer()

    user_id = user.id
    config_store: ConfigStore = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)

    # Decode the callback.
    try:
        cb = decode(query.data)
    except (ValueError, IndexError):
        logger.warning(f"Invalid callback_data: {query.data}")
        return

    # Get card_service and message_id.
    card_service: CardService = context.bot_data["card_service"]
    msg_id_map = context.user_data.get("options_menu_message_id", {})
    message_id = msg_id_map.get(chat_id)

    if message_id is None:
        # Shouldn't happen, but fall back to the current message.
        message_id = query.message.message_id if query.message else None

    if message_id is None:
        return

    # Route to the target.
    if cb.action == CallbackAction.OPTIONS_OPEN:
        target = OptionsTarget(cb.arg or 0)

        if target == OptionsTarget.VEHICLE:
            # Show vehicle selection (Requirement 1.9, 1.11).
            await _show_vehicle_selection(
                query, context, user_id, chat_id, message_id, lang
            )

        elif target == OptionsTarget.LANG:
            # Show language selection (Requirement 1.9, 1.11).
            await _show_language_selection(
                query, context, user_id, chat_id, message_id, lang
            )

        elif target == OptionsTarget.STATUS:
            # Show connectivity and queue status (Requirement 1.9, 1.11).
            await _show_status(query, context, user_id, chat_id, message_id, lang)

        elif target == OptionsTarget.QUEUE:
            # Show queue details (Requirement 1.9, 1.11).
            await _show_queue(query, context, user_id, chat_id, message_id, lang)

    elif cb.action == CallbackAction.OPTIONS_BACK:
        # Back button → return to Options_Menu.
        # Requirement 1.11.
        text = get_text("card_options_menu_title", lang)
        markup = options_menu_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        msg_id_map[chat_id] = message_id


async def _show_vehicle_selection(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show the vehicle selection screen with back button (Requirement 1.11, 1.13)."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    card_service: CardService = context.bot_data["card_service"]

    try:
        snapshots = await client.get_vehicle_snapshots()
    except LubeLoggerUnreachableError:
        text = get_text("card_options_unreachable", lang)
        markup = options_back_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("options_menu_message_id", {})[chat_id] = message_id
        return

    if not snapshots:
        text = get_text("card_options_no_vehicles", lang)
        markup = options_back_keyboard(lang)
        message_id = await card_service.update(chat_id, message_id, text, markup)
        context.user_data.get("options_menu_message_id", {})[chat_id] = message_id
        return

    # Build vehicle list.
    vehicles = [
        VehicleChoice(vehicle_id=snap.vehicle.id, name=snap.vehicle.display_name)
        for snap in snapshots
    ]

    text = get_text("card_options_vehicle_title", lang)
    markup = vehicle_keyboard(vehicles, lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id


async def handle_vehicle_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle vehicle selection from Options_Menu (Requirement 1.10, 1.13).

    Edits the message to show the new active vehicle and keep the back button.
    Vehicle selection stays off the Menu_Keyboard per Requirement 1.13.
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None

    if query is None or user is None or chat_id is None:
        return

    await query.answer()

    user_id = user.id
    config_store: ConfigStore = context.bot_data["config_store"]
    card_service: CardService = context.bot_data["card_service"]
    lang = await config_store.get_language(user_id)

    # Decode the callback to get vehicle_id.
    try:
        cb = decode(query.data)
        if cb.action != CallbackAction.VEHICLE_SET:
            return
        vehicle_id = cb.arg
        if vehicle_id is None:
            return
    except (ValueError, IndexError):
        logger.warning(f"Invalid callback_data: {query.data}")
        return

    # Persist the vehicle.
    try:
        snapshots = await context.bot_data["lubelogger_client"].get_vehicle_snapshots()
        snap = next((s for s in snapshots if s.vehicle.id == vehicle_id), None)
        if snap is None:
            return
        vehicle_name = snap.vehicle.display_name
    except LubeLoggerUnreachableError:
        vehicle_name = ""

    await config_store.set_active_vehicle(user_id, vehicle_id, vehicle_name)

    # Show confirmation and back button (Requirement 1.10, 1.11).
    text = get_text("card_options_vehicle_selected", lang, vehicle_name=vehicle_name)
    markup = options_back_keyboard(lang)
    message_id = await card_service.update(
        chat_id, query.message.message_id, text, markup
    )
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id


async def _show_language_selection(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show the language selection screen with back button (Requirement 1.11, 1.13)."""
    card_service: CardService = context.bot_data["card_service"]

    text = get_text("card_options_lang_title", lang)
    markup = language_keyboard(lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id


async def handle_language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle language selection from Options_Menu (Requirement 1.10, 1.13).

    Edits the message to show the new language and keep the back button.
    Language selection stays off the Menu_Keyboard per Requirement 1.13.
    Re-registers commands in the new language.
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None

    if query is None or user is None or chat_id is None:
        return

    await query.answer()

    user_id = user.id
    config_store: ConfigStore = context.bot_data["config_store"]
    card_service: CardService = context.bot_data["card_service"]

    # Decode the callback to get locale ordinal.
    try:
        cb = decode(query.data)
        if cb.action != CallbackAction.LANG_SET:
            return
        ordinal = cb.arg
        if ordinal is None:
            return
        locales = available_locales()
        if ordinal < 0 or ordinal >= len(locales):
            return
        new_lang = locales[ordinal]
    except (ValueError, IndexError):
        logger.warning(f"Invalid callback_data: {query.data}")
        return

    # Persist the language (Requirement 2.5).
    await config_store.set_language(user_id, new_lang)

    # Re-register commands in the new language (Requirement 2.5).
    await register_for_chat(context.bot, chat_id, new_lang)

    # Show confirmation and back button in the new language (Requirement 1.10, 1.11).
    text = get_text("card_options_lang_selected", new_lang, lang_name=new_lang.upper())
    markup = options_back_keyboard(new_lang)
    message_id = await card_service.update(
        chat_id, query.message.message_id, text, markup
    )
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id


async def _show_status(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show LubeLogger and queue status (Requirement 1.9, 1.11)."""
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    card_service: CardService = context.bot_data["card_service"]

    reachable = await client.health_check()
    pending_counts = await queue_service.get_pending_count()
    total_pending = sum(pending_counts.values())

    if reachable:
        status_msg = get_text("status_ok", lang)
    else:
        status_msg = get_text("status_offline", lang)

    if total_pending > 0:
        queue_msg = get_text("queue_status", lang, pending_count=total_pending)
    else:
        queue_msg = get_text("queue_empty", lang)

    text = f"{status_msg}\n{queue_msg}"
    markup = options_back_keyboard(lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id


async def _show_queue(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    message_id: int,
    lang: str,
) -> None:
    """Show queue details (Requirement 1.9, 1.11)."""
    queue_service: QueueService = context.bot_data["queue_service"]
    card_service: CardService = context.bot_data["card_service"]

    pending_counts = await queue_service.get_pending_count()
    total_pending = sum(pending_counts.values())

    if total_pending == 0:
        text = get_text("queue_empty", lang)
    else:
        lines = [get_text("queue_status", lang, pending_count=total_pending)]
        for record_type, count in sorted(pending_counts.items()):
            lines.append(f"  • {record_type}: {count}")
        text = "\n".join(lines)

    markup = options_back_keyboard(lang)
    message_id = await card_service.update(chat_id, message_id, text, markup)
    context.user_data.get("options_menu_message_id", {})[chat_id] = message_id
