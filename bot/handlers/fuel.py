"""Fuel record handler — inline args or multi-step conversation flow."""

from __future__ import annotations

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

from bot.exceptions import LubeLoggerUnreachableError, ParseError
from bot.i18n import get_text
from bot.models.payloads import GasRecordPayload
from bot.models.validators import GasRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

# Conversation states
ODOMETER, LITERS, COST, FULL_TANK = range(4)


def _parse_vehicle_override(args_text: str) -> tuple[int | None, str]:
    """Extract --vehicle <id> from arguments and return (vehicle_id, remaining_args).

    Args:
        args_text: The raw argument string from the command.

    Returns:
        A tuple of (vehicle_id or None, cleaned argument string without --vehicle flag).
    """
    pattern = re.compile(r"--vehicle\s+(\d+)")
    match = pattern.search(args_text)
    if match:
        vehicle_id = int(match.group(1))
        remaining = pattern.sub("", args_text).strip()
        return vehicle_id, remaining
    return None, args_text


def _map_validation_error(exc: ValidationError, lang: str) -> str:
    """Map a Pydantic ValidationError to a user-friendly i18n message.

    Args:
        exc: The Pydantic validation error.
        lang: The user's language code.

    Returns:
        A localized error message for the first failing field.
    """
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else ""
        if field == "odometer":
            return get_text("invalid_odometer", lang)
        if field == "liters":
            return get_text("invalid_liters", lang)
        if field == "cost":
            return get_text("invalid_cost", lang)
    # Fallback to the first error message
    return str(exc.errors()[0]["msg"])


async def fuel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /fuel — either inline args or start conversation.

    If arguments are provided, parse, validate, and submit immediately.
    Otherwise, start a multi-step conversation to collect fuel record fields.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Build full argument string
    args_text = " ".join(context.args) if context.args else ""

    # Check for --vehicle override
    vehicle_override, args_text = _parse_vehicle_override(args_text)

    # Resolve vehicle ID
    vehicle_id = vehicle_override or await config_store.get_active_vehicle(user_id)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return ConversationHandler.END

    # Store vehicle_id in user_data for use in conversation steps
    context.user_data["fuel_vehicle_id"] = vehicle_id

    if not args_text.strip():
        # No args — start conversation flow
        await update.message.reply_text(get_text("fuel_ask_odometer", lang))
        return ODOMETER

    # Inline args mode — parse, validate, submit
    try:
        fuel_input = CommandParser.parse_fuel(args_text)
    except ParseError:
        await update.message.reply_text(get_text("usage_fuel", lang))
        return ConversationHandler.END

    try:
        record = GasRecordModel(
            odometer=int(float(fuel_input.odometer)),
            liters=float(fuel_input.liters),
            cost=float(fuel_input.cost),
            is_fill_to_full=fuel_input.is_fill_to_full,
            missed_fuel_up=fuel_input.missed_fuel_up,
        )
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            await update.message.reply_text(_map_validation_error(exc, lang))
        else:
            await update.message.reply_text(get_text("usage_fuel", lang))
        return ConversationHandler.END

    payload = GasRecordPayload.from_validated(record)

    # Submit to LubeLogger
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

    return ConversationHandler.END


async def fuel_odometer_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive odometer reading."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    text = CommandParser.normalize_decimal(update.message.text.strip())
    try:
        value = int(float(text))
        if value <= 0:
            raise ValueError
    except (ValueError, TypeError):
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

    text = CommandParser.normalize_decimal(update.message.text.strip())
    try:
        value = float(text)
        if value <= 0:
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

    text = CommandParser.normalize_decimal(update.message.text.strip())
    try:
        value = float(text)
        if value < 0:
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
    is_fill_to_full = response not in ("no", "n", "0", "false")

    # Build validated record
    record = GasRecordModel(
        odometer=context.user_data["fuel_odometer"],
        liters=context.user_data["fuel_liters"],
        cost=context.user_data["fuel_cost"],
        is_fill_to_full=is_fill_to_full,
        missed_fuel_up=False,
    )

    payload = GasRecordPayload.from_validated(record)
    vehicle_id: int = context.user_data["fuel_vehicle_id"]

    # Submit to LubeLogger
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

    # Clean up user_data
    for key in ("fuel_vehicle_id", "fuel_odometer", "fuel_liters", "fuel_cost"):
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during conversation — abort the fuel entry."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Clean up user_data
    for key in ("fuel_vehicle_id", "fuel_odometer", "fuel_liters", "fuel_cost"):
        context.user_data.pop(key, None)

    await update.message.reply_text(get_text("conversation_cancelled", lang))
    return ConversationHandler.END


def get_fuel_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Build and return the ConversationHandler for the /fuel command.

    Args:
        auth_filter: Optional filter to restrict entry to authorized users.

    Returns:
        A ConversationHandler that handles both inline args and multi-step input.
    """
    entry_filters = auth_filter if auth_filter is not None else None
    return ConversationHandler(
        entry_points=[CommandHandler("fuel", fuel_command, filters=entry_filters)],
        states={
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_odometer_step)],
            LITERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_liters_step)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_cost_step)],
            FULL_TANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_full_tank_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )
