"""Unit tests for the record_flow skeleton: guard, clear_flow, MenuLabelFilter."""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from telegram.ext import ConversationHandler

from bot.callbacks import NO_TOKEN, Callback, CallbackAction, encode, new_token
from bot.exceptions import LubeLoggerUnreachableError
from bot.flows.definitions import FlowKind, MenuAction
from bot.handlers.record_flow import (
    ABANDON,
    COLLECT,
    REGRESSION,
    SUMMARY,
    FlowState,
    MenuLabelFilter,
    clear_flow,
    collect_value,
    get_record_conversation_handler,
    guard,
    start_flow,
)
from bot.models.records import VehicleSnapshot
from bot.models.responses import Vehicle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(flow: FlowState | None = None, lang: str = "en") -> MagicMock:
    """Build a minimal ContextTypes.DEFAULT_TYPE stand-in."""
    ctx = MagicMock()
    user_data: dict[str, object] = {"lang": lang}
    if flow is not None:
        user_data["flow"] = flow
    ctx.user_data = user_data
    return ctx


def _make_update(
    *,
    user_id: int = 42,
    callback_query_id: str = "cq-1",
) -> MagicMock:
    """Build a minimal Update with a callback_query."""
    update = MagicMock()
    query = AsyncMock()
    query.answer = AsyncMock()
    query.id = callback_query_id
    update.callback_query = query
    user = MagicMock()
    user.id = user_id
    update.effective_user = user
    return update


def _make_auth_filter(allowed_ids: set[int]) -> MagicMock:
    """Build a filter object with check_user(user_id) -> bool."""
    af = MagicMock()
    af.check_user = MagicMock(side_effect=lambda uid: uid in allowed_ids)
    return af


# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------


def test_state_constants_are_sequential() -> None:
    assert (COLLECT, SUMMARY, REGRESSION, ABANDON) == (0, 1, 2, 3)


# ---------------------------------------------------------------------------
# clear_flow
# ---------------------------------------------------------------------------


def test_clear_flow_removes_flow_key() -> None:
    ctx = _make_context(flow=FlowState(kind=FlowKind.FUEL, token="abc", vehicle_id=1,
                                        vehicle_name="Panda"))
    assert "flow" in ctx.user_data
    clear_flow(ctx)
    assert "flow" not in ctx.user_data


def test_clear_flow_noop_when_no_flow() -> None:
    ctx = _make_context(flow=None)
    clear_flow(ctx)  # should not raise
    assert "flow" not in ctx.user_data


def test_clear_flow_handles_none_user_data() -> None:
    ctx = MagicMock()
    ctx.user_data = None
    clear_flow(ctx)  # should not raise


# ---------------------------------------------------------------------------
# guard — always answers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_always_answers_callback_query() -> None:
    token = new_token()
    flow = FlowState(kind=FlowKind.FUEL, token=token, vehicle_id=1, vehicle_name="X")
    ctx = _make_context(flow=flow)
    update = _make_update()
    cb = Callback(action=CallbackAction.CANCEL, token=token)

    result = await guard(update, ctx, cb)

    assert result is True
    update.callback_query.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# guard — auth rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_rejects_unauthorized_user() -> None:
    token = new_token()
    flow = FlowState(kind=FlowKind.FUEL, token=token, vehicle_id=1, vehicle_name="X")
    ctx = _make_context(flow=flow)
    update = _make_update(user_id=99)
    auth = _make_auth_filter(allowed_ids={42})
    cb = Callback(action=CallbackAction.CANCEL, token=token)

    result = await guard(update, ctx, cb, auth_filter=auth)

    assert result is False
    # Second answer call is the alert.
    assert update.callback_query.answer.await_count == 2
    alert_call = update.callback_query.answer.await_args_list[1]
    assert alert_call.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_guard_passes_authorized_user() -> None:
    token = new_token()
    flow = FlowState(kind=FlowKind.FUEL, token=token, vehicle_id=1, vehicle_name="X")
    ctx = _make_context(flow=flow)
    update = _make_update(user_id=42)
    auth = _make_auth_filter(allowed_ids={42})
    cb = Callback(action=CallbackAction.CANCEL, token=token)

    result = await guard(update, ctx, cb, auth_filter=auth)

    assert result is True


# ---------------------------------------------------------------------------
# guard — token mismatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_rejects_mismatched_token() -> None:
    flow_token = new_token()
    stale_token = new_token()
    flow = FlowState(kind=FlowKind.FUEL, token=flow_token, vehicle_id=1, vehicle_name="X")
    ctx = _make_context(flow=flow)
    update = _make_update()
    cb = Callback(action=CallbackAction.CANCEL, token=stale_token)

    result = await guard(update, ctx, cb)

    assert result is False
    assert update.callback_query.answer.await_count == 2


@pytest.mark.asyncio
async def test_guard_rejects_in_flow_token_when_no_flow_active() -> None:
    ctx = _make_context(flow=None)
    update = _make_update()
    cb = Callback(action=CallbackAction.CANCEL, token="some_token")

    result = await guard(update, ctx, cb)

    assert result is False


@pytest.mark.asyncio
async def test_guard_passes_no_token_callback_without_flow() -> None:
    """A non-flow callback (NO_TOKEN) should pass even without an active flow."""
    ctx = _make_context(flow=None)
    update = _make_update()
    cb = Callback(action=CallbackAction.LATEST_OPEN, token=NO_TOKEN)

    result = await guard(update, ctx, cb)

    assert result is True


# ---------------------------------------------------------------------------
# MenuLabelFilter
# ---------------------------------------------------------------------------


def test_menu_label_filter_matches_fuel_label() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "⛽ Fuel"
    assert f.filter(msg) is True


def test_menu_label_filter_matches_service_label() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "🔧 Service"
    assert f.filter(msg) is True


def test_menu_label_filter_matches_odometer_label() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "🚧 Odometer"
    assert f.filter(msg) is True


def test_menu_label_filter_rejects_latest() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "📊 Latest"
    assert f.filter(msg) is False


def test_menu_label_filter_rejects_options() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "⚙️ Options"
    assert f.filter(msg) is False


def test_menu_label_filter_rejects_random_text() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = "hello world"
    assert f.filter(msg) is False


def test_menu_label_filter_rejects_none_text() -> None:
    f = MenuLabelFilter()
    msg = MagicMock()
    msg.text = None
    assert f.filter(msg) is False


# ---------------------------------------------------------------------------
# ConversationHandler factory
# ---------------------------------------------------------------------------


def test_get_record_conversation_handler_returns_handler() -> None:
    handler = get_record_conversation_handler()
    assert isinstance(handler, ConversationHandler)


def test_handler_allow_reentry() -> None:
    handler = get_record_conversation_handler()
    assert handler.allow_reentry is True


# ---------------------------------------------------------------------------
# FlowState dataclass
# ---------------------------------------------------------------------------


def test_flow_state_defaults() -> None:
    fs = FlowState(kind=FlowKind.SERVICE, token="t", vehicle_id=5, vehicle_name="V")
    assert fs.step_index == 0
    assert fs.values == {}
    assert fs.card_message_id == 0
    assert fs.reference is None
    assert fs.regression_confirmed is False
    assert fs.editing_field is None
    assert fs.pending_target is None
    assert fs.lang == "en"


def test_flow_state_is_mutable() -> None:
    fs = FlowState(kind=FlowKind.ODOMETER, token="t", vehicle_id=1, vehicle_name="X")
    fs.step_index = 3
    fs.values["odometer"] = 45000
    assert fs.step_index == 3
    assert fs.values["odometer"] == 45000


# ---------------------------------------------------------------------------
# Property 5: The callback guard answers once and rejects safely
# Feature: improve-ux, Property 5: The callback guard answers once and rejects safely
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p5_) ---

_p5_actions = st.sampled_from(list(CallbackAction))
_p5_tokens = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=8,
)
_p5_flow_kinds = st.sampled_from(list(FlowKind))
_p5_vehicle_ids = st.integers(min_value=1, max_value=9999)
_p5_user_ids = st.integers(min_value=1, max_value=9999)


@st.composite
def _p5_scenario(draw: st.DrawFn) -> dict:
    """Generate a full guard scenario: callback, flow state, auth filter configuration."""
    action = draw(_p5_actions)

    # Decide whether the callback is in-flow or not.
    cb_in_flow = draw(st.booleans())
    if cb_in_flow:
        cb_token = draw(_p5_tokens)
    else:
        cb_token = NO_TOKEN

    cb = Callback(action=action, token=cb_token)

    # Flow state: present or absent.
    flow_present = draw(st.booleans())
    if flow_present:
        flow_token = draw(_p5_tokens)
        flow = FlowState(
            kind=draw(_p5_flow_kinds),
            token=flow_token,
            vehicle_id=draw(_p5_vehicle_ids),
            vehicle_name="V",
        )
    else:
        flow = None
        flow_token = None

    # Auth filter: present or absent; if present, user allowed or denied.
    user_id = draw(_p5_user_ids)
    has_auth = draw(st.booleans())
    if has_auth:
        user_allowed = draw(st.booleans())
    else:
        user_allowed = None  # no filter → always passes

    return {
        "cb": cb,
        "flow": flow,
        "flow_token": flow_token,
        "user_id": user_id,
        "has_auth": has_auth,
        "user_allowed": user_allowed,
    }


