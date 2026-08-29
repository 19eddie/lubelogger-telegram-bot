"""Vehicle selection handler — inline keyboard for picking the active vehicle."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.exceptions import LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient


async def vehicle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /vehicle command — show available vehicles as inline keyboard."""
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    try:
        snapshots = await client.get_vehicle_snapshots()
    except LubeLoggerUnreachableError:
        await update.message.reply_text(get_text("lubelogger_unreachable", lang))
        return

    if not snapshots:
        await update.message.reply_text(get_text("no_vehicles", lang))
        return

    # Build id-to-name mapping and store it for the callback to resolve later.
    vehicle_map: dict[int, str] = {
        s.vehicle.id: s.vehicle.display_name for s in snapshots
    }
    context.user_data["_vehicle_map"] = vehicle_map

    keyboard = [
        [InlineKeyboardButton(
            name.strip() or get_text("vehicle_fallback_name", lang),
            callback_data=f"vehicle:{vid}",
        )]
        for vid, name in vehicle_map.items()
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

    # Resolve vehicle name from the stored mapping — never issue a second API call.
    vehicle_map: dict[int, str] = context.user_data.get("_vehicle_map", {})
    vehicle_name = vehicle_map.get(vehicle_id) or get_text("vehicle_fallback_name", lang)

    # Clean up the transient mapping.
    context.user_data.pop("_vehicle_map", None)

    await config_store.set_active_vehicle(user_id, vehicle_id, vehicle_name)
    await query.edit_message_text(get_text("vehicle_selected", lang, vehicle_name=vehicle_name))


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
