"""Read models for records returned by LubeLogger.

These models are for **reading**: `bot/models/payloads.py` keeps owning the
all-string write format. Every field is optional and tolerant, because the
serialized shape depends on the instance's `LUBELOGGER_INVARIANT_API` setting
(design finding F5) and because LubeLogger adds fields between versions
(`startingSoc`, `extraFields`, `files`, `tags`, ...), so an unknown field must
never break a read (NF-6.1).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bot.models.loose import (
    parse_loose_bool,
    parse_loose_date,
    parse_loose_int,
    parse_loose_number,
)
from bot.models.responses import Vehicle


class LooseRecord(BaseModel):
    """Base for every read model: aliases or field names, unknown fields kept."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class GasRecord(LooseRecord):
    """A fuel record as returned by `/api/vehicle/gasrecords`."""

    id: int | None = None
    date: dt.date | None = None
    odometer: int | None = None
    fuel_consumed: Decimal | None = Field(default=None, alias="fuelConsumed")
    cost: Decimal | None = None
    fuel_economy: Decimal | None = Field(default=None, alias="fuelEconomy")
    is_fill_to_full: bool = Field(default=False, alias="isFillToFull")
    missed_fuel_up: bool = Field(default=False, alias="missedFuelUp")
    notes: str = ""

    @field_validator("id", "odometer", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> int | None:
        return parse_loose_int(value)

    @field_validator("fuel_consumed", "cost", "fuel_economy", mode="before")
    @classmethod
    def _coerce_number(cls, value: object) -> Decimal | None:
        return parse_loose_number(value)

    @field_validator("is_fill_to_full", "missed_fuel_up", mode="before")
    @classmethod
    def _coerce_bool(cls, value: object) -> bool:
        return parse_loose_bool(value)

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_date(cls, value: object) -> dt.date | None:
        return parse_loose_date(value)

    @field_validator("notes", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        return _as_text(value)


class ServiceRecord(LooseRecord):
    """A service record as returned by `/api/vehicle/servicerecords`."""

    id: int | None = None
    date: dt.date | None = None
    odometer: int | None = None
    description: str = ""
    cost: Decimal | None = None

    @field_validator("id", "odometer", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> int | None:
        return parse_loose_int(value)

    @field_validator("cost", mode="before")
    @classmethod
    def _coerce_number(cls, value: object) -> Decimal | None:
        return parse_loose_number(value)

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_date(cls, value: object) -> dt.date | None:
        return parse_loose_date(value)

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        return _as_text(value)


class OdometerRecord(LooseRecord):
    """An odometer record as returned by `/api/vehicle/odometerrecords`."""

    id: int | None = None
    date: dt.date | None = None
    odometer: int | None = None
    initial_odometer: int | None = Field(default=None, alias="initialOdometer")

    @field_validator("id", "odometer", "initial_odometer", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> int | None:
        return parse_loose_int(value)

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_date(cls, value: object) -> dt.date | None:
        return parse_loose_date(value)


class VehicleSnapshot(BaseModel):
    """A vehicle plus the odometer LubeLogger last reported for it (finding F6).

    `last_reported_odometer` is `None` when the snapshot comes from the
    `/api/vehicles` fallback, which carries no odometer at all.
    """

    model_config = ConfigDict(populate_by_name=True)

    vehicle: Vehicle
    last_reported_odometer: int | None = Field(default=None, alias="lastReportedOdometer")

    @field_validator("last_reported_odometer", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> int | None:
        return parse_loose_int(value)


def _as_text(value: object) -> str:
    """Coerce a free-text field to `str`; a missing value reads as empty."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)
