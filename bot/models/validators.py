"""Pydantic validation models for record input."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GasRecordModel(BaseModel):
    """Validates fuel record input."""

    model_config = ConfigDict(strict=False)

    date: str = Field(default_factory=lambda: date.today().isoformat())
    odometer: int = Field(gt=0)
    liters: float = Field(gt=0)
    cost: float = Field(ge=0)
    is_fill_to_full: bool = True
    missed_fuel_up: bool = False


class ServiceRecordModel(BaseModel):
    """Validates service record input."""

    model_config = ConfigDict(strict=False)

    date: str = Field(default_factory=lambda: date.today().isoformat())
    odometer: int = Field(gt=0)
    description: str = Field(min_length=1)
    cost: float = Field(ge=0)

    @field_validator("description")
    @classmethod
    def description_not_whitespace(cls, v: str) -> str:
        """Reject whitespace-only descriptions and strip surrounding whitespace."""
        if not v.strip():
            raise ValueError("Description cannot be empty or whitespace-only")
        return v.strip()


class OdometerRecordModel(BaseModel):
    """Validates odometer record input."""

    model_config = ConfigDict(strict=False)

    date: str = Field(default_factory=lambda: date.today().isoformat())
    odometer: int = Field(gt=0)
