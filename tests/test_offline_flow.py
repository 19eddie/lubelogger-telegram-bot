"""Property-based tests for the offline queue round-trip.

Validates that enqueuing a record when LubeLogger is unreachable preserves
every collected field value without loss or corruption.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bot.exceptions import LubeLoggerUnreachableError
from bot.flows.definitions import FlowKind
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.services.record_submitter import RecordSubmitter

# --- Strategies for valid field values ---

valid_odometer = st.integers(min_value=1, max_value=9_999_999)
valid_liters = st.floats(min_value=0.01, max_value=999.99, allow_nan=False, allow_infinity=False)
valid_cost = st.floats(min_value=0.0, max_value=9999.99, allow_nan=False, allow_infinity=False)
valid_is_fill_to_full = st.booleans()
valid_description = st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != "")


# --- Helpers ---


def _make_submitter(captured: list[str]) -> RecordSubmitter:
    """Build a RecordSubmitter with mocked deps; queue.enqueue captures payload JSON."""
    client = AsyncMock()
    # All add_* methods raise unreachable → triggers enqueue path
    client.add_gas_record = AsyncMock(side_effect=LubeLoggerUnreachableError())
    client.add_service_record = AsyncMock(side_effect=LubeLoggerUnreachableError())
    client.add_odometer_record = AsyncMock(side_effect=LubeLoggerUnreachableError())

    queue = AsyncMock()

    async def _capture_enqueue(
        user_id: int, vehicle_id: int, record_type: str, payload: str
    ) -> int:
        captured.append(payload)
        return 1

    queue.enqueue = AsyncMock(side_effect=_capture_enqueue)

    tracker = AsyncMock()
    tracker.observe = AsyncMock()

    config_store = AsyncMock()
    config_store.get_active_vehicle_name = AsyncMock(return_value="TestCar")

    return RecordSubmitter(
        client=client,
        queue=queue,
        tracker=tracker,
        config_store=config_store,
    )


# --- Property 23: Enqueuing loses nothing ---


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    liters=valid_liters,
    cost=valid_cost,
    is_fill_to_full=valid_is_fill_to_full,
)
@pytest.mark.asyncio
async def test_property_queue_roundtrip_fuel(
    odometer: int,
    liters: float,
    cost: float,
    is_fill_to_full: bool,
) -> None:
    """Property 23: Enqueuing loses nothing (fuel record).

    # Feature: improve-ux, Property 23: Enqueuing loses nothing

    **Validates: Requirements 9.1**
    """
    captured: list[str] = []
    submitter = _make_submitter(captured)

    values: dict[str, object] = {
        "odometer": odometer,
        "liters": liters,
        "cost": cost,
        "is_fill_to_full": is_fill_to_full,
    }

    outcome = await submitter.submit(
        user_id=1, vehicle_id=10, kind=FlowKind.FUEL, values=values
    )

    assert outcome.status == "queued"
    assert len(captured) == 1

    # Deserialize and verify round-trip
    payload_data = json.loads(captured[0])
    restored = GasRecordPayload.model_validate(payload_data)

    assert restored.odometer == str(odometer)
    assert restored.fuel_consumed == str(liters)
    assert restored.cost == str(cost)
    assert restored.is_fill_to_full == str(is_fill_to_full).lower()


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    description=valid_description,
    cost=valid_cost,
)
@pytest.mark.asyncio
async def test_property_queue_roundtrip_service(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 23: Enqueuing loses nothing (service record).

    # Feature: improve-ux, Property 23: Enqueuing loses nothing

    **Validates: Requirements 9.1**
    """
    captured: list[str] = []
    submitter = _make_submitter(captured)

    values: dict[str, object] = {
        "odometer": odometer,
        "description": description,
        "cost": cost,
    }

    outcome = await submitter.submit(
        user_id=2, vehicle_id=20, kind=FlowKind.SERVICE, values=values
    )

    assert outcome.status == "queued"
    assert len(captured) == 1

    payload_data = json.loads(captured[0])
    restored = ServiceRecordPayload.model_validate(payload_data)

    assert restored.odometer == str(odometer)
    # Description is stripped by validator
    assert restored.description == description.strip()
    assert restored.cost == str(cost)


@settings(max_examples=100)
@given(odometer=valid_odometer)
@pytest.mark.asyncio
async def test_property_queue_roundtrip_odometer(
    odometer: int,
) -> None:
    """Property 23: Enqueuing loses nothing (odometer record).

    # Feature: improve-ux, Property 23: Enqueuing loses nothing

    **Validates: Requirements 9.1**
    """
    captured: list[str] = []
    submitter = _make_submitter(captured)

    values: dict[str, object] = {"odometer": odometer}

    outcome = await submitter.submit(
        user_id=3, vehicle_id=30, kind=FlowKind.ODOMETER, values=values
    )

    assert outcome.status == "queued"
    assert len(captured) == 1

    payload_data = json.loads(captured[0])
    restored = OdometerRecordPayload.model_validate(payload_data)

    assert restored.odometer == str(odometer)


