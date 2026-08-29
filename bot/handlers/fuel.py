"""Fuel record handler — inline-argument submission or guided flow delegation.

With arguments: parse → validate → submit through RecordSubmitter → render rich confirmation.
Without arguments: delegate to ``start_flow`` (the unified ConversationHandler takes over).

Requirements: 12.1, 12.2, 12.3, 12.4, 13.1
"""

from __future__ import annotations

import logging
from datetime import date

from pydantic import ValidationError
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

from bot.callbacks import NO_TOKEN
from bot.exceptions import LubeLoggerApiError, ParseError
from bot.flows.definitions import FlowKind
from bot.flows.views import ConfirmationView, FieldEntry
from bot.formatters import render_confirmation, render_queued, render_regression
from bot.handlers.record_flow import COLLECT, start_flow
from bot.i18n import get_text
from bot.keyboards import confirmation_keyboard
from bot.services.command_parser import CommandParser, parse_vehicle_override
from bot.services.config_store import ConfigStore
from bot.services.odometer_tracker import OdometerTracker
from bot.services.record_submitter import RecordSubmitter

logger = logging.getLogger(__name__)

END = ConversationHandler.END


async def fuel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /fuel — inline submission with args, guided flow without.

    Returns:
        ConversationHandler.END for inline path, or COLLECT state for guided flow.
    """
    config_store: ConfigStore = context.bot_data["config_store"]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    lang = await config_store.get_language(user_id)

    # Build full argument string
    args_text = " ".join(context.args) if context.args else ""

    # Extract --vehicle override
    vehicle_override, args_text = parse_vehicle_override(args_text)

    if not args_text.strip():
        # No args → delegate to guided flow
        return await start_flow(update, context, kind=FlowKind.FUEL, vehicle_override=vehicle_override)

    # --- Inline-argument path ---

    # Resolve vehicle ID
    vehicle_id: int | None = vehicle_override
    if vehicle_id is None:
        vehicle_id = await config_store.get_active_vehicle(user_id)
    if vehicle_id is None:
        await update.message.reply_text(get_text("no_vehicle", lang))  # type: ignore[union-attr]
        return END

    # Parse
    try:
        fuel_input = CommandParser.parse_fuel(args_text)
    except ParseError:
        await update.message.reply_text(get_text("usage_fuel", lang))  # type: ignore[union-attr]
        return END

    # Build values dict
    try:
        odometer = int(float(fuel_input.odometer))
        liters = float(fuel_input.liters)
        cost = float(fuel_input.cost)
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("usage_fuel", lang))  # type: ignore[union-attr]
        return END

    if odometer <= 0 or liters <= 0 or cost < 0:
        await update.message.reply_text(get_text("usage_fuel", lang))  # type: ignore[union-attr]
        return END

    values: dict[str, object] = {
        "odometer": odometer,
        "liters": liters,
        "cost": cost,
        "is_fill_to_full": fuel_input.is_fill_to_full,
        "missed_fuel_up": fuel_input.missed_fuel_up,
    }

    # Odometer regression check (warn but proceed — Req 5.10, 12.1)
    tracker: OdometerTracker = context.bot_data["tracker"]
    reference = await tracker.get_reference(vehicle_id)
    if reference is not None and odometer < reference.value:
        warning = render_regression(odometer, reference, lang)
        await update.message.reply_text(warning, parse_mode="HTML")  # type: ignore[union-attr]

    # Submit
    submitter: RecordSubmitter = context.bot_data["record_submitter"]
    try:
        outcome = await submitter.submit(
            user_id=user_id,
            vehicle_id=vehicle_id,
            kind=FlowKind.FUEL,
            values=values,
        )
    except (LubeLoggerApiError, ValidationError) as exc:
        logger.warning("Inline fuel submit failed: %s", exc)
        await update.message.reply_text(get_text("usage_fuel", lang))  # type: ignore[union-attr]
        return END

    # Build confirmation view
    entries = _build_fuel_entries(values, lang)
    view = ConfirmationView(
        kind=FlowKind.FUEL,
        vehicle_name=outcome.vehicle_name,
        on_date=date.today(),
        entries=entries,
        consumption=outcome.consumption,
    )

    if outcome.status == "saved":
        text = render_confirmation(view, lang)
        markup = confirmation_keyboard(NO_TOKEN, queued=False, lang=lang)
    else:
        text = render_queued(view, lang)
        markup = confirmation_keyboard(NO_TOKEN, queued=True, lang=lang)

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)  # type: ignore[union-attr]
    return END


def _build_fuel_entries(values: dict[str, object], lang: str) -> tuple[FieldEntry, ...]:
    """Build FieldEntry tuples for fuel values."""
    from bot.formatters import fmt_display, fmt_int

    odometer = int(values["odometer"])  # type: ignore[arg-type]
    liters = float(values["liters"])  # type: ignore[arg-type]
    cost = float(values["cost"])  # type: ignore[arg-type]
    is_full = bool(values.get("is_fill_to_full", True))

    return (
        FieldEntry(
            index=0,
            label_key="field_odometer",
            rendered_value=f"{fmt_int(odometer, lang)} {get_text('fmt_unit_distance', lang)}",
        ),
        FieldEntry(
            index=1,
            label_key="field_liters",
            rendered_value=f"{fmt_display(liters, lang)} {get_text('fmt_unit_volume', lang)}",
        ),
        FieldEntry(
            index=2,
            label_key="field_cost",
            rendered_value=f"{fmt_display(cost, lang)} {get_text('fmt_unit_currency', lang)}",
        ),
        FieldEntry(
            index=3,
            label_key="field_full_tank",
            rendered_value=get_text("btn_yes" if is_full else "btn_no", lang),
        ),
    )
