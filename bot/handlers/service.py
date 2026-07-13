"""Service record handler — inline args or conversation flow for maintenance records."""

from __future__ import annotations

import logging
import re
from datetime import date

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

from bot.exceptions import LubeLoggerUnreachableError, ParseError
from bot.i18n import get_text
from bot.models.payloads import ServiceRecordPayload
from bot.models.validators import ServiceRecordModel
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
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# Conversation states
VEHICLE_SELECT, ODOMETER, DESCRIPTION, COST, SUMMARY = range(5)


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
    vehicle_name: str,
    lang: str,
) -> None:
    """Validate, submit to LubeLogger (or queue), and respond with rich confirmation.

    Args:
        update: The Telegram update.
        context: The callback context.
        record: The validated service record model.
        vehicle_id: The target vehicle ID.
        vehicle_name: Display name of the vehicle.
        lang: The user's language preference.
    """
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id  # type: ignore[union-attr]

    payload = ServiceRecordPayload.from_validated(record)

    try:
        await client.add_service_record(vehicle_id, payload)
        # Rich confirmation message
        confirm_text = get_text(
            "confirm_service",
            lang,
            vehicle=vehicle_name,
            odometer=record.odometer,
            description=record.description,
            cost=record.cost,
            date=record.date,
        )
        await send_or_edit(
            update,
            context,
            confirm_text,
            reply_markup=confirmation_inline_keyboard("service", lang),
        )
    except LubeLoggerUnreachableError:
        await queue_service.enqueue(
            user_id=user_id,
            vehicle_id=vehicle_id,
            record_type="service",
            payload=payload.model_dump_json(by_alias=True),
        )
        await send_or_edit(update, context, get_text("service_queued", lang))


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


async def service_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Handle /service command — inline args or start conversation flow.

    With args: parse → validate → submit → confirm or queue.
    Without args: start conversation with vehicle auto-select or selection.

    Returns:
        ConversationHandler state if starting conversation, None otherwise.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    raw_args = (
        update.message.text.partition(" ")[2].strip()  # type: ignore[union-attr]
        if update.message and update.message.text and update.message.text.startswith("/")
        else ""
    )

    # Extract --vehicle override
    remaining_args, vehicle_override = _extract_vehicle_override(raw_args)

    # If inline args provided, handle in legacy mode
    if remaining_args:
        vehicle_id = await _get_vehicle_id(user_id, config_store, vehicle_override)
        if vehicle_id is None:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("no_vehicle", lang),
                reply_markup=main_menu_keyboard(lang),
            )
            return ConversationHandler.END

        try:
            service_input = CommandParser.parse_service(remaining_args)
        except ParseError:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("usage_service", lang),
                reply_markup=main_menu_keyboard(lang),
            )
            return ConversationHandler.END

        try:
            record = ServiceRecordModel(
                odometer=service_input.odometer,
                description=service_input.description,
                cost=service_input.cost,
            )
        except ValidationError as exc:
            error_msg = _validation_error_to_message(exc, lang)
            await update.message.reply_text(  # type: ignore[union-attr]
                error_msg, reply_markup=main_menu_keyboard(lang)
            )
            return ConversationHandler.END

        # Get vehicle name for confirmation
        vehicles = await client.get_vehicles()
        vehicle_name = next(
            (v.display_name for v in vehicles if v.id == vehicle_id),
            f"Vehicle #{vehicle_id}",
        )
        context.user_data["service_vehicle_id"] = vehicle_id  # type: ignore[index]
        context.user_data["service_vehicle_name"] = vehicle_name  # type: ignore[index]

        await _submit_service_record(update, context, record, vehicle_id, vehicle_name, lang)
        return ConversationHandler.END

    # No args — start conversation flow with vehicle selection
    try:
        vehicles = await client.get_vehicles()
    except LubeLoggerUnreachableError:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("lubelogger_unreachable", lang),
            reply_markup=main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    if not vehicles:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("no_vehicles", lang),
            reply_markup=main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    if len(vehicles) == 1:
        # Auto-select the single vehicle
        vehicle = vehicles[0]
        context.user_data["service_vehicle_id"] = vehicle.id  # type: ignore[index]
        context.user_data["service_vehicle_name"] = vehicle.display_name  # type: ignore[index]
        context.user_data["service_total_steps"] = 3  # type: ignore[index]

        # Show auto-select message and prompt for odometer
        auto_msg = get_text("auto_vehicle_selected", lang, vehicle=vehicle.display_name)

        # Try to get last odometer reading
        hint = ""
        try:
            last_record = await client.get_latest_odometer(vehicle.id)
            if last_record and "odometer" in last_record:
                hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
        except LubeLoggerUnreachableError:
            pass

        progress = format_progress(1, 3)
        prompt = f"{auto_msg}\n\n{progress}\n{get_text('service_prompt_odometer', lang)}{hint}"
        msg = await update.message.reply_text(  # type: ignore[union-attr]
            prompt, reply_markup=cancel_keyboard(lang)
        )
        context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]
        return ODOMETER

    # Multiple vehicles — show inline keyboard for selection
    context.user_data["service_total_steps"] = 4  # type: ignore[index]
    buttons = [
        [InlineKeyboardButton(v.display_name, callback_data=f"service_vehicle:{v.id}")]
        for v in vehicles
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    msg = await update.message.reply_text(  # type: ignore[union-attr]
        get_text("vehicle_prompt", lang),
        reply_markup=keyboard,
    )
    context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]
    return VEHICLE_SELECT


