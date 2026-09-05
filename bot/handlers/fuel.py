"""Fuel record handler — inline args or multi-step conversation flow."""

from __future__ import annotations

import math
import re
from datetime import date

from pydantic import ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError, ParseError
from bot.i18n import get_text
from bot.models.payloads import GasRecordPayload
from bot.models.validators import GasRecordModel, validate_fuel_date
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

# Conversation states
DATE, ODOMETER, LITERS, COST, FULL_TANK, MISSED_FUEL_UP = range(6)
FUEL_DATE_TODAY_CALLBACK = "fuel_date_today"
FUEL_FULL_TANK_YES_CALLBACK = "fuel_full_tank_yes"
FUEL_FULL_TANK_NO_CALLBACK = "fuel_full_tank_no"
FUEL_MISSED_YES_CALLBACK = "fuel_missed_yes"
FUEL_MISSED_NO_CALLBACK = "fuel_missed_no"


_VEHICLE_OVERRIDE_RE = re.compile(r"--vehicle\s+([1-9]\d*)")


def _fuel_date_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the inline keyboard for selecting today's fuel date."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text("fuel_today_button", lang),
                    callback_data=FUEL_DATE_TODAY_CALLBACK,
                )
            ]
        ]
    )


def _fuel_boolean_keyboard(
    lang: str,
    yes_callback: str,
    no_callback: str,
) -> InlineKeyboardMarkup:
    """Build a localized yes/no keyboard for a fuel metadata question."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text("fuel_yes_button", lang),
                    callback_data=yes_callback,
                ),
                InlineKeyboardButton(
                    get_text("fuel_no_button", lang),
                    callback_data=no_callback,
                ),
            ]
        ]
    )


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


def _parse_yes_no(value: str) -> bool | None:
    """Parse localized yes/no-style answers used by the guided fuel flow."""
    response = value.strip().lower()
    if response in {"yes", "y", "1", "true", "si", "sì", "s"}:
        return True
    if response in {"no", "n", "0", "false"}:
        return False
    return None


def _clear_fuel_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove temporary fuel conversation values."""
    for key in (
        "fuel_vehicle_id",
        "fuel_date",
        "fuel_odometer",
        "fuel_liters",
        "fuel_cost",
        "fuel_is_fill_to_full",
    ):
        context.user_data.pop(key, None)


def _map_validation_error(exc: ValidationError, lang: str) -> str:
    """Map a Pydantic validation error to a user-friendly i18n message."""
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else ""
        if field == "date":
            return get_text("invalid_date", lang)
        if field == "odometer":
            return get_text("invalid_odometer", lang)
        if field == "liters":
            return get_text("invalid_liters", lang)
        if field == "cost":
            return get_text("invalid_cost", lang)
    return get_text("unexpected_error", lang)