@settings(max_examples=100)
@given(scenario=_p5_scenario())
def test_property_callback_guard(scenario: dict) -> None:
    """Property 5: The callback guard answers once and rejects safely.

    **Validates: Requirements 11.2, 11.4, 11.8**
    """
    cb: Callback = scenario["cb"]
    flow: FlowState | None = scenario["flow"]
    user_id: int = scenario["user_id"]
    has_auth: bool = scenario["has_auth"]
    user_allowed: bool | None = scenario["user_allowed"]

    # Build mocks (same pattern as existing unit tests).
    ctx = MagicMock()
    user_data: dict[str, object] = {"lang": "en"}
    if flow is not None:
        user_data["flow"] = flow
    ctx.user_data = user_data

    update = MagicMock()
    query = AsyncMock()
    query.answer = AsyncMock()
    query.id = "cq-prop"
    update.callback_query = query
    user_mock = MagicMock()
    user_mock.id = user_id
    update.effective_user = user_mock

    # Build auth filter if applicable.
    if has_auth:
        auth_filter = MagicMock()
        if user_allowed:
            auth_filter.check_user = MagicMock(side_effect=lambda uid: True)
        else:
            auth_filter.check_user = MagicMock(side_effect=lambda uid: False)
    else:
        auth_filter = None

    # Run guard.
    result = asyncio.run(guard(update, ctx, cb, auth_filter=auth_filter))

    # --- Assertions ---

    # Req 11.4: query.answer() is always called at least once.
    assert query.answer.await_count >= 1, "guard must always answer the callback query"

    # Determine expected outcome.
    # Auth rejection takes priority (checked first after initial answer).
    auth_rejected = has_auth and not user_allowed

    # Token mismatch: cb is in-flow AND (no flow active OR tokens differ).
    if cb.in_flow:
        token_mismatch = flow is None or flow.token != cb.token
    else:
        token_mismatch = False

    should_reject = auth_rejected or token_mismatch

    if should_reject:
        # Req 11.2 / 11.8: returns False.
        assert result is False, (
            f"guard should reject: auth_rejected={auth_rejected}, "
            f"token_mismatch={token_mismatch}"
        )
        # Second answer call has show_alert=True.
        assert query.answer.await_count == 2, "rejection must call answer exactly twice"
        alert_call = query.answer.await_args_list[1]
        assert alert_call.kwargs.get("show_alert") is True, (
            "rejection alert must have show_alert=True"
        )
    else:
        # Acceptance: returns True, no alert.
        assert result is True, "guard should accept when auth passes and token matches"
        # Only the initial answer was called (no alert).
        assert query.answer.await_count == 1, "acceptance must call answer exactly once"


# ---------------------------------------------------------------------------
# Property 19: An invalid typed value never ends the flow
# Feature: improve-ux, Property 19: An invalid typed value never ends the flow
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p19_) ---

_p19_flow_kinds = st.sampled_from(list(FlowKind))


@st.composite
def _p19_invalid_input(draw: st.DrawFn) -> dict:
    """Generate a flow kind, a step index for a non-CHOICE field, and an invalid value.

    Invalid values per FieldKind:
    - INT (odometer): empty, non-numeric, zero, negative
    - DECIMAL (liters): empty, non-numeric, zero for liters, negative for liters
    - DECIMAL (cost): non-numeric, negative
    - TEXT (description): empty string
    """
    from bot.flows.definitions import FIELDS, FieldKind, field_at

    kind = draw(_p19_flow_kinds)
    fields = FIELDS[kind]

    # Only pick non-CHOICE fields (typed input validation applies to INT, DECIMAL, TEXT)
    eligible_indices = [
        i for i, spec in enumerate(fields) if spec.kind != FieldKind.CHOICE
    ]
    step_index = draw(st.sampled_from(eligible_indices))
    spec = field_at(kind, step_index)

    # Generate an invalid value based on the field kind and key
    if spec.kind == FieldKind.INT:
        # odometer: must be positive integer → invalid = empty, non-numeric, 0, negative
        invalid = draw(
            st.sampled_from([
                "",              # empty
                "abc",           # non-numeric
                "12.5",          # float for INT
                "0",             # zero (odometer must be > 0)
                "-1",            # negative
                "-100",          # large negative
                "not a number",  # text
            ])
        )
    elif spec.kind == FieldKind.DECIMAL:
        if spec.key == "liters":
            # liters must be > 0 → invalid = empty, non-numeric, 0, negative
            invalid = draw(
                st.sampled_from([
                    "",           # empty
                    "abc",        # non-numeric
                    "0",          # zero liters
                    "0.0",        # zero liters (float)
                    "-5",         # negative
                    "-2.5",       # negative decimal
                    "not num",    # text
                ])
            )
        elif spec.key == "cost":
            # cost must be >= 0 → invalid = empty, non-numeric, negative
            invalid = draw(
                st.sampled_from([
                    "",           # empty
                    "abc",        # non-numeric
                    "-1",         # negative
                    "-0.01",      # slightly negative
                    "xyz 123",    # mixed
                ])
            )
        else:
            # generic DECIMAL: must be >= 0
            invalid = draw(
                st.sampled_from([
                    "",
                    "abc",
                    "-5",
                    "not-a-number",
                ])
            )
    elif spec.kind == FieldKind.TEXT:
        # description: must be non-empty → invalid = empty (after strip)
        invalid = draw(
            st.sampled_from([
                "",       # empty
                "   ",    # whitespace only (strips to empty)
                "\t",     # tab only
                "\n",     # newline only
            ])
        )
    else:
        invalid = ""  # pragma: no cover

    return {
        "kind": kind,
        "step_index": step_index,
        "spec": spec,
        "invalid_text": invalid,
    }


@settings(max_examples=100)
@given(data=_p19_invalid_input())
def test_property_invalid_value_reprompts(data: dict) -> None:
    """Property 19: An invalid typed value never ends the flow.

    # Feature: improve-ux, Property 19: An invalid typed value never ends the flow

    **Validates: Requirements 4.11, 13.1**

    For any flow kind and any step, typing an invalid value results in collect_value
    returning COLLECT (not END or SUMMARY), the card being updated with an error_key
    matching the field's error_key, and the flow state remaining intact.
    """
    from bot.handlers.record_flow import collect_value
    from bot.i18n import get_text

    kind: FlowKind = data["kind"]
    step_index: int = data["step_index"]
    spec = data["spec"]
    invalid_text: str = data["invalid_text"]

    # --- Build FlowState at the given step ---
    token = new_token()
    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=1,
        vehicle_name="TestCar",
        step_index=step_index,
        lang="en",
    )
    # Pre-populate earlier steps (to ensure they stay untouched)
    pre_values: dict[str, object] = {}
    from bot.flows.definitions import field_at as _fa

    for i in range(step_index):
        prev_spec = _fa(kind, i)
        pre_values[prev_spec.key] = 999  # dummy collected value
    flow.values = dict(pre_values)

    original_step_index = flow.step_index
    original_values = dict(flow.values)

    # --- Build mocked Update ---
    update = MagicMock()
    message = MagicMock()
    message.text = invalid_text
    message.chat_id = 12345
    update.effective_message = message

    # --- Build mocked context ---
    ctx = MagicMock()
    user_data: dict[str, object] = {"flow": flow}
    ctx.user_data = user_data

    # --- Build mocked bot_data with card_service ---
    card_service = MagicMock()
    # update returns a new message id (simulates card update)
    card_service.update = AsyncMock(return_value=100)
    card_service.consume_prompt_reply = AsyncMock()

    ctx.bot_data = {"card_service": card_service}

    # --- Call collect_value ---
    result = asyncio.run(collect_value(update, ctx))

    # --- Assertions ---

    # 1. Return value is COLLECT (not END or SUMMARY)
    assert result == COLLECT, (
        f"Expected COLLECT ({COLLECT}), got {result}. "
        f"kind={kind}, step={step_index}, text={invalid_text!r}"
    )

    # 2. card_service.update was called with text containing the error key's localized text
    error_text = get_text(spec.error_key, "en")
    card_service.update.assert_awaited_once()
    call_args = card_service.update.await_args
    card_text_arg = call_args[0][2] if len(call_args[0]) > 2 else call_args.kwargs.get("text", "")
    # The rendered card should contain the error message
    assert error_text in card_text_arg, (
        f"Card text should contain error '{error_text}', got: {card_text_arg[:200]}"
    )

    # 3. card_service.consume_prompt_reply was called (deletes user message)
    card_service.consume_prompt_reply.assert_awaited_once_with(message)

    # 4. flow.step_index unchanged
    assert flow.step_index == original_step_index, (
        f"step_index changed from {original_step_index} to {flow.step_index}"
    )

    # 5. flow.values does not gain the invalid field's key
    assert spec.key not in flow.values or flow.values[spec.key] == original_values.get(spec.key), (
        f"flow.values gained key {spec.key!r} with value {flow.values.get(spec.key)!r}"
    )
    # Original values preserved
    for k, v in original_values.items():
        assert flow.values[k] == v, f"Pre-existing value for {k!r} changed"