async def vehicle_selected_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vehicle selection from inline keyboard callback.

    Returns:
        Next conversation state (ODOMETER).
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Parse vehicle ID from callback_data
    vehicle_id = int(query.data.split(":")[1])  # type: ignore[union-attr]

    # Get vehicle name
    vehicles = await client.get_vehicles()
    vehicle_name = next(
        (v.display_name for v in vehicles if v.id == vehicle_id),
        f"Vehicle #{vehicle_id}",
    )

    context.user_data["service_vehicle_id"] = vehicle_id  # type: ignore[index]
    context.user_data["service_vehicle_name"] = vehicle_name  # type: ignore[index]
    context.user_data["service_total_steps"] = 4  # type: ignore[index]

    # Show odometer prompt with progress
    hint = ""
    try:
        last_record = await client.get_latest_odometer(vehicle_id)
        if last_record and "odometer" in last_record:
            hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
    except LubeLoggerUnreachableError:
        pass

    total_steps = context.user_data["service_total_steps"]  # type: ignore[index]
    progress = format_progress(1, total_steps)
    prompt = f"{progress}\n{get_text('service_prompt_odometer', lang)}{hint}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return ODOMETER


async def service_odometer_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive odometer reading.

    Returns:
        Next conversation state (DESCRIPTION).
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    text = update.message.text.strip()  # type: ignore[union-attr]
    odometer = CommandParser.normalize_decimal(text)

    # Validate odometer is a positive integer
    try:
        value = int(float(odometer))
        if value <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_odometer", lang)
        )
        return ODOMETER

    context.user_data["service_odometer"] = value  # type: ignore[index]

    total_steps = context.user_data.get("service_total_steps", 3)  # type: ignore[index]
    step = 2 if total_steps == 3 else 2
    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('service_prompt_description', lang)}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return DESCRIPTION


async def service_description_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive service description.

    Returns:
        Next conversation state (COST).
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    text = update.message.text.strip()  # type: ignore[union-attr]

    if not text:
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_description", lang)
        )
        return DESCRIPTION

    context.user_data["service_description"] = text  # type: ignore[index]

    total_steps = context.user_data.get("service_total_steps", 3)  # type: ignore[index]
    step = 3 if total_steps == 3 else 3
    progress = format_progress(step, total_steps)
    prompt = f"{progress}\n{get_text('service_prompt_cost', lang)}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return COST


async def service_cost_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Conversation step: receive cost and show summary.

    Returns:
        Next conversation state (SUMMARY).
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    text = update.message.text.strip()  # type: ignore[union-attr]
    cost = CommandParser.normalize_decimal(text)

    # Validate cost is a non-negative number
    try:
        cost_value = float(cost)
        if cost_value < 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_cost", lang)
        )
        return COST

    context.user_data["service_cost"] = cost_value  # type: ignore[index]

    # Build summary
    vehicle_name = context.user_data.get("service_vehicle_name", "Unknown")  # type: ignore[index]
    odometer = context.user_data["service_odometer"]  # type: ignore[index]
    description = context.user_data["service_description"]  # type: ignore[index]
    date_str = date.today().isoformat()
    context.user_data["service_date"] = date_str  # type: ignore[index]

    fields = {
        "Vehicle": vehicle_name,
        "Odometer": f"{odometer} km",
        "Service": description,
        "Cost": f"€{cost_value}",
        "Date": date_str,
    }

    summary_text = format_summary(fields, lang)
    await send_or_edit(update, context, summary_text, reply_markup=summary_inline_keyboard(lang))
    return SUMMARY


async def summary_save_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '✅ Save' callback from summary inline keyboard.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    odometer = context.user_data["service_odometer"]  # type: ignore[index]
    description = context.user_data["service_description"]  # type: ignore[index]
    cost_value = context.user_data["service_cost"]  # type: ignore[index]
    vehicle_id = context.user_data["service_vehicle_id"]  # type: ignore[index]
    vehicle_name = context.user_data.get("service_vehicle_name", "Unknown")  # type: ignore[index]

    try:
        record = ServiceRecordModel(
            odometer=odometer,
            description=description,
            cost=cost_value,
        )
    except ValidationError as exc:
        error_msg = _validation_error_to_message(exc, lang)
        await send_or_edit(update, context, error_msg, reply_markup=main_menu_keyboard(lang))
        return ConversationHandler.END

    await _submit_service_record(update, context, record, vehicle_id, vehicle_name, lang)

    # Restore main keyboard
    chat_id = update.effective_chat.id  # type: ignore[union-attr]
    await context.bot.send_message(
        chat_id=chat_id,
        text="✓",
        reply_markup=main_menu_keyboard(lang),
    )

    # Clean up user_data
    _cleanup_user_data(context)
    return ConversationHandler.END


