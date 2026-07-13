"""Fuel record handler — inline args or multi-step conversation flow with full UX."""

from __future__ import annotations

import re

from pydantic import ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from bot.models.validators import GasRecordModel
from bot.services.command_parser import CommandParser
from bot.services.config_store import ConfigStore
from bot.services.conversation import format_progress, format_summary, send_or_edit
from bot.services.keyboard import (
    cancel_keyboard,
    confirmation_inline_keyboard,
    main_menu_keyboard,
    summary_inline_keyboard,
)
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.metrics import compute_consumption
from bot.services.queue_service import QueueService

# Conversation states
VEHICLE_SELECT, ODOMETER, LITERS, COST, FULL_TANK, SUMMARY = range(6)


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

    if args_text.strip():
        # Inline args mode — resolve vehicle and submit immediately
        vehicle_id = vehicle_override or await config_store.get_active_vehicle(user_id)
        if vehicle_id is None:
            await update.message.reply_text(
                get_text("no_vehicle", lang), reply_markup=main_menu_keyboard(lang)
            )
            return ConversationHandler.END

        return await _handle_inline_args(update, context, args_text, vehicle_id, lang)

    # No args — start conversation flow with vehicle auto-select
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]

    # Determine vehicle(s)
    if vehicle_override:
        # Explicit override — use it directly
        context.user_data["fuel_vehicle_id"] = vehicle_override
        context.user_data["fuel_vehicle_name"] = f"Vehicle #{vehicle_override}"
        context.user_data["fuel_total_steps"] = 4
        return await _prompt_odometer(update, context, lang)

    # Fetch vehicles to determine auto-select vs selection
    try:
        vehicles = await client.get_vehicles()
    except (LubeLoggerUnreachableError, LubeLoggerApiError):
        # Fallback to active vehicle from config
        vehicle_id = await config_store.get_active_vehicle(user_id)
        if vehicle_id is None:
            await update.message.reply_text(
                get_text("no_vehicle", lang), reply_markup=main_menu_keyboard(lang)
            )
            return ConversationHandler.END
        context.user_data["fuel_vehicle_id"] = vehicle_id
        context.user_data["fuel_vehicle_name"] = f"Vehicle #{vehicle_id}"
        context.user_data["fuel_total_steps"] = 4
        return await _prompt_odometer(update, context, lang)

    if not vehicles:
        await update.message.reply_text(
            get_text("no_vehicles", lang), reply_markup=main_menu_keyboard(lang)
        )
        return ConversationHandler.END

    if len(vehicles) == 1:
        # Auto-select the single vehicle
        vehicle = vehicles[0]
        context.user_data["fuel_vehicle_id"] = vehicle.id
        context.user_data["fuel_vehicle_name"] = vehicle.display_name
        context.user_data["fuel_total_steps"] = 4

        # Inform user about auto-selection
        auto_msg = get_text("auto_vehicle_selected", lang, vehicle=vehicle.display_name)
        await update.message.reply_text(auto_msg, reply_markup=cancel_keyboard(lang))

        return await _prompt_odometer(update, context, lang)

    # Multiple vehicles — show selection keyboard
    context.user_data["fuel_total_steps"] = 5
    buttons = [
        [InlineKeyboardButton(v.display_name, callback_data=f"fuel_vehicle:{v.id}")]
        for v in vehicles
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    msg = await update.message.reply_text(
        get_text("vehicle_prompt", lang),
        reply_markup=keyboard,
    )
    context.user_data["last_bot_message_id"] = msg.message_id
    # Show cancel keyboard
    await update.message.reply_text("✓", reply_markup=cancel_keyboard(lang))
    return VEHICLE_SELECT


async def _handle_inline_args(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    args_text: str,
    vehicle_id: int,
    lang: str,
) -> int:
    """Handle inline arguments mode — parse, validate, submit.

    Args:
        update: The Telegram update.
        context: The callback context.
        args_text: The argument string to parse.
        vehicle_id: The resolved vehicle ID.
        lang: The user's language code.

    Returns:
        ConversationHandler.END always.
    """
    try:
        fuel_input = CommandParser.parse_fuel(args_text)
    except ParseError:
        await update.message.reply_text(
            get_text("usage_fuel", lang), reply_markup=main_menu_keyboard(lang)
        )
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
            await update.message.reply_text(
                _map_validation_error(exc, lang), reply_markup=main_menu_keyboard(lang)
            )
        else:
            await update.message.reply_text(
                get_text("usage_fuel", lang), reply_markup=main_menu_keyboard(lang)
            )
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
            ),
            reply_markup=main_menu_keyboard(lang),
        )
    except LubeLoggerUnreachableError:
        queue_service: QueueService = context.bot_data["queue_service"]
        await queue_service.enqueue(
            update.effective_user.id, vehicle_id, "gas", payload.model_dump_json(by_alias=True)
        )
        await update.message.reply_text(
            get_text("fuel_queued", lang), reply_markup=main_menu_keyboard(lang)
        )

    return ConversationHandler.END


