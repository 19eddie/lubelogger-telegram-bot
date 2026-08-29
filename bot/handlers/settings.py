"""Settings handlers — language selection."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from bot.i18n import get_text
from bot.services.command_registry import register_for_chat
from bot.services.config_store import ConfigStore

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lang — show language selection inline keyboard."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"lang:{code}")]
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_text("lang_prompt", lang), reply_markup=reply_markup
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

    # Re-register commands for this chat in the new language (Req 2.5).
    bot = context.bot
    await register_for_chat(bot, user_id, lang_code)

    lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code)
    await query.edit_message_text(get_text("lang_changed", lang_code, language=lang_name))


def get_settings_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, CallbackQueryHandler]:
    """Return the command and callback handlers for language settings.

    Args:
        auth_filter: Optional filter to restrict commands to authorized users.
    """
    return (
        CommandHandler("lang", lang_command, filters=auth_filter),
        CallbackQueryHandler(lang_callback, pattern=r"^lang:\w+$"),
    )
