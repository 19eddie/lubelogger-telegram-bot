"""Unit tests for bot.services.record_submitter."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.flows.definitions import FlowKind
from bot.models.records import GasRecord
from bot.models.responses import ApiResponse
from bot.services.consumption import ConsumptionResult
from bot.services.odometer_tracker import OdometerReference, OdometerTracker
from bot.services.record_submitter import RecordSubmitter, SubmitOutcome


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.add_gas_record = AsyncMock(return_value=ApiResponse(success=True, message="ok"))
    client.add_service_record = AsyncMock(return_value=ApiResponse(success=True, message="ok"))
    client.add_odometer_record = AsyncMock(return_value=ApiResponse(success=True, message="ok"))
    client.get_gas_records = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_queue() -> AsyncMock:
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=1)
    return queue


@pytest.fixture
def mock_tracker() -> AsyncMock:
    tracker = AsyncMock()
    tracker.observe = AsyncMock()
    tracker.observe_records = AsyncMock()
    return tracker


@pytest.fixture
def mock_config_store() -> AsyncMock:
    store = AsyncMock()
    store.get_active_vehicle_name = AsyncMock(return_value="Fiat Panda")
    return store


@pytest.fixture
def submitter(
    mock_client: AsyncMock,
    mock_queue: AsyncMock,
    mock_tracker: AsyncMock,
    mock_config_store: AsyncMock,
) -> RecordSubmitter:
    return RecordSubmitter(
        client=mock_client,
        queue=mock_queue,
        tracker=mock_tracker,
        config_store=mock_config_store,
    )


# ------------------------------------------------------------------
# Fuel record — successful save, no consumption (empty records)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_fuel_saved_no_consumption(
    submitter: RecordSubmitter, mock_client: AsyncMock, mock_tracker: AsyncMock
) -> None:
    """Fuel save succeeds, get_gas_records returns empty → saved, no consumption."""
    mock_client.get_gas_records.return_value = []

    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.FUEL,
        values={"odometer": 50000, "liters": 40.5, "cost": 75.0, "is_fill_to_full": True},
    )

    assert outcome.status == "saved"
    assert outcome.consumption is None
    assert outcome.vehicle_name == "Fiat Panda"
    mock_client.add_gas_record.assert_awaited_once()
    mock_client.get_gas_records.assert_awaited_once_with(1)
    mock_tracker.observe.assert_awaited_once()


# ------------------------------------------------------------------
# Fuel record — consumption resolved from two records
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_fuel_saved_with_consumption(
    submitter: RecordSubmitter, mock_client: AsyncMock
) -> None:
    """Fuel save + 2 gas records → consumption resolved."""
    previous = GasRecord(
        id=1,
        date=dt.date(2025, 7, 1),
        odometer=49500,
        fuel_consumed=Decimal("35.0"),
        cost=Decimal("60.0"),
        fuel_economy=Decimal("7.0"),
        is_fill_to_full=True,
        missed_fuel_up=False,
    )
    current = GasRecord(
        id=2,
        date=dt.date(2025, 7, 10),
        odometer=50000,
        fuel_consumed=Decimal("40.5"),
        cost=Decimal("75.0"),
        fuel_economy=Decimal("8.1"),
        is_fill_to_full=True,
        missed_fuel_up=False,
    )
    mock_client.get_gas_records.return_value = [previous, current]

    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.FUEL,
        values={"odometer": 50000, "liters": 40.5, "cost": 75.0, "is_fill_to_full": True},
    )

    assert outcome.status == "saved"
    assert outcome.consumption is not None
    # reported fuelEconomy = 8.1 > 0 → used as-is (not estimated)
    assert outcome.consumption.estimated is False
    assert outcome.consumption.value == Decimal("8.1")


# ------------------------------------------------------------------
# Fuel record — follow-up fails → saved with no consumption (Req 6.9)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_fuel_followup_fails(
    submitter: RecordSubmitter, mock_client: AsyncMock
) -> None:
    """When get_gas_records fails, outcome is still saved with consumption=None."""
    mock_client.get_gas_records.side_effect = LubeLoggerUnreachableError("timeout")

    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.FUEL,
        values={"odometer": 50000, "liters": 40.5, "cost": 75.0, "is_fill_to_full": True},
    )

    assert outcome.status == "saved"
    assert outcome.consumption is None


# ------------------------------------------------------------------
# Service record — successful save
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_service_saved(
    submitter: RecordSubmitter, mock_client: AsyncMock, mock_tracker: AsyncMock
) -> None:
    """Service record saves without consumption resolution."""
    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.SERVICE,
        values={"odometer": 60000, "description": "Oil change", "cost": 120.0},
    )

    assert outcome.status == "saved"
    assert outcome.consumption is None
    mock_client.add_service_record.assert_awaited_once()
    mock_client.get_gas_records.assert_not_awaited()
    mock_tracker.observe.assert_awaited_once()


# ------------------------------------------------------------------
# Odometer record — successful save
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_odometer_saved(
    submitter: RecordSubmitter, mock_client: AsyncMock, mock_tracker: AsyncMock
) -> None:
    """Odometer record saves without consumption resolution."""
    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.ODOMETER,
        values={"odometer": 70000},
    )

    assert outcome.status == "saved"
    assert outcome.consumption is None
    mock_client.add_odometer_record.assert_awaited_once()
    mock_client.get_gas_records.assert_not_awaited()
    mock_tracker.observe.assert_awaited_once()


# ------------------------------------------------------------------
# Unreachable → enqueue (Req 9.1, 9.3)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_unreachable_enqueues(
    submitter: RecordSubmitter,
    mock_client: AsyncMock,
    mock_queue: AsyncMock,
    mock_tracker: AsyncMock,
) -> None:
    """When LubeLogger is unreachable, the record is enqueued and odometer observed."""
    mock_client.add_gas_record.side_effect = LubeLoggerUnreachableError("down")

    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.FUEL,
        values={"odometer": 50000, "liters": 40.5, "cost": 75.0, "is_fill_to_full": True},
    )

    assert outcome.status == "queued"
    assert outcome.consumption is None
    mock_queue.enqueue.assert_awaited_once()
    # Verify enqueue args: user_id, vehicle_id, record_type, payload_json
    call_args = mock_queue.enqueue.call_args
    assert call_args[0][0] == 100  # user_id
    assert call_args[0][1] == 1  # vehicle_id
    assert call_args[0][2] == "gas"  # record_type
    # Odometer still observed
    mock_tracker.observe.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_service_unreachable_enqueues(
    submitter: RecordSubmitter,
    mock_client: AsyncMock,
    mock_queue: AsyncMock,
) -> None:
    """Service record enqueued when unreachable."""
    mock_client.add_service_record.side_effect = LubeLoggerUnreachableError("down")

    outcome = await submitter.submit(
        user_id=200,
        vehicle_id=2,
        kind=FlowKind.SERVICE,
        values={"odometer": 60000, "description": "Brakes", "cost": 300.0},
    )

    assert outcome.status == "queued"
    call_args = mock_queue.enqueue.call_args
    assert call_args[0][2] == "service"


# ------------------------------------------------------------------
# Vehicle name fallback
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicle_name_fallback_empty_string(
    submitter: RecordSubmitter, mock_config_store: AsyncMock
) -> None:
    """When config_store returns None, vehicle_name is empty string."""
    mock_config_store.get_active_vehicle_name.return_value = None

    outcome = await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.ODOMETER,
        values={"odometer": 80000},
    )

    assert outcome.vehicle_name == ""


# ------------------------------------------------------------------
# Odometer observation has correct source and date
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_odometer_observed_with_bot_source(
    submitter: RecordSubmitter, mock_tracker: AsyncMock
) -> None:
    """The odometer observation uses source='bot' and extracts date from values."""
    await submitter.submit(
        user_id=100,
        vehicle_id=1,
        kind=FlowKind.FUEL,
        values={
            "odometer": 50000,
            "liters": 40.5,
            "cost": 75.0,
            "is_fill_to_full": True,
            "date": "2025-07-10",
        },
    )

    ref = mock_tracker.observe.call_args[0][1]
    assert isinstance(ref, OdometerReference)
    assert ref.value == 50000
    assert ref.source == "bot"
    assert ref.on_date == dt.date(2025, 7, 10)


# ------------------------------------------------------------------
# API error propagates (not enqueued)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_error_propagates(
    submitter: RecordSubmitter, mock_client: AsyncMock, mock_queue: AsyncMock
) -> None:
    """LubeLoggerApiError is not caught (only unreachable triggers enqueue)."""
    mock_client.add_gas_record.side_effect = LubeLoggerApiError(400, "bad request")

    with pytest.raises(LubeLoggerApiError):
        await submitter.submit(
            user_id=100,
            vehicle_id=1,
            kind=FlowKind.FUEL,
            values={"odometer": 50000, "liters": 40.5, "cost": 75.0, "is_fill_to_full": True},
        )

    mock_queue.enqueue.assert_not_awaited()