async def _prompt_odometer(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> int:
    """Prompt user for odometer reading with progress indicator and last-reading hint.

    Args:
        update: The Telegram update.
        context: The callback context.
        lang: The user's language code.

    Returns:
        ODOMETER conversation state.
    """
    total_steps = context.user_data["fuel_total_steps"]
    # Odometer is always step 1 relative to data entry
    step = 1

    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('fuel_ask_odometer', lang)}"

    # Try to fetch last odometer reading as hint
    vehicle_id = context.user_data["fuel_vehicle_id"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        last_odo = await client.get_latest_odometer(vehicle_id)
        if last_odo and last_odo.get("odometer"):
            hint = get_text("last_odometer_hint", lang, odometer=last_odo["odometer"])
            prompt += f"\n{hint}"
    except (LubeLoggerUnreachableError, LubeLoggerApiError):
        pass  # Skip hint if API unreachable

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return ODOMETER


async def vehicle_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vehicle selection from inline keyboard.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ODOMETER conversation state.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Extract vehicle ID from callback data
    vehicle_id = int(query.data.split(":")[1])
    context.user_data["fuel_vehicle_id"] = vehicle_id

    # Try to get vehicle name
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        vehicles = await client.get_vehicles()
        vehicle = next((v for v in vehicles if v.id == vehicle_id), None)
        context.user_data["fuel_vehicle_name"] = (
            vehicle.display_name if vehicle else f"Vehicle #{vehicle_id}"
        )
    except (LubeLoggerUnreachableError, LubeLoggerApiError):
        context.user_data["fuel_vehicle_name"] = f"Vehicle #{vehicle_id}"

    return await _prompt_odometer(update, context, lang)


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
        await send_or_edit(update, context, get_text("invalid_odometer", lang))
        return ODOMETER

    context.user_data["fuel_odometer"] = value

    total_steps = context.user_data["fuel_total_steps"]
    step = 2
    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('fuel_ask_liters', lang)}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
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
        await send_or_edit(update, context, get_text("invalid_liters", lang))
        return LITERS

    context.user_data["fuel_liters"] = value

    total_steps = context.user_data["fuel_total_steps"]
    step = 3
    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('fuel_ask_cost', lang)}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
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
        await send_or_edit(update, context, get_text("invalid_cost", lang))
        return COST

    context.user_data["fuel_cost"] = value

    total_steps = context.user_data["fuel_total_steps"]
    step = 4
    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('fuel_ask_full_tank', lang)}"

    buttons = [
        [
            InlineKeyboardButton(get_text("btn_yes", lang), callback_data="fuel_full_tank:yes"),
            InlineKeyboardButton(get_text("btn_no", lang), callback_data="fuel_full_tank:no"),
        ]
    ]
    await send_or_edit(update, context, prompt, reply_markup=InlineKeyboardMarkup(buttons))
    return FULL_TANK


async def fuel_full_tank_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive full-tank flag (text fallback) and show summary."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    response = update.message.text.strip().lower()
    is_fill_to_full = response not in ("no", "n", "0", "false")
    context.user_data["fuel_full_tank"] = is_fill_to_full

    # Show summary
    return await _show_summary(update, context, lang)