async def summary_edit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '✏️ Edit' callback — restart flow from odometer step.

    Returns:
        ODOMETER state.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data["service_vehicle_id"]  # type: ignore[index]
    total_steps = context.user_data.get("service_total_steps", 3)  # type: ignore[index]

    # Show odometer prompt with progress
    hint = ""
    try:
        last_record = await client.get_latest_odometer(vehicle_id)
        if last_record and "odometer" in last_record:
            hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
    except LubeLoggerUnreachableError:
        pass

    progress = format_progress(1, total_steps)
    prompt = f"{progress}\n{get_text('service_prompt_odometer', lang)}{hint}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return ODOMETER


async def summary_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '❌ Cancel' callback from summary — discard and restore keyboard.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    await send_or_edit(update, context, get_text("conversation_cancelled_notice", lang))

    # Restore main keyboard
    chat_id = update.effective_chat.id  # type: ignore[union-attr]
    await context.bot.send_message(
        chat_id=chat_id,
        text="✓",
        reply_markup=main_menu_keyboard(lang),
    )

    _cleanup_user_data(context)
    return ConversationHandler.END


async def log_another_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '🔁 Log another' callback — start new service flow with vehicle pre-selected.

    Returns:
        ODOMETER state.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Vehicle is already stored in user_data from previous flow
    vehicle_id = context.user_data.get("service_vehicle_id")  # type: ignore[index]
    vehicle_name = context.user_data.get("service_vehicle_name", "Unknown")  # type: ignore[index]

    if vehicle_id is None:
        # Fallback — shouldn't happen but handle gracefully
        await send_or_edit(
            update, context, get_text("no_vehicle", lang), reply_markup=main_menu_keyboard(lang)
        )
        return ConversationHandler.END

    context.user_data["service_total_steps"] = 3  # type: ignore[index]

    # Show odometer prompt with progress (vehicle pre-selected)
    hint = ""
    try:
        last_record = await client.get_latest_odometer(vehicle_id)
        if last_record and "odometer" in last_record:
            hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
    except LubeLoggerUnreachableError:
        pass

    auto_msg = get_text("auto_vehicle_selected", lang, vehicle=vehicle_name)
    progress = format_progress(1, 3)
    prompt = f"{auto_msg}\n\n{progress}\n{get_text('service_prompt_odometer', lang)}{hint}"

    await send_or_edit(update, context, prompt, reply_markup=cancel_keyboard(lang))
    return ODOMETER


async def history_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle '📊 History' callback — show last service record.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data.get("service_vehicle_id")  # type: ignore[index]
    if vehicle_id is None:
        vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is None:
        await query.edit_message_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
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
    except LubeLoggerUnreachableError:
        text = get_text("lubelogger_unreachable", lang)

    await query.edit_message_text(text)  # type: ignore[union-attr]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text=get_text("history_prompt", lang),
        reply_markup=main_menu_keyboard(lang),
    )
    _cleanup_user_data(context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel or ❌ Cancel button during service conversation flow.

    Returns:
        ConversationHandler.END to end the conversation.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    await update.message.reply_text(  # type: ignore[union-attr]
        get_text("conversation_cancelled_notice", lang),
        reply_markup=main_menu_keyboard(lang),
    )
    _cleanup_user_data(context)
    return ConversationHandler.END


def _cleanup_user_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove service-related keys from user_data."""
    keys = (
        "service_vehicle_id",
        "service_vehicle_name",
        "service_odometer",
        "service_description",
        "service_cost",
        "service_date",
        "service_total_steps",
        "last_bot_message_id",
    )
    for key in keys:
        context.user_data.pop(key, None)  # type: ignore[union-attr]


def get_service_conversation_handler(
    auth_filter: filters.BaseFilter | None = None,
) -> ConversationHandler:
    """Create and return the ConversationHandler for the /service command.

    Args:
        auth_filter: Optional filter to restrict entry to authorized users.

    Returns:
        A ConversationHandler that manages the service record conversation flow.
    """
    msg_filter = filters.Regex(r"^🔧") & (auth_filter if auth_filter else filters.ALL)
    return ConversationHandler(
        entry_points=[
            CommandHandler("service", service_command, filters=auth_filter),
            MessageHandler(msg_filter, service_command),
        ],
        states={
            VEHICLE_SELECT: [
                CallbackQueryHandler(vehicle_selected_cb, pattern=r"^service_vehicle:\d+$")
            ],
            ODOMETER: [MessageHandler(filters.TEXT & ~filters.COMMAND, service_odometer_step)],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, service_description_step)
            ],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, service_cost_step)],
            SUMMARY: [
                CallbackQueryHandler(summary_save_cb, pattern=r"^summary_save$"),
                CallbackQueryHandler(summary_edit_cb, pattern=r"^summary_edit$"),
                CallbackQueryHandler(summary_cancel_cb, pattern=r"^summary_cancel$"),
                CallbackQueryHandler(log_another_cb, pattern=r"^confirm_log_another:service$"),
                CallbackQueryHandler(history_cb, pattern=r"^confirm_history$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r"^❌"), cancel_command),
        ],
        allow_reentry=True,
    )
