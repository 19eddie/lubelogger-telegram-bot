"""Input data models for raw parsed user input (pre-validation)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FuelInput:
    """Raw parsed fuel record input from command parser."""

    odometer: str
    liters: str
    cost: str
    date: str | None = None
    is_fill_to_full: bool = True
    missed_fuel_up: bool = False


@dataclass
class ServiceInput:
    """Raw parsed service record input from command parser."""

    odometer: str
    description: str
    cost: str
    date: str | None = None


@dataclass
class OdometerInput:
    """Raw parsed odometer record input from command parser."""

    odometer: str
    date: str | None = None
