"""Unified record flow: fuel, service, odometer in a single ConversationHandler.

This module owns the flow skeleton, states, guard logic and the ConversationHandler factory.
Actual flow logic (collect, summary, regression, abandon) lives in tasks 11.3–11.15 and is
stubbed here with handlers that immediately end the conversation.

Design Decision 9: one handler for all three record types so that cross-flow navigation
(Requirement 11.5/11.6) is expressible without returning a state that belongs to another handler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.callbacks import Callback, CallbackAction, decode, new_token
from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.flows.definitions import FieldKind, FlowKind, MenuAction, field_at, field_count
from bot.flows.views import CardView, ConfirmationView, FieldEntry, SummaryView
from bot.formatters import (
    fmt_display,
    fmt_int,
    render_abandon_prompt,
    render_cancelled,
    render_card,
    render_confirmation,
    render_queued,
    render_regression,
    render_summary,
)
from bot.i18n import get_text, resolve_menu_label
from bot.keyboards import (
    abandon_keyboard,
    confirmation_keyboard,
    field_picker_keyboard,
    flow_step_keyboard,
    menu_action_at,
    menu_keyboard,
    regression_keyboard,
    summary_keyboard,
)

if TYPE_CHECKING:
    from bot.services.card_service import CardService
    from bot.services.config_store import ConfigStore
    from bot.services.lubelogger_client import LubeLoggerClient
    from bot.services.odometer_tracker import OdometerReference, OdometerTracker
    from bot.services.record_submitter import RecordSubmitter

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

COLLECT, SUMMARY, REGRESSION, ABANDON = range(4)

END = ConversationHandler.END

#: Mapping from command name to flow kind.
_COMMAND_TO_KIND: dict[str, FlowKind] = {
    "fuel": FlowKind.FUEL,
    "service": FlowKind.SERVICE,
    "km": FlowKind.ODOMETER,
}

#: Mapping from MenuAction to FlowKind for the write actions.
_ACTION_TO_KIND: dict[MenuAction, FlowKind] = {
    MenuAction.FUEL: FlowKind.FUEL,
    MenuAction.SERVICE: FlowKind.SERVICE,
    MenuAction.ODOMETER: FlowKind.ODOMETER,
}

CTX = ContextTypes.DEFAULT_TYPE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flow state dataclass
# ---------------------------------------------------------------------------


@dataclass
class FlowState:
    """Mutable state of an in-progress record flow, stored in ``context.user_data["flow"]``."""

    kind: FlowKind
    token: str
    vehicle_id: int
    vehicle_name: str
    step_index: int = 0
    values: dict[str, object] = field(default_factory=dict)
    card_message_id: int = 0
    reference: OdometerReference | None = None
    regression_confirmed: bool = False
    editing_field: str | None = None
    pending_target: MenuAction | None = None
    lang: str = "en"


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the flow state from user_data (Req 13.2 — one place clears the state)."""
    if context.user_data is not None:
        context.user_data.pop("flow", None)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