# ---------------------------------------------------------------------------
# Property 21: An odometer regression warns and gates, but never rejects
# Feature: improve-ux, Property 21: An odometer regression warns and gates, but never rejects
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p21_) ---

_p21_references = st.integers(min_value=1, max_value=3_000_000)
_p21_entered_values = st.integers(min_value=1, max_value=3_000_000)
_p21_regression_confirmed = st.booleans()
_p21_flow_kinds = st.sampled_from([FlowKind.FUEL, FlowKind.SERVICE, FlowKind.ODOMETER])


def _p21_make_flow(
    *,
    kind: FlowKind,
    token: str,
    reference_value: int,
    regression_confirmed: bool,
) -> FlowState:
    """Build a FlowState at the odometer step with a known reference."""
    from bot.services.odometer_tracker import OdometerReference

    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=1,
        vehicle_name="TestCar",
        reference=OdometerReference(value=reference_value, on_date=None, source="bot"),
        regression_confirmed=regression_confirmed,
    )
    # step_index 0 is always odometer for all flow kinds.
    flow.step_index = 0
    return flow


def _p21_build_collect_mocks(
    flow: FlowState,
    entered_text: str,
) -> tuple[MagicMock, MagicMock]:
    """Build minimal Update/Context mocks for collect_value."""
    ctx = MagicMock()
    user_data: dict[str, object] = {"flow": flow}
    ctx.user_data = user_data

    # bot_data services — mock card_service.
    card_service = AsyncMock()
    card_service.consume_prompt_reply = AsyncMock()
    card_service.update = AsyncMock(return_value=flow.card_message_id)
    ctx.bot_data = {"card_service": card_service}
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()

    update = MagicMock()
    message = MagicMock()
    message.text = entered_text
    message.chat_id = 123
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123

    return update, ctx


def _p21_build_regression_mocks(
    flow: FlowState,
    action: CallbackAction,
) -> tuple[MagicMock, MagicMock]:
    """Build minimal Update/Context mocks for on_regression."""
    from bot.callbacks import encode

    ctx = MagicMock()
    user_data: dict[str, object] = {"flow": flow}
    ctx.user_data = user_data

    card_service = AsyncMock()
    card_service.update = AsyncMock(return_value=flow.card_message_id)
    card_service.finalize = AsyncMock()
    ctx.bot_data = {"card_service": card_service}
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()

    update = MagicMock()
    query = AsyncMock()
    query.answer = AsyncMock()
    query.data = encode(action, flow.token)
    update.callback_query = query
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123

    return update, ctx


@settings(max_examples=100)
@given(
    reference_value=_p21_references,
    entered_value=_p21_entered_values,
    regression_confirmed=_p21_regression_confirmed,
    kind=_p21_flow_kinds,
)
def test_property_odometer_regression_gate(
    reference_value: int,
    entered_value: int,
    regression_confirmed: bool,
    kind: FlowKind,
) -> None:
    """Property 21: An odometer regression warns and gates, but never rejects.

    # Feature: improve-ux, Property 21: An odometer regression warns and gates, but never rejects

    For any odometer value strictly less than the reference, `collect_value` returns REGRESSION;
    after confirming (`on_regression` with ODO_CONFIRM), the value is kept in
    `flow.values["odometer"]` and `regression_confirmed` is True; after re-entering
    (`on_regression` with ODO_REENTER), the value is removed and the flow returns to COLLECT at
    the same step. A value >= reference or with `regression_confirmed=True` never enters REGRESSION.

    **Validates: Requirements 5.8, 5.9, 5.10**
    """
    from bot.handlers.record_flow import COLLECT, REGRESSION, SUMMARY, collect_value, on_regression

    token = new_token()
    flow = _p21_make_flow(
        kind=kind,
        token=token,
        reference_value=reference_value,
        regression_confirmed=regression_confirmed,
    )

    entered_text = str(entered_value)
    update, ctx = _p21_build_collect_mocks(flow, entered_text)

    # --- Call collect_value ---
    result = asyncio.run(collect_value(update, ctx))

    is_regression_case = (
        entered_value < reference_value and not regression_confirmed
    )

    if is_regression_case:
        # Req 5.8: entered < reference → REGRESSION state.
        assert result == REGRESSION, (
            f"Expected REGRESSION for entered={entered_value} < ref={reference_value}, "
            f"got state {result}"
        )
        # The value is optimistically stored for confirm path.
        assert flow.values.get("odometer") == entered_value

        # --- Test ODO_CONFIRM path (Req 5.9) ---
        confirm_flow = _p21_make_flow(
            kind=kind,
            token=token,
            reference_value=reference_value,
            regression_confirmed=False,
        )
        confirm_flow.values["odometer"] = entered_value
        update_confirm, ctx_confirm = _p21_build_regression_mocks(
            confirm_flow, CallbackAction.ODO_CONFIRM
        )

        confirm_result = asyncio.run(on_regression(update_confirm, ctx_confirm))

        # After confirming: regression_confirmed is True, value kept.
        assert confirm_flow.regression_confirmed is True, (
            "ODO_CONFIRM must set regression_confirmed=True"
        )
        assert confirm_flow.values.get("odometer") == entered_value, (
            "ODO_CONFIRM must keep the entered value"
        )
        # Returns COLLECT (advancing to next step) or SUMMARY (if last/editing).
        assert confirm_result in (COLLECT, SUMMARY), (
            f"After ODO_CONFIRM, expected COLLECT or SUMMARY, got {confirm_result}"
        )

        # --- Test ODO_REENTER path (Req 5.10: never rejects; value removed, back to COLLECT) ---
        reenter_flow = _p21_make_flow(
            kind=kind,
            token=token,
            reference_value=reference_value,
            regression_confirmed=False,
        )
        reenter_flow.values["odometer"] = entered_value
        update_reenter, ctx_reenter = _p21_build_regression_mocks(
            reenter_flow, CallbackAction.ODO_REENTER
        )

        reenter_result = asyncio.run(on_regression(update_reenter, ctx_reenter))

        # After re-entering: value removed, returns COLLECT at same step.
        assert reenter_result == COLLECT, (
            f"ODO_REENTER must return COLLECT, got {reenter_result}"
        )
        assert "odometer" not in reenter_flow.values, (
            "ODO_REENTER must remove the odometer value"
        )
        assert reenter_flow.step_index == 0, (
            "ODO_REENTER must stay at the same step_index"
        )

    else:
        # Req 5.10: value >= reference OR regression_confirmed → never enters REGRESSION.
        assert result != REGRESSION, (
            f"Expected no regression for entered={entered_value}, ref={reference_value}, "
            f"confirmed={regression_confirmed}, but got REGRESSION"
        )
        # Value was accepted and stored.
        assert flow.values.get("odometer") == entered_value, (
            "Value >= reference (or confirmed) must be stored"
        )


# ---------------------------------------------------------------------------
# Property 35: Message content is never logged
# Feature: improve-ux, Property 35: Message content is never logged
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p35_) ---

_p35_sensitive_fragments = st.sampled_from([
    "<script>alert(1)</script>",
    "user@example.com",
    "+39 333 1234567",
    "€1.500,00",
    "🔑 secret-key-abc",
    "油 change <5000km",
    "Mario Rossi",
    'desc "quoted"',
])

_p35_text = st.builds(
    lambda marker, fragment: f"{marker}-{fragment}",
    marker=st.from_regex(r"[A-F0-9]{8}", fullmatch=True),
    fragment=_p35_sensitive_fragments,
)


def _p35_make_flow_context(
    text: str,
    *,
    flow_kind: FlowKind = FlowKind.SERVICE,
    step_index: int = 1,
) -> tuple[MagicMock, MagicMock, str]:
    """Build update+context for collect_value with a text step and return the unique marker."""
    token = new_token()
    flow = FlowState(
        kind=flow_kind,
        token=token,
        vehicle_id=1,
        vehicle_name="TestVehicle",
        step_index=step_index,
        lang="en",
    )

    ctx = MagicMock()
    ctx.user_data = {"flow": flow, "lang": "en"}

    # card_service mock
    card_service = AsyncMock()
    card_service.consume_prompt_reply = AsyncMock()
    card_service.update = AsyncMock(return_value=100)

    ctx.bot_data = {
        "card_service": card_service,
        "config_store": AsyncMock(),
        "lubelogger_client": AsyncMock(),
        "tracker": AsyncMock(),
        "record_submitter": AsyncMock(),
    }
    ctx.bot = AsyncMock()

    update = MagicMock()
    message = MagicMock()
    message.text = text
    message.chat_id = 123
    message.message_id = 456
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123
    update.effective_user = MagicMock()
    update.effective_user.id = 42

    # Extract unique marker (first 8 chars before the dash)
    marker = text.split("-", 1)[0]
    return update, ctx, marker


