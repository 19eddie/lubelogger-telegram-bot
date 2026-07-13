"""Property-based tests for Queue Service FIFO ordering, enqueue-dequeue, and retry exhaustion."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.database import init_db
from bot.services.queue_service import QueueService

# Shared database path and initialization for all hypothesis examples
_DB_PATH = os.path.join(tempfile.gettempdir(), f"pbt_queue_service_{os.getpid()}.db")
_DB_INITIALIZED = False


async def _get_service(max_retries: int = 3) -> QueueService:
    """Get a QueueService backed by a shared test database (initialized once)."""
    global _DB_INITIALIZED  # noqa: PLW0603
    if not _DB_INITIALIZED:
        if os.path.exists(_DB_PATH):
            os.unlink(_DB_PATH)
        await init_db(_DB_PATH)
        _DB_INITIALIZED = True
    return QueueService(_DB_PATH, max_retries=max_retries)


# Strategies
_user_id_st = st.integers(min_value=1, max_value=2**31)
_vehicle_id_st = st.integers(min_value=1, max_value=10000)
_record_type_st = st.sampled_from(["gas", "service", "odometer"])
_payload_st = st.fixed_dictionaries(
    {"date": st.just("2024-01-01"), "odometer": st.just("45000")}
).map(json.dumps)


@settings(max_examples=100, deadline=None)
@given(
    user_id=_user_id_st,
    vehicle_id=_vehicle_id_st,
    records=st.lists(
        st.tuples(_record_type_st, _payload_st),
        min_size=2,
        max_size=5,
    ),
)
@pytest.mark.asyncio
async def test_property_queue_fifo_ordering(
    user_id: int,
    vehicle_id: int,
    records: list[tuple[str, str]],
) -> None:
    """For any sequence of records enqueued at distinct timestamps,
    get_pending() returns them ordered by creation time ascending.

    # Feature: lubelogger-telegram-bot, Property 12: Queue FIFO ordering

    **Validates: Requirements 8.1, 8.5**
    """
    service = await _get_service()

    # Enqueue records sequentially and collect their IDs
    enqueued_ids: list[int] = []
    for record_type, payload in records:
        item_id = await service.enqueue(user_id, vehicle_id, record_type, payload)
        enqueued_ids.append(item_id)

    # Retrieve pending items
    pending = await service.get_pending()

    # Filter to only the IDs we just inserted (shared DB may have other items)
    pending_ids = [item.id for item in pending if item.id in enqueued_ids]

    # Verify FIFO order: IDs should appear in the same order they were enqueued
    assert pending_ids == enqueued_ids

    # Clean up: mark all as sent so they don't pollute other test runs
    for item_id in enqueued_ids:
        await service.mark_sent(item_id)


@settings(max_examples=100, deadline=None)
@given(
    user_id=_user_id_st,
    vehicle_id=_vehicle_id_st,
    record_type=_record_type_st,
    payload=_payload_st,
)
@pytest.mark.asyncio
async def test_property_queue_enqueue_dequeue(
    user_id: int,
    vehicle_id: int,
    record_type: str,
    payload: str,
) -> None:
    """For any valid record payload enqueued via enqueue(), the item appears in
    get_pending() with status pending, and after mark_sent() it no longer
    appears in pending results.

    # Feature: lubelogger-telegram-bot, Property 13: Queue enqueue-dequeue consistency

    **Validates: Requirements 8.1, 8.4, 8.7**
    """
    service = await _get_service()

    # Enqueue a record
    item_id = await service.enqueue(user_id, vehicle_id, record_type, payload)

    # Verify it appears in pending with correct status
    pending = await service.get_pending()
    matching = [item for item in pending if item.id == item_id]
    assert len(matching) == 1
    assert matching[0].status == "pending"
    assert matching[0].user_id == user_id
    assert matching[0].vehicle_id == vehicle_id
    assert matching[0].record_type == record_type
    assert matching[0].payload == payload

    # Mark as sent
    await service.mark_sent(item_id)

    # Verify it no longer appears in pending
    pending_after = await service.get_pending()
    matching_after = [item for item in pending_after if item.id == item_id]
    assert len(matching_after) == 0


@settings(max_examples=100)
@given(
    user_id=_user_id_st,
    vehicle_id=_vehicle_id_st,
    record_type=_record_type_st,
    payload=_payload_st,
)
@pytest.mark.asyncio
async def test_property_queue_retry_exhaustion(
    user_id: int,
    vehicle_id: int,
    record_type: str,
    payload: str,
) -> None:
    """After exactly 3 consecutive failed retry attempts (increment_retry reaching
    max_retry_attempts), mark_failed() sets status to failed and the item no
    longer appears in pending results.

    # Feature: lubelogger-telegram-bot, Property 14: Queue retry exhaustion marks failure

    **Validates: Requirements 8.8**
    """
    service = await _get_service(max_retries=3)

    # Enqueue a record
    item_id = await service.enqueue(user_id, vehicle_id, record_type, payload)

    # Increment retry 3 times
    count_1 = await service.increment_retry(item_id)
    assert count_1 == 1
    count_2 = await service.increment_retry(item_id)
    assert count_2 == 2
    count_3 = await service.increment_retry(item_id)
    assert count_3 == 3

    # After 3 retries (== max_retries), mark as failed
    assert count_3 >= service.max_retries
    await service.mark_failed(item_id)

    # Verify it no longer appears in pending
    pending = await service.get_pending()
    matching = [item for item in pending if item.id == item_id]
    assert len(matching) == 0
