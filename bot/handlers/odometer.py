"""Odometer record handler — inline args or conversation flow for /km command."""

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
from bot.models.payloads import OdometerRecordPayload
from bot.models.validators import OdometerRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# Conversation states
ODOMETER = 0

# Regex for --vehicle <id> override
_VEHICLE_OVERRIDE_RE = re.compile(r"--vehicle\s+(\d+)")


def _extract_vehicle_override(args: str) -> tuple[str, int | None]:
    """Extract --vehicle <id> from args string and return remaining args + vehicle_id.

    Args:
        args: The raw argument string from the command.

    Returns:
        Tuple of (remaining_args, vehicle_id_override or None).
    """
    match = _VEHICLE_OVERRIDE_RE.search(args)
    if match:
        vehicle_id = int(match.group(1))
        remaining = _VEHICLE_OVERRIDE_RE.sub("", args).strip()
        return remaining, vehicle_id
    return args, None


async def _get_vehicle_id(
    user_id: int, config_store: ConfigStore, override: int | None
) -> int | None:
    """Resolve the vehicle ID from override or active vehicle config.

    Args:
        user_id: Telegram user ID.
        config_store: The config store instance.
        override: Optional vehicle ID override from --vehicle flag.

    Returns:
        The resolved vehicle ID, or None if no vehicle is configured.
    """
    if override is not None:
        return override
    return await config_store.get_active_vehicle(user_id)


async def _submit_odometer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    odometer_value: str,
    vehicle_override: int | None = None,
) -> None:
    """Validate and submit an odometer record.

    Args:
        update: The Telegram update.
        context: The bot context with shared services.
        odometer_value: The raw odometer string value.
        vehicle_override: Optional vehicle ID from --vehicle flag.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = await _get_vehicle_id(user_id, config_store, vehicle_override)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
        return

    # Validate
    try:
        record = OdometerRecordModel(odometer=odometer_value)
    except ValidationError:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_odometer", lang)
        )
        return

    # Build payload
    payload = OdometerRecordPayload.from_validated(record)

    # Submit or queue
    try:
        await client.add_odometer_record(vehicle_id, payload)
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("odometer_saved", lang, odometer=record.odometer)
        )
    except LubeLoggerUnreachableError:
        await queue_service.enqueue(
            user_id=user_id,
            vehicle_id=vehicle_id,
            record_type="odometer",
            payload=payload.model_dump_json(by_alias=True),
        )
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("odometer_queued", lang)
        )


async def km_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Handle /km command — inline args or start conversation.

    If arguments are provided, parse and submit immediately.
    If no arguments, prompt user for odometer reading (conversation mode).

    Returns:
        ConversationHandler.END or ODOMETER state, or None for inline mode.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Get raw text after the command
    message_text = update.message.text  # type: ignore[union-attr]
    parts = message_text.split(None, 1)
    raw_args = parts[1] if len(parts) > 1 else ""

    if not raw_args.strip():
        # No args — start conversation
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("prompt_odometer", lang)
        )
        return ODOMETER

    # Inline mode: extract vehicle override and parse
    remaining_args, vehicle_override = _extract_vehicle_override(raw_args)

    try:
        parsed = CommandParser.parse_odometer(remaining_args)
    except ParseError as exc:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("usage_km", lang)
        )
        logger.debug("Parse error for /km: %s", exc.hint)
        return ConversationHandler.END

    await _submit_odometer(update, context, parsed.odometer, vehicle_override)
    return ConversationHandler.END


async def odometer_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle odometer value received in conversation mode.

    Args:
        update: The Telegram update containing user's odometer input.
        context: The bot context with shared services.

    Returns:
        ConversationHandler.END to finish the conversation.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)
    text = update.message.text.strip()  # type: ignore[union-attr]

    # Normalize decimal separator
    normalized = CommandParser.normalize_decimal(text)

    # Validate it's a number
    try:
        float(normalized)
    except ValueError:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_odometer", lang)
        )
        return ConversationHandler.END

    await _submit_odometer(update, context, normalized)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel — abort the conversation.

    Returns:
        ConversationHandler.END to finish the conversation.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    await update.message.reply_text(  # type: ignore[union-attr]
        get_text("conversation_cancelled", lang)
    )
    return ConversationHandler.END


def get_odometer_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Create and return the ConversationHandler for /km command.

    Args:
        auth_filter: Optional filter to restrict entry to authorized users.

    Returns:
        A ConversationHandler managing the odometer entry flow.
    """
    return ConversationHandler(
        entry_points=[CommandHandler("km", km_command, filters=auth_filter)],
        states={
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, odometer_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