@settings(max_examples=100)
@given(text=_p35_text)
def test_property_no_message_content_logged(text: str) -> None:
    """Property 35: Message content is never logged.

    # Feature: improve-ux, Property 35: Message content is never logged

    **Validates: Requirements NF-4.1**

    For any text a user types as a prompt reply (including sensitive data like vehicle names,
    service descriptions, amounts), after collect_value processes it, that text never appears in
    any log record emitted by the bot logger tree.
    """
    update, ctx, marker = _p35_make_flow_context(text, flow_kind=FlowKind.SERVICE, step_index=1)

    bot_logger = logging.getLogger("bot")
    handler = logging.handlers.MemoryHandler(capacity=1000, target=None)
    handler.setLevel(logging.DEBUG)
    bot_logger.addHandler(handler)
    old_level = bot_logger.level
    bot_logger.setLevel(logging.DEBUG)
    try:
        asyncio.run(collect_value(update, ctx))

        # Collect all logged messages.
        log_output = " ".join(
            handler.format(record) for record in handler.buffer
        )
    finally:
        bot_logger.removeHandler(handler)
        bot_logger.setLevel(old_level)
        handler.close()

    # The unique marker must NOT appear anywhere in captured log output.
    assert marker not in log_output, (
        f"Sensitive content marker '{marker}' leaked into log output: {log_output}"
    )
    # Full text must not appear either.
    assert text not in log_output, (
        f"Full message content leaked into log output: {log_output}"
    )


# ---------------------------------------------------------------------------
# Property 20: Cancelling clears the flow, whichever way it is cancelled
# Feature: improve-ux, Property 20: Cancelling clears the flow, whichever way it is cancelled
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p20_) ---

_p20_flow_kinds = st.sampled_from(list(FlowKind))
_p20_tokens = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=8,
)
_p20_step_indices = st.integers(min_value=0, max_value=3)
_p20_vehicle_ids = st.integers(min_value=1, max_value=9999)
_p20_langs = st.sampled_from(["en", "it"])

_p20_cancel_paths = st.sampled_from([
    "command",       # /cancel handler
    "summary",      # inline cancel from SUMMARY (on_summary_action)
    "regression",   # inline cancel from REGRESSION (on_regression)
    "abandon",      # inline cancel from ABANDON (on_abandon)
])


@st.composite
def _p20_values(draw: st.DrawFn) -> dict[str, object]:
    """Draw a partial set of collected values for a flow."""
    values: dict[str, object] = {}
    if draw(st.booleans()):
        values["odometer"] = draw(st.integers(min_value=1, max_value=999999))
    if draw(st.booleans()):
        values["liters"] = draw(st.floats(min_value=0.1, max_value=200.0, allow_nan=False))
    if draw(st.booleans()):
        values["cost"] = draw(st.floats(min_value=0.0, max_value=500.0, allow_nan=False))
    if draw(st.booleans()):
        values["is_fill_to_full"] = draw(st.booleans())
    if draw(st.booleans()):
        values["description"] = draw(st.text(min_size=1, max_size=30))
    return values


@st.composite
def _p20_scenario(draw: st.DrawFn) -> dict:
    """Generate a full cancellation scenario."""
    kind = draw(_p20_flow_kinds)
    token = draw(_p20_tokens)
    step_index = draw(_p20_step_indices)
    vehicle_id = draw(_p20_vehicle_ids)
    lang = draw(_p20_langs)
    regression_confirmed = draw(st.booleans())
    editing_field = draw(st.one_of(st.none(), st.sampled_from(["odometer", "liters", "cost"])))
    values = draw(_p20_values())
    cancel_path = draw(_p20_cancel_paths)

    return {
        "kind": kind,
        "token": token,
        "step_index": step_index,
        "vehicle_id": vehicle_id,
        "lang": lang,
        "regression_confirmed": regression_confirmed,
        "editing_field": editing_field,
        "values": values,
        "cancel_path": cancel_path,
    }


@settings(max_examples=100)
@given(scenario=_p20_scenario())
def test_property_cancel_equivalence(scenario: dict) -> None:
    """Property 20: Cancelling clears the flow, whichever way it is cancelled.

    # Feature: improve-ux, Property 20: Cancelling clears the flow, whichever way it is cancelled

    **Validates: Requirements 4.4, 4.12, 13.2**
    """
    from bot.formatters import render_cancelled
    from bot.handlers.record_flow import cancel, on_abandon, on_regression, on_summary_action

    kind: FlowKind = scenario["kind"]
    token: str = scenario["token"]
    step_index: int = scenario["step_index"]
    vehicle_id: int = scenario["vehicle_id"]
    lang: str = scenario["lang"]
    regression_confirmed: bool = scenario["regression_confirmed"]
    editing_field: str | None = scenario["editing_field"]
    values: dict[str, object] = scenario["values"]
    cancel_path: str = scenario["cancel_path"]

    # Build FlowState with the random values.
    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=vehicle_id,
        vehicle_name="TestCar",
        step_index=step_index,
        values=dict(values),  # copy so mutations don't leak
        card_message_id=12345,
        regression_confirmed=regression_confirmed,
        editing_field=editing_field,
        lang=lang,
    )

    # Build context with flow state.
    ctx = MagicMock()
    user_data: dict[str, object] = {"lang": lang, "flow": flow}
    ctx.user_data = user_data
    ctx.bot_data = {}

    # Build card_service mock.
    card_service = AsyncMock()
    card_service.finalize = AsyncMock()
    ctx.bot_data["card_service"] = card_service

    # Build update mock.
    chat_id = 99
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.id = 42

    # For callback-based paths, set up the callback query.
    query = AsyncMock()
    query.answer = AsyncMock()
    query.data = encode(CallbackAction.CANCEL, token)
    update.callback_query = query

    # Also supply effective_message for the /cancel path.
    update.effective_message = MagicMock()

    # Execute the cancellation path.
    if cancel_path == "command":
        result = asyncio.run(cancel(update, ctx))
    elif cancel_path == "summary":
        result = asyncio.run(on_summary_action(update, ctx))
    elif cancel_path == "regression":
        result = asyncio.run(on_regression(update, ctx))
    elif cancel_path == "abandon":
        result = asyncio.run(on_abandon(update, ctx))
    else:
        raise AssertionError(f"Unknown cancel path: {cancel_path}")  # pragma: no cover

    # --- Assertions: all four paths must produce the same outcome ---

    # 1. Return value is END (ConversationHandler.END).
    assert result == ConversationHandler.END, (
        f"cancel via '{cancel_path}' must return END, got {result}"
    )

    # 2. card_service.finalize called with render_cancelled(lang) text and None markup.
    expected_text = render_cancelled(lang)
    card_service.finalize.assert_awaited_once_with(
        chat_id, flow.card_message_id, expected_text, None
    )

    # 3. context.user_data["flow"] is removed after the call.
    assert "flow" not in ctx.user_data, (
        f"cancel via '{cancel_path}' must remove flow from user_data"
    )


# ---------------------------------------------------------------------------
# Unit tests: smart-default scenarios
# ---------------------------------------------------------------------------

def _make_start_flow_context(
    *,
    config_store: AsyncMock | None = None,
    lubelogger_client: AsyncMock | None = None,
    tracker: AsyncMock | None = None,
    card_service: AsyncMock | None = None,
) -> MagicMock:
    """Build a context object wired with bot_data services for start_flow tests."""
    ctx = MagicMock()
    ctx.user_data = {}

    cs = config_store or AsyncMock()
    ll = lubelogger_client or AsyncMock()
    tr = tracker or AsyncMock()
    cd = card_service or AsyncMock()

    ctx.bot_data = {
        "config_store": cs,
        "lubelogger_client": ll,
        "tracker": tr,
        "card_service": cd,
    }
    # card_service.open returns a message id
    if cd.open.return_value is None:
        cd.open.return_value = 100

    # Default config_store methods
    if cs.get_language.return_value is None:
        cs.get_language.return_value = "en"

    return ctx


def _make_start_flow_update(*, user_id: int = 42, chat_id: int = 123) -> MagicMock:
    """Build a minimal Update for start_flow entry."""
    update = MagicMock()
    user = MagicMock()
    user.id = user_id
    update.effective_user = user
    chat = MagicMock()
    chat.id = chat_id
    update.effective_chat = chat
    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update.effective_message = msg
    return update


