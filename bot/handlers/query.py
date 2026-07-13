"""Handlers for data consultation commands: /last, /status, /queue."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.exceptions import LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.keyboard import main_menu_keyboard
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /last <type> or keyboard button — show latest record.

    Without args: show inline keyboard to choose fuel or odometer.
    With args: show the record directly.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)
    vehicle_id = await config_store.get_active_vehicle(user_id)
    keyboard = main_menu_keyboard(lang)

    if vehicle_id is None:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("no_vehicle", lang), reply_markup=keyboard
        )
        return

    args = context.args
    if not args:
        # Show inline keyboard to choose record type
        buttons = [
            [
                InlineKeyboardButton(
                    get_text("btn_last_fuel", lang), callback_data="last_type:fuel"
                ),
                InlineKeyboardButton(get_text("btn_last_km", lang), callback_data="last_type:km"),
            ]
        ]
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("history_prompt", lang),
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    subcommand = args[0].lower()
    text = await _show_last_record(update, context, subcommand, vehicle_id, lang)
    await update.message.reply_text(text, reply_markup=keyboard)  # type: ignore[union-attr]


async def _show_last_record(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    record_type: str,
    vehicle_id: int,
    lang: str,
) -> str:
    """Fetch and format the last record of the given type.

    Args:
        update: The Telegram update.
        context: The callback context.
        record_type: "fuel" or "km".
        vehicle_id: The active vehicle ID.
        lang: User's language code.

    Returns:
        The formatted text of the record.
    """
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]

    try:
        if record_type == "fuel":
            record = await client.get_latest_gas_record(vehicle_id)
            if record:
                return get_text(
                    "last_fuel",
                    lang,
                    date=record.get("date", "N/A"),
                    liters=record.get("fuelConsumed", "N/A"),
                    cost=record.get("cost", "N/A"),
                    odometer=record.get("odometer", "N/A"),
                )
            return get_text("last_fuel_empty", lang)
        elif record_type == "km":
            record = await client.get_latest_odometer(vehicle_id)
            if record:
                return get_text(
                    "last_km",
                    lang,
                    date=record.get("date", "N/A"),
                    odometer=record.get("odometer", "N/A"),
                )
            return get_text("last_km_empty", lang)
        else:
            return get_text("usage_last", lang)
    except LubeLoggerUnreachableError:
        return get_text("lubelogger_unreachable", lang)


async def last_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard selection for record type (fuel/km)."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)
    vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is None:
        await query.edit_message_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
        return

    record_type = query.data.split(":")[1]  # type: ignore[union-attr]
    text = await _show_last_record(update, context, record_type, vehicle_id, lang)

    await query.edit_message_text(text)  # type: ignore[union-attr]


def get_query_callback_handler(auth_filter: object) -> CallbackQueryHandler:  # type: ignore[type-arg]
    """Return a CallbackQueryHandler for the last_type inline keyboard."""
    return CallbackQueryHandler(last_type_callback, pattern=r"^last_type:(fuel|km)$")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — check LubeLogger connectivity and queue status."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

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

    await update.message.reply_text(  # type: ignore[union-attr]
        f"{status_msg}\n{queue_msg}",
        reply_markup=main_menu_keyboard(lang),
    )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /queue — display pending record count and types."""
    config_store: ConfigStore = context.bot_data["config_store"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    pending_counts = await queue_service.get_pending_count()
    total_pending = sum(pending_counts.values())

    if total_pending == 0:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("queue_empty", lang),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    lines = [get_text("queue_status", lang, pending_count=total_pending)]
    for record_type, count in sorted(pending_counts.items()):
        lines.append(f"  • {record_type}: {count}")

    await update.message.reply_text(  # type: ignore[union-attr]
        "\n".join(lines),
        reply_markup=main_menu_keyboard(lang),
    )
