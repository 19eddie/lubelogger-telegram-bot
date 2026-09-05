"""API payload models matching LubeLogger's expected format (all-string fields)."""

from __future__ import annotations

from collections.abc import Mapping
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
    """Format a decimal string for the current LubeLogger locale."""
    formatted = format(Decimal(str(value)), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


class GasRecordPayload(BaseModel):
    """Matches LubeLogger GasRecordExportModel — all fields as strings."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: str
    fuel_consumed: str = Field(alias="fuelConsumed")
    cost: str
    is_fill_to_full: str = Field(alias="isFillToFull")  # "true" / "false"
    missed_fuel_up: str = Field(alias="missedFuelUp")  # "true" / "false"
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: GasRecordModel) -> GasRecordPayload:
        """Create a payload from a validated GasRecordModel."""
        return cls(
            date=record.date,
            odometer=str(record.odometer),
            fuel_consumed=_format_lubelogger_decimal(record.liters),
            cost=_format_lubelogger_decimal(record.cost),
            is_fill_to_full=str(record.is_fill_to_full).lower(),
            missed_fuel_up=str(record.missed_fuel_up).lower(),
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


def gas_payload_matches_record(
    payload: GasRecordPayload,
    remote_record: Mapping[str, object],
) -> bool:
    """Return whether a remote gas record matches a payload fingerprint."""
    remote_date = str(remote_record.get("date", "")).strip().split("T", maxsplit=1)[0]
    if remote_date != payload.date:
        return False

    if str(remote_record.get("odometer", "")).strip() != payload.odometer:
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
    """Matches LubeLogger GenericRecordExportModel — all fields as strings."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: str
    description: str
    cost: str
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: ServiceRecordModel) -> ServiceRecordPayload:
        """Create a payload from a validated ServiceRecordModel."""
        return cls(
            date=record.date,
            odometer=str(record.odometer),
            description=record.description,
            cost=_format_lubelogger_decimal(record.cost),
        )


class OdometerRecordPayload(BaseModel):
    """Matches LubeLogger OdometerRecordExportModel — all fields as strings."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: str
    notes: str = ""
    tags: str = ""

    @classmethod
    def from_validated(cls, record: OdometerRecordModel) -> OdometerRecordPayload:
        """Create a payload from a validated OdometerRecordModel."""
        return cls(
            date=record.date,
            odometer=str(record.odometer),
        )
