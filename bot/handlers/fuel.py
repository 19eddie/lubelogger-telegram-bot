"""Fuel record handler — inline args or multi-step conversation flow."""

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
from bot.models.payloads import GasRecordPayload
from bot.models.validators import GasRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

# Conversation states
ODOMETER, LITERS, COST, FULL_TANK = range(4)


_VEHICLE_OVERRIDE_RE = re.compile(r"--vehicle\s+([1-9]\d*)")


def _parse_vehicle_override(args_text: str) -> tuple[int | None, str]:
    """Extract --vehicle <id> from arguments and return (vehicle_id, remaining_args)."""
    match = _VEHICLE_OVERRIDE_RE.search(args_text)
    if match:
        vehicle_id = int(match.group(1))
        remaining = _VEHICLE_OVERRIDE_RE.sub("", args_text).strip()
        return vehicle_id, remaining
    return None, args_text


def _parse_positive_integer(value: str) -> int | None:
    """Parse a finite positive integer supplied by a user."""
    try:
        number = float(CommandParser.normalize_decimal(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _clear_fuel_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove temporary fuel conversation values."""
    for key in ("fuel_vehicle_id", "fuel_odometer", "fuel_liters", "fuel_cost"):
        context.user_data.pop(key, None)


def _map_validation_error(exc: ValidationError, lang: str) -> str:
    """Map a Pydantic validation error to a user-friendly i18n message."""
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else ""
        if field == "odometer":
            return get_text("invalid_odometer", lang)
        if field == "liters":
            return get_text("invalid_liters", lang)
        if field == "cost":
            return get_text("invalid_cost", lang)
    return get_text("unexpected_error", lang)


async def fuel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /fuel with inline args or start the guided conversation."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    args_text = " ".join(context.args) if context.args else ""
    vehicle_override, args_text = _parse_vehicle_override(args_text)
    vehicle_id = (
        vehicle_override
        if vehicle_override is not None
        else await config_store.get_active_vehicle(user_id)
    )
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return ConversationHandler.END

    if not args_text.strip():
        context.user_data["fuel_vehicle_id"] = vehicle_id
        await update.message.reply_text(get_text("fuel_ask_odometer", lang))
        return ODOMETER

    try:
        fuel_input = CommandParser.parse_fuel(args_text)
    except ParseError:
        await update.message.reply_text(get_text("usage_fuel", lang))
        return ConversationHandler.END

    try:
        record = GasRecordModel(
            odometer=fuel_input.odometer,
            liters=fuel_input.liters,
            cost=fuel_input.cost,
            is_fill_to_full=fuel_input.is_fill_to_full,
            missed_fuel_up=fuel_input.missed_fuel_up,
        )
    except (ValidationError, ValueError):
        await update.message.reply_text(get_text("usage_fuel", lang))
        return ConversationHandler.END

    payload = GasRecordPayload.from_validated(record)
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        await client.add_gas_record(vehicle_id, payload)
        await update.message.reply_text(
            get_text(
                "fuel_saved",
                lang,
                liters=str(record.liters),
                cost=str(record.cost),
                odometer=str(record.odometer),
            )
        )
    except LubeLoggerUnreachableError:
        queue_service: QueueService = context.bot_data["queue_service"]
        await queue_service.enqueue(
            user_id, vehicle_id, "gas", payload.model_dump_json(by_alias=True)
        )
        await update.message.reply_text(get_text("fuel_queued", lang))
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))

    return ConversationHandler.END


async def fuel_odometer_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive odometer reading."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    value = _parse_positive_integer(update.message.text.strip())
    if value is None:
        await update.message.reply_text(get_text("invalid_odometer", lang))
        return ODOMETER

    context.user_data["fuel_odometer"] = value
    await update.message.reply_text(get_text("fuel_ask_liters", lang))
    return LITERS


async def fuel_liters_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive liters."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        value = float(CommandParser.normalize_decimal(update.message.text.strip()))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_liters", lang))
        return LITERS

    context.user_data["fuel_liters"] = value
    await update.message.reply_text(get_text("fuel_ask_cost", lang))
    return COST


async def fuel_cost_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive cost."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        value = float(CommandParser.normalize_decimal(update.message.text.strip()))
        if not math.isfinite(value) or value < 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_cost", lang))
        return COST

    context.user_data["fuel_cost"] = value
    await update.message.reply_text(get_text("fuel_ask_full_tank", lang))
    return FULL_TANK


async def fuel_full_tank_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive full-tank flag and submit record."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    response = update.message.text.strip().lower()
    if response in {"yes", "y", "1", "true", "si", "sì", "s"}:
        is_fill_to_full = True
    elif response in {"no", "n", "0", "false"}:
        is_fill_to_full = False
    else:
        await update.message.reply_text(get_text("fuel_ask_full_tank", lang))
        return FULL_TANK

    try:
        record = GasRecordModel(
            odometer=context.user_data["fuel_odometer"],
            liters=context.user_data["fuel_liters"],
            cost=context.user_data["fuel_cost"],
            is_fill_to_full=is_fill_to_full,
            missed_fuel_up=False,
        )
    except ValidationError as exc:
        await update.message.reply_text(_map_validation_error(exc, lang))
        _clear_fuel_context(context)
        return ConversationHandler.END

    payload = GasRecordPayload.from_validated(record)
    vehicle_id: int = context.user_data["fuel_vehicle_id"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        await client.add_gas_record(vehicle_id, payload)
        await update.message.reply_text(
            get_text(
                "fuel_saved",
                lang,
                liters=str(record.liters),
                cost=str(record.cost),
                odometer=str(record.odometer),
            )
        )
    except LubeLoggerUnreachableError:
        queue_service: QueueService = context.bot_data["queue_service"]
        await queue_service.enqueue(
            user_id, vehicle_id, "gas", payload.model_dump_json(by_alias=True)
        )
        await update.message.reply_text(get_text("fuel_queued", lang))
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))
    finally:
        _clear_fuel_context(context)

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during fuel conversation."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    _clear_fuel_context(context)
    await update.message.reply_text(get_text("conversation_cancelled", lang))
    return ConversationHandler.END


def get_fuel_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Build and return the ConversationHandler for /fuel."""
    return ConversationHandler(
        entry_points=[CommandHandler("fuel", fuel_command, filters=auth_filter)],
        states={
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_odometer_step)],
            LITERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_liters_step)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_cost_step)],
            FULL_TANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_full_tank_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )
