"""Property-based tests for the tolerant read models of `bot.models.records`.

Covers design Property 29: every representation LubeLogger can emit for a value
parses to the same Python value, and a record payload built in either the
invariant or the culture-dependent shape of finding F5 validates into an equal
read model.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.models.loose import (
    parse_loose_bool,
    parse_loose_date,
    parse_loose_int,
    parse_loose_number,
)
from bot.models.records import (
    GasRecord,
    OdometerRecord,
    ServiceRecord,
    VehicleSnapshot,
)

# --- Strategies -------------------------------------------------------------

odometers = st.integers(min_value=1, max_value=3_000_000)
money = st.decimals(min_value=Decimal("0"), max_value=Decimal("99999.99"), places=2)
dates = st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2099, 12, 31))
descriptions = st.text(max_size=40)
years = st.integers(min_value=1900, max_value=2099)


# --- Renderers for the two shapes of finding F5 -----------------------------


def _invariant_decimal(value: Decimal) -> float:
    """The invariant shape emits a decimal as a JSON number."""
    return float(value)


def _culture_decimal(value: Decimal) -> str:
    """The culture-dependent shape emits a decimal as `"4,52"`."""
    return f"{value:.2f}".replace(".", ",")


def _grouped_culture_decimal(value: Decimal) -> str:
    """The same decimal with dot grouping, e.g. `"1.234,56"`."""
    whole, _, frac = f"{value:.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{grouped},{frac}"


def _decimal_representations(value: Decimal) -> list[object]:
    return [
        _invariant_decimal(value),
        f"{value:.2f}",
        _culture_decimal(value),
        _grouped_culture_decimal(value),
        value,
    ]


def _int_representations(value: int) -> list[object]:
    return [value, str(value), f"{value}.0", float(value)]


def _bool_representations(value: bool) -> list[object]:
    return [value, "True" if value else "False", "true" if value else "false", int(value)]


def _date_representations(value: dt.date) -> list[object]:
    return [
        value,
        value.isoformat(),
        value.strftime("%d/%m/%Y"),
        value.strftime("%d.%m.%Y"),
        value.strftime("%d-%m-%Y"),
        value.strftime("%Y/%m/%d"),
    ]


def _gas_payloads(
    *,
    record_id: int,
    on_date: dt.date,
    odometer: int,
    liters: Decimal,
    cost: Decimal,
    economy: Decimal,
    full_tank: bool,
    missed: bool,
    notes: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The same fuel record in the invariant and the culture-dependent shape."""
    invariant = {
        "id": record_id,
        "date": on_date.isoformat(),
        "odometer": odometer,
        "fuelConsumed": _invariant_decimal(liters),
        "cost": _invariant_decimal(cost),
        "fuelEconomy": _invariant_decimal(economy),
        "isFillToFull": full_tank,
        "missedFuelUp": missed,
        "notes": notes,
    }
    culture = {
        "id": str(record_id),
        "date": on_date.strftime("%d/%m/%Y"),
        "odometer": str(odometer),
        "fuelConsumed": _culture_decimal(liters),
        "cost": _culture_decimal(cost),
        "fuelEconomy": _culture_decimal(economy),
        "isFillToFull": "True" if full_tank else "False",
        "missedFuelUp": "True" if missed else "False",
        "notes": notes,
    }
    return invariant, culture


# --- Property 29 ------------------------------------------------------------


@settings(max_examples=100)
@given(
    record_id=odometers,
    on_date=dates,
    odometer=odometers,
    liters=money,
    cost=money,
    economy=money,
    full_tank=st.booleans(),
    missed=st.booleans(),
    notes=descriptions,
    year=years,
)
def test_property_loose_parsing_equivalence(
    record_id: int,
    on_date: dt.date,
    odometer: int,
    liters: Decimal,
    cost: Decimal,
    economy: Decimal,
    full_tank: bool,
    missed: bool,
    notes: str,
    year: int,
) -> None:
    """Property 29: Every representation LubeLogger can emit parses to the same value.

    # Feature: improve-ux, Property 29: Every representation LubeLogger can emit
    # parses to the same value

    Validates: Requirements NF-6.1
    """
    # Every representation of one underlying value collapses to that value.
    for representation in _decimal_representations(liters):
        assert parse_loose_number(representation) == liters
    for representation in _int_representations(odometer):
        assert parse_loose_int(representation) == odometer
    for representation in _bool_representations(full_tank):
        assert parse_loose_bool(representation) is full_tank
    for representation in _date_representations(on_date):
        assert parse_loose_date(representation) == on_date

    # A fuel record validates into an equal read model from either shape.
    invariant, culture = _gas_payloads(
        record_id=record_id,
        on_date=on_date,
        odometer=odometer,
        liters=liters,
        cost=cost,
        economy=economy,
        full_tank=full_tank,
        missed=missed,
        notes=notes,
    )
    gas_invariant = GasRecord.model_validate(invariant)
    gas_culture = GasRecord.model_validate(culture)
    assert gas_invariant == gas_culture
    assert gas_invariant.odometer == odometer
    assert gas_invariant.date == on_date
    assert gas_invariant.fuel_consumed == liters
    assert gas_invariant.fuel_economy == economy
    assert gas_invariant.is_fill_to_full is full_tank
    assert gas_invariant.missed_fuel_up is missed

    # So does a service record.
    service_invariant = ServiceRecord.model_validate(
        {
            "id": record_id,
            "date": on_date.isoformat(),
            "odometer": odometer,
            "description": notes,
            "cost": _invariant_decimal(cost),
        }
    )
    service_culture = ServiceRecord.model_validate(
        {
            "id": str(record_id),
            "date": on_date.strftime("%d/%m/%Y"),
            "odometer": str(odometer),
            "description": notes,
            "cost": _culture_decimal(cost),
        }
    )
    assert service_invariant == service_culture
    assert service_culture.cost == cost

    # So does an odometer record.
    odometer_invariant = OdometerRecord.model_validate(
        {
            "id": record_id,
            "date": on_date.isoformat(),
            "odometer": odometer,
            "initialOdometer": odometer,
        }
    )
    odometer_culture = OdometerRecord.model_validate(
        {
            "id": str(record_id),
            "date": on_date.strftime("%d/%m/%Y"),
            "odometer": str(odometer),
            "initialOdometer": str(odometer),
        }
    )
    assert odometer_invariant == odometer_culture
    assert odometer_culture.initial_odometer == odometer

    # And so does a vehicle snapshot, whose odometer follows the same shapes.
    snapshot_invariant = VehicleSnapshot.model_validate(
        {
            "vehicle": {"id": record_id, "year": year, "make": "Fiat", "model": "Panda"},
            "lastReportedOdometer": odometer,
        }
    )
    snapshot_culture = VehicleSnapshot.model_validate(
        {
            "vehicle": {"id": str(record_id), "year": str(year), "make": "Fiat", "model": "Panda"},
            "lastReportedOdometer": str(odometer),
        }
    )
    assert snapshot_invariant == snapshot_culture
    assert snapshot_culture.last_reported_odometer == odometer
