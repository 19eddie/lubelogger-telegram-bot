"""Pydantic validation models for record input."""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_fuel_date(value: str) -> str:
    """Validate an ISO fuel date that is not in the future."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Fuel date is required")
    normalized = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized) is None:
        raise ValueError("Fuel date must use YYYY-MM-DD format")

    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Fuel date must use YYYY-MM-DD format") from exc

    if parsed > date.today():
        raise ValueError("Fuel date cannot be in the future")
    return normalized


class GasRecordModel(BaseModel):
    """Validates fuel record input."""

    model_config = ConfigDict(strict=False, allow_inf_nan=False, validate_default=True)

    date: str = Field(default_factory=lambda: date.today().isoformat())
    odometer: int = Field(gt=0)
    liters: float = Field(gt=0)
    cost: float = Field(ge=0)
    is_fill_to_full: bool = True
    missed_fuel_up: bool = False

    @field_validator("date")
    @classmethod
    def date_is_valid(cls, value: str) -> str:
        """Require an ISO date that is today or earlier."""
        return validate_fuel_date(value)


class ServiceRecordModel(BaseModel):
    """Validates service record input."""

    model_config = ConfigDict(strict=False, allow_inf_nan=False)

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

    model_config = ConfigDict(strict=False, allow_inf_nan=False)

    date: str = Field(default_factory=lambda: date.today().isoformat())
    odometer: int = Field(gt=0)
