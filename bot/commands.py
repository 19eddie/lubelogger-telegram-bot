"""BotFather command registration at startup."""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application

from bot.i18n import get_text

logger = logging.getLogger(__name__)

COMMANDS = ["fuel", "service", "km", "vehicle", "last", "status", "lang", "start", "help"]


def build_commands(lang: str) -> list[BotCommand]:
    """Build the list of BotCommand objects with localized descriptions.

    Args:
        lang: The language code for descriptions.

    Returns:
        List of BotCommand with command name and description.
    """
    return [BotCommand(command=cmd, description=get_text(f"cmd_{cmd}", lang)) for cmd in COMMANDS]


async def register_commands(app: Application) -> None:
    """Register bot commands with Telegram via setMyCommands.

    Called in post_init. Logs a warning and continues if the call fails.
    """
    try:
        commands = build_commands("en")
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands registered successfully")
    except Exception:
        logger.warning("Failed to register bot commands", exc_info=True)