@pytest.mark.asyncio
async def test_single_vehicle_auto_selected() -> None:
    """Req 5.1: single vehicle auto-selected, persisted and announced once."""
    # Setup: one vehicle available, no active vehicle persisted.
    vehicle = Vehicle(id=7, year=2020, make="Fiat", model="Panda")
    snapshot = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=45000)

    config_store = AsyncMock()
    config_store.get_language.return_value = "en"
    config_store.get_active_vehicle.return_value = None
    config_store.set_active_vehicle.return_value = None
    config_store.get_active_vehicle_name.return_value = None

    lubelogger_client = AsyncMock()
    lubelogger_client.get_vehicle_snapshots.return_value = [snapshot]

    tracker = AsyncMock()
    tracker.observe_snapshot.return_value = None
    tracker.get_reference.return_value = None

    card_service = AsyncMock()
    card_service.open.return_value = 100

    ctx = _make_start_flow_context(
        config_store=config_store,
        lubelogger_client=lubelogger_client,
        tracker=tracker,
        card_service=card_service,
    )
    update = _make_start_flow_update()

    result = await start_flow(update, ctx, kind=FlowKind.FUEL)

    # Should be in COLLECT state.
    assert result == COLLECT

    # set_active_vehicle was called with the vehicle id and name (Req 5.1).
    config_store.set_active_vehicle.assert_awaited_once_with(
        42, 7, "2020 Fiat Panda"
    )

    # card_service.open was called with text containing the vehicle name.
    card_service.open.assert_awaited_once()
    card_text = card_service.open.call_args[0][1]  # positional arg: text
    assert "Fiat Panda" in card_text


@pytest.mark.asyncio
async def test_already_active_vehicle_reused_without_prompting() -> None:
    """Req 5.2: already active vehicle reused without prompting."""
    # Setup: multiple vehicles, one already active.
    vehicle_a = Vehicle(id=3, year=2019, make="Toyota", model="Yaris")
    vehicle_b = Vehicle(id=7, year=2020, make="Fiat", model="Panda")
    snap_a = VehicleSnapshot(vehicle=vehicle_a, last_reported_odometer=30000)
    snap_b = VehicleSnapshot(vehicle=vehicle_b, last_reported_odometer=45000)

    config_store = AsyncMock()
    config_store.get_language.return_value = "en"
    config_store.get_active_vehicle.return_value = 7  # already active
    config_store.set_active_vehicle.return_value = None
    config_store.get_active_vehicle_name.return_value = "2020 Fiat Panda"

    lubelogger_client = AsyncMock()
    lubelogger_client.get_vehicle_snapshots.return_value = [snap_a, snap_b]

    tracker = AsyncMock()
    tracker.observe_snapshot.return_value = None
    tracker.get_reference.return_value = None

    card_service = AsyncMock()
    card_service.open.return_value = 100

    ctx = _make_start_flow_context(
        config_store=config_store,
        lubelogger_client=lubelogger_client,
        tracker=tracker,
        card_service=card_service,
    )
    update = _make_start_flow_update()

    result = await start_flow(update, ctx, kind=FlowKind.SERVICE)

    assert result == COLLECT

    # set_active_vehicle is called to refresh name (not a new selection).
    config_store.set_active_vehicle.assert_awaited_once_with(
        42, 7, "2020 Fiat Panda"
    )

    # No vehicle_prompt sent — no message asking the user to pick a vehicle.
    # The effective_message.reply_text was called only for the placeholder "\u200b".
    for call in update.effective_message.reply_text.call_args_list:
        text_arg = call[0][0] if call[0] else call.kwargs.get("text", "")
        assert "vehicle" not in text_arg.lower() or text_arg == "\u200b"


@pytest.mark.asyncio
async def test_no_reference_when_instance_down_and_nothing_known() -> None:
    """Req 5.6: no reference when nothing is known locally and instance is down."""
    config_store = AsyncMock()
    config_store.get_language.return_value = "en"
    config_store.get_active_vehicle.return_value = 5
    config_store.get_active_vehicle_name.return_value = "My Car"
    config_store.set_active_vehicle.return_value = None

    lubelogger_client = AsyncMock()
    lubelogger_client.get_vehicle_snapshots.side_effect = LubeLoggerUnreachableError()

    tracker = AsyncMock()
    tracker.get_reference.return_value = None  # nothing known locally

    card_service = AsyncMock()
    card_service.open.return_value = 100

    ctx = _make_start_flow_context(
        config_store=config_store,
        lubelogger_client=lubelogger_client,
        tracker=tracker,
        card_service=card_service,
    )
    update = _make_start_flow_update()

    result = await start_flow(update, ctx, kind=FlowKind.ODOMETER)

    assert result == COLLECT

    # Card was still opened successfully.
    card_service.open.assert_awaited_once()

    # Card text does NOT contain the reference line.
    card_text = card_service.open.call_args[0][1]
    assert "Last:" not in card_text


# ---------------------------------------------------------------------------
# Property 26: Log another starts an equivalent fresh flow
# Feature: improve-ux, Property 26: Log another starts an equivalent fresh flow
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p26_) ---

_p26_flow_kinds = st.sampled_from(list(FlowKind))
_p26_vehicle_ids = st.integers(min_value=1, max_value=9999)
_p26_vehicle_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=30,
)
_p26_card_message_ids = st.integers(min_value=1, max_value=999999)


@settings(max_examples=100)
@given(
    kind=_p26_flow_kinds,
    vehicle_id=_p26_vehicle_ids,
    vehicle_name=_p26_vehicle_names,
    prev_card_msg_id=_p26_card_message_ids,
)
def test_property_log_another_fresh_flow(
    kind: FlowKind,
    vehicle_id: int,
    vehicle_name: str,
    prev_card_msg_id: int,
) -> None:
    """Property 26: Log another starts an equivalent fresh flow.

    # Feature: improve-ux, Property 26: Log another starts an equivalent fresh flow

    **Validates: Requirements 7.1, 7.2, 7.3**

    When on_log_another is called with last_flow_info in user_data, it:
    - strips the markup from the previous confirmation (Req 7.3),
    - starts a fresh flow of the same kind with the same vehicle (Req 7.1, 7.2),
    - the resulting FlowState has a new token, step_index=0, empty values, same vehicle_id.
    """
    from bot.handlers.record_flow import on_log_another

    # --- Build user_data with last_flow_info ---
    old_token = new_token()
    last_flow_info = {
        "kind": kind,
        "vehicle_id": vehicle_id,
        "vehicle_name": vehicle_name,
        "card_message_id": prev_card_msg_id,
    }

    # --- Mock services ---
    card_service = AsyncMock()
    card_service.strip_markup = AsyncMock()
    card_service.open = AsyncMock(return_value=200)

    config_store = AsyncMock()
    config_store.get_language = AsyncMock(return_value="en")
    config_store.get_active_vehicle_name = AsyncMock(return_value=vehicle_name)

    tracker = AsyncMock()
    tracker.get_reference = AsyncMock(return_value=None)

    # --- Build context ---
    ctx = MagicMock()
    user_data: dict[str, object] = {
        "last_flow_info": last_flow_info,
    }
    ctx.user_data = user_data
    ctx.bot_data = {
        "card_service": card_service,
        "config_store": config_store,
        "lubelogger_client": AsyncMock(),  # not called with vehicle_override
        "tracker": tracker,
    }

    # --- Build update with callback_query ---
    chat_id = 777
    user_id = 42

    update = MagicMock()
    query = AsyncMock()
    query.answer = AsyncMock()
    update.callback_query = query
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update.effective_message = msg

    # --- Call on_log_another ---
    result = asyncio.run(on_log_another(update, ctx))

    # --- Assertions ---

    # 1. Req 7.3: strip_markup called on the previous confirmation card.
    card_service.strip_markup.assert_awaited_once_with(chat_id, prev_card_msg_id)

    # 2. Result is COLLECT (a new flow started).
    assert result == COLLECT, f"Expected COLLECT ({COLLECT}), got {result}"

    # 3. A new FlowState was stored in user_data.
    flow: FlowState = ctx.user_data["flow"]

    # 4. Req 7.1: same kind.
    assert flow.kind == kind, f"Expected kind={kind}, got {flow.kind}"

    # 5. Req 7.2: same vehicle_id.
    assert flow.vehicle_id == vehicle_id, (
        f"Expected vehicle_id={vehicle_id}, got {flow.vehicle_id}"
    )

    # 6. Fresh flow: new token (different from old).
    assert flow.token != old_token, "New flow must have a different token"
    assert len(flow.token) > 0, "Token must be non-empty"

    # 7. Fresh flow: step_index=0, values empty.
    assert flow.step_index == 0, f"Expected step_index=0, got {flow.step_index}"
    assert flow.values == {}, f"Expected empty values, got {flow.values}"

    # 8. last_flow_info was consumed (popped) from user_data.
    assert "last_flow_info" not in ctx.user_data, (
        "last_flow_info should be popped after on_log_another"
    )