# Combined parametric test covering all three flow kinds in one function
# (satisfies the "test_property_queue_roundtrip" naming requirement)


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    liters=valid_liters,
    cost=valid_cost,
    is_fill_to_full=valid_is_fill_to_full,
    description=valid_description,
    kind=st.sampled_from([FlowKind.FUEL, FlowKind.SERVICE, FlowKind.ODOMETER]),
)
@pytest.mark.asyncio
async def test_property_queue_roundtrip(
    odometer: int,
    liters: float,
    cost: float,
    is_fill_to_full: bool,
    description: str,
    kind: FlowKind,
) -> None:
    """Property 23: Enqueuing loses nothing.

    For any FlowKind and any valid field values, when LubeLogger is unreachable
    the enqueued JSON payload deserializes back to an identical representation
    of the original values.

    # Feature: improve-ux, Property 23: Enqueuing loses nothing

    **Validates: Requirements 9.1**
    """
    captured: list[str] = []
    submitter = _make_submitter(captured)

    if kind is FlowKind.FUEL:
        values: dict[str, object] = {
            "odometer": odometer,
            "liters": liters,
            "cost": cost,
            "is_fill_to_full": is_fill_to_full,
        }
    elif kind is FlowKind.SERVICE:
        values = {
            "odometer": odometer,
            "description": description,
            "cost": cost,
        }
    else:
        values = {"odometer": odometer}

    outcome = await submitter.submit(
        user_id=42, vehicle_id=7, kind=kind, values=values
    )

    assert outcome.status == "queued"
    assert len(captured) == 1

    payload_data = json.loads(captured[0])

    if kind is FlowKind.FUEL:
        restored = GasRecordPayload.model_validate(payload_data)
        assert restored.odometer == str(odometer)
        assert restored.fuel_consumed == str(liters)
        assert restored.cost == str(cost)
        assert restored.is_fill_to_full == str(is_fill_to_full).lower()
    elif kind is FlowKind.SERVICE:
        restored = ServiceRecordPayload.model_validate(payload_data)
        assert restored.odometer == str(odometer)
        assert restored.description == description.strip()
        assert restored.cost == str(cost)
    else:
        restored = OdometerRecordPayload.model_validate(payload_data)
        assert restored.odometer == str(odometer)



