"""Handlers for data consultation commands: /last, /status, /queue."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.exceptions import LubeLoggerUnreachableError
from bot.formatters import render_latest_fuel, render_latest_odometer
from bot.i18n import get_text
from bot.models.records import GasRecord
from bot.services.config_store import ConfigStore
from bot.services.consumption import ConsumptionResult, FuelPoint
from bot.services.consumption import resolve as resolve_consumption
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.odometer_tracker import OdometerTracker
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)


def _gas_record_to_fuel_point(record: GasRecord) -> FuelPoint | None:
    """Convert a GasRecord to a FuelPoint for consumption resolution."""
    if record.odometer is None or record.fuel_consumed is None:
        return None
    return FuelPoint(
        odometer=record.odometer,
        liters=record.fuel_consumed,
        is_fill_to_full=record.is_fill_to_full,
        missed_fuel_up=record.missed_fuel_up,
    )


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /last <type> — show the latest record of the given type.

    Supported subcommands:
      /last fuel — display latest gas record (rendered through formatters, escaped)
      /last km   — display latest odometer record (rendered through formatters, escaped)
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    tracker: OdometerTracker = context.bot_data["odometer_tracker"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)
    vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
        return

    args = context.args
    if not args:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("usage_last", lang)
        )
        return

    subcommand = args[0].lower()
    try:
        if subcommand == "fuel":
            await _last_fuel(update, config_store, client, tracker, user_id, vehicle_id, lang)
        elif subcommand == "km":
            await _last_km(update, config_store, client, tracker, user_id, vehicle_id, lang)
        else:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("usage_last", lang)
            )
    except LubeLoggerUnreachableError:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("lubelogger_unreachable", lang)
        )


async def _last_fuel(
    update: Update,
    config_store: ConfigStore,
    client: LubeLoggerClient,
    tracker: OdometerTracker,
    user_id: int,
    vehicle_id: int,
    lang: str,
) -> None:
    """Fetch the latest gas record, fold into tracker, render through formatters."""
    records = await client.get_gas_records(vehicle_id)

    # Fold all gas records into odometer tracker (Req 5.4)
    if records:
        await tracker.observe_records(vehicle_id, gas=records)

    record = records[-1] if records else None
    vehicle_name = await config_store.get_active_vehicle_name(user_id) or ""

    # Resolve consumption from the last two records
    consumption: ConsumptionResult | None = None
    if record is not None:
        current_point = _gas_record_to_fuel_point(record)
        previous_rec = records[-2] if len(records) >= 2 else None
        previous_point = (
            _gas_record_to_fuel_point(previous_rec) if previous_rec is not None else None
        )
        if current_point is not None:
            consumption = resolve_consumption(
                reported=record.fuel_economy,
                current=current_point,
                previous=previous_point,
            )

    msg = render_latest_fuel(record, vehicle_name, consumption, lang)
    await update.message.reply_text(msg, parse_mode="HTML")  # type: ignore[union-attr]


async def _last_km(
    update: Update,
    config_store: ConfigStore,
    client: LubeLoggerClient,
    tracker: OdometerTracker,
    user_id: int,
    vehicle_id: int,
    lang: str,
) -> None:
    """Fetch the latest odometer record, fold into tracker, render through formatters."""
    records = await client.get_odometer_records(vehicle_id)

    # Fold all odometer records into tracker (Req 5.4)
    if records:
        await tracker.observe_records(vehicle_id, odometer=records)

    record = records[-1] if records else None
    vehicle_name = await config_store.get_active_vehicle_name(user_id) or ""

    msg = render_latest_odometer(record, vehicle_name, lang)
    await update.message.reply_text(msg, parse_mode="HTML")  # type: ignore[union-attr]


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
        f"{status_msg}\n{queue_msg}"
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
            get_text("queue_empty", lang)
        )
        return

    lines = [get_text("queue_status", lang, pending_count=total_pending)]
    for record_type, count in sorted(pending_counts.items()):
        lines.append(f"  • {record_type}: {count}")

    await update.message.reply_text("\n".join(lines))  # type: ignore[union-attr]
