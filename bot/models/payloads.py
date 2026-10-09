"""API payload models matching LubeLogger's culture-invariant format."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from bot.models.validators import (
        GasRecordModel,
        OdometerRecordModel,
        ServiceRecordModel,
    )


def _format_lubelogger_decimal(value: float) -> str:
    """Format a decimal string for LubeLogger API (culture-invariant dot separator)."""
    formatted = format(Decimal(str(value)), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


class GasRecordPayload(BaseModel):
    """Matches LubeLogger GasRecordExportModel using native numeric and boolean JSON types."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: int
    fuel_consumed: float = Field(alias="fuelConsumed")
    cost: float
    is_fill_to_full: bool = Field(default=True, alias="isFillToFull")
    missed_fuel_up: bool = Field(default=False, alias="missedFuelUp")
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: GasRecordModel) -> GasRecordPayload:
        """Create a payload from a validated GasRecordModel."""
        return cls(
            date=record.date,
            odometer=record.odometer,
            fuel_consumed=record.liters,
            cost=record.cost,
            is_fill_to_full=record.is_fill_to_full,
            missed_fuel_up=record.missed_fuel_up,
        )


def _parse_lubelogger_decimal(value: object) -> Decimal | None:
    """Parse either dot- or comma-separated numeric API values for comparison."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _parse_lubelogger_boolean(value: object) -> bool | None:
    """Parse boolean values returned by different LubeLogger versions."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "si", "sì"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _normalize_date_iso(value: object) -> str:
    """Normalize date strings to YYYY-MM-DD for fingerprint comparison."""
    s = str(value).strip().split("T", maxsplit=1)[0]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def gas_payload_matches_record(
    payload: GasRecordPayload,
    remote_record: Mapping[str, object],
) -> bool:
    """Return whether a remote gas record matches a payload fingerprint."""
    remote_date = _normalize_date_iso(remote_record.get("date", ""))
    if remote_date != payload.date:
        return False

    remote_odometer_raw = str(remote_record.get("odometer", "")).strip()
    try:
        remote_odometer = int(float(remote_odometer_raw.replace(",", ".")))
    except (ValueError, TypeError):
        remote_odometer = None

    if remote_odometer != payload.odometer:
        return False

    for remote_key, expected_value in (
        ("fuelConsumed", payload.fuel_consumed),
        ("cost", payload.cost),
    ):
        remote_value = _parse_lubelogger_decimal(remote_record.get(remote_key))
        expected_decimal = _parse_lubelogger_decimal(expected_value)
        if remote_value is None or expected_decimal is None or remote_value != expected_decimal:
            return False

    for remote_key, expected_value in (
        ("isFillToFull", payload.is_fill_to_full),
        ("missedFuelUp", payload.missed_fuel_up),
    ):
        if remote_key not in remote_record:
            continue
        remote_value = _parse_lubelogger_boolean(remote_record[remote_key])
        expected_bool = _parse_lubelogger_boolean(expected_value)
        if remote_value is None or expected_bool is None or remote_value != expected_bool:
            return False

    return True


class ServiceRecordPayload(BaseModel):
    """Matches LubeLogger GenericRecordExportModel using native numeric JSON types."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: int
    description: str
    cost: float
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: ServiceRecordModel) -> ServiceRecordPayload:
        """Create a payload from a validated ServiceRecordModel."""
        return cls(
            date=record.date,
            odometer=record.odometer,
            description=record.description,
            cost=record.cost,
        )


class OdometerRecordPayload(BaseModel):
    """Matches LubeLogger OdometerRecordExportModel using native integer odometer."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: int
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: OdometerRecordModel) -> OdometerRecordPayload:
        """Create a payload from a validated OdometerRecordModel."""
        return cls(
            date=record.date,
            odometer=record.odometer,
        )
