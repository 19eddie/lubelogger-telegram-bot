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
    """Handle /start — welcome message plus vehicle prompt if needed."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    vehicle = await config_store.get_active_vehicle(user_id)

    if vehicle is None:
        await update.message.reply_text(get_text("start_no_vehicle", lang))
    else:
        await update.message.reply_text(get_text("welcome", lang))


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lang and show language selection keyboard."""
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"lang:{code}")]
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    await update.message.reply_text(
        "Select language / Seleziona lingua:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback from inline keyboard."""
    query = update.callback_query
    user_id = update.effective_user.id
    allowed_ids = context.bot_data.get("allowed_user_ids")
    if allowed_ids is not None and user_id not in allowed_ids:
        await query.answer()
        return

    await query.answer()
    callback_data = query.data or ""
    lang_code = callback_data.split(":", 1)[1] if ":" in callback_data else ""
    if lang_code not in SUPPORTED_LANGUAGES:
        await query.edit_message_text(get_text("invalid_language", "en"))
        return

    config_store: ConfigStore = context.bot_data["config_store"]
    await config_store.set_language(user_id, lang_code)
    await query.edit_message_text(
        get_text("lang_changed", lang_code, language=SUPPORTED_LANGUAGES[lang_code])
    )


def get_settings_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CommandHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for settings."""
    return (
        CommandHandler("start", start_command, filters=auth_filter),
        CommandHandler("lang", lang_command, filters=auth_filter),
        CallbackQueryHandler(lang_callback, pattern=r"^lang:(?:en|it)$"),
    )
