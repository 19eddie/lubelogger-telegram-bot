"""Handlers for data consultation commands: /last, /status, /queue."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /last <type> and show the latest record of that type."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return

    args = context.args
    if not args:
        await update.message.reply_text(get_text("usage_last", lang))
        return

    subcommand = args[0].lower()
    try:
        if subcommand == "fuel":
            record = await client.get_latest_gas_record(vehicle_id)
            if record:
                await update.message.reply_text(
                    get_text(
                        "last_fuel",
                        lang,
                        date=record.get("date", "N/A"),
                        liters=record.get("fuelConsumed", "N/A"),
                        cost=record.get("cost", "N/A"),
                        odometer=record.get("odometer", "N/A"),
                    )
                )
            else:
                await update.message.reply_text(get_text("last_fuel_empty", lang))
        elif subcommand == "km":
            record = await client.get_latest_odometer(vehicle_id)
            if record:
                await update.message.reply_text(
                    get_text(
                        "last_km",
                        lang,
                        date=record.get("date", "N/A"),
                        odometer=record.get("odometer", "N/A"),
                    )
                )
            else:
                await update.message.reply_text(get_text("last_km_empty", lang))
        else:
            await update.message.reply_text(get_text("usage_last", lang))
    except LubeLoggerUnreachableError:
        await update.message.reply_text(get_text("lubelogger_unreachable", lang))
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — check LubeLogger connectivity and queue status."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    reachable = await client.health_check()
    pending_counts = await queue_service.get_pending_count()
    total_pending = sum(pending_counts.values())

    status_msg = get_text("status_ok", lang) if reachable else get_text("status_offline", lang)
    queue_msg = (
        get_text("queue_status", lang, pending_count=total_pending)
        if total_pending > 0
        else get_text("queue_empty", lang)
    )
    await update.message.reply_text(f"{status_msg}\n{queue_msg}")


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /queue — display pending record count and types."""
    config_store: ConfigStore = context.bot_data["config_store"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    pending_counts = await queue_service.get_pending_count()
    total_pending = sum(pending_counts.values())
    if total_pending == 0:
        await update.message.reply_text(get_text("queue_empty", lang))
        return

    lines = [get_text("queue_status", lang, pending_count=total_pending)]
    for record_type, count in sorted(pending_counts.items()):
        lines.append(f"  • {record_type}: {count}")
    await update.message.reply_text("\n".join(lines))
