"""BotFather command registration with per-locale and per-chat scopes."""

from __future__ import annotations

import logging

from telegram import Bot, BotCommand, BotCommandScopeChat
from telegram.error import TelegramError

from bot.i18n import available_locales, get_text
from bot.services.config_store import ConfigStore

logger = logging.getLogger(__name__)

#: Tuple of (command_name, description_locale_key) for BotFather registration.
#: Requirement 2.1: start, fuel, service, km, last, vehicle, status, queue, lang, cancel.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "cmd_start"),
    ("fuel", "cmd_fuel"),
    ("service", "cmd_service"),
    ("km", "cmd_km"),
    ("last", "cmd_last"),
    ("vehicle", "cmd_vehicle"),
    ("status", "cmd_status"),
    ("queue", "cmd_queue"),
    ("lang", "cmd_lang"),
    ("cancel", "cmd_cancel"),
)


def commands_for(lang: str) -> list[BotCommand]:
    """Build the command list for the given language.

    Pure function: no I/O, no state. Returns a list of BotCommand objects
    with descriptions localized to `lang`.

    Args:
        lang: Language code (e.g. 'en', 'it').

    Returns:
        List of BotCommand objects with command names and localized descriptions.
    """
    return [BotCommand(name, get_text(key, lang)) for name, key in COMMANDS]


async def register_all(
    bot: Bot,
    config_store: ConfigStore,
    allowed_user_ids: list[int],
) -> None:
    """Register commands in all locales and per-chat for whitelisted users.

    Requirement 2.2: one call per locale with language_code.
    Requirement 2.3: one call per whitelisted user with BotCommandScopeChat and stored language.
    Requirement 2.4: one default call without language_code.
    Requirement 2.6: every failure is logged at WARNING level and startup continues.

    Args:
        bot: Telegram bot instance.
        config_store: Config store providing user languages.
        allowed_user_ids: List of authorized user IDs for per-chat registration.
    """
    locales = available_locales()

    # Per-locale registration with language_code (Req 2.2).
    for lang in locales:
        try:
            commands = commands_for(lang)
            await bot.set_my_commands(commands, language_code=lang)
            logger.debug("Registered commands for locale %s", lang)
        except TelegramError as exc:
            logger.warning(
                "Failed to register commands for locale %s: %s",
                lang,
                exc,
            )

    # Default registration without language_code (Req 2.4).
    try:
        commands = commands_for("en")
        await bot.set_my_commands(commands)
        logger.debug("Registered default commands")
    except TelegramError as exc:
        logger.warning("Failed to register default commands: %s", exc)

    # Per-chat registration for whitelisted users (Req 2.3).
    user_languages = await config_store.get_all_languages()
    for user_id in allowed_user_ids:
        try:
            user_lang = user_languages.get(user_id, "en")
            commands = commands_for(user_lang)
            scope = BotCommandScopeChat(chat_id=user_id)
            await bot.set_my_commands(commands, scope=scope)
            logger.debug("Registered commands for user %d in language %s", user_id, user_lang)
        except TelegramError as exc:
            logger.warning(
                "Failed to register commands for user %d: %s",
                user_id,
                exc,
            )


async def register_for_chat(bot: Bot, chat_id: int, lang: str) -> None:
    """Re-register commands for a specific chat in a new language.

    Called after /lang changes the user's language (Requirement 2.5).

    Args:
        bot: Telegram bot instance.
        chat_id: Telegram chat (user) ID.
        lang: New language code.
    """
    try:
        commands = commands_for(lang)
        scope = BotCommandScopeChat(chat_id=chat_id)
        await bot.set_my_commands(commands, scope=scope)
        logger.debug("Re-registered commands for user %d in language %s", chat_id, lang)
    except TelegramError as exc:
        logger.warning(
            "Failed to re-register commands for user %d: %s",
            chat_id,
            exc,
        )