async def _submit_fuel_record(
    context: ContextTypes.DEFAULT_TYPE,
    record: GasRecordModel,
    vehicle_id: int,
    user_id: int,
    lang: str,
    reply_message: Message,
) -> None:
    """Submit a validated fuel record or enqueue it when LubeLogger is unreachable."""
    payload = GasRecordPayload.from_validated(record)
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        await client.add_gas_record(vehicle_id, payload)
        await reply_message.reply_text(
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
        await reply_message.reply_text(get_text("fuel_queued", lang))
    except LubeLoggerApiError:
        await reply_message.reply_text(get_text("lubelogger_error", lang))


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
        await update.message.reply_text(
            get_text("fuel_ask_date", lang),
            reply_markup=_fuel_date_keyboard(lang),
        )
        return DATE

    try:
        fuel_input = CommandParser.parse_fuel(args_text)
    except ParseError:
        await update.message.reply_text(get_text("usage_fuel", lang))
        return ConversationHandler.END

    try:
        record = GasRecordModel(
            date=fuel_input.date or date.today().isoformat(),
            odometer=fuel_input.odometer,
            liters=fuel_input.liters,
            cost=fuel_input.cost,
            is_fill_to_full=fuel_input.is_fill_to_full,
            missed_fuel_up=fuel_input.missed_fuel_up,
        )
    except ValidationError as exc:
        await update.message.reply_text(_map_validation_error(exc, lang))
        return ConversationHandler.END

    await _submit_fuel_record(
        context,
        record,
        vehicle_id,
        user_id,
        lang,
        reply_message=update.message,
    )
    return ConversationHandler.END


async def fuel_today_date_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: accept today's date from the inline button."""
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    context.user_data["fuel_date"] = date.today().isoformat()
    await query.edit_message_text(get_text("fuel_ask_odometer", lang))
    return ODOMETER


async def fuel_date_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive the fuel record date."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    raw_value = update.message.text.strip()
    value = date.today().isoformat() if raw_value.lower() in {"", "today", "oggi"} else raw_value

    try:
        validated_date = validate_fuel_date(value)
    except ValueError:
        await update.message.reply_text(get_text("invalid_date", lang))
        return DATE

    context.user_data["fuel_date"] = validated_date
    await update.message.reply_text(get_text("fuel_ask_odometer", lang))
    return ODOMETER


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
    await update.message.reply_text(
        get_text("fuel_ask_full_tank", lang),
        reply_markup=_fuel_boolean_keyboard(
            lang,
            FUEL_FULL_TANK_YES_CALLBACK,
            FUEL_FULL_TANK_NO_CALLBACK,
        ),
    )
    return FULL_TANK


async def fuel_full_tank_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive full-tank flag as text fallback."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    is_fill_to_full = _parse_yes_no(update.message.text)
    if is_fill_to_full is None:
        await update.message.reply_text(
            get_text("fuel_ask_full_tank", lang),
            reply_markup=_fuel_boolean_keyboard(
                lang,
                FUEL_FULL_TANK_YES_CALLBACK,
                FUEL_FULL_TANK_NO_CALLBACK,
            ),
        )
        return FULL_TANK

    context.user_data["fuel_is_fill_to_full"] = is_fill_to_full
    await update.message.reply_text(
        get_text("fuel_ask_missed", lang),
        reply_markup=_fuel_boolean_keyboard(
            lang,
            FUEL_MISSED_YES_CALLBACK,
            FUEL_MISSED_NO_CALLBACK,
        ),
    )
    return MISSED_FUEL_UP


async def fuel_full_tank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive full-tank flag from an inline button."""
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    context.user_data["fuel_is_fill_to_full"] = query.data == FUEL_FULL_TANK_YES_CALLBACK
    await query.edit_message_text(
        get_text("fuel_ask_missed", lang),
        reply_markup=_fuel_boolean_keyboard(
            lang,
            FUEL_MISSED_YES_CALLBACK,
            FUEL_MISSED_NO_CALLBACK,
        ),
    )
    return MISSED_FUEL_UP


async def _finish_fuel_record(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    lang: str,
    missed_fuel_up: bool,
    reply_message: Message,
) -> int:
    """Build and submit guided fuel record after final metadata is available."""
    try:
        record = GasRecordModel(
            date=context.user_data["fuel_date"],
            odometer=context.user_data["fuel_odometer"],
            liters=context.user_data["fuel_liters"],
            cost=context.user_data["fuel_cost"],
            is_fill_to_full=context.user_data["fuel_is_fill_to_full"],
            missed_fuel_up=missed_fuel_up,
        )
    except ValidationError as exc:
        await reply_message.reply_text(_map_validation_error(exc, lang))
        _clear_fuel_context(context)
        return ConversationHandler.END

    try:
        await _submit_fuel_record(
            context,
            record,
            context.user_data["fuel_vehicle_id"],
            user_id,
            lang,
            reply_message=reply_message,
        )
    finally:
        _clear_fuel_context(context)

    return ConversationHandler.END


async def fuel_missed_fuel_up_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive missed-fuel flag as text fallback."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    missed_fuel_up = _parse_yes_no(update.message.text)
    if missed_fuel_up is None:
        await update.message.reply_text(
            get_text("fuel_ask_missed", lang),
            reply_markup=_fuel_boolean_keyboard(
                lang,
                FUEL_MISSED_YES_CALLBACK,
                FUEL_MISSED_NO_CALLBACK,
            ),
        )
        return MISSED_FUEL_UP

    return await _finish_fuel_record(
        context,
        user_id,
        lang,
        missed_fuel_up,
        reply_message=update.message,
    )


async def fuel_missed_fuel_up_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Conversation step: receive missed-fuel flag from an inline button."""
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    message = query.message

    if message is None:
        _clear_fuel_context(context)
        return ConversationHandler.END

    await query.edit_message_text(get_text("fuel_submitting", lang))
    missed_fuel_up = query.data == FUEL_MISSED_YES_CALLBACK
    return await _finish_fuel_record(
        context,
        user_id,
        lang,
        missed_fuel_up,
        reply_message=message,
    )


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
            DATE: [
                CallbackQueryHandler(
                    fuel_today_date_step,
                    pattern=f"^{FUEL_DATE_TODAY_CALLBACK}$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_date_step),
            ],
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_odometer_step)],
            LITERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_liters_step)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_cost_step)],
            FULL_TANK: [
                CallbackQueryHandler(
                    fuel_full_tank_callback,
                    pattern=(f"^({FUEL_FULL_TANK_YES_CALLBACK}|{FUEL_FULL_TANK_NO_CALLBACK})$"),
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_full_tank_step),
            ],
            MISSED_FUEL_UP: [
                CallbackQueryHandler(
                    fuel_missed_fuel_up_callback,
                    pattern=f"^({FUEL_MISSED_YES_CALLBACK}|{FUEL_MISSED_NO_CALLBACK})$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_missed_fuel_up_step),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )
