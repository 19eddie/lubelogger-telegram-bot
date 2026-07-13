"""Vehicle selection handler — inline keyboard for picking the active vehicle."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.exceptions import LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.keyboard import main_menu_keyboard
from bot.services.lubelogger_client import LubeLoggerClient


async def vehicle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /vehicle command — show available vehicles as inline keyboard."""
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        vehicles = await client.get_vehicles()
    except LubeLoggerUnreachableError:
        await update.message.reply_text(get_text("lubelogger_unreachable", lang))
        return

    if not vehicles:
        await update.message.reply_text(get_text("no_vehicles", lang))
        return

    keyboard = [
        [InlineKeyboardButton(v.display_name, callback_data=f"vehicle:{v.id}")] for v in vehicles
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(get_text("vehicle_prompt", lang), reply_markup=reply_markup)


async def vehicle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callback for vehicle selection."""
    query = update.callback_query

    # Verify user is authorized
    user_id = update.effective_user.id
    allowed_ids: list[int] = context.bot_data.get("allowed_user_ids", [])
    if allowed_ids and user_id not in allowed_ids:
        await query.answer()
        return

    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    vehicle_id = int(query.data.split(":")[1])

    # Get vehicle name for confirmation message
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    try:
        vehicles = await client.get_vehicles()
        vehicle_name = next(
            (v.display_name for v in vehicles if v.id == vehicle_id),
            f"Vehicle #{vehicle_id}",
        )
    except LubeLoggerUnreachableError:
        vehicle_name = f"Vehicle #{vehicle_id}"

    await config_store.set_active_vehicle(user_id, vehicle_id)
    await query.edit_message_text(get_text("vehicle_selected", lang, vehicle_name=vehicle_name))
    # Send a follow-up message with the main Reply keyboard so it stays visible
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=get_text("start_welcome_back", lang, vehicle=vehicle_name),
        reply_markup=main_menu_keyboard(lang),
    )


def get_vehicle_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for vehicle selection.

    Args:
        auth_filter: Optional filter to restrict the command to authorized users.
    """
    return (
        CommandHandler("vehicle", vehicle_command, filters=auth_filter),
        CallbackQueryHandler(vehicle_callback, pattern=r"^vehicle:\d+$"),
    )
