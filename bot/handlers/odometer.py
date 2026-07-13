"""Odometer record handler — inline args or conversation flow for /km command."""

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
from bot.models.payloads import OdometerRecordPayload
from bot.models.validators import OdometerRecordModel
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
VEHICLE_SELECT, ODOMETER, SUMMARY = range(3)

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


def _cleanup_user_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove odometer conversation keys from user_data."""
    keys = (
        "conv_vehicle_id",
        "conv_vehicle_name",
        "odo_odometer",
        "last_bot_message_id",
        "odo_total_steps",
    )
    for key in keys:
        context.user_data.pop(key, None)  # type: ignore[union-attr]


async def km_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /km command — inline args or start conversation.

    If arguments are provided, parse and submit immediately.
    If no arguments, start the guided conversation flow.

    Returns:
        ConversationHandler state or END.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Get raw text after the command
    message_text = update.message.text  # type: ignore[union-attr]
    parts = message_text.split(None, 1)
    raw_args = parts[1] if len(parts) > 1 else ""

    if raw_args.strip():
        # Inline mode: extract vehicle override and parse
        remaining_args, vehicle_override = _extract_vehicle_override(raw_args)

        vehicle_id = vehicle_override or await config_store.get_active_vehicle(user_id)
        if vehicle_id is None:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("no_vehicle", lang),
                reply_markup=main_menu_keyboard(lang),
            )
            return ConversationHandler.END

        try:
            parsed = CommandParser.parse_odometer(remaining_args)
        except ParseError as exc:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("usage_km", lang),
                reply_markup=main_menu_keyboard(lang),
            )
            logger.debug("Parse error for /km: %s", exc.hint)
            return ConversationHandler.END

        # Validate and submit inline
        try:
            record = OdometerRecordModel(odometer=parsed.odometer)
        except ValidationError:
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("invalid_odometer", lang),
                reply_markup=main_menu_keyboard(lang),
            )
            return ConversationHandler.END

        payload = OdometerRecordPayload.from_validated(record)
        queue_service: QueueService = context.bot_data["queue_service"]

        try:
            await client.add_odometer_record(vehicle_id, payload)
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("odometer_saved", lang, odometer=record.odometer),
                reply_markup=main_menu_keyboard(lang),
            )
        except LubeLoggerUnreachableError:
            await queue_service.enqueue(
                user_id=user_id,
                vehicle_id=vehicle_id,
                record_type="odometer",
                payload=payload.model_dump_json(by_alias=True),
            )
            await update.message.reply_text(  # type: ignore[union-attr]
                get_text("odometer_queued", lang),
                reply_markup=main_menu_keyboard(lang),
            )

        return ConversationHandler.END

    # No args — start conversation flow
    # Determine vehicle(s)
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
        context.user_data["conv_vehicle_id"] = vehicle.id  # type: ignore[index]
        context.user_data["conv_vehicle_name"] = vehicle.display_name  # type: ignore[index]
        context.user_data["odo_total_steps"] = 1  # type: ignore[index]

        # Show auto-select notice and prompt for odometer
        auto_msg = get_text("auto_vehicle_selected", lang, vehicle=vehicle.display_name)

        # Fetch last odometer for hint
        hint = ""
        try:
            last_record = await client.get_latest_odometer(vehicle.id)
            if last_record and last_record.get("odometer"):
                hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
        except LubeLoggerUnreachableError:
            pass

        progress = format_progress(1, 1)
        prompt_text = f"{auto_msg}\n\n{progress}\n{get_text('prompt_odometer', lang)}{hint}"

        msg = await update.message.reply_text(  # type: ignore[union-attr]
            prompt_text,
            reply_markup=cancel_keyboard(lang),
        )
        context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]
        return ODOMETER

    # Multiple vehicles — show selection keyboard
    context.user_data["odo_total_steps"] = 2  # type: ignore[index]
    keyboard = [
        [InlineKeyboardButton(v.display_name, callback_data=f"odo_vehicle:{v.id}")]
        for v in vehicles
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    progress = format_progress(1, 2)
    prompt_text = f"{progress}\n{get_text('vehicle_prompt', lang)}"

    msg = await update.message.reply_text(  # type: ignore[union-attr]
        prompt_text,
        reply_markup=reply_markup,
    )
    context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]
    return VEHICLE_SELECT


async def vehicle_selected_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vehicle selection from inline keyboard.

    Returns:
        ODOMETER state to proceed to odometer entry.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = int(query.data.split(":")[1])  # type: ignore[union-attr]

    # Get vehicle name
    try:
        vehicles = await client.get_vehicles()
        vehicle_name = next(
            (v.display_name for v in vehicles if v.id == vehicle_id),
            f"Vehicle #{vehicle_id}",
        )
    except LubeLoggerUnreachableError:
        vehicle_name = f"Vehicle #{vehicle_id}"

    context.user_data["conv_vehicle_id"] = vehicle_id  # type: ignore[index]
    context.user_data["conv_vehicle_name"] = vehicle_name  # type: ignore[index]

    # Fetch last odometer for hint
    hint = ""
    try:
        last_record = await client.get_latest_odometer(vehicle_id)
        if last_record and last_record.get("odometer"):
            hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
    except LubeLoggerUnreachableError:
        pass

    total_steps = context.user_data.get("odo_total_steps", 2)  # type: ignore[union-attr]
    progress = format_progress(2, total_steps)
    prompt_text = f"{progress}\n{get_text('prompt_odometer', lang)}{hint}"

    # Edit the inline message to show vehicle selected confirmation
    await query.edit_message_text(  # type: ignore[union-attr]
        get_text("auto_vehicle_selected", lang, vehicle=vehicle_name)
    )

    # Send the odometer prompt as a new message with cancel keyboard
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text=prompt_text,
        reply_markup=cancel_keyboard(lang),
    )
    context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]

    return ODOMETER


async def odometer_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle odometer value received in conversation mode.

    Returns:
        SUMMARY state to show summary, or ODOMETER to re-prompt on invalid input.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)
    text = update.message.text.strip()  # type: ignore[union-attr]

    # Normalize decimal separator
    normalized = CommandParser.normalize_decimal(text)

    # Validate it's a positive number
    try:
        value = int(float(normalized))
        if value <= 0:
            raise ValueError  # noqa: TRY301
    except (ValueError, TypeError):
        await update.message.reply_text(  # type: ignore[union-attr]
            get_text("invalid_odometer", lang),
        )
        return ODOMETER

    context.user_data["odo_odometer"] = value  # type: ignore[index]

    # Show summary
    vehicle_name = context.user_data.get("conv_vehicle_name", "—")  # type: ignore[union-attr]
    date_str = date.today().isoformat()

    fields = {
        "Vehicle": vehicle_name,
        "Odometer": f"{value} km",
        "Date": date_str,
    }

    summary_text = format_summary(fields, lang)
    msg = await send_or_edit(
        update, context, summary_text, reply_markup=summary_inline_keyboard(lang)
    )
    # Store message_id if send_or_edit returned a Message
    if msg:
        context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]

    return SUMMARY


async def summary_save_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Save' button from summary — submit the odometer record.

    Returns:
        ConversationHandler.END after successful submission.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    queue_service: QueueService = context.bot_data["queue_service"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data["conv_vehicle_id"]  # type: ignore[index]
    vehicle_name = context.user_data.get("conv_vehicle_name", "—")  # type: ignore[union-attr]
    odometer_value = context.user_data["odo_odometer"]  # type: ignore[index]
    date_str = date.today().isoformat()

    # Validate and build payload
    record = OdometerRecordModel(odometer=odometer_value)
    payload = OdometerRecordPayload.from_validated(record)

    # Submit or queue
    try:
        await client.add_odometer_record(vehicle_id, payload)
    except LubeLoggerUnreachableError:
        await queue_service.enqueue(
            user_id=user_id,
            vehicle_id=vehicle_id,
            record_type="odometer",
            payload=payload.model_dump_json(by_alias=True),
        )

    # Show rich confirmation
    confirm_text = get_text(
        "confirm_odometer",
        lang,
        vehicle=vehicle_name,
        odometer=str(odometer_value),
        date=date_str,
    )

    # Edit the summary message to show confirmation with inline buttons
    await query.edit_message_text(  # type: ignore[union-attr]
        confirm_text,
        reply_markup=confirmation_inline_keyboard("odometer", lang),
    )

    # Restore main keyboard
    await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text="✓",
        reply_markup=main_menu_keyboard(lang),
    )

    _cleanup_user_data(context)
    return ConversationHandler.END


async def summary_edit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Edit' button from summary — restart the odometer entry.

    Returns:
        ODOMETER state to re-collect the odometer value.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data.get("conv_vehicle_id")  # type: ignore[union-attr]

    # Fetch last odometer for hint
    hint = ""
    if vehicle_id:
        try:
            last_record = await client.get_latest_odometer(vehicle_id)
            if last_record and last_record.get("odometer"):
                hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
        except LubeLoggerUnreachableError:
            pass

    total_steps = context.user_data.get("odo_total_steps", 1)  # type: ignore[union-attr]
    step = total_steps  # Odometer is always the last step
    progress = format_progress(step, total_steps)
    prompt_text = f"{progress}\n{get_text('prompt_odometer', lang)}{hint}"

    await send_or_edit(update, context, prompt_text)
    return ODOMETER


async def summary_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Cancel' button from summary — discard and restore main keyboard.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    await query.edit_message_text(  # type: ignore[union-attr]
        get_text("conversation_cancelled_notice", lang),
    )

    # Restore main keyboard
    await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text="✓",
        reply_markup=main_menu_keyboard(lang),
    )

    _cleanup_user_data(context)
    return ConversationHandler.END


async def log_another_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Log another' button — restart odometer flow with same vehicle.

    Returns:
        ODOMETER state.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Keep vehicle from previous flow or re-fetch
    vehicle_id = context.user_data.get("conv_vehicle_id")  # type: ignore[union-attr]
    vehicle_name = context.user_data.get("conv_vehicle_name", "—")  # type: ignore[union-attr]

    if not vehicle_id:
        # Shouldn't happen, but handle gracefully
        await query.edit_message_text(  # type: ignore[union-attr]
            get_text("no_vehicle", lang),
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,  # type: ignore[union-attr]
            text="✓",
            reply_markup=main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    context.user_data["odo_total_steps"] = 1  # type: ignore[index]

    # Fetch last odometer for hint
    hint = ""
    try:
        last_record = await client.get_latest_odometer(vehicle_id)
        if last_record and last_record.get("odometer"):
            hint = "\n" + get_text("last_odometer_hint", lang, odometer=last_record["odometer"])
    except LubeLoggerUnreachableError:
        pass

    progress = format_progress(1, 1)
    prompt_text = (
        f"{get_text('auto_vehicle_selected', lang, vehicle=vehicle_name)}\n\n"
        f"{progress}\n{get_text('prompt_odometer', lang)}{hint}"
    )

    await query.edit_message_text(prompt_text)  # type: ignore[union-attr]

    # Send cancel keyboard
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text=get_text("prompt_odometer", lang),
        reply_markup=cancel_keyboard(lang),
    )
    context.user_data["last_bot_message_id"] = msg.message_id  # type: ignore[index]
    return ODOMETER


async def history_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'History' button — show last odometer record.

    Returns:
        ConversationHandler.END.
    """
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    vehicle_id = context.user_data.get("conv_vehicle_id")  # type: ignore[union-attr]
    if not vehicle_id:
        vehicle_id = await config_store.get_active_vehicle(user_id)

    if not vehicle_id:
        await query.edit_message_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
        return ConversationHandler.END

    try:
        record = await client.get_latest_odometer(vehicle_id)
        if record:
            text = get_text(
                "last_km",
                lang,
                date=record.get("date", "N/A"),
                odometer=record.get("odometer", "N/A"),
            )
        else:
            text = get_text("last_km_empty", lang)
    except LubeLoggerUnreachableError:
        text = get_text("lubelogger_unreachable", lang)

    await query.edit_message_text(text)  # type: ignore[union-attr]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        text="✓",
        reply_markup=main_menu_keyboard(lang),
    )
    _cleanup_user_data(context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel or ❌ button — abort the conversation and restore keyboard.

    Returns:
        ConversationHandler.END.
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
            VEHICLE_SELECT: [
                CallbackQueryHandler(vehicle_selected_cb, pattern=r"^odo_vehicle:\d+$"),
            ],
            ODOMETER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, odometer_step),
            ],
            SUMMARY: [
                CallbackQueryHandler(summary_save_cb, pattern=r"^summary_save$"),
                CallbackQueryHandler(summary_edit_cb, pattern=r"^summary_edit$"),
                CallbackQueryHandler(summary_cancel_cb, pattern=r"^summary_cancel$"),
                CallbackQueryHandler(log_another_cb, pattern=r"^confirm_log_another:odometer$"),
                CallbackQueryHandler(history_cb, pattern=r"^confirm_history$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r"^❌"), cancel_command),
        ],
        allow_reentry=True,
    )
