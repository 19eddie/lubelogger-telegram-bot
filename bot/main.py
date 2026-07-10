"""Main entry point — load config, initialize services, start polling."""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CommandHandler

from bot.config import load_config
from bot.exceptions import ConfigurationError
from bot.handlers.fuel import get_fuel_conversation_handler
from bot.handlers.odometer import get_odometer_conversation_handler
from bot.handlers.query import last_command, queue_command, status_command
from bot.handlers.service import get_service_conversation_handler
from bot.handlers.settings import get_settings_handlers
from bot.handlers.vehicle import get_vehicle_handlers
from bot.middleware.auth import create_auth_filter
from bot.services.config_store import ConfigStore
from bot.services.database import init_db
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)


async def retry_queue_job(context: object) -> None:
    """Job queue callback: flush pending records periodically."""
    from telegram.ext import CallbackContext

    ctx: CallbackContext = context  # type: ignore[assignment]
    queue_service: QueueService = ctx.bot_data["queue_service"]
    client: LubeLoggerClient = ctx.bot_data["lubelogger_client"]
    result = await queue_service.flush(client)
    if result.sent > 0 or result.failed > 0:
        logger.info(
            "Queue flush: sent=%d, failed=%d, remaining=%d",
            result.sent,
            result.failed,
            result.remaining,
        )


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

    # Build application
    app = Application.builder().token(config.telegram_bot_token).build()

    # Create auth filter
    auth = create_auth_filter(config.allowed_user_ids)

    # Initialize services via post_init (runs after application is fully built)
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

        # Set up retry job (every queue_retry_interval seconds)
        if application.job_queue is not None:
            application.job_queue.run_repeating(
                retry_queue_job,
                interval=config.queue_retry_interval,
                first=config.queue_retry_interval,
            )

    app.post_init = post_init

    # Register handlers — all with auth filter

    # Conversation handlers (auth filter on entry points)
    app.add_handler(get_fuel_conversation_handler(auth_filter=auth))
    app.add_handler(get_service_conversation_handler(auth_filter=auth))
    app.add_handler(get_odometer_conversation_handler(auth_filter=auth))

    # Vehicle handlers (command + callback)
    vehicle_cmd, vehicle_cb = get_vehicle_handlers(auth_filter=auth)
    app.add_handler(vehicle_cmd)
    app.add_handler(vehicle_cb)

    # Settings handlers
    start_handler, lang_handler, lang_cb = get_settings_handlers(auth_filter=auth)
    app.add_handler(start_handler)
    app.add_handler(lang_handler)
    app.add_handler(lang_cb)

    # Query handlers
    app.add_handler(CommandHandler("last", last_command, filters=auth))
    app.add_handler(CommandHandler("status", status_command, filters=auth))
    app.add_handler(CommandHandler("queue", queue_command, filters=auth))

    # Start polling
    app.run_polling()


if __name__ == "__main__":
    main()
