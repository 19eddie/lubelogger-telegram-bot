"""Odometer record handler — inline args or conversation flow for /km command."""

from __future__ import annotations

import math
import re

from pydantic import ValidationError
from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError, ParseError
from bot.i18n import get_text
from bot.models.payloads import OdometerRecordPayload
from bot.models.validators import OdometerRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

# Conversation states
ODOMETER = 0

_VEHICLE_OVERRIDE_RE = re.compile(r"--vehicle\s+([1-9]\d*)")


def _extract_vehicle_override(args: str) -> tuple[str, int | None]:
    """Extract --vehicle <id> and return remaining args plus vehicle ID."""
    match = _VEHICLE_OVERRIDE_RE.search(args)
    if match:
        vehicle_id = int(match.group(1))
        remaining = _VEHICLE_OVERRIDE_RE.sub("", args).strip()
        return remaining, vehicle_id
    return args, None


def _parse_positive_integer(value: str) -> int | None:
    """Parse a finite positive integer supplied by a user."""
    try:
        number = float(CommandParser.normalize_decimal(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


async def _get_vehicle_id(
    user_id: int, config_store: ConfigStore, override: int | None
) -> int | None:
    """Resolve the vehicle ID from override or active vehicle config."""
    if override is not None:
        return override
    return await config_store.get_active_vehicle(user_id)


async def _submit_odometer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    odometer_value: str,
    vehicle_override: int | None = None,
) -> None:
    """Validate and submit an odometer record, or queue it when offline."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    vehicle_id = await _get_vehicle_id(user_id, config_store, vehicle_override)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return

    try:
        record = OdometerRecordModel(odometer=odometer_value)
    except ValidationError:
        await update.message.reply_text(get_text("invalid_odometer", lang))
        return

    payload = OdometerRecordPayload.from_validated(record)
    try:
        await client.add_odometer_record(vehicle_id, payload)
        await update.message.reply_text(get_text("odometer_saved", lang, odometer=record.odometer))
    except LubeLoggerUnreachableError:
        await queue_service.enqueue(
            user_id=user_id,
            vehicle_id=vehicle_id,
            record_type="odometer",
            payload=payload.model_dump_json(by_alias=True),
        )
        await update.message.reply_text(get_text("odometer_queued", lang))
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))


async def km_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /km with inline args or start the guided conversation."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    message_text = update.message.text or ""
    parts = message_text.split(None, 1)
    raw_args = parts[1] if len(parts) > 1 else ""
    remaining_args, vehicle_override = _extract_vehicle_override(raw_args)

    if not remaining_args.strip():
        if vehicle_override is None:
            active_vehicle = await config_store.get_active_vehicle(user_id)
            if active_vehicle is None:
                await update.message.reply_text(get_text("no_vehicle", lang))
                return ConversationHandler.END
        context.user_data["km_vehicle_override"] = vehicle_override
        await update.message.reply_text(get_text("prompt_odometer", lang))
        return ODOMETER

    try:
        parsed = CommandParser.parse_odometer(remaining_args)
    except ParseError:
        await update.message.reply_text(get_text("usage_km", lang))
        return ConversationHandler.END

    await _submit_odometer(update, context, parsed.odometer, vehicle_override)
    return ConversationHandler.END


async def odometer_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle odometer value received in conversation mode."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    value = _parse_positive_integer(update.message.text.strip())

    if value is None:
        await update.message.reply_text(get_text("invalid_odometer", lang))
        return ODOMETER

    vehicle_override = context.user_data.get("km_vehicle_override")
    try:
        await _submit_odometer(update, context, str(value), vehicle_override)
    finally:
        context.user_data.pop("km_vehicle_override", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel and abort the odometer conversation."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    context.user_data.pop("km_vehicle_override", None)
    await update.message.reply_text(get_text("conversation_cancelled", lang))
    return ConversationHandler.END


def get_odometer_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Create and return the ConversationHandler for /km command."""
    return ConversationHandler(
        entry_points=[CommandHandler("km", km_command, filters=auth_filter)],
        states={
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, odometer_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
