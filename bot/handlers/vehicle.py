"""Vehicle selection handler — inline keyboard for picking the active vehicle."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient


async def vehicle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /vehicle and show available vehicles as an inline keyboard."""
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        vehicles = await client.get_vehicles()
    except LubeLoggerUnreachableError:
        await update.message.reply_text(get_text("lubelogger_unreachable", lang))
        return
    except LubeLoggerApiError:
        await update.message.reply_text(get_text("lubelogger_error", lang))
        return

    if not vehicles:
        await update.message.reply_text(get_text("no_vehicles", lang))
        return

    keyboard = [
        [InlineKeyboardButton(v.display_name, callback_data=f"vehicle:{v.id}")] for v in vehicles
    ]
    await update.message.reply_text(
        get_text("vehicle_prompt", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def vehicle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callback for vehicle selection."""
    query = update.callback_query
    user_id = update.effective_user.id
    allowed_ids = context.bot_data.get("allowed_user_ids")
    if allowed_ids is not None and user_id not in allowed_ids:
        await query.answer()
        return

    await query.answer()
    callback_data = query.data or ""
    vehicle_id = int(callback_data.split(":", 1)[1])

    config_store: ConfigStore = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]

    try:
        vehicles = await client.get_vehicles()
    except LubeLoggerUnreachableError:
        # The button came from a previously valid list; retain selection offline.
        vehicle_name = f"Vehicle #{vehicle_id}"
    except LubeLoggerApiError:
        await query.edit_message_text(get_text("lubelogger_error", lang))
        return
    else:
        selected_vehicle = next((vehicle for vehicle in vehicles if vehicle.id == vehicle_id), None)
        if selected_vehicle is None:
            await query.edit_message_text(get_text("vehicle_not_found", lang))
            return
        vehicle_name = selected_vehicle.display_name

    await config_store.set_active_vehicle(user_id, vehicle_id)
    await query.edit_message_text(get_text("vehicle_selected", lang, vehicle_name=vehicle_name))


def get_vehicle_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for vehicle selection."""
    return (
        CommandHandler("vehicle", vehicle_command, filters=auth_filter),
        CallbackQueryHandler(vehicle_callback, pattern=r"^vehicle:[1-9]\d*$"),
    )