# ---------------------------------------------------------------------------
# Property 18: Editing one field from the Field_Picker preserves every other value
# Feature: improve-ux, Property 18: Editing one field from the Field_Picker
# preserves every other value
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p18_) ---

_p18_flow_kinds = st.sampled_from([FlowKind.FUEL, FlowKind.SERVICE])
# Odometer excluded: single field → no "other values" to verify preservation.


@st.composite
def _p18_completed_flow(draw: st.DrawFn) -> dict:
    """Generate a FlowKind with all fields populated and a random field index to edit."""
    from bot.flows.definitions import FieldKind, field_at, field_count

    kind = draw(_p18_flow_kinds)
    total = field_count(kind)

    # Populate all values with valid data per field kind.
    values: dict[str, object] = {}
    for idx in range(total):
        spec = field_at(kind, idx)
        if spec.kind == FieldKind.INT:
            values[spec.key] = draw(st.integers(min_value=1, max_value=999_999))
        elif spec.kind == FieldKind.DECIMAL:
            values[spec.key] = draw(
                st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False)
            )
        elif spec.kind == FieldKind.TEXT:
            values[spec.key] = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
                categories=("L", "N", "P", "S", "Z"), exclude_characters="\x00"
            )))
        elif spec.kind == FieldKind.CHOICE:
            values[spec.key] = draw(st.booleans())

    # Pick a random field index to edit.
    picked_index = draw(st.integers(min_value=0, max_value=total - 1))
    picked_spec = field_at(kind, picked_index)

    # Generate a new replacement value (different from original where possible).
    if picked_spec.kind == FieldKind.INT:
        new_value: object = draw(st.integers(min_value=1, max_value=999_999))
    elif picked_spec.kind == FieldKind.DECIMAL:
        new_value = draw(
            st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False)
        )
    elif picked_spec.kind == FieldKind.TEXT:
        new_value = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
            categories=("L", "N", "P", "S", "Z"), exclude_characters="\x00"
        )))
    elif picked_spec.kind == FieldKind.CHOICE:
        new_value = draw(st.booleans())
    else:
        new_value = "x"  # pragma: no cover

    return {
        "kind": kind,
        "values": values,
        "picked_index": picked_index,
        "picked_spec": picked_spec,
        "new_value": new_value,
    }


@settings(max_examples=100)
@given(data=_p18_completed_flow())
def test_property_field_picker_preserves_values(data: dict) -> None:
    """Property 18: Editing one field from the Field_Picker preserves every other value.

    # Feature: improve-ux, Property 18: Editing one field from the
    # Field_Picker preserves every other value

    **Validates: Requirements 4.8, 4.9**

    For any completed flow (all values filled), calling `on_field_pick` with a FIELD callback
    sets `editing_field` to that field's key and `step_index` to the picked index, without
    changing any existing value in `flow.values`. After re-entering a new value via
    `collect_value`, the edited field is updated and `editing_field` is cleared; all other
    values remain unchanged and the flow returns to SUMMARY.
    """
    from bot.flows.definitions import FieldKind, field_count
    from bot.handlers.record_flow import COLLECT, SUMMARY, collect_value, on_field_pick

    kind: FlowKind = data["kind"]
    values: dict[str, object] = data["values"]
    picked_index: int = data["picked_index"]
    picked_spec = data["picked_spec"]
    new_value: object = data["new_value"]

    total = field_count(kind)
    token = new_token()

    # Build a FlowState in SUMMARY (all values filled, step_index at total).
    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=1,
        vehicle_name="TestCar",
        step_index=total,  # past last field = summary
        values=dict(values),
        card_message_id=500,
        lang="en",
    )

    original_values = dict(values)

    # --- Phase 1: on_field_pick ---

    # Build mocks for on_field_pick (callback query with FIELD action).
    update_pick = MagicMock()
    query_pick = AsyncMock()
    query_pick.answer = AsyncMock()
    query_pick.data = encode(CallbackAction.FIELD, token, arg=picked_index)
    update_pick.callback_query = query_pick
    update_pick.effective_user = MagicMock()
    update_pick.effective_user.id = 42
    update_pick.effective_chat = MagicMock()
    update_pick.effective_chat.id = 123

    ctx = MagicMock()
    ctx.user_data = {"flow": flow}
    ctx.bot_data = {}

    card_service = AsyncMock()
    card_service.update = AsyncMock(return_value=flow.card_message_id)
    ctx.bot_data["card_service"] = card_service
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()

    pick_result = asyncio.run(on_field_pick(update_pick, ctx))

    # After on_field_pick: returns COLLECT, editing_field set, step_index set, values unchanged.
    assert pick_result == COLLECT, (
        f"on_field_pick must return COLLECT, got {pick_result}"
    )
    assert flow.editing_field == picked_spec.key, (
        f"editing_field should be {picked_spec.key!r}, got {flow.editing_field!r}"
    )
    assert flow.step_index == picked_index, (
        f"step_index should be {picked_index}, got {flow.step_index}"
    )
    # All values unchanged after pick.
    for key, val in original_values.items():
        assert flow.values[key] == val, (
            f"Value for {key!r} changed after on_field_pick: {val!r} -> {flow.values[key]!r}"
        )

    # --- Phase 2: collect_value (or on_choice) with new value ---

    if picked_spec.kind == FieldKind.CHOICE:
        # Choice fields are handled by on_choice, not typed text.
        from bot.handlers.record_flow import on_choice

        choice_ordinal = 0 if new_value else 1  # True=0(yes), False=1(no)
        update_choice = MagicMock()
        query_choice = AsyncMock()
        query_choice.answer = AsyncMock()
        query_choice.data = encode(CallbackAction.CHOICE, token, arg=choice_ordinal)
        update_choice.callback_query = query_choice
        update_choice.effective_user = MagicMock()
        update_choice.effective_user.id = 42
        update_choice.effective_chat = MagicMock()
        update_choice.effective_chat.id = 123

        ctx_choice = MagicMock()
        ctx_choice.user_data = {"flow": flow}
        card_service2 = AsyncMock()
        card_service2.update = AsyncMock(return_value=flow.card_message_id)
        ctx_choice.bot_data = {"card_service": card_service2}
        ctx_choice.bot = AsyncMock()
        ctx_choice.bot.send_message = AsyncMock()

        edit_result = asyncio.run(on_choice(update_choice, ctx_choice))

        expected_stored = new_value  # True or False

    else:
        # Typed text value — format for collect_value.
        if picked_spec.kind == FieldKind.INT:
            typed_text = str(int(new_value))
        elif picked_spec.kind == FieldKind.DECIMAL:
            typed_text = str(round(float(new_value), 2))
        elif picked_spec.kind == FieldKind.TEXT:
            typed_text = str(new_value)
        else:
            typed_text = str(new_value)  # pragma: no cover

        update_val = MagicMock()
        message_val = MagicMock()
        message_val.text = typed_text
        message_val.chat_id = 123
        update_val.effective_message = message_val
        update_val.effective_chat = MagicMock()
        update_val.effective_chat.id = 123

        ctx_val = MagicMock()
        ctx_val.user_data = {"flow": flow}
        card_service3 = AsyncMock()
        card_service3.update = AsyncMock(return_value=flow.card_message_id)
        card_service3.consume_prompt_reply = AsyncMock()
        ctx_val.bot_data = {"card_service": card_service3}
        ctx_val.bot = AsyncMock()
        ctx_val.bot.send_message = AsyncMock()

        edit_result = asyncio.run(collect_value(update_val, ctx_val))

        # Determine what was stored (collect_value parses and stores).
        if picked_spec.kind == FieldKind.INT:
            expected_stored = int(typed_text)
        elif picked_spec.kind == FieldKind.DECIMAL:
            expected_stored = float(typed_text.replace(",", "."))
        else:
            expected_stored = typed_text.strip()

    # --- Assertions after re-entering the value ---

    # Must return to SUMMARY (editing_field path).
    assert edit_result == SUMMARY, (
        f"After editing field, must return SUMMARY, got {edit_result}"
    )

    # editing_field must be cleared.
    assert flow.editing_field is None, (
        f"editing_field should be None after edit, got {flow.editing_field!r}"
    )

    # Picked field has the new value.
    assert flow.values[picked_spec.key] == expected_stored, (
        f"Picked field {picked_spec.key!r} should have new value {expected_stored!r}, "
        f"got {flow.values[picked_spec.key]!r}"
    )

    # All other values remain unchanged.
    for key, val in original_values.items():
        if key == picked_spec.key:
            continue
        assert flow.values[key] == val, (
            f"Other value {key!r} changed from {val!r} to {flow.values[key]!r}"
        )


# ---------------------------------------------------------------------------
# Property 27: A Menu_Label typed during a flow is navigation, not data
# Feature: improve-ux, Property 27: A Menu_Label typed during a flow is navigation, not data
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p27_) ---

