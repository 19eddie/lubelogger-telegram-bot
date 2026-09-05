"""Main entry point — load config, initialize services, start polling."""

from __future__ import annotations

import logging
import sys

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import load_config
from bot.exceptions import ConfigurationError
from bot.handlers.fuel import get_fuel_conversation_handler
from bot.handlers.help import help_command
from bot.handlers.odometer import get_odometer_conversation_handler
from bot.handlers.query import last_command, queue_command, status_command
from bot.handlers.service import get_service_conversation_handler
from bot.handlers.settings import get_settings_handlers
from bot.handlers.vehicle import get_vehicle_handlers
from bot.i18n import get_text
from bot.middleware.auth import create_auth_filter
from bot.models.responses import QueueItem
from bot.services.config_store import ConfigStore
from bot.services.database import init_db
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)


def _group_by_user(items: list[QueueItem]) -> dict[int, int]:
    """Count queue items per submitting user ID."""
    counts: dict[int, int] = {}
    for item in items:
        counts[item.user_id] = counts.get(item.user_id, 0) + 1
    return counts


async def _notify_users(
    bot: Bot,
    config_store: ConfigStore,
    items: list[QueueItem],
    single_key: str,
    multi_key: str,
) -> None:
    """Send one localized summary message per user for queue outcomes."""
    for user_id, count in _group_by_user(items).items():
        lang = await config_store.get_language(user_id)
        text = get_text(single_key, lang) if count == 1 else get_text(multi_key, lang, count=count)
        try:
            await bot.send_message(chat_id=user_id, text=text)
        except TelegramError as exc:
            logger.warning("Could not notify user %d about queue outcome: %s", user_id, exc)


async def retry_queue_job(context: object) -> None:
    """Job queue callback: flush pending records periodically, then notify users."""
    from telegram.ext import CallbackContext

    ctx: CallbackContext = context  # type: ignore[assignment]
    queue_service: QueueService = ctx.bot_data["queue_service"]
    client: LubeLoggerClient = ctx.bot_data["lubelogger_client"]
    config_store: ConfigStore = ctx.bot_data["config_store"]
    result = await queue_service.flush(client)
    if result.sent > 0 or result.failed > 0:
        logger.info(
            "Queue flush: sent=%d, failed=%d, remaining=%d",
            result.sent,
            result.failed,
            result.remaining,
        )

    if result.sent_items:
        await _notify_users(
            ctx.bot, config_store, result.sent_items, "queue_synced", "queue_synced_multi"
        )
    if result.failed_items:
        await _notify_users(
            ctx.bot, config_store, result.failed_items, "queue_failed", "queue_failed_multi"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected update errors and return a safe user-facing message."""
    error = context.error
    if error is None:
        logger.error("Unhandled Telegram update error without exception details")
    else:
        logger.error("Unhandled Telegram update error", exc_info=error)

    message = getattr(update, "effective_message", None)
    if message is None:
        return

    try:
        await message.reply_text(get_text("unexpected_error", "en"))
    except TelegramError as exc:
        logger.warning("Could not send unexpected-error message: %s", exc)


def main() -> None:
    """Entry point — load config, initialize services, start polling."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        config = load_config()
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info(
        "Starting bot: LubeLogger URL=%s, allowed users=%d",
        config.lubelogger_url,
        len(config.allowed_user_ids),
    )

    app = Application.builder().token(config.telegram_bot_token).build()
    auth = create_auth_filter(config.allowed_user_ids)

    async def post_init(application: Application) -> None:  # type: ignore[type-arg]
        await init_db(config.db_path)
        client = LubeLoggerClient(
            config.lubelogger_url, config.lubelogger_api_key, config.http_timeout
        )
        queue_service = QueueService(config.db_path, config.max_retry_attempts)
        config_store = ConfigStore(config.db_path)

        application.bot_data["lubelogger_client"] = client
        application.bot_data["queue_service"] = queue_service
        application.bot_data["config_store"] = config_store
        application.bot_data["allowed_user_ids"] = config.allowed_user_ids

        if application.job_queue is not None:
            application.job_queue.run_repeating(
                retry_queue_job,
                interval=config.queue_retry_interval,
                first=config.queue_retry_interval,
            )

    async def post_shutdown(application: Application) -> None:  # type: ignore[type-arg]
        client: LubeLoggerClient | None = application.bot_data.get("lubelogger_client")
        if client is not None:
            await client.close()

    app.post_init = post_init
    app.post_shutdown = post_shutdown
    app.add_error_handler(error_handler)

    app.add_handler(get_fuel_conversation_handler(auth_filter=auth))
    app.add_handler(get_service_conversation_handler(auth_filter=auth))
    app.add_handler(get_odometer_conversation_handler(auth_filter=auth))
    app.add_handler(CommandHandler("help", help_command, filters=auth))

    vehicle_cmd, vehicle_cb = get_vehicle_handlers(auth_filter=auth)
    app.add_handler(vehicle_cmd)
    app.add_handler(vehicle_cb)

    start_handler, lang_handler, lang_cb = get_settings_handlers(auth_filter=auth)
    app.add_handler(start_handler)
    app.add_handler(lang_handler)
    app.add_handler(lang_cb)

    app.add_handler(CommandHandler("last", last_command, filters=auth))
    app.add_handler(CommandHandler("status", status_command, filters=auth))
    app.add_handler(CommandHandler("queue", queue_command, filters=auth))

    app.run_polling()


if __name__ == "__main__":
    main()
