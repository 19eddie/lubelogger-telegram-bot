"""Help command handler."""

from __future__ import annotations

from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.command_catalog import COMMAND_CATALOG
from bot.i18n import get_text
from bot.services.config_store import ConfigStore


def build_help_message(lang: str) -> str:
    """Build localized, HTML-formatted help text from the command catalog."""
    title = escape(get_text("help_title", lang), quote=False)
    lines = [f"<b>{title}</b>", ""]
    current_section: str | None = None

    for command in COMMAND_CATALOG:
        if not command.show_in_help:
            continue

        if command.section_key != current_section:
            if current_section is not None:
                lines.append("")
            section = escape(get_text(command.section_key, lang), quote=False)
            lines.append(f"<b>{section}</b>")
            lines.append("")
            current_section = command.section_key

        description = escape(get_text(command.description_key, lang), quote=False)
        command_text = f"/{command.name}"
        if command.usage_key is not None:
            usage = get_text(command.usage_key, lang)
            if usage.startswith(command_text):
                arguments = usage[len(command_text) :].strip()
                usage_html = escape(arguments, quote=False)
                command_text = f"{command_text} <code>{usage_html}</code>"
            else:
                usage_html = escape(usage, quote=False)
                command_text = f"{command_text} <code>{usage_html}</code>"

        lines.append(f"{command_text} — {description}")

    return "\n".join(lines)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the localized list of available bot commands."""
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id
    lang = await config_store.get_language(user_id)
    await update.message.reply_text(build_help_message(lang), parse_mode=ParseMode.HTML)