_p27_flow_kinds = st.sampled_from(list(FlowKind))
_p27_actions = st.sampled_from(list(MenuAction))
_p27_langs = st.sampled_from(["en", "it"])
_p27_step_indices = st.integers(min_value=0, max_value=3)
_p27_vehicle_ids = st.integers(min_value=1, max_value=9999)


@st.composite
def _p27_scenario(draw: st.DrawFn) -> dict:
    """Generate a flow + menu label combination for on_menu_label_during_flow.

    Picks a locale and a menu action, resolves the label text from that locale,
    then builds a flow at a random step with some pre-collected values.
    """
    from bot.i18n import MENU_LABEL_KEYS, get_text

    # Choose locale for the label text and the action.
    label_lang = draw(_p27_langs)
    action = draw(_p27_actions)

    # Resolve the actual label text as a user would type it.
    label_key = MENU_LABEL_KEYS[action]
    label_text = get_text(label_key, label_lang)

    # Flow state: any kind, any step, any language (can differ from label_lang).
    kind = draw(_p27_flow_kinds)
    flow_lang = draw(_p27_langs)

    from bot.flows.definitions import field_count

    max_step = field_count(kind) - 1
    step_index = draw(st.integers(min_value=0, max_value=max(max_step, 0)))

    vehicle_id = draw(_p27_vehicle_ids)

    # Pre-populate some values (earlier steps collected).
    pre_values: dict[str, object] = {}
    from bot.flows.definitions import field_at as _fa

    for i in range(step_index):
        spec = _fa(kind, i)
        pre_values[spec.key] = 12345  # dummy value

    return {
        "kind": kind,
        "step_index": step_index,
        "vehicle_id": vehicle_id,
        "flow_lang": flow_lang,
        "action": action,
        "label_text": label_text,
        "pre_values": pre_values,
    }


@settings(max_examples=100)
@given(scenario=_p27_scenario())
def test_property_menu_label_is_navigation(scenario: dict) -> None:
    """Property 27: A Menu_Label typed during a flow is navigation, not data.

    # Feature: improve-ux, Property 27: A Menu_Label typed during a flow is navigation, not data

    **Validates: Requirements 11.5, 11.6**

    For any active flow and any menu label text (from any locale, any of the 5 actions),
    `on_menu_label_during_flow` does NOT store the text as a field value, moves to ABANDON,
    updates the card with the abandon prompt, and deletes the user message. The label text
    itself never appears in `flow.values`.
    """
    from bot.handlers.record_flow import ABANDON, on_menu_label_during_flow

    kind: FlowKind = scenario["kind"]
    step_index: int = scenario["step_index"]
    vehicle_id: int = scenario["vehicle_id"]
    flow_lang: str = scenario["flow_lang"]
    action: MenuAction = scenario["action"]
    label_text: str = scenario["label_text"]
    pre_values: dict[str, object] = scenario["pre_values"]

    # --- Build FlowState ---
    token = new_token()
    flow = FlowState(
        kind=kind,
        token=token,
        vehicle_id=vehicle_id,
        vehicle_name="TestCar",
        step_index=step_index,
        values=dict(pre_values),
        card_message_id=555,
        lang=flow_lang,
    )
    original_values = dict(flow.values)

    # --- Build mocked Update ---
    update = MagicMock()
    message = MagicMock()
    message.text = label_text
    message.chat_id = 123
    update.effective_message = message

    # --- Build mocked context ---
    ctx = MagicMock()
    user_data: dict[str, object] = {"flow": flow}
    ctx.user_data = user_data

    # --- Build mocked card_service ---
    card_service = AsyncMock()
    card_service.update = AsyncMock(return_value=556)
    card_service.consume_prompt_reply = AsyncMock()
    ctx.bot_data = {"card_service": card_service}

    # --- Call on_menu_label_during_flow ---
    result = asyncio.run(on_menu_label_during_flow(update, ctx))

    # --- Assertions ---

    # 1. Returns ABANDON state.
    assert result == ABANDON, (
        f"Expected ABANDON ({ABANDON}), got {result}. "
        f"action={action.value}, label={label_text!r}"
    )

    # 2. Label text never stored as a field value.
    for key, val in flow.values.items():
        assert val != label_text, (
            f"Label text {label_text!r} was stored as flow.values[{key!r}]"
        )

    # 3. Original pre-collected values are preserved (no mutation).
    for k, v in original_values.items():
        assert flow.values.get(k) == v, (
            f"Pre-existing value for {k!r} changed from {v!r} to {flow.values.get(k)!r}"
        )

    # 4. No new keys added to flow.values.
    assert set(flow.values.keys()) == set(original_values.keys()), (
        f"flow.values gained keys: {set(flow.values.keys()) - set(original_values.keys())}"
    )

    # 5. pending_target is set to the resolved action.
    assert flow.pending_target == action, (
        f"flow.pending_target should be {action}, got {flow.pending_target}"
    )

    # 6. card_service.update was called (card updated with abandon prompt).
    card_service.update.assert_awaited_once()

    # 7. card_service.consume_prompt_reply was called (user message deleted).
    card_service.consume_prompt_reply.assert_awaited_once_with(message)


# ---------------------------------------------------------------------------
# Property 14: A flow costs one API call at start and none per step
# Feature: improve-ux, Property 14: A flow costs one API call at start and none per step
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p14_) ---

_p14_flow_kinds = st.sampled_from(list(FlowKind))
_p14_num_steps = st.integers(min_value=1, max_value=3)


@st.composite
def _p14_scenario(draw: st.DrawFn) -> dict:
    """Draw a FlowKind and valid values for the first 1-3 fields."""
    from bot.flows.definitions import FieldKind, field_at, field_count

    kind = draw(_p14_flow_kinds)
    total = field_count(kind)
    num_steps = draw(st.integers(min_value=1, max_value=min(3, total)))

    # Generate valid values for the chosen number of steps.
    step_values: list[tuple[str, object]] = []
    for i in range(num_steps):
        spec = field_at(kind, i)
        if spec.kind == FieldKind.INT:
            val = draw(st.integers(min_value=1, max_value=999_999))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.DECIMAL:
            val = draw(st.floats(min_value=0.01, max_value=9999.0, allow_nan=False,
                                 allow_infinity=False))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.TEXT:
            val = draw(st.text(min_size=1, max_size=20,
                               alphabet=st.characters(whitelist_categories=("L", "N", "P"))))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.CHOICE:
            val = draw(st.booleans())
            step_values.append((spec.key, val))

    return {
        "kind": kind,
        "num_steps": num_steps,
        "step_values": step_values,
    }


