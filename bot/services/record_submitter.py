"""Record submission: save to LubeLogger or enqueue for later.

Single entry point for both the guided-flow path and the inline-argument path,
which is how Requirement 12.2 stays true by construction. On a successful fuel
save, one follow-up call resolves the Consumption_Metric (Requirements 6.5, 6.6).
On LubeLoggerUnreachableError the record is queued and the odometer is still
observed (Requirements 9.1, 9.3).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.flows.definitions import FlowKind
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel
from bot.services.config_store import ConfigStore
from bot.services.consumption import ConsumptionResult, FuelPoint, resolve
from bot.services.lubelogger_client import LubeLoggerClient
from bot.services.odometer_tracker import OdometerReference, OdometerTracker
from bot.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# FlowKind → record_type string expected by QueueService
_KIND_TO_RECORD_TYPE: dict[FlowKind, str] = {
    FlowKind.FUEL: "gas",
    FlowKind.SERVICE: "service",
    FlowKind.ODOMETER: "odometer",
}


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """Result of a record submission attempt."""

    status: Literal["saved", "queued"]
    consumption: ConsumptionResult | None
    vehicle_name: str


class RecordSubmitter:
    """Builds, validates and submits (or enqueues) a record for any flow kind.

    This is the only module that decides between "save" and "enqueue", so both
    the inline-argument path and the guided-card path produce identical outcomes
    (Requirement 12.2).
    """

    def __init__(
        self,
        client: LubeLoggerClient,
        queue: QueueService,
        tracker: OdometerTracker,
        config_store: ConfigStore,
    ) -> None:
        self._client = client
        self._queue = queue
        self._tracker = tracker
        self._config_store = config_store

    async def submit(
        self,
        *,
        user_id: int,
        vehicle_id: int,
        kind: FlowKind,
        values: Mapping[str, object],
    ) -> SubmitOutcome:
        """Validate, build and send (or enqueue) a record.

        Args:
            user_id: Telegram user ID of the submitting user.
            vehicle_id: Target LubeLogger vehicle ID.
            kind: Which record type to submit.
            values: Collected field values keyed by field name.

        Returns:
            A SubmitOutcome with status, optional consumption, and vehicle name.
        """
        vehicle_name = await self._resolve_vehicle_name(user_id)
        payload, odometer_value = _build_payload(kind, values)

        try:
            await self._send(vehicle_id, kind, payload)
        except LubeLoggerUnreachableError:
            logger.warning("LubeLogger unreachable, enqueueing %s record", kind.value)
            await self._enqueue(user_id, vehicle_id, kind, payload)
            await self._observe_odometer(vehicle_id, odometer_value, values)
            return SubmitOutcome(status="queued", consumption=None, vehicle_name=vehicle_name)

        # Saved successfully — observe odometer
        await self._observe_odometer(vehicle_id, odometer_value, values)

        # Fuel-only: resolve consumption metric
        consumption: ConsumptionResult | None = None
        if kind is FlowKind.FUEL:
            consumption = await self._resolve_consumption(vehicle_id)

        return SubmitOutcome(status="saved", consumption=consumption, vehicle_name=vehicle_name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_vehicle_name(self, user_id: int) -> str:
        """Get the persisted vehicle name, falling back to empty string."""
        name = await self._config_store.get_active_vehicle_name(user_id)
        return name or ""

    async def _send(
        self,
        vehicle_id: int,
        kind: FlowKind,
        payload: GasRecordPayload | ServiceRecordPayload | OdometerRecordPayload,
    ) -> None:
        """Dispatch the payload to the correct client method.

        Raises:
            LubeLoggerUnreachableError: When the instance is unreachable.
            LubeLoggerApiError: On API-level errors (not retried here).
        """
        if kind is FlowKind.FUEL:
            assert isinstance(payload, GasRecordPayload)
            await self._client.add_gas_record(vehicle_id, payload)
        elif kind is FlowKind.SERVICE:
            assert isinstance(payload, ServiceRecordPayload)
            await self._client.add_service_record(vehicle_id, payload)
        else:
            assert isinstance(payload, OdometerRecordPayload)
            await self._client.add_odometer_record(vehicle_id, payload)

    async def _enqueue(
        self,
        user_id: int,
        vehicle_id: int,
        kind: FlowKind,
        payload: GasRecordPayload | ServiceRecordPayload | OdometerRecordPayload,
    ) -> None:
        """Persist the record into the offline queue."""
        record_type = _KIND_TO_RECORD_TYPE[kind]
        payload_json = payload.model_dump_json(by_alias=True)
        await self._queue.enqueue(user_id, vehicle_id, record_type, payload_json)

    async def _observe_odometer(
        self, vehicle_id: int, odometer_value: int, values: Mapping[str, object]
    ) -> None:
        """Record the odometer observation into the tracker (Requirement 5.5)."""
        on_date = _extract_date(values)
        ref = OdometerReference(value=odometer_value, on_date=on_date, source="bot")
        await self._tracker.observe(vehicle_id, ref)

    async def _resolve_consumption(self, vehicle_id: int) -> ConsumptionResult | None:
        """Fetch gas records and compute consumption after a successful fuel save.

        On any failure the outcome stays saved with no consumption (Req 6.9).
        """
        try:
            records = await self._client.get_gas_records(vehicle_id)
        except (LubeLoggerUnreachableError, LubeLoggerApiError):
            logger.debug("Follow-up get_gas_records failed; consumption unavailable")
            return None

        if not records:
            return None

        # Also fold all gas records into the odometer tracker
        try:
            await self._tracker.observe_records(vehicle_id, gas=records)
        except Exception:  # noqa: BLE001
            logger.debug("observe_records after fuel save failed; non-critical")

        # Last record = just saved; second-to-last = previous
        current_rec = records[-1]
        previous_rec = records[-2] if len(records) >= 2 else None

        current_point = _gas_record_to_fuel_point(current_rec)
        if current_point is None:
            return None

        previous_point = (
            _gas_record_to_fuel_point(previous_rec) if previous_rec is not None else None
        )

        reported = current_rec.fuel_economy
        return resolve(reported, current_point, previous_point)


# ======================================================================
# Module-level helpers
# ======================================================================


def _build_payload(
    kind: FlowKind, values: Mapping[str, object]
) -> tuple[GasRecordPayload | ServiceRecordPayload | OdometerRecordPayload, int]:
    """Validate inputs and build the correct payload.

    Returns:
        A tuple of (payload, odometer_value).
    """
    if kind is FlowKind.FUEL:
        model = GasRecordModel(**values)  # type: ignore[arg-type]
        payload = GasRecordPayload.from_validated(model)
        return payload, model.odometer
    elif kind is FlowKind.SERVICE:
        model = ServiceRecordModel(**values)  # type: ignore[arg-type]
        payload = ServiceRecordPayload.from_validated(model)
        return payload, model.odometer
    else:
        model = OdometerRecordModel(**values)  # type: ignore[arg-type]
        payload = OdometerRecordPayload.from_validated(model)
        return payload, model.odometer


def _extract_date(values: Mapping[str, object]) -> date | None:
    """Extract the date from collected values if present."""
    raw = values.get("date")
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _gas_record_to_fuel_point(record: object) -> FuelPoint | None:
    """Convert a GasRecord to a FuelPoint for consumption resolution."""
    from bot.models.records import GasRecord

    if not isinstance(record, GasRecord):
        return None
    if record.odometer is None or record.fuel_consumed is None:
        return None

    return FuelPoint(
        odometer=record.odometer,
        liters=record.fuel_consumed,
        is_fill_to_full=record.is_fill_to_full,
        missed_fuel_up=record.missed_fuel_up,
    )
