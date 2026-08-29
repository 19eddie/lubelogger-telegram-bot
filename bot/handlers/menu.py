"""Menu handler — welcome, onboarding, and persistent navigation keyboard."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bot.exceptions import LubeLoggerUnreachableError
from bot.flows.definitions import MenuAction
from bot.formatters import render_welcome
from bot.i18n import get_text, resolve_menu_label
from bot.keyboards import VehicleChoice, menu_keyboard, vehicle_keyboard
from bot.services.config_store import ConfigStore
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.odometer_tracker import OdometerTracker

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome + vehicle selection if needed + establish Menu_Keyboard.

    Requirement 8.1-8.6, 1.1, 1.3, 1.4, 1.5, 1.6:
    - No active vehicle: 3-line welcome + inline vehicle keyboard
    - Single vehicle auto-select: persist + confirm + Menu_Keyboard
    - Multiple vehicles, none active: prompt for selection
    - Active vehicle already set: short welcome naming it + Menu_Keyboard
    - Unreachable: explain + suggest retry + Menu_Keyboard anyway
    """
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    msg = update.effective_message

    if user is None or chat_id is None or msg is None:  # pragma: no cover
        return

    user_id = user.id

    # Services.
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    tracker: OdometerTracker = context.bot_data["tracker"]

    # Step 1: language.
    lang = await config_store.get_language(user_id)

    # Step 2: check if active vehicle is already set.
    persisted_vehicle_id = await config_store.get_active_vehicle(user_id)
    persisted_vehicle_name = await config_store.get_active_vehicle_name(user_id)

    if persisted_vehicle_id is not None:
        # Short welcome-back greeting naming the vehicle + establish Menu_Keyboard.
        # Requirement 8.4, 8.6.
        welcome_text = render_welcome(vehicle_name=persisted_vehicle_name, lang=lang)
        await msg.reply_text(welcome_text, reply_markup=menu_keyboard(lang))
        return

    # Step 3: no active vehicle → fetch vehicle list.
    try:
        snapshots = await client.get_vehicle_snapshots()

        # Observe snapshots in tracker (Req 5.4, 5.11).
        for snap in snapshots:
            await tracker.observe_snapshot(snap)

        if not snapshots:
            # No vehicles at all.
            await msg.reply_text(get_text("no_vehicles", lang))
            # Still establish Menu_Keyboard so user is not left without navigation.
            await msg.reply_text("\u200b", reply_markup=menu_keyboard(lang))
            return

        if len(snapshots) == 1:
            # Auto-select and persist the only vehicle (Req 5.1, 8.3, 8.6).
            snap = snapshots[0]
            vehicle_id = snap.vehicle.id
            vehicle_name = snap.vehicle.display_name
            await config_store.set_active_vehicle(user_id, vehicle_id, vehicle_name)

            # Confirm selection and establish Menu_Keyboard.
            welcome_text = render_welcome(vehicle_name=vehicle_name, lang=lang)
            await msg.reply_text(
                get_text("vehicle_auto_selected", lang, vehicle_name=vehicle_name)
            )
            await msg.reply_text(welcome_text, reply_markup=menu_keyboard(lang))
            return

        # Multiple vehicles available → show selection keyboard (Req 8.2).
        welcome_text = render_welcome(vehicle_name=None, lang=lang)
        await msg.reply_text(welcome_text)

        vehicles = [
            VehicleChoice(vehicle_id=snap.vehicle.id, name=snap.vehicle.display_name)
            for snap in snapshots
        ]
        markup = vehicle_keyboard(vehicles, lang)
        await msg.reply_text(get_text("vehicle_prompt", lang), reply_markup=markup)

    except LubeLoggerUnreachableError:
        # Unreachable (Req 8.5, 8.6).
        if persisted_vehicle_id is not None:
            # Use persisted vehicle even though we couldn't refresh.
            welcome_text = render_welcome(vehicle_name=persisted_vehicle_name, lang=lang)
            await msg.reply_text(welcome_text, reply_markup=menu_keyboard(lang))
        else:
            # No persisted vehicle and can't reach LubeLogger → explain and still set Menu_Keyboard.
            await msg.reply_text(get_text("welcome_unreachable", lang))
            await msg.reply_text("\u200b", reply_markup=menu_keyboard(lang))


async def menu_label_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route a tapped Menu_Keyboard button (plain text) to its action.

    When a user taps a button on the Menu_Keyboard, it sends a plain text message.
    This handler resolves the label to a MenuAction and dispatches to the appropriate
    handler. Write actions (fuel, service, odometer) are routed to their handlers.
    Read actions (latest, options) are dispatched to their respective handlers.

    Requirement 1.3, 1.5, 1.6, 11.5.
    """
    msg = update.effective_message
    if msg is None or msg.text is None:
        return

    user = update.effective_user
    if user is None:
        return

    # Try to resolve the text to a menu action via the allowlist.
    action = resolve_menu_label(msg.text)
    if action is None:
        # Not a menu label, ignore.
        return

    # Dispatch to the appropriate handler based on the action.
    # For write actions (fuel/service/odometer), delegate to their handlers.
    if action == MenuAction.FUEL:
        from bot.handlers.fuel import fuel_command

        await fuel_command(update, context)
    elif action == MenuAction.SERVICE:
        from bot.handlers.service import service_command

        await service_command(update, context)
    elif action == MenuAction.ODOMETER:
        from bot.handlers.odometer import km_command

        await km_command(update, context)
    elif action == MenuAction.LATEST:
        # Latest menu handler (Req 10).
        from bot.handlers.latest import open_latest_menu

        await open_latest_menu(update, context)
    elif action == MenuAction.OPTIONS:
        # Options menu handler (Req 1.9).
        from bot.handlers.options import open_options_menu

        await open_options_menu(update, context)


def get_menu_handlers(
    auth_filter: filters.BaseFilter | None = None,
) -> tuple[CommandHandler, MessageHandler]:
    """Return the command and message handlers for the menu system.

    Args:
        auth_filter: Optional filter to restrict handlers to authorized users.

    Returns:
        Tuple of (start_handler, menu_label_handler).
    """
    return (
        CommandHandler("start", start_command, filters=auth_filter),
        MessageHandler(filters.TEXT & ~filters.COMMAND & auth_filter, menu_label_handler),
    )
