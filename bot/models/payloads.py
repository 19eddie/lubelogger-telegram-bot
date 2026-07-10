"""API payload models matching LubeLogger's expected format (all-string fields)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from bot.models.validators import (
        GasRecordModel,
        OdometerRecordModel,
        ServiceRecordModel,
    )


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
            fuel_consumed=str(record.liters),
            cost=str(record.cost),
            is_fill_to_full=str(record.is_fill_to_full).lower(),
            missed_fuel_up=str(record.missed_fuel_up).lower(),
        )


class ServiceRecordPayload(BaseModel):
    """Matches LubeLogger GenericRecordExportModel — all fields as strings."""

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
            cost=str(record.cost),
        )


class OdometerRecordPayload(BaseModel):
    """Matches LubeLogger OdometerRecordExportModel — all fields as strings."""

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
