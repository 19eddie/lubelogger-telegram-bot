"""API response and database models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiResponse(BaseModel):
    """Represents a response from the LubeLogger API."""

    success: bool
    message: str
    data: dict[str, Any] | None = None


class Vehicle(BaseModel):
    """Represents a vehicle from LubeLogger."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    year: int | None = None
    make: str = ""
    model: str = ""
    license_plate: str = Field(default="", alias="licensePlate")

    @property
    def display_name(self) -> str:
        """Human-readable vehicle name, falling back to ID if no details available."""
        parts = [str(self.year) if self.year else "", self.make, self.model]
        name = " ".join(p for p in parts if p).strip()
        return name or f"Vehicle #{self.id}"


class QueueItem(BaseModel):
    """Represents a queued record in SQLite."""

    id: int
    user_id: int
    vehicle_id: int
    record_type: str  # "gas" | "service" | "odometer"
    payload: str  # JSON-serialized *Payload model
    status: str  # "pending" | "sent" | "failed"
    retry_count: int = 0
    created_at: str
    updated_at: str


class UserConfig(BaseModel):
    """Represents user preferences in SQLite."""

    user_id: int
    active_vehicle_id: int | None = None
    language: str = "en"
    updated_at: str