async def guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    cb: Callback,
    *,
    auth_filter: object | None = None,
) -> bool:
    """Validate a callback query before dispatching it.

    1. Always answer the callback query (Req 11.4 — no spinning clock).
    2. Reject unauthorized users with ``alert_denied`` (Req 11.8).
    3. Reject mismatched Flow_Token with ``alert_expired`` (Req 11.2).
    4. Return True when the callback is valid and the handler may proceed.
    """
    query = update.callback_query
    if query is None:  # pragma: no cover — defensive
        return False

    # Always clear the spinning indicator.
    await query.answer()

    # Determine language from flow state or fallback.
    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    lang: str = flow.lang if flow is not None else user_data.get("lang", "en")

    # Auth check.
    if auth_filter is not None:
        user = update.effective_user
        if user is None or not auth_filter.check_user(user.id):
            await query.answer(
                text=get_text("alert_denied", lang),
                show_alert=True,
            )
            return False

    # Flow token check.
    if cb.in_flow:
        if flow is None or flow.token != cb.token:
            await query.answer(
                text=get_text("alert_expired", lang),
                show_alert=True,
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Menu-label filter
# ---------------------------------------------------------------------------

#: The write actions that trigger a record flow from the Menu_Keyboard.
_WRITE_ACTIONS: frozenset[MenuAction] = frozenset(
    {MenuAction.FUEL, MenuAction.SERVICE, MenuAction.ODOMETER}
)


class MenuLabelFilter(filters.MessageFilter):
    """Match any text that `resolve_menu_label` maps to one of the three write actions."""

    def filter(self, message: Any) -> bool:  # noqa: ANN401
        if message.text is None:
            return False
        action = resolve_menu_label(message.text)
        return action is not None and action in _WRITE_ACTIONS


# ---------------------------------------------------------------------------
# Flow start logic
# ---------------------------------------------------------------------------


async def start_flow(
    update: Update,
    context: CTX,
    *,
    kind: FlowKind,
    vehicle_override: int | None = None,
    log_another: bool = False,
) -> int:
    """Start the guided record flow with smart defaults.

    1. Determine language.
    2. Call get_vehicle_snapshots() — single API call (Req 5.11, NF-2.2).
    3. Auto-select or reuse active vehicle.
    4. Read local odometer reference (NF-2.3).
    5. Build and send the Card_Message.
    6. Store FlowState and return COLLECT.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if user is None or chat_id is None:  # pragma: no cover
        return END

    user_id = user.id

    # Services from bot_data.
    config_store: ConfigStore = context.bot_data["config_store"]
    client: LubeLoggerClient = context.bot_data["lubelogger_client"]
    tracker: OdometerTracker = context.bot_data["tracker"]
    card_service: CardService = context.bot_data["card_service"]

    # Step 1: language.
    lang = await config_store.get_language(user_id)

    # Step 2: vehicle resolution via snapshots.
    vehicle_id: int | None = vehicle_override
    vehicle_name: str = ""

    if vehicle_id is None:
        try:
            snapshots = await client.get_vehicle_snapshots()

            # Observe each snapshot in the tracker and refresh persisted vehicle name.
            for snap in snapshots:
                await tracker.observe_snapshot(snap)

            # Determine active vehicle.
            persisted_vehicle_id = await config_store.get_active_vehicle(user_id)

            if persisted_vehicle_id is not None:
                # Reuse already persisted vehicle without prompting (Req 5.2).
                vehicle_id = persisted_vehicle_id
                # Refresh the persisted name from snapshot if available.
                for snap in snapshots:
                    if snap.vehicle.id == vehicle_id:
                        name = snap.vehicle.display_name
                        if name:
                            await config_store.set_active_vehicle(user_id, vehicle_id, name)
                            vehicle_name = name
                        break
                if not vehicle_name:
                    vehicle_name = await config_store.get_active_vehicle_name(user_id) or ""
            elif len(snapshots) == 1:
                # Auto-select and persist the only vehicle (Req 5.1).
                snap = snapshots[0]
                vehicle_id = snap.vehicle.id
                vehicle_name = snap.vehicle.display_name
                await config_store.set_active_vehicle(user_id, vehicle_id, vehicle_name)
            else:
                # Multiple vehicles, none persisted → no vehicle selected.
                vehicle_id = None

        except LubeLoggerUnreachableError:
            # Fallback to persisted vehicle (Req 5.12, 9.6).
            vehicle_id = await config_store.get_active_vehicle(user_id)
            vehicle_name = await config_store.get_active_vehicle_name(user_id) or ""

    else:
        # vehicle_override provided — resolve name from config.
        vehicle_name = await config_store.get_active_vehicle_name(user_id) or ""

    # Step 3: no vehicle → inform user and end.
    if vehicle_id is None:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(get_text("no_vehicle", lang))
        return END

    # Step 4: local odometer reference (NF-2.3).
    reference = await tracker.get_reference(vehicle_id)

    # Step 5: build FlowState.
    token = new_token()
    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=vehicle_id,
        vehicle_name=vehicle_name,
        reference=reference,
        lang=lang,
    )

    # Step 6: build and send Card_Message for step 0.
    field = field_at(kind, 0)
    total = field_count(kind)
    progress: tuple[int, int] | None = (1, total) if total > 1 else None

    view = CardView(
        kind=kind,
        vehicle_name=vehicle_name,
        collected=(),
        prompt_key=field.prompt_key,
        progress=progress,
        reference=reference,
    )
    text = render_card(view, lang)

    suggestion = reference.value if reference is not None else None
    markup = flow_step_keyboard(token, field, suggestion=suggestion, lang=lang)

    # Step 7: open card.
    card_message_id = await card_service.open(chat_id, text, markup)
    flow.card_message_id = card_message_id

    # Step 8: store flow state.
    if context.user_data is not None:
        context.user_data["flow"] = flow

    # Step 9: send menu keyboard with placeholder hint (Req 3.8).
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(
            "\u200b",
            reply_markup=menu_keyboard(lang, placeholder_key=field.placeholder_key),
        )

    # Step 10: return COLLECT state.
    return COLLECT


# ---------------------------------------------------------------------------
# Helpers: rendering steps and summary
# ---------------------------------------------------------------------------


def _build_collected_entries(flow: FlowState) -> tuple[FieldEntry, ...]:
    """Build FieldEntry tuples for all values collected so far."""
    entries: list[FieldEntry] = []
    for idx in range(flow.step_index):
        spec = field_at(flow.kind, idx)
        raw = flow.values.get(spec.key)
        if raw is None:
            continue
        rendered = _render_value(raw, spec.kind, flow.lang, key=spec.key)
        entries.append(FieldEntry(index=idx, label_key=spec.label_key, rendered_value=rendered))
    return tuple(entries)


def _build_all_entries(flow: FlowState) -> tuple[FieldEntry, ...]:
    """Build FieldEntry tuples for every field in the flow (summary mode)."""
    entries: list[FieldEntry] = []
    total = field_count(flow.kind)
    for idx in range(total):
        spec = field_at(flow.kind, idx)
        raw = flow.values.get(spec.key)
        if raw is None:
            continue
        rendered = _render_value(raw, spec.kind, flow.lang, key=spec.key)
        entries.append(FieldEntry(index=idx, label_key=spec.label_key, rendered_value=rendered))
    return tuple(entries)


def _render_value(raw: object, kind: FieldKind, lang: str, *, key: str = "") -> str:
    """Format a collected value for display according to its field kind."""
    if kind is FieldKind.INT:
        return f"{fmt_int(int(raw), lang)} {get_text('fmt_unit_distance', lang)}"  # type: ignore[arg-type]
    if kind is FieldKind.DECIMAL:
        unit_key = "fmt_unit_currency" if key == "cost" else "fmt_unit_volume"
        return f"{fmt_display(float(raw), lang)} {get_text(unit_key, lang)}"  # type: ignore[arg-type]
    if kind is FieldKind.CHOICE:
        return get_text("btn_yes" if raw else "btn_no", lang)
    # TEXT
    return str(raw)


async def _render_step(flow: FlowState, context: CTX, chat_id: int) -> int:
    """Build and send the card for the current step, returning the new card_message_id."""
    card_service: CardService = context.bot_data["card_service"]
    spec = field_at(flow.kind, flow.step_index)
    total = field_count(flow.kind)
    progress: tuple[int, int] | None = (flow.step_index + 1, total) if total > 1 else None
    collected = _build_collected_entries(flow)

    view = CardView(
        kind=flow.kind,
        vehicle_name=flow.vehicle_name,
        collected=collected,
        prompt_key=spec.prompt_key,
        progress=progress,
        reference=flow.reference,
    )
    text = render_card(view, flow.lang)

    suggestion = (
        flow.reference.value
        if flow.reference is not None and spec.key == "odometer"
        else None
    )
    markup = flow_step_keyboard(flow.token, spec, suggestion=suggestion, lang=flow.lang)

    new_id = await card_service.update(chat_id, flow.card_message_id, text, markup)
    flow.card_message_id = new_id

    # Send placeholder via menu keyboard (Req 3.8).
    await context.bot.send_message(
        chat_id,
        "\u200b",
        reply_markup=menu_keyboard(flow.lang, placeholder_key=spec.placeholder_key),
    )
    return new_id


async def _render_summary(flow: FlowState, context: CTX, chat_id: int) -> int:
    """Build and send the summary card, returning the new card_message_id."""
    card_service: CardService = context.bot_data["card_service"]
    entries = _build_all_entries(flow)
    view = SummaryView(kind=flow.kind, vehicle_name=flow.vehicle_name, entries=entries)
    text = render_summary(view, flow.lang)
    markup = summary_keyboard(flow.token, flow.lang)

    new_id = await card_service.update(chat_id, flow.card_message_id, text, markup)
    flow.card_message_id = new_id
    return new_id


# ---------------------------------------------------------------------------
# Stub handlers (to be replaced by tasks 11.4–11.15)
# ---------------------------------------------------------------------------


async def _stub_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Placeholder handler — ends the conversation immediately."""
    return ConversationHandler.END


async def start_from_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry: /fuel, /service, /km — dispatch to the per-kind command handler.

    Each handler either submits inline (returns END) or starts the guided flow (returns COLLECT).
    """
    from bot.handlers.fuel import fuel_command
    from bot.handlers.odometer import km_command
    from bot.handlers.service import service_command

    message = update.effective_message
    if message is None:  # pragma: no cover
        return END

    # Determine FlowKind from the command name.
    command = (message.text or "").lstrip("/").split()[0].split("@")[0].lower()

    if command == "fuel":
        return await fuel_command(update, context)
    elif command == "service":
        return await service_command(update, context)
    elif command == "km":
        return await km_command(update, context)

    return END


async def start_from_menu_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry: Menu_Label tap for a write action."""
    message = update.effective_message
    if message is None or message.text is None:  # pragma: no cover
        return END

    action = resolve_menu_label(message.text)
    if action is None or action not in _ACTION_TO_KIND:  # pragma: no cover
        return END

    kind = _ACTION_TO_KIND[action]
    return await start_flow(update, context, kind=kind)


async def on_log_another(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry: 🔁 Log another callback (Requirements 7.1, 7.2, 7.3)."""
    query = update.callback_query
    if query:
        await query.answer()

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    last = user_data.pop("last_flow_info", None)
    if last is None:
        return END

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    # Strip the inline keyboard from the previous confirmation (Req 7.3).
    card_service: CardService = context.bot_data["card_service"]
    await card_service.strip_markup(chat_id, last["card_message_id"])

    # Start a fresh flow of the same kind, skipping vehicle selection (Req 7.1, 7.2).
    return await start_flow(
        update, context, kind=last["kind"], vehicle_override=last["vehicle_id"]
    )


async def collect_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """COLLECT state: validate typed text, delete it, advance or show error."""
    message = update.effective_message
    if message is None or message.text is None:  # pragma: no cover
        return COLLECT

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    chat_id = message.chat_id
    card_service: CardService = context.bot_data["card_service"]
    spec = field_at(flow.kind, flow.step_index)
    text = message.text.strip()

    # --- Validate ---
    validated: int | float | str | None = None
    try:
        if spec.kind is FieldKind.INT:
            validated = int(text)
            if spec.key == "odometer" and validated <= 0:
                validated = None
        elif spec.kind is FieldKind.DECIMAL:
            normalized = text.replace(",", ".")
            val = float(normalized)
            if spec.key == "cost" and val < 0:
                validated = None
            elif spec.key == "liters" and val <= 0:
                validated = None
            elif val < 0:
                validated = None
            else:
                validated = val
        elif spec.kind is FieldKind.TEXT:
            if text:
                validated = text
        else:
            # CHOICE field should not receive typed text
            validated = None
    except (ValueError, OverflowError):
        validated = None

    # --- Delete user message ---
    await card_service.consume_prompt_reply(message)

    # --- Validation failure → re-render same step with error ---
    if validated is None:
        collected = _build_collected_entries(flow)
        total = field_count(flow.kind)
        progress: tuple[int, int] | None = (
            (flow.step_index + 1, total) if total > 1 else None
        )
        view = CardView(
            kind=flow.kind,
            vehicle_name=flow.vehicle_name,
            collected=collected,
            prompt_key=spec.prompt_key,
            progress=progress,
            reference=flow.reference,
            error_key=spec.error_key,
        )
        card_text = render_card(view, flow.lang)
        suggestion = (
            flow.reference.value
            if flow.reference is not None and spec.key == "odometer"
            else None
        )
        markup = flow_step_keyboard(flow.token, spec, suggestion=suggestion, lang=flow.lang)
        new_id = await card_service.update(chat_id, flow.card_message_id, card_text, markup)
        flow.card_message_id = new_id
        return COLLECT

    # --- Store value ---
    flow.values[spec.key] = validated

    # --- Odometer regression check ---
    if (
        spec.key == "odometer"
        and flow.reference is not None
        and not flow.regression_confirmed
        and int(validated) < flow.reference.value
    ):
        regression_text = render_regression(int(validated), flow.reference, flow.lang)
        markup = regression_keyboard(flow.token, flow.lang)
        new_id = await card_service.update(chat_id, flow.card_message_id, regression_text, markup)
        flow.card_message_id = new_id
        return REGRESSION

    # --- Advance ---
    if flow.editing_field is not None:
        flow.editing_field = None
        await _render_summary(flow, context, chat_id)
        return SUMMARY

    total = field_count(flow.kind)
    if flow.step_index + 1 < total:
        flow.step_index += 1
        await _render_step(flow, context, chat_id)
        return COLLECT

    # Last field → summary
    await _render_summary(flow, context, chat_id)
    return SUMMARY


async def on_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """COLLECT state: inline choice button (e.g. full-tank yes/no)."""
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return COLLECT

    cb = decode(query.data)
    if cb.action is not CallbackAction.CHOICE:
        return COLLECT

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return COLLECT

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    spec = field_at(flow.kind, flow.step_index)

    # Map ordinal to value: for is_fill_to_full, 0=True (yes), 1=False (no)
    if spec.key == "is_fill_to_full":
        value: object = cb.arg == 0
    else:
        value = cb.arg  # generic ordinal for future choice fields

    flow.values[spec.key] = value

    # Advance
    if flow.editing_field is not None:
        flow.editing_field = None
        await _render_summary(flow, context, chat_id)
        return SUMMARY

    total = field_count(flow.kind)
    if flow.step_index + 1 < total:
        flow.step_index += 1
        await _render_step(flow, context, chat_id)
        return COLLECT

    await _render_summary(flow, context, chat_id)
    return SUMMARY


async def on_keep_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """COLLECT state: keep-suggestion button — accept the reference value without retyping."""
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return COLLECT

    cb = decode(query.data)
    if cb.action is not CallbackAction.KEEP:
        return COLLECT

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return COLLECT

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    spec = field_at(flow.kind, flow.step_index)

    # The kept value is the reference odometer
    if flow.reference is None:  # pragma: no cover — should not happen if button was shown
        return COLLECT
    flow.values[spec.key] = flow.reference.value

    # No regression check needed — keeping reference means not lower

    # Advance
    if flow.editing_field is not None:
        flow.editing_field = None
        await _render_summary(flow, context, chat_id)
        return SUMMARY

    total = field_count(flow.kind)
    if flow.step_index + 1 < total:
        flow.step_index += 1
        await _render_step(flow, context, chat_id)
        return COLLECT

    await _render_summary(flow, context, chat_id)
    return SUMMARY


async def on_menu_label_during_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """COLLECT/SUMMARY state: Menu_Label while flow active → abandon prompt (Reqs 11.5, 11.6).

    A menu-label typed while a flow is active does not silently start a new flow. Instead, the
    card transitions to an abandon prompt that asks the user to confirm discarding the values
    collected so far. Confirming starts the requested action; declining returns to the state the
    flow came from.
    """
    message = update.effective_message
    if message is None or message.text is None:  # pragma: no cover
        return COLLECT

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    action = resolve_menu_label(message.text)
    if action is None:
        # Not a recognized menu label — stay in current state.
        return COLLECT

    chat_id = message.chat_id
    card_service: CardService = context.bot_data["card_service"]

    # Store the target action for on_abandon to pick up.
    flow.pending_target = action

    # Render abandon prompt on the card.
    text = render_abandon_prompt(action, flow.lang)
    markup = abandon_keyboard(flow.token, action, flow.lang)
    new_id = await card_service.update(chat_id, flow.card_message_id, text, markup)
    flow.card_message_id = new_id

    # Delete the user's menu-label message (it's a typed answer that shouldn't stay).
    await card_service.consume_prompt_reply(message)

    return ABANDON


async def on_summary_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """SUMMARY state: save, edit or cancel (Requirements 4.6, 4.7, 6.1–6.3, 6.10, 9.1–9.4)."""
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return SUMMARY

    cb = decode(query.data)

    # Only handle SAVE, EDIT, CANCEL here; FIELD is routed to on_field_pick.
    if cb.action not in (CallbackAction.SAVE, CallbackAction.EDIT, CallbackAction.CANCEL):
        return SUMMARY

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return SUMMARY

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    card_service: CardService = context.bot_data["card_service"]

    # --- CANCEL ---
    if cb.action is CallbackAction.CANCEL:
        text = render_cancelled(flow.lang)
        await card_service.finalize(chat_id, flow.card_message_id, text, None)
        clear_flow(context)
        return END

    # --- EDIT → show Field_Picker ---
    if cb.action is CallbackAction.EDIT:
        entries = _build_all_entries(flow)
        markup = field_picker_keyboard(flow.token, entries, flow.lang)
        # Keep the summary text, swap to picker buttons.
        view = SummaryView(kind=flow.kind, vehicle_name=flow.vehicle_name, entries=entries)
        text = render_summary(view, flow.lang)
        new_id = await card_service.update(chat_id, flow.card_message_id, text, markup)
        flow.card_message_id = new_id
        return SUMMARY

    # --- SAVE ---
    submitter: RecordSubmitter = context.bot_data["record_submitter"]

    try:
        outcome = await submitter.submit(
            user_id=update.effective_user.id,  # type: ignore[union-attr]
            vehicle_id=flow.vehicle_id,
            kind=flow.kind,
            values=flow.values,
        )
    except LubeLoggerApiError:
        # Render API-error card, keep summary keyboard so user can retry.
        error_text = get_text("card_api_error", flow.lang)
        markup = summary_keyboard(flow.token, flow.lang)
        new_id = await card_service.update(chat_id, flow.card_message_id, error_text, markup)
        flow.card_message_id = new_id
        return SUMMARY

    # Build ConfirmationView.
    entries = _build_all_entries(flow)
    view = ConfirmationView(
        kind=flow.kind,
        vehicle_name=outcome.vehicle_name or flow.vehicle_name,
        on_date=date.today(),
        entries=entries,
        consumption=outcome.consumption,
    )

    if outcome.status == "saved":
        text = render_confirmation(view, flow.lang)
        markup = confirmation_keyboard(flow.token, queued=False, lang=flow.lang)
    else:
        text = render_queued(view, flow.lang)
        markup = confirmation_keyboard(flow.token, queued=True, lang=flow.lang)

    await card_service.finalize(chat_id, flow.card_message_id, text, markup)

    # Persist info needed by "Log another" before clearing the flow (Req 7.1, 7.2).
    if context.user_data is not None:
        context.user_data["last_flow_info"] = {
            "kind": flow.kind,
            "vehicle_id": flow.vehicle_id,
            "vehicle_name": flow.vehicle_name,
            "card_message_id": flow.card_message_id,
        }

    clear_flow(context)
    return END


async def on_field_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """SUMMARY state: field picker selection — re-prompt chosen field (Requirements 4.8, 4.9)."""
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return SUMMARY

    cb = decode(query.data)
    if cb.action is not CallbackAction.FIELD:
        return SUMMARY

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return SUMMARY

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    # arg = field index in the flow's field table.
    field_idx = cb.arg
    if field_idx is None:  # pragma: no cover
        return SUMMARY

    spec = field_at(flow.kind, field_idx)
    flow.editing_field = spec.key
    flow.step_index = field_idx

    # Re-render that step's card and keyboard.
    await _render_step(flow, context, chat_id)
    return COLLECT


async def on_regression(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """REGRESSION state: confirm, re-enter or cancel (Reqs 5.8, 5.9, 5.10)."""
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return REGRESSION

    cb = decode(query.data)

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return REGRESSION

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    if cb.action is CallbackAction.ODO_CONFIRM:
        # Req 5.9: no further warning for this flow
        flow.regression_confirmed = True
        # Value already stored in flow.values["odometer"] by collect_value

        if flow.editing_field is not None:
            flow.editing_field = None
            await _render_summary(flow, context, chat_id)
            return SUMMARY

        total = field_count(flow.kind)
        if flow.step_index + 1 < total:
            flow.step_index += 1
            await _render_step(flow, context, chat_id)
            return COLLECT

        # Last field → summary
        await _render_summary(flow, context, chat_id)
        return SUMMARY

    if cb.action is CallbackAction.ODO_REENTER:
        # Remove the optimistically stored value
        flow.values.pop("odometer", None)
        # Re-render the current step (step_index stays)
        await _render_step(flow, context, chat_id)
        return COLLECT

    if cb.action is CallbackAction.CANCEL:
        # Inline cancel from regression keyboard
        card_service: CardService = context.bot_data["card_service"]
        text = render_cancelled(flow.lang)
        await card_service.finalize(chat_id, flow.card_message_id, text, None)
        clear_flow(context)
        return END

    # Unknown action — stay in REGRESSION
    return REGRESSION


async def on_abandon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ABANDON state: yes discards and starts requested action, no returns (Reqs 11.5, 11.6).

    ABANDON_YES: discard values, finalize card with cancellation text, start the requested action
    if it's a write action, or END if it's LATEST/OPTIONS (those are handled outside this handler).
    ABANDON_NO: restore card to the state before the abandon prompt was shown.
    CANCEL: same as the normal cancel — finalize with cancelled text, clear flow.
    """
    query = update.callback_query
    if query is None or query.data is None:  # pragma: no cover
        return ABANDON

    cb = decode(query.data)

    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")
    if flow is None:  # pragma: no cover
        return END

    if not await guard(update, context, cb):
        return ABANDON

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:  # pragma: no cover
        return END

    card_service: CardService = context.bot_data["card_service"]

    # --- ABANDON_YES: discard and start requested action ---
    if cb.action is CallbackAction.ABANDON_YES:
        # Resolve target from callback arg (MenuAction ordinal).
        target: MenuAction | None = flow.pending_target
        if cb.arg is not None:
            try:
                target = menu_action_at(cb.arg)
            except IndexError:
                pass

        # Finalize current card with cancellation text.
        text = render_cancelled(flow.lang)
        await card_service.finalize(chat_id, flow.card_message_id, text, None)

        # Discard flow state.
        clear_flow(context)

        # Start the requested action if it's a write action.
        if target is not None and target in _ACTION_TO_KIND:
            return await start_flow(update, context, kind=_ACTION_TO_KIND[target])

        # LATEST or OPTIONS → END (those handlers pick it up from the keyboard).
        return END

    # --- ABANDON_NO: return to previous state ---
    if cb.action is CallbackAction.ABANDON_NO:
        flow.pending_target = None
        total = field_count(flow.kind)

        # Heuristic: if all fields collected → we were in SUMMARY, else COLLECT.
        if len(flow.values) >= total:
            await _render_summary(flow, context, chat_id)
            return SUMMARY
        else:
            await _render_step(flow, context, chat_id)
            return COLLECT

    # --- CANCEL: same as normal cancel ---
    if cb.action is CallbackAction.CANCEL:
        text = render_cancelled(flow.lang)
        await card_service.finalize(chat_id, flow.card_message_id, text, None)
        clear_flow(context)
        return END

    # Unknown action — stay in ABANDON.
    return ABANDON


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel button or /cancel command (Reqs 4.4, 4.12)."""
    user_data: dict[str, Any] = context.user_data if context.user_data is not None else {}
    flow: FlowState | None = user_data.get("flow")

    if flow is not None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is not None:
            card_service: CardService = context.bot_data["card_service"]
            text = render_cancelled(flow.lang)
            await card_service.finalize(chat_id, flow.card_message_id, text, None)

    clear_flow(context)
    return END


async def fallback_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback: ignore unrecognized commands without ending the flow (stub)."""
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler factory
# ---------------------------------------------------------------------------


def get_record_conversation_handler(
    auth_filter: Any | None = None,  # noqa: ANN401
) -> ConversationHandler:  # type: ignore[type-arg]
    """Build the unified record ConversationHandler.

    Parameters
    ----------
    auth_filter:
        Optional filter object with a ``check_user(user_id: int) -> bool`` method.
        When provided, ``guard`` rejects unauthorized users.

    Returns
    -------
    ConversationHandler with ``allow_reentry=True``, entry points for the three commands,
    the write Menu_Labels and the Log-another callback.
    """
    menu_label_filter = MenuLabelFilter()

    # Pattern matching LOG_ANOTHER callback action prefix.
    log_another_pattern = f"^{CallbackAction.LOG_ANOTHER.value}:"

    entry_points = [
        CommandHandler(["fuel", "service", "km"], start_from_command),
        MessageHandler(menu_label_filter, start_from_menu_label),
        CallbackQueryHandler(on_log_another, pattern=log_another_pattern),
    ]

    states = {
        COLLECT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~menu_label_filter, collect_value),
            CallbackQueryHandler(on_choice),
            CallbackQueryHandler(on_keep_suggestion),
            MessageHandler(menu_label_filter, on_menu_label_during_flow),
        ],
        SUMMARY: [
            CallbackQueryHandler(on_summary_action),
            CallbackQueryHandler(on_field_pick),
            MessageHandler(menu_label_filter, on_menu_label_during_flow),
        ],
        REGRESSION: [
            CallbackQueryHandler(on_regression),
        ],
        ABANDON: [
            CallbackQueryHandler(on_abandon),
        ],
    }

    fallbacks = [
        CommandHandler("cancel", cancel),
        MessageHandler(filters.COMMAND, fallback_ignore),
    ]

    return ConversationHandler(
        entry_points=entry_points,
        states=states,
        fallbacks=fallbacks,
        allow_reentry=True,
    )