@settings(max_examples=100)
@given(scenario=_p14_scenario())
def test_property_api_call_budget(scenario: dict) -> None:
    """Property 14: A flow costs one API call at start and none per step.

    # Feature: improve-ux, Property 14: A flow costs one API call at start and none per step

    **Validates: Requirements 5.11, NF-2.1, NF-2.2, NF-2.3**

    After start_flow completes, lubelogger_client.get_vehicle_snapshots was called exactly once
    (Req 5.11, NF-2.2). Then for each subsequent collect_value / on_choice / on_keep_suggestion
    step, no additional LubeLogger API call is made (NF-2.3). The only external calls during
    steps are card_service.update and card_service.consume_prompt_reply (Telegram, not API).
    """
    from bot.flows.definitions import FieldKind, field_at, field_count
    from bot.handlers.record_flow import (
        COLLECT,
        collect_value,
        on_choice,
        start_flow,
    )
    from bot.models.records import VehicleSnapshot
    from bot.models.responses import Vehicle
    from bot.services.odometer_tracker import OdometerReference

    kind: FlowKind = scenario["kind"]
    num_steps: int = scenario["num_steps"]
    step_values: list[tuple[str, object]] = scenario["step_values"]

    # --- Setup services ---
    vehicle = Vehicle(id=1, year=2020, make="Test", model="Car")
    snapshot = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=10000)

    config_store = AsyncMock()
    config_store.get_language.return_value = "en"
    config_store.get_active_vehicle.return_value = None
    config_store.set_active_vehicle.return_value = None
    config_store.get_active_vehicle_name.return_value = None

    lubelogger_client = AsyncMock()
    lubelogger_client.get_vehicle_snapshots.return_value = [snapshot]

    # Reference large enough to never trigger regression.
    reference = OdometerReference(value=1, on_date=None, source="bot")
    tracker = AsyncMock()
    tracker.observe_snapshot.return_value = None
    tracker.get_reference.return_value = reference

    card_service = AsyncMock()
    card_service.open.return_value = 100
    card_service.update.return_value = 100
    card_service.consume_prompt_reply.return_value = None

    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot_data = {
        "config_store": config_store,
        "lubelogger_client": lubelogger_client,
        "tracker": tracker,
        "card_service": card_service,
    }
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()

    update = MagicMock()
    user = MagicMock()
    user.id = 42
    update.effective_user = user
    chat = MagicMock()
    chat.id = 123
    update.effective_chat = chat
    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update.effective_message = msg

    # --- start_flow ---
    result = asyncio.run(start_flow(update, ctx, kind=kind))
    assert result == COLLECT

    # Req 5.11, NF-2.2: exactly one API call at start.
    assert lubelogger_client.get_vehicle_snapshots.await_count == 1, (
        "start_flow must call get_vehicle_snapshots exactly once"
    )

    # Reset the call count to track steps independently.
    lubelogger_client.reset_mock()

    # --- Simulate 1-N steps ---
    flow = ctx.user_data["flow"]
    total = field_count(kind)

    for i in range(num_steps):
        if i >= total:
            break  # pragma: no cover

        spec = field_at(kind, flow.step_index)
        _key, value = step_values[i]

        if spec.kind == FieldKind.CHOICE:
            # Use on_choice handler.
            from bot.callbacks import CallbackAction, encode

            query = AsyncMock()
            query.answer = AsyncMock()
            # For is_fill_to_full: 0=True, 1=False
            arg = 0 if value else 1
            query.data = encode(CallbackAction.CHOICE, flow.token, arg)
            step_update = MagicMock()
            step_update.callback_query = query
            step_update.effective_user = MagicMock()
            step_update.effective_user.id = 42
            step_update.effective_chat = MagicMock()
            step_update.effective_chat.id = 123

            asyncio.run(on_choice(step_update, ctx))

        elif spec.key == "odometer" and reference is not None:
            # Use on_keep_suggestion to keep the reference value (avoids regression).
            from bot.callbacks import CallbackAction, encode

            # Override with a large value from step_values to avoid regression.
            # Use collect_value with a text-based entry instead.
            step_update = MagicMock()
            step_msg = MagicMock()
            step_msg.text = str(value)
            step_msg.chat_id = 123
            step_update.effective_message = step_msg
            step_update.effective_chat = MagicMock()
            step_update.effective_chat.id = 123

            asyncio.run(collect_value(step_update, ctx))

        else:
            # Use collect_value for INT (non-odometer), DECIMAL, TEXT.
            step_update = MagicMock()
            step_msg = MagicMock()
            if spec.kind == FieldKind.DECIMAL:
                step_msg.text = f"{value:.2f}"
            else:
                step_msg.text = str(value)
            step_msg.chat_id = 123
            step_update.effective_message = step_msg
            step_update.effective_chat = MagicMock()
            step_update.effective_chat.id = 123

            asyncio.run(collect_value(step_update, ctx))

        # NF-2.3: no LubeLogger API calls during this step.
        assert lubelogger_client.get_vehicle_snapshots.await_count == 0, (
            f"Step {i}: get_vehicle_snapshots must not be called during steps"
        )
        assert lubelogger_client.get_gas_records.await_count == 0, (
            f"Step {i}: get_gas_records must not be called during steps"
        )
        assert lubelogger_client.get_service_records.await_count == 0, (
            f"Step {i}: get_service_records must not be called during steps"
        )
        assert lubelogger_client.get_odometer_records.await_count == 0, (
            f"Step {i}: get_odometer_records must not be called during steps"
        )


# ---------------------------------------------------------------------------
# Property 11: One card message per operation, one edit per step
# Feature: improve-ux, Property 11: One card message per operation, one edit per step
# ---------------------------------------------------------------------------

# --- Strategies (prefixed _p11_) ---

_p11_flow_kinds = st.sampled_from(list(FlowKind))


@st.composite
def _p11_scenario(draw: st.DrawFn) -> dict:
    """Draw a FlowKind and valid values for 1-3 steps."""
    from bot.flows.definitions import FieldKind, field_at, field_count

    kind = draw(_p11_flow_kinds)
    total = field_count(kind)
    num_steps = draw(st.integers(min_value=1, max_value=min(3, total)))

    step_values: list[tuple[str, object]] = []
    for i in range(num_steps):
        spec = field_at(kind, i)
        if spec.kind == FieldKind.INT:
            val = draw(st.integers(min_value=1, max_value=999_999))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.DECIMAL:
            val = draw(st.floats(min_value=0.01, max_value=9999.0, allow_nan=False,
                                 allow_infinity=False))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.TEXT:
            val = draw(st.text(min_size=1, max_size=20,
                               alphabet=st.characters(whitelist_categories=("L", "N", "P"))))
            step_values.append((spec.key, val))
        elif spec.kind == FieldKind.CHOICE:
            val = draw(st.booleans())
            step_values.append((spec.key, val))

    return {
        "kind": kind,
        "num_steps": num_steps,
        "step_values": step_values,
    }


@settings(max_examples=100)
@given(scenario=_p11_scenario())
def test_property_single_card_message(scenario: dict) -> None:
    """Property 11: One card message per operation, one edit per step.

    # Feature: improve-ux, Property 11: One card message per operation, one edit per step

    **Validates: Requirements 3.1, 3.2, NF-2.4**

    card_service.open is called exactly once per start_flow (Req 3.1). Each step calls
    card_service.update exactly once (Req 3.2, NF-2.4). card_service.open is never called
    again during the same flow.
    """
    from bot.flows.definitions import FieldKind, field_at, field_count
    from bot.handlers.record_flow import (
        COLLECT,
        collect_value,
        on_choice,
        start_flow,
    )
    from bot.models.records import VehicleSnapshot
    from bot.models.responses import Vehicle
    from bot.services.odometer_tracker import OdometerReference

    kind: FlowKind = scenario["kind"]
    num_steps: int = scenario["num_steps"]
    step_values: list[tuple[str, object]] = scenario["step_values"]

    # --- Setup services ---
    vehicle = Vehicle(id=1, year=2020, make="Test", model="Car")
    snapshot = VehicleSnapshot(vehicle=vehicle, last_reported_odometer=10000)

    config_store = AsyncMock()
    config_store.get_language.return_value = "en"
    config_store.get_active_vehicle.return_value = None
    config_store.set_active_vehicle.return_value = None
    config_store.get_active_vehicle_name.return_value = None

    lubelogger_client = AsyncMock()
    lubelogger_client.get_vehicle_snapshots.return_value = [snapshot]

    # Reference = 1 so any positive odometer passes without regression.
    reference = OdometerReference(value=1, on_date=None, source="bot")
    tracker = AsyncMock()
    tracker.observe_snapshot.return_value = None
    tracker.get_reference.return_value = reference

    card_service = AsyncMock()
    card_service.open.return_value = 100
    card_service.update.return_value = 100
    card_service.consume_prompt_reply.return_value = None

    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot_data = {
        "config_store": config_store,
        "lubelogger_client": lubelogger_client,
        "tracker": tracker,
        "card_service": card_service,
    }
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()

    update = MagicMock()
    user = MagicMock()
    user.id = 42
    update.effective_user = user
    chat = MagicMock()
    chat.id = 123
    update.effective_chat = chat
    msg = AsyncMock()
    msg.reply_text = AsyncMock()
    update.effective_message = msg

    # --- start_flow ---
    result = asyncio.run(start_flow(update, ctx, kind=kind))
    assert result == COLLECT

    # Req 3.1: card_service.open called exactly once.
    assert card_service.open.await_count == 1, (
        "start_flow must call card_service.open exactly once"
    )

    # Reset update count to track per-step.
    card_service.update.reset_mock()

    # --- Simulate steps ---
    flow = ctx.user_data["flow"]
    total = field_count(kind)

    for i in range(num_steps):
        if i >= total:
            break  # pragma: no cover

        spec = field_at(kind, flow.step_index)
        _key, value = step_values[i]

        update_count_before = card_service.update.await_count

        if spec.kind == FieldKind.CHOICE:
            from bot.callbacks import CallbackAction, encode

            query = AsyncMock()
            query.answer = AsyncMock()
            arg = 0 if value else 1
            query.data = encode(CallbackAction.CHOICE, flow.token, arg)
            step_update = MagicMock()
            step_update.callback_query = query
            step_update.effective_user = MagicMock()
            step_update.effective_user.id = 42
            step_update.effective_chat = MagicMock()
            step_update.effective_chat.id = 123

            asyncio.run(on_choice(step_update, ctx))

        else:
            step_update = MagicMock()
            step_msg = MagicMock()
            if spec.kind == FieldKind.DECIMAL:
                step_msg.text = f"{value:.2f}"
            else:
                step_msg.text = str(value)
            step_msg.chat_id = 123
            step_update.effective_message = step_msg
            step_update.effective_chat = MagicMock()
            step_update.effective_chat.id = 123

            asyncio.run(collect_value(step_update, ctx))

        # Req 3.2, NF-2.4: each step calls card_service.update exactly once.
        update_count_after = card_service.update.await_count
        updates_this_step = update_count_after - update_count_before
        assert updates_this_step == 1, (
            f"Step {i}: expected exactly 1 card_service.update call, got {updates_this_step}"
        )

        # card_service.open must never be called again (still at 1 from start_flow).
        assert card_service.open.await_count == 1, (
            f"Step {i}: card_service.open must not be called during steps "
            f"(count={card_service.open.await_count})"
        )
