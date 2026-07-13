"""Settings handlers — language selection and improved /start onboarding."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.exceptions import LubeLoggerUnreachableError
from bot.i18n import get_text
from bot.services.config_store import ConfigStore
from bot.services.keyboard import main_menu_keyboard
from bot.services.lubelogger_client import LubeLoggerClient

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — onboarding for new users, welcome-back for returning users."""
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    vehicle_id = await config_store.get_active_vehicle(user_id)

    if vehicle_id is not None:
        # Returning user — get vehicle name and show welcome-back
        try:
            vehicles = await client.get_vehicles()
            vehicle_name = next(
                (v.display_name for v in vehicles if v.id == vehicle_id),
                f"Vehicle #{vehicle_id}",
            )
        except LubeLoggerUnreachableError:
            vehicle_name = f"Vehicle #{vehicle_id}"

        await update.message.reply_text(
            get_text("start_welcome_back", lang, vehicle=vehicle_name),
            reply_markup=main_menu_keyboard(lang),
        )
    else:
        # New user — fetch vehicles and show inline selection
        try:
            vehicles = await client.get_vehicles()
        except LubeLoggerUnreachableError:
            await update.message.reply_text(get_text("start_api_unreachable", lang))
            return

        keyboard = [
            [InlineKeyboardButton(v.display_name, callback_data=f"start_vehicle:{v.id}")]
            for v in vehicles
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            get_text("start_welcome_new", lang),
            reply_markup=reply_markup,
        )


async def start_vehicle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle vehicle selection from onboarding inline keyboard."""
    query = update.callback_query

    # Verify user is authorized
    user_id = update.effective_user.id
    allowed_ids: list[int] = context.bot_data.get("allowed_user_ids", [])
    if allowed_ids and user_id not in allowed_ids:
        await query.answer()
        return

    await query.answer()

    config_store: ConfigStore = context.bot_data["config_store"]
    lang = await config_store.get_language(user_id)

    vehicle_id = int(query.data.split(":")[1])

    # Get vehicle name for confirmation
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

    # Edit the onboarding message to show confirmation, then send main keyboard
    await query.edit_message_text(
        get_text("vehicle_selected", lang, vehicle_name=vehicle_name),
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=get_text("start_welcome_back", lang, vehicle=vehicle_name),
        reply_markup=main_menu_keyboard(lang),
    )


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lang — show language selection inline keyboard."""
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"lang:{code}")]
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Select language / Seleziona lingua:", reply_markup=reply_markup
    )


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback from inline keyboard."""
    query = update.callback_query
    await query.answer()

    # Verify user is authorized
    allowed_ids: list[int] = context.bot_data.get("allowed_user_ids", [])
    if allowed_ids and update.effective_user.id not in allowed_ids:
        return

    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id

    lang_code = query.data.split(":")[1]
    await config_store.set_language(user_id, lang_code)

    lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code)
    await query.edit_message_text(get_text("lang_changed", lang_code, language=lang_name))
    # Send a follow-up message with the main Reply keyboard updated to the new language
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✓",
        reply_markup=main_menu_keyboard(lang_code),
    )


def get_settings_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CommandHandler, CallbackQueryHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for settings.

    Args:
        auth_filter: Optional filter to restrict commands to authorized users.

    Returns:
        A tuple of (start_command, lang_command, lang_callback, start_vehicle_callback).
    """
    return (
        CommandHandler("start", start_command, filters=auth_filter),
        CommandHandler("lang", lang_command, filters=auth_filter),
        CallbackQueryHandler(lang_callback, pattern=r"^lang:\w+$"),
        CallbackQueryHandler(start_vehicle_callback, pattern=r"^start_vehicle:\d+$"),
    )
