"""Service record handler — inline args or conversation flow for maintenance records."""

from __future__ import annotations

import logging
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
from bot.models.payloads import ServiceRecordPayload
from bot.models.validators import ServiceRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# Conversation states
ODOMETER, DESCRIPTION, COST = range(3)


def _extract_vehicle_override(args: str) -> tuple[str, int | None]:
    """Extract --vehicle <id> option from args and return remaining args + vehicle_id.

    Args:
        args: Raw command arguments string.

    Returns:
        Tuple of (remaining_args, vehicle_id_or_None).
    """
    pattern = re.compile(r"--vehicle\s+(\d+)")
    match = pattern.search(args)
    if match:
        vehicle_id = int(match.group(1))
        remaining = pattern.sub("", args).strip()
        return remaining, vehicle_id
    return args, None


async def _get_vehicle_id(
    user_id: int, config_store: ConfigStore, override_id: int | None
) -> int | None:
    """Resolve the vehicle ID from override or active vehicle config.

    Args:
        user_id: Telegram user ID.
        config_store: The config store instance.
        override_id: Optional vehicle ID override from --vehicle flag.

    Returns:
        The resolved vehicle ID, or None if no vehicle is set.
    """
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
    """Validate, submit to LubeLogger (or queue), and respond to user.

    Args:
        update: The Telegram update.
        context: The callback context.
        record: The validated service record model.
        vehicle_id: The target vehicle ID.
        lang: The user's language preference.
    """
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


async def service_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Handle /service command — inline args or start conversation flow.

    With args: parse → validate → submit → confirm or queue.
    Without args: start conversation (odometer → description → cost).

    Returns:
        ConversationHandler state if starting conversation, None otherwise.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    raw_args = update.message.text.partition(" ")[2].strip() if update.message.text else ""

    # Extract --vehicle override
    remaining_args, vehicle_override = _extract_vehicle_override(raw_args)

    # Resolve vehicle ID
    vehicle_id = await _get_vehicle_id(user_id, config_store, vehicle_override)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))
        return ConversationHandler.END

    # Store vehicle_id in user_data for conversation use
    context.user_data["service_vehicle_id"] = vehicle_id

    # If no args, start conversation
    if not remaining_args:
        await update.message.reply_text(get_text("service_prompt_odometer", lang))
        return ODOMETER

    # Inline args mode: parse → validate → submit
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
        error_msg = _validation_error_to_message(exc, lang)
        await update.message.reply_text(error_msg)
        return ConversationHandler.END

    await _submit_service_record(update, context, record, vehicle_id, lang)
    return ConversationHandler.END


async def service_odometer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive odometer reading.

    Returns:
        Next conversation state (DESCRIPTION).
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    text = update.message.text.strip()
    odometer = CommandParser.normalize_decimal(text)

    # Validate odometer is a positive integer
    try:
        value = int(float(odometer))
        if value <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_odometer", lang))
        return ODOMETER

    context.user_data["service_odometer"] = str(value)
    await update.message.reply_text(get_text("service_prompt_description", lang))
    return DESCRIPTION


async def service_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive service description.

    Returns:
        Next conversation state (COST).
    """
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
    """Conversation step: receive cost and finalize record.

    Returns:
        ConversationHandler.END to end the conversation.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    text = update.message.text.strip()
    cost = CommandParser.normalize_decimal(text)

    # Validate cost is a non-negative number
    try:
        cost_value = float(cost)
        if cost_value < 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("invalid_cost", lang))
        return COST

    # Build and validate the record
    odometer = context.user_data["service_odometer"]
    description = context.user_data["service_description"]
    vehicle_id = context.user_data["service_vehicle_id"]

    try:
        record = ServiceRecordModel(
            odometer=odometer,
            description=description,
            cost=cost,
        )
    except ValidationError as exc:
        error_msg = _validation_error_to_message(exc, lang)
        await update.message.reply_text(error_msg)
        return ConversationHandler.END

    await _submit_service_record(update, context, record, vehicle_id, lang)
    return ConversationHandler.END


async def service_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during service conversation flow.

    Returns:
        ConversationHandler.END to end the conversation.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    await update.message.reply_text(get_text("conversation_cancelled", lang))
    return ConversationHandler.END


def _validation_error_to_message(exc: ValidationError, lang: str) -> str:
    """Convert a Pydantic ValidationError to a user-friendly localized message.

    Args:
        exc: The Pydantic validation error.
        lang: The user's language preference.

    Returns:
        A localized error message for the first failed field.
    """
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else "unknown"
        if field == "odometer":
            return get_text("invalid_odometer", lang)
        if field == "cost":
            return get_text("invalid_cost", lang)
        if field == "description":
            return get_text("invalid_description", lang)
    return get_text("invalid_odometer", lang)


def get_service_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Create and return the ConversationHandler for the /service command.

    Args:
        auth_filter: Optional filter to restrict entry to authorized users.

    Returns:
        A ConversationHandler that manages the service record conversation flow.
    """
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
