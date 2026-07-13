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
    """Matches LubeLogger GasRecordInput — uses input model field names."""

    model_config = ConfigDict(populate_by_name=True)

    date: str
    odometer: int
    fuel_consumed: float = Field(alias="fuelConsumed")
    cost: float
    is_fill_to_full: bool = Field(alias="isFillToFull")
    missed_fuel_up: bool = Field(alias="missedFuelUp")
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
