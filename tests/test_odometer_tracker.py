"""Unit tests for the Last_Known_Odometer tracker.

Covers Requirements 5.4 (maximum across every observation), 5.5 (per-vehicle local
persistence), 5.6 (no reference when nothing is known locally), NF-2.3 (reads are local)
and NF-2.5 (nothing beyond the odometer is persisted).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import tempfile
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import get_args

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.models.records import GasRecord, OdometerRecord, ServiceRecord, VehicleSnapshot
from bot.models.responses import Vehicle
from bot.services.database import init_db
from bot.services.odometer_tracker import (
    OdometerReference,
    OdometerSource,
    OdometerTracker,
    fold,
)


async def _tracker(tmp_path: Path, name: str = "odo.db") -> OdometerTracker:
    db_path = str(tmp_path / name)
    await init_db(db_path)
    return OdometerTracker(db_path)


def _ref(value: int, source: str = "bot", on_date: dt.date | None = None) -> OdometerReference:
    return OdometerReference(value=value, on_date=on_date, source=source)  # type: ignore[arg-type]


def test_fold_keeps_the_greater_value() -> None:
    """The candidate wins only when its value is strictly greater."""
    lower = _ref(100, "gas")
    higher = _ref(200, "api")

    assert fold(lower, higher) is higher
    assert fold(higher, lower) is higher
    # A tie keeps the current reference, so folding is idempotent.
    assert fold(higher, _ref(200, "service")) is higher


def test_fold_handles_missing_sides() -> None:
    """None on either side is neutral."""
    reference = _ref(500)

    assert fold(None, reference) is reference
    assert fold(reference, None) is reference
    assert fold(None, None) is None


async def test_get_reference_is_none_when_nothing_is_known(tmp_path: Path) -> None:
    """An unobserved vehicle has no reference at all (Requirement 5.6)."""
    tracker = await _tracker(tmp_path)

    assert await tracker.get_reference(7) is None


async def test_observe_roundtrips_value_date_and_source(tmp_path: Path) -> None:
    """A stored reference reads back with its value, date and source."""
    tracker = await _tracker(tmp_path)
    on_date = dt.date(2025, 7, 12)

    await tracker.observe(7, _ref(45_230, "gas", on_date))
    stored = await tracker.get_reference(7)

    assert stored == OdometerReference(value=45_230, on_date=on_date, source="gas")


async def test_observe_never_lowers_the_stored_value(tmp_path: Path) -> None:
    """A lower observation leaves the persisted reference untouched (Requirement 5.5)."""
    tracker = await _tracker(tmp_path)

    await tracker.observe(7, _ref(45_230, "gas", dt.date(2025, 7, 12)))
    await tracker.observe(7, _ref(1_000, "bot", dt.date(2025, 8, 1)))
    stored = await tracker.get_reference(7)

    assert stored is not None
    assert stored.value == 45_230
    assert stored.source == "gas"


async def test_state_is_keyed_by_vehicle(tmp_path: Path) -> None:
    """Two vehicles keep independent references."""
    tracker = await _tracker(tmp_path)

    await tracker.observe(1, _ref(100))
    await tracker.observe(2, _ref(9_000))

    first = await tracker.get_reference(1)
    second = await tracker.get_reference(2)
    assert first is not None and first.value == 100
    assert second is not None and second.value == 9_000


async def test_observe_snapshot_records_the_api_value(tmp_path: Path) -> None:
    """A snapshot carrying an odometer is stored with source 'api'."""
    tracker = await _tracker(tmp_path)
    snapshot = VehicleSnapshot(
        vehicle=Vehicle(id=3, make="Fiat", model="Panda"),
        lastReportedOdometer="52100",
    )

    await tracker.observe_snapshot(snapshot)
    stored = await tracker.get_reference(3)

    assert stored == OdometerReference(value=52_100, on_date=None, source="api")


async def test_observe_snapshot_without_odometer_stores_nothing(tmp_path: Path) -> None:
    """The /api/vehicles fallback carries no odometer, so there is nothing to observe."""
    tracker = await _tracker(tmp_path)
    snapshot = VehicleSnapshot(vehicle=Vehicle(id=3, make="Fiat", model="Panda"))

    await tracker.observe_snapshot(snapshot)

    assert await tracker.get_reference(3) is None


async def test_observe_records_takes_the_maximum_across_kinds(tmp_path: Path) -> None:
    """The reference is the maximum across gas, service and odometer records (Req 5.4)."""
    tracker = await _tracker(tmp_path)

    await tracker.observe_records(
        4,
        gas=[GasRecord(odometer=1_000, date=dt.date(2025, 1, 1))],
        service=[ServiceRecord(odometer=3_000, date=dt.date(2025, 3, 1))],
        odometer=[OdometerRecord(odometer=2_000, date=dt.date(2025, 2, 1))],
    )
    stored = await tracker.get_reference(4)

    assert stored == OdometerReference(value=3_000, on_date=dt.date(2025, 3, 1), source="service")


async def test_observe_records_ignores_records_without_an_odometer(tmp_path: Path) -> None:
    """Records with no odometer contribute nothing and leave the state empty."""
    tracker = await _tracker(tmp_path)

    await tracker.observe_records(4, gas=[GasRecord(cost="10.00")])

    assert await tracker.get_reference(4) is None


async def test_observe_records_with_no_records_at_all(tmp_path: Path) -> None:
    """An empty batch is a no-op, not an error."""
    tracker = await _tracker(tmp_path)

    await tracker.observe_records(4)

    assert await tracker.get_reference(4) is None


async def test_corrupted_stored_date_reads_as_absent(tmp_path: Path) -> None:
    """An unparsable stored date degrades to None instead of raising."""
    db_path = str(tmp_path / "corrupt.db")
    await init_db(db_path)
    tracker = OdometerTracker(db_path)
    await tracker.observe(9, _ref(500, "gas", dt.date(2025, 5, 5)))

    from bot.services.database import get_db  # local import: test-only fixup

    async with get_db(db_path) as db:
        await db.execute(
            "UPDATE vehicle_state SET last_odometer_date = 'not-a-date' WHERE vehicle_id = 9"
        )
        await db.commit()

    stored = await tracker.get_reference(9)
    assert stored is not None
    assert stored.value == 500
    assert stored.on_date is None


# ---------------------------------------------------------------------------
# Property 1: Last_Known_Odometer fold is maximal and order-independent
# ---------------------------------------------------------------------------

_sources = st.sampled_from(get_args(OdometerSource))
_observation_dates = st.one_of(
    st.none(),
    st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 1, 1)),
)


@st.composite
def _observation_sequences(
    draw: st.DrawFn,
) -> tuple[list[OdometerReference | None], list[OdometerReference | None]]:
    """Draw an observation sequence and a permutation of it.

    Values are unique so the maximum is unambiguous: two observations sharing the
    greatest value would legitimately differ in date and source depending on which
    one arrived first, which is outside what this property states. Absent
    observations are interleaved because `fold` must treat them as neutral.
    """
    values = draw(st.lists(st.integers(min_value=1, max_value=3_000_000), max_size=12, unique=True))
    observations: list[OdometerReference | None] = [
        OdometerReference(
            value=value,
            on_date=draw(_observation_dates),
            source=draw(_sources),
        )
        for value in values
    ]
    observations.extend([None] * draw(st.integers(min_value=0, max_value=3)))

    sequence = draw(st.permutations(observations))
    permuted = draw(st.permutations(sequence))
    return list(sequence), list(permuted)


@settings(max_examples=100, deadline=None)
@given(sequences=_observation_sequences())
def test_property_odometer_fold_is_max(
    sequences: tuple[list[OdometerReference | None], list[OdometerReference | None]],
) -> None:
    """# Feature: improve-ux, Property 1: Last_Known_Odometer fold is maximal and order-independent

    For any finite sequence of odometer observations for a vehicle, folding them with `fold`
    yields a reference whose value equals the maximum of the observed values, and any
    permutation of the same sequence yields the same value, date and source.

    Validates: Requirements 5.4
    """
    sequence, permuted = sequences
    observed = [item for item in sequence if item is not None]

    result = reduce(fold, sequence, None)
    permuted_result = reduce(fold, permuted, None)

    if not observed:
        assert result is None
        assert permuted_result is None
        return

    assert result is not None
    assert result.value == max(item.value for item in observed)
    # The winning reference is one of the observations, carried through intact.
    assert result in observed
    # Order-independence covers the whole reference, not only its value.
    assert permuted_result == result


# ---------------------------------------------------------------------------
# Property 2: Persisted Last_Known_Odometer never decreases
# ---------------------------------------------------------------------------

_PROPERTY_VEHICLE_ID = 42

_odometer_values = st.integers(min_value=1, max_value=3_000_000)


@dataclass(frozen=True, slots=True)
class _ObserveOp:
    """A single direct observation, as the Bot makes after a save."""

    value: int
    source: OdometerSource
    on_date: dt.date | None


@dataclass(frozen=True, slots=True)
class _RecordsOp:
    """A batch of records; a `None` odometer stands for a record that carries none."""

    gas: tuple[int | None, ...]
    service: tuple[int | None, ...]
    odometer: tuple[int | None, ...]


@dataclass(frozen=True, slots=True)
class _SnapshotOp:
    """A `/api/vehicle/info` snapshot; `None` is the `/api/vehicles` fallback."""

    value: int | None


_Op = _ObserveOp | _RecordsOp | _SnapshotOp

_record_odometers = st.lists(st.one_of(st.none(), _odometer_values), max_size=4).map(tuple)

_ops = st.one_of(
    st.builds(_ObserveOp, value=_odometer_values, source=_sources, on_date=_observation_dates),
    st.builds(
        _RecordsOp, gas=_record_odometers, service=_record_odometers, odometer=_record_odometers
    ),
    st.builds(_SnapshotOp, value=st.one_of(st.none(), _odometer_values)),
)


def _contributed(op: _Op) -> list[int]:
    """The odometer values an operation offers to the tracker."""
    if isinstance(op, _ObserveOp):
        return [op.value]
    if isinstance(op, _SnapshotOp):
        return [] if op.value is None else [op.value]
    return [value for value in (*op.gas, *op.service, *op.odometer) if value is not None]


async def _apply(tracker: OdometerTracker, op: _Op) -> None:
    """Route one operation to the matching tracker entry point."""
    if isinstance(op, _ObserveOp):
        await tracker.observe(
            _PROPERTY_VEHICLE_ID,
            OdometerReference(value=op.value, on_date=op.on_date, source=op.source),
        )
    elif isinstance(op, _SnapshotOp):
        vehicle = Vehicle(id=_PROPERTY_VEHICLE_ID, make="Fiat", model="Panda")
        snapshot = (
            VehicleSnapshot(vehicle=vehicle)
            if op.value is None
            else VehicleSnapshot(vehicle=vehicle, lastReportedOdometer=op.value)
        )
        await tracker.observe_snapshot(snapshot)
    else:
        await tracker.observe_records(
            _PROPERTY_VEHICLE_ID,
            gas=[GasRecord(odometer=value) for value in op.gas],
            service=[ServiceRecord(odometer=value) for value in op.service],
            odometer=[OdometerRecord(odometer=value) for value in op.odometer],
        )


async def _persisted_readings(ops: list[_Op]) -> list[int | None]:
    """Apply the operations to a fresh database, reading the reference after each one."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "monotonic.db")
        await init_db(db_path)
        tracker = OdometerTracker(db_path)

        readings: list[int | None] = []
        for op in ops:
            await _apply(tracker, op)
            reference = await tracker.get_reference(_PROPERTY_VEHICLE_ID)
            readings.append(None if reference is None else reference.value)
        return readings


@settings(max_examples=100, deadline=None)
@given(ops=st.lists(_ops, max_size=10))
def test_property_odometer_monotonic(ops: list[_Op]) -> None:
    """# Feature: improve-ux, Property 2: Persisted Last_Known_Odometer never decreases

    For any sequence of observations applied to a vehicle, the persisted reference read back
    after every step is greater than or equal to the previous one, and equals the running
    maximum of every value observed so far.

    Validates: Requirements 5.5
    """
    readings = asyncio.run(_persisted_readings(ops))

    assert len(readings) == len(ops)

    running_max: int | None = None
    previous: int | None = None
    for op, reading in zip(ops, readings, strict=True):
        contributed = _contributed(op)
        if contributed:
            candidate = max(contributed)
            running_max = candidate if running_max is None else max(running_max, candidate)

        # Nothing observed yet leaves no reference at all; afterwards the stored value is
        # exactly the running maximum and can never have gone backwards.
        assert reading == running_max
        if previous is not None:
            assert reading is not None
            assert reading >= previous
        previous = reading
