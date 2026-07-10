"""Settings handlers — language selection and welcome message."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.i18n import get_text
from bot.services.config_store import ConfigStore

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message + vehicle selection prompt if needed."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    vehicle = await config_store.get_active_vehicle(user_id)

    if vehicle is None:
        await update.message.reply_text(get_text("start_no_vehicle", lang))
    else:
        await update.message.reply_text(get_text("welcome", lang))


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


def get_settings_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CommandHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for settings.

    Args:
        auth_filter: Optional filter to restrict commands to authorized users.
    """
    return (
        CommandHandler("start", start_command, filters=auth_filter),
        CommandHandler("lang", lang_command, filters=auth_filter),
        CallbackQueryHandler(lang_callback, pattern=r"^lang:\w+$"),
    )