async def fuel_full_tank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle full tank yes/no button press."""
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    choice = query.data.split(":")[1]  # "yes" or "no"
    context.user_data["fuel_full_tank"] = choice == "yes"

    return await _show_summary(update, context, lang)


async def _show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> int:
    """Display the summary message with save/edit/cancel buttons.

    Args:
        update: The Telegram update.
        context: The callback context.
        lang: The user's language code.

    Returns:
        SUMMARY conversation state.
    """
    vehicle_name = context.user_data.get("fuel_vehicle_name", "Unknown")
    odometer = context.user_data["fuel_odometer"]
    liters = context.user_data["fuel_liters"]
    cost = context.user_data["fuel_cost"]
    full_tank = context.user_data["fuel_full_tank"]

    fields = {
        "🚗 Vehicle": vehicle_name,
        "📍 Odometer": f"{odometer} km",
        "⛽ Fuel": f"{liters} L",
        "💰 Cost": f"€{cost}",
        "🔋 Full tank": "Yes" if full_tank else "No",
    }

    summary_text = format_summary(fields, lang)
    await send_or_edit(update, context, summary_text, reply_markup=summary_inline_keyboard(lang))
    return SUMMARY


async def summary_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '✅ Save' callback — submit record to LubeLogger.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Build validated record
    record = GasRecordModel(
        odometer=context.user_data["fuel_odometer"],
        liters=context.user_data["fuel_liters"],
        cost=context.user_data["fuel_cost"],
        is_fill_to_full=context.user_data["fuel_full_tank"],
        missed_fuel_up=False,
    )

    payload = GasRecordPayload.from_validated(record)
    vehicle_id: int = context.user_data["fuel_vehicle_id"]
    vehicle_name: str = context.user_data.get("fuel_vehicle_name", "Unknown")

    # Submit to LubeLogger
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        await client.add_gas_record(vehicle_id, payload)

        # Build rich confirmation
        confirmation = get_text(
            "confirm_fuel",
            lang,
            vehicle=vehicle_name,
            odometer=str(record.odometer),
            liters=str(record.liters),
            cost=str(record.cost),
            full_tank="Yes" if record.is_fill_to_full else "No",
            date=record.date,
        )

        # Try to compute consumption
        try:
            last_gas = await client.get_latest_gas_record(vehicle_id)
            if last_gas and last_gas.get("odometer"):
                prev_odo = int(float(last_gas["odometer"]))
                consumption = compute_consumption(record.liters, record.odometer, prev_odo)
                if consumption is not None:
                    consumption_text = get_text(
                        "confirm_fuel_consumption",
                        lang,
                        consumption=f"{consumption:.1f}",
                    )
                    confirmation += f"\n{consumption_text}"
        except (LubeLoggerUnreachableError, LubeLoggerApiError, ValueError, TypeError):
            pass  # Skip consumption if we can't fetch previous record

        await send_or_edit(
            update, context, confirmation, reply_markup=confirmation_inline_keyboard("fuel", lang)
        )

    except LubeLoggerUnreachableError:
        queue_service: QueueService = context.bot_data["queue_service"]
        await queue_service.enqueue(
            user_id, vehicle_id, "gas", payload.model_dump_json(by_alias=True)
        )
        await send_or_edit(update, context, get_text("fuel_queued", lang))

    # Restore main keyboard
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text="✓", reply_markup=main_menu_keyboard(lang))

    # Clean up user_data
    _cleanup_user_data(context)
    return ConversationHandler.END


async def summary_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '✏️ Edit' callback — restart flow at step 1 with preserved values.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ODOMETER conversation state.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Values are preserved in user_data, restart from odometer prompt
    return await _prompt_odometer(update, context, lang)


async def summary_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '❌ Cancel' callback — discard data, restore main keyboard.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    await send_or_edit(update, context, get_text("conversation_cancelled_notice", lang))

    # Restore main keyboard
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text="✓", reply_markup=main_menu_keyboard(lang))

    _cleanup_user_data(context)
    return ConversationHandler.END


async def log_another_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '🔁 Log another' callback — start new fuel flow with vehicle pre-selected.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ODOMETER conversation state.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    # Keep vehicle pre-selected, reset data fields
    vehicle_id = context.user_data.get("fuel_vehicle_id")
    vehicle_name = context.user_data.get("fuel_vehicle_name")

    # If no vehicle in user_data (already cleaned up), get from config
    if vehicle_id is None:
        vehicle_id = await config_store.get_active_vehicle(user_id)
        vehicle_name = f"Vehicle #{vehicle_id}" if vehicle_id else None

    if vehicle_id is None:
        await send_or_edit(
            update, context, get_text("no_vehicle", lang), reply_markup=main_menu_keyboard(lang)
        )
        return ConversationHandler.END

    # Reset for new flow
    context.user_data["fuel_vehicle_id"] = vehicle_id
    context.user_data["fuel_vehicle_name"] = vehicle_name or f"Vehicle #{vehicle_id}"
    context.user_data["fuel_total_steps"] = 4
    # Clear previous data
    for key in ("fuel_odometer", "fuel_liters", "fuel_cost", "fuel_full_tank"):
        context.user_data.pop(key, None)

    return await _prompt_odometer(update, context, lang)


async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '📊 History' callback — show last fuel record.

    Args:
        update: The Telegram update (callback query).
        context: The callback context.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data.get("fuel_vehicle_id")
    if vehicle_id is None:
        vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is None:
        await query.edit_message_text(get_text("no_vehicle", lang))
        return ConversationHandler.END

    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        last_gas = await client.get_latest_gas_record(vehicle_id)
        if last_gas:
            text = get_text(
                "last_fuel",
                lang,
                date=last_gas.get("date", ""),
                liters=last_gas.get("fuelConsumed", ""),
                cost=last_gas.get("cost", ""),
                odometer=last_gas.get("odometer", ""),
            )
        else:
            text = get_text("last_fuel_empty", lang)
    except (LubeLoggerUnreachableError, LubeLoggerApiError):
        text = get_text("lubelogger_unreachable", lang)

    await query.edit_message_text(text)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=get_text("history_prompt", lang),
        reply_markup=main_menu_keyboard(lang),
    )
    _cleanup_user_data(context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel or ❌ Cancel button during conversation — abort the fuel entry."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    _cleanup_user_data(context)

    await update.message.reply_text(
        get_text("conversation_cancelled_notice", lang), reply_markup=main_menu_keyboard(lang)
    )
    return ConversationHandler.END


def _cleanup_user_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove all fuel-related keys from user_data.

    Args:
        context: The callback context.
    """
    keys_to_remove = (
        "fuel_vehicle_id",
        "fuel_vehicle_name",
        "fuel_odometer",
        "fuel_liters",
        "fuel_cost",
        "fuel_full_tank",
        "fuel_total_steps",
        "last_bot_message_id",
    )
    for key in keys_to_remove:
        context.user_data.pop(key, None)


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
    msg_filter = filters.Regex(r"^⛽") & (entry_filters if entry_filters else filters.ALL)
    return ConversationHandler(
        entry_points=[
            CommandHandler("fuel", fuel_command, filters=entry_filters),
            MessageHandler(msg_filter, fuel_command),
        ],
        states={
            VEHICLE_SELECT: [
                CallbackQueryHandler(vehicle_selected_callback, pattern=r"^fuel_vehicle:\d+$")
            ],
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_odometer_step)],
            LITERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_liters_step)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_cost_step)],
            FULL_TANK: [
                CallbackQueryHandler(fuel_full_tank_callback, pattern=r"^fuel_full_tank:(yes|no)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fuel_full_tank_step),
            ],
            SUMMARY: [
                CallbackQueryHandler(summary_save_callback, pattern=r"^summary_save$"),
                CallbackQueryHandler(summary_edit_callback, pattern=r"^summary_edit$"),
                CallbackQueryHandler(summary_cancel_callback, pattern=r"^summary_cancel$"),
                CallbackQueryHandler(log_another_callback, pattern=r"^confirm_log_another:fuel$"),
                CallbackQueryHandler(history_callback, pattern=r"^confirm_history$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r"^❌"), cancel_command),
        ],
        allow_reentry=True,
    )
