"""Service record handler — inline args or conversation flow for maintenance records."""

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
from bot.models.payloads import ServiceRecordPayload
from bot.models.validators import ServiceRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

# Conversation states
ODOMETER, DESCRIPTION, COST = range(3)

_VEHICLE_OVERRIDE_RE = re.compile(r"--vehicle\s+([1-9]\d*)")


def _extract_vehicle_override(args: str) -> tuple[str, int | None]:
    """Extract --vehicle <id> and return remaining args plus vehicle ID."""
    match = _VEHICLE_OVERRIDE_RE.search(args)
    if match:
        vehicle_id = int(match.group(1))
        remaining = _VEHICLE_OVERRIDE_RE.sub("", args).strip()
        return remaining, vehicle_id
    return args, None


def _clear_service_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove temporary service conversation values."""
    for key in ("service_vehicle_id", "service_odometer", "service_description"):
        context.user_data.pop(key, None)


async def _get_vehicle_id(
    user_id: int, config_store: ConfigStore, override_id: int | None
) -> int | None:
    """Resolve the vehicle ID from override or active vehicle config."""
    if override_id is not None:
        return override_id
    return await config_store.get_active_vehicle(user_id)


async def _submit_service_record(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    record: ServiceRecordModel,
    vehicle_id: int,
    lang: str,
) -> None:
    """Submit a validated service record or queue it when offline."""
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id
    payload = ServiceRecordPayload.from_validated(record)

    try:
        await client.add_service_record(vehicle_id, payload)
        await update.message.reply_text(
            get_text(
                "service_saved",
                lang,
                description=record.description,
                cost=record.cost,
                odometer=record.odometer,
            )
        )
    except LubeLoggerUnreachableError:
        await queue_service.enqueue(
            user_id=user_id,
            vehicle_id=vehicle_id,
            record_type="service",
            payload=payload.model_dump_json(by_alias=True),
        )
        await update.message.reply_text(get_text("service_queued", lang))
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))


async def service_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /service with inline args or start the guided conversation."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    raw_args = update.message.text.partition(" ")[2].strip() if update.message.text else ""
    remaining_args, vehicle_override = _extract_vehicle_override(raw_args)
    vehicle_id = await _get_vehicle_id(user_id, config_store, vehicle_override)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return ConversationHandler.END

    if not remaining_args:
        context.user_data["service_vehicle_id"] = vehicle_id
        await update.message.reply_text(get_text("service_prompt_odometer", lang))
        return ODOMETER

    try:
        service_input = CommandParser.parse_service(remaining_args)
    except ParseError:
        await update.message.reply_text(get_text("usage_service", lang))
        return ConversationHandler.END

    try:
        record = ServiceRecordModel(
            odometer=service_input.odometer,
            description=service_input.description,
            cost=service_input.cost,
        )
    except ValidationError as exc:
        await update.message.reply_text(_validation_error_to_message(exc, lang))
        return ConversationHandler.END

    await _submit_service_record(update, context, record, vehicle_id, lang)
    return ConversationHandler.END


async def service_odometer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive a positive integer odometer reading."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        value = float(CommandParser.normalize_decimal(update.message.text.strip()))
        if not math.isfinite(value) or value <= 0 or not value.is_integer():
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_odometer", lang))
        return ODOMETER

    context.user_data["service_odometer"] = str(int(value))
    await update.message.reply_text(get_text("service_prompt_description", lang))
    return DESCRIPTION


async def service_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive service description."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text(get_text("invalid_description", lang))
        return DESCRIPTION

    context.user_data["service_description"] = text
    await update.message.reply_text(get_text("service_prompt_cost", lang))
    return COST


async def service_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive cost and finalize the service record."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        cost_value = float(CommandParser.normalize_decimal(update.message.text.strip()))
        if not math.isfinite(cost_value) or cost_value < 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_cost", lang))
        return COST

    try:
        record = ServiceRecordModel(
            odometer=context.user_data["service_odometer"],
            description=context.user_data["service_description"],
            cost=cost_value,
        )
    except ValidationError as exc:
        await update.message.reply_text(_validation_error_to_message(exc, lang))
        _clear_service_context(context)
        return ConversationHandler.END

    vehicle_id: int = context.user_data["service_vehicle_id"]
    try:
        await _submit_service_record(update, context, record, vehicle_id, lang)
    finally:
        _clear_service_context(context)
    return ConversationHandler.END


async def service_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during service conversation flow."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    _clear_service_context(context)
    await update.message.reply_text(get_text("conversation_cancelled", lang))
    return ConversationHandler.END


def _validation_error_to_message(exc: ValidationError, lang: str) -> str:
    """Convert a Pydantic validation error to a localized user message."""
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else "unknown"
        if field == "odometer":
            return get_text("invalid_odometer", lang)
        if field == "cost":
            return get_text("invalid_cost", lang)
        if field == "description":
            return get_text("invalid_description", lang)
    return get_text("unexpected_error", lang)


def get_service_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Create and return the ConversationHandler for /service."""
    return ConversationHandler(
        entry_points=[CommandHandler("service", service_command, filters=auth_filter)],
        states={
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, service_odometer)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, service_description)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, service_cost)],
        },
        fallbacks=[CommandHandler("cancel", service_cancel)],
        allow_reentry=True,
    )
