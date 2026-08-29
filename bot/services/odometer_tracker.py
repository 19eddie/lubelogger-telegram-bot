"""Last_Known_Odometer tracking, persisted per vehicle in `vehicle_state`.

The odometer reference the Bot shows while prompting is the maximum across
everything it has seen for a vehicle: the latest gas, service and odometer
records, whatever `/api/vehicle/info` reported, and every value the Bot itself
submitted or queued (Requirement 5.4).

`fold` is the pure core of that rule, so maximality and order-independence are
provable without touching SQLite. Everything else in this module is persistence
around it. `get_reference` is a local read only: advancing a step of a flow must
cost zero API calls (NF-2.3), and an unreachable instance must still leave a
usable reference behind (Requirement 5.6).

This module is the only writer of the `vehicle_state` table.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import reduce
from typing import TYPE_CHECKING, Literal, get_args

from bot.services.database import get_db

if TYPE_CHECKING:
    from bot.models.records import GasRecord, OdometerRecord, ServiceRecord, VehicleSnapshot

logger = logging.getLogger(__name__)

OdometerSource = Literal["gas", "service", "odometer", "bot", "api"]

_SOURCES: frozenset[str] = frozenset(get_args(OdometerSource))
_DEFAULT_SOURCE: OdometerSource = "bot"


@dataclass(frozen=True, slots=True)
class OdometerReference:
    """An odometer value with the date and the origin it was observed from."""

    value: int
    on_date: dt.date | None
    source: OdometerSource


def fold(
    current: OdometerReference | None,
    candidate: OdometerReference | None,
) -> OdometerReference | None:
    """Return the reference that should be kept between the two.

    Pure and total: the candidate wins only when its value is strictly greater
    than the current one, so folding is idempotent, monotone and independent of
    the order the observations arrive in (Requirement 5.4).
    """
    if candidate is None:
        return current
    if current is None:
        return candidate
    return candidate if candidate.value > current.value else current


class OdometerTracker:
    """Reads and updates the locally persisted Last_Known_Odometer per vehicle.

    The state is keyed by vehicle, not by user: a vehicle is shared by the
    whitelisted users and its odometer is a property of the vehicle
    (Requirement 5.5).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def get_reference(self, vehicle_id: int) -> OdometerReference | None:
        """Return the locally known reference for a vehicle, or None.

        Never performs a network call. Returns None when nothing has ever been
        observed for that vehicle, which the renderer turns into no reference
        line at all (Requirement 5.6).
        """
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                """SELECT last_odometer, last_odometer_date, last_odometer_source
                FROM vehicle_state WHERE vehicle_id = ?""",
                (vehicle_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return OdometerReference(
            value=int(row["last_odometer"]),
            on_date=_parse_date(row["last_odometer_date"]),
            source=_coerce_source(row["last_odometer_source"]),
        )

    async def observe(self, vehicle_id: int, candidate: OdometerReference) -> None:
        """Record one observation, keeping the greater of stored and candidate."""
        await self._persist(vehicle_id, candidate)

    async def observe_snapshot(self, snapshot: VehicleSnapshot) -> None:
        """Record the odometer LubeLogger reports for the snapshot's vehicle.

        A snapshot coming from the `/api/vehicles` fallback carries no odometer
        at all, in which case there is nothing to observe.
        """
        if snapshot.last_reported_odometer is None:
            return
        await self._persist(
            snapshot.vehicle.id,
            OdometerReference(
                value=snapshot.last_reported_odometer,
                on_date=None,
                source="api",
            ),
        )

    async def observe_records(
        self,
        vehicle_id: int,
        *,
        gas: Sequence[GasRecord] = (),
        service: Sequence[ServiceRecord] = (),
        odometer: Sequence[OdometerRecord] = (),
    ) -> None:
        """Record every odometer carried by the given records in one write.

        Records without an odometer are ignored. The candidates are folded in
        memory first, so a batch of any size costs a single database write.
        """
        candidates: list[OdometerReference] = [
            *_references(gas, "gas"),
            *_references(service, "service"),
            *_references(odometer, "odometer"),
        ]
        best = reduce(fold, candidates, None)
        if best is None:
            return
        await self._persist(vehicle_id, best)

    async def _persist(self, vehicle_id: int, candidate: OdometerReference) -> None:
        """Apply the fold against the stored row and write it back when it wins.

        The `WHERE` clause of the upsert mirrors `fold`, which makes the update
        atomic: two concurrent observations cannot make the stored value go
        backwards (Requirement 5.5).
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                """INSERT INTO vehicle_state
                (vehicle_id, last_odometer, last_odometer_date, last_odometer_source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(vehicle_id) DO UPDATE SET
                    last_odometer = excluded.last_odometer,
                    last_odometer_date = excluded.last_odometer_date,
                    last_odometer_source = excluded.last_odometer_source,
                    updated_at = excluded.updated_at
                WHERE excluded.last_odometer > vehicle_state.last_odometer""",
                (
                    vehicle_id,
                    candidate.value,
                    candidate.on_date.isoformat() if candidate.on_date is not None else None,
                    candidate.source,
                    now,
                ),
            )
            await db.commit()


def _references(
    records: Iterable[GasRecord | ServiceRecord | OdometerRecord],
    source: OdometerSource,
) -> list[OdometerReference]:
    """Turn records into references, dropping those without an odometer."""
    return [
        OdometerReference(value=record.odometer, on_date=record.date, source=source)
        for record in records
        if record.odometer is not None
    ]


def _parse_date(value: object) -> dt.date | None:
    """Parse a stored ISO date, tolerating a missing or corrupted value."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        logger.debug("Discarding unparsable stored odometer date")
        return None


def _coerce_source(value: object) -> OdometerSource:
    """Map a stored source onto the known set, defaulting to 'bot'."""
    if isinstance(value, str) and value in _SOURCES:
        return value  # type: ignore[return-value]
    return _DEFAULT_SOURCE