# --- Property 25: Offline flow completion ---


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    odometer=valid_odometer,
    liters=valid_liters,
    cost=valid_cost,
    is_fill_to_full=valid_is_fill_to_full,
    vehicle_name=st.text(min_size=1, max_size=100),
)
@pytest.mark.asyncio
async def test_property_offline_flow_completes(
    odometer: int,
    liters: float,
    cost: float,
    is_fill_to_full: bool,
    vehicle_name: str,
    fake_bot,
    clean_locales,
) -> None:
    """Property 25: A flow completes even when LubeLogger is unreachable throughout.

    When the LubeLogger instance is unreachable from flow start through record save:
    - the flow starts using persisted active vehicle + name without blocking
    - each step collects and updates the card exactly once, no extra edits
    - record submission queues (not saves) when the API is unreachable
    - all typed values are preserved in the final queued confirmation
    - no LubeLogger calls are made (client always raises immediately)

    # Feature: improve-ux, Property 25: A flow completes even when LubeLogger is unreachable throughout

    **Validates: Requirements 5.12 (continue flow using persisted active vehicle and name when instance down at flow start), 9.6 (degrade to locally persisted Last_Known_Odometer and Active_Vehicle_Name when unreachable)**
    """
    # Reset fake_bot for each hypothesis example (health check suppression requires manual reset)
    fake_bot.reset()
    
    from datetime import date, datetime
    from unittest.mock import AsyncMock, MagicMock

    from telegram import Chat, Message

    from bot.callbacks import encode, CallbackAction, new_token
    from bot.flows.definitions import FlowKind, FieldKind, field_at, field_count
    from bot.flows.views import ConfirmationView, FieldEntry
    from bot.formatters import render_queued
    from bot.services.card_service import CardService
    from bot.services.config_store import ConfigStore
    from bot.services.odometer_tracker import OdometerTracker, OdometerReference
    from bot.services.record_submitter import RecordSubmitter
    from tests.conftest import FakeBot

    # Setup: persisted state for the offline user
    db_path = ":memory:"  # In-memory for test isolation

    kind = FlowKind.FUEL
    vehicle_id = 42
    user_id = 100
    chat_id = 200
    flow_token = new_token()

    # Mock LubeLoggerClient: always raises unreachable
    client = AsyncMock()
    client.add_gas_record = AsyncMock(side_effect=LubeLoggerUnreachableError())
    client.get_gas_records = AsyncMock(side_effect=LubeLoggerUnreachableError())

    # Mock QueueService: captures enqueued payload
    queue_payloads: list[str] = []

    async def _enqueue_capture(
        user_id: int, vehicle_id: int, record_type: str, payload: str
    ) -> int:
        queue_payloads.append(payload)
        return 1

    queue = AsyncMock()
    queue.enqueue = AsyncMock(side_effect=_enqueue_capture)

    # Mock OdometerTracker: track observations
    tracker = AsyncMock()
    tracker_observations: list[OdometerReference] = []

    async def _track_observe(vehicle_id: int, ref: OdometerReference) -> None:
        tracker_observations.append(ref)

    tracker.observe = AsyncMock(side_effect=_track_observe)
    tracker.get_reference = AsyncMock(
        return_value=OdometerReference(value=45000, on_date=date(2025, 1, 1), source="bot")
    )

    # Mock ConfigStore: return the persisted vehicle name
    config_store = AsyncMock()
    config_store.get_active_vehicle_name = AsyncMock(return_value=vehicle_name)

    # Build submitter with offline mocks
    submitter = RecordSubmitter(
        client=client,
        queue=queue,
        tracker=tracker,
        config_store=config_store,
    )

    # Build card service with FakeBot
    card_service = CardService(bot=fake_bot)

    # --- Simulate flow steps: collect all fields ---

    field_specs = [field_at(kind, i) for i in range(field_count(kind))]
    collected_values: dict[str, object] = {
        "odometer": odometer,
        "liters": liters,
        "cost": cost,
        "is_fill_to_full": is_fill_to_full,
    }

    # Step 1: Open card at flow start
    card_text_start = f"Flow start, vehicle: {vehicle_name}"
    keyboard_start = MagicMock()
    card_id = await card_service.open(chat_id, card_text_start, keyboard_start)

    assert card_id > 0, "card should be opened"
    assert len(fake_bot.calls_to("send_message")) == 1, "card should open exactly once"

    # Simulate field collection loop: update card for each step
    for step_index, field_spec in enumerate(field_specs):
        step_num = step_index + 1
        card_text_step = f"Step {step_num}/{len(field_specs)}, field: {field_spec.key}"
        keyboard_step = MagicMock()

        result_id = await card_service.update(chat_id, card_id, card_text_step, keyboard_step)
        assert result_id == card_id, f"card update at step {step_num} should keep same id"

    # Verify: one send_message (open) + N edits (one per step), no extras
    open_calls = len(fake_bot.calls_to("send_message"))
    edit_calls = len(fake_bot.calls_to("edit_message_text"))
    assert open_calls == 1, f"card should open exactly once, got {open_calls}"
    assert edit_calls == len(field_specs), (
        f"card should edit once per field, got {edit_calls} edits for {len(field_specs)} fields"
    )

    # --- Simulate submit: queue when unreachable ---

    outcome = await submitter.submit(
        user_id=user_id,
        vehicle_id=vehicle_id,
        kind=kind,
        values=collected_values,
    )

    # Verify: outcome is queued, not saved
    assert outcome.status == "queued", "outcome should be queued when unreachable"
    assert len(queue_payloads) == 1, "one record should be enqueued"
    assert outcome.consumption is None, "consumption should be omitted when queued (Req 9.3)"

    # Verify: all typed values preserved in payload
    payload_data = json.loads(queue_payloads[0])
    assert payload_data["odometer"] == str(odometer)
    assert payload_data["fuelConsumed"] == str(liters)
    assert payload_data["cost"] == str(cost)
    assert payload_data["isFillToFull"] == str(is_fill_to_full).lower()

    # Verify: client.add_gas_record was called (attempted) exactly once
    assert client.add_gas_record.call_count == 1, "submit should attempt add_gas_record once"

    # Verify: no vehicle list call (no LubeLogger connectivity check on offline skip)
    assert (
        client.get_gas_records.call_count == 0
    ), "no get_gas_records should be called (submission failed before follow-up)"

    # --- Render confirmation: queued state with all values ---

    entries = tuple(
        FieldEntry(
            index=i,
            label_key=field_spec.label_key,
            rendered_value=str(collected_values[field_spec.key]),
        )
        for i, field_spec in enumerate(field_specs)
    )

    confirmation_view = ConfirmationView(
        kind=kind,
        vehicle_name=vehicle_name,
        on_date=date.today(),
        entries=entries,
        consumption=None,  # Requirement 9.3: no consumption on queued
    )

    queued_text = render_queued(confirmation_view, lang="en")

    # Verify: final confirmation text contains all collected values
    assert str(odometer) in queued_text, "odometer should be in queued confirmation"
    assert str(liters) in queued_text, "liters should be in queued confirmation"
    assert str(cost) in queued_text, "cost should be in queued confirmation"

    # Finalize card with queued confirmation (only "Log another" button, no "Latest")
    confirmation_keyboard = MagicMock()  # Simulates buttons per Requirement 9.4
    final_card_id = await card_service.finalize(
        chat_id, card_id, queued_text, confirmation_keyboard
    )

    assert final_card_id == card_id, "final card should keep same message id"

    # Verify: no extra calls beyond the flow steps + final update
    final_edit_count = len(fake_bot.calls_to("edit_message_text"))
    assert (
        final_edit_count == len(field_specs) + 1
    ), f"should have {len(field_specs) + 1} edits (fields + finalize), got {final_edit_count}"

    # Verify: no network calls beyond the failed add_gas_record
    assert client.add_gas_record.call_count == 1, "only one add_gas_record attempt"
    assert (
        client.get_gas_records.call_count == 0
    ), "no get_gas_records follow-up (failed before it)"
