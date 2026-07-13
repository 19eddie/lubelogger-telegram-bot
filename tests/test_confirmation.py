"""Property tests for confirmation message completeness."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.i18n import get_text
from bot.services.metrics import compute_consumption


@settings(max_examples=100)
@given(
    vehicle=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "S"))),
    odometer=st.integers(min_value=1, max_value=999999),
    liters=st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False),
    cost=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    full_tank=st.booleans(),
    date=st.dates().map(lambda d: d.isoformat()),
)
def test_property_fuel_confirmation_completeness(
    vehicle: str, odometer: int, liters: float, cost: float, full_tank: bool, date: str
) -> None:
    """Property 4: Fuel confirmation message completeness.

    **Validates: Requirements 5.1, 5.5**

    # Feature: telegram-ux-improvements, Property 4: Confirmation message completeness
    """
    full_tank_str = "Yes" if full_tank else "No"
    result = get_text(
        "confirm_fuel",
        "en",
        vehicle=vehicle,
        odometer=str(odometer),
        liters=str(liters),
        cost=str(cost),
        full_tank=full_tank_str,
        date=date,
    )

    assert vehicle in result
    assert str(odometer) in result
    assert str(liters) in result
    assert str(cost) in result
    assert full_tank_str in result
    assert date in result


@settings(max_examples=100)
@given(
    vehicle=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "S"))),
    odometer=st.integers(min_value=1, max_value=999999),
    description=st.text(
        min_size=1, max_size=100, alphabet=st.characters(categories=("L", "N", "P", "S"))
    ),
    cost=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    date=st.dates().map(lambda d: d.isoformat()),
)
def test_property_service_confirmation_completeness(
    vehicle: str, odometer: int, description: str, cost: float, date: str
) -> None:
    """Property 4: Service confirmation message completeness.

    **Validates: Requirements 5.1, 5.5**

    # Feature: telegram-ux-improvements, Property 4: Confirmation message completeness
    """
    result = get_text(
        "confirm_service",
        "en",
        vehicle=vehicle,
        odometer=str(odometer),
        description=description,
        cost=str(cost),
        date=date,
    )

    assert vehicle in result
    assert str(odometer) in result
    assert description in result
    assert str(cost) in result
    assert date in result


class TestFuelConfirmation:
    """Unit tests for fuel confirmation messages."""

    def test_includes_all_fields(self) -> None:
        """Fuel confirmation includes vehicle, odometer, liters, cost, full_tank, date."""
        result = get_text(
            "confirm_fuel",
            "en",
            vehicle="Toyota Corolla",
            odometer="45000",
            liters="35.2",
            cost="62.50",
            full_tank="Yes",
            date="2024-01-15",
        )
        assert "Toyota Corolla" in result
        assert "45000" in result
        assert "35.2" in result
        assert "62.50" in result
        assert "Yes" in result
        assert "2024-01-15" in result

    def test_includes_consumption_metric(self) -> None:
        """Fuel confirmation includes consumption when computed."""
        consumption = compute_consumption(35.0, 45500, 45000)
        assert consumption is not None
        consumption_text = get_text(
            "confirm_fuel_consumption",
            "en",
            consumption=f"{consumption:.1f}",
        )
        assert "7.0" in consumption_text
        assert "L/100km" in consumption_text

    def test_omits_consumption_when_no_previous(self) -> None:
        """Consumption returns None when no delta (no previous record)."""
        result = compute_consumption(35.0, 45000, 45000)
        assert result is None


class TestServiceConfirmation:
    """Unit tests for service confirmation messages."""

    def test_includes_all_fields(self) -> None:
        """Service confirmation includes vehicle, odometer, description, cost, date."""
        result = get_text(
            "confirm_service",
            "en",
            vehicle="Honda Civic",
            odometer="50000",
            description="Oil change",
            cost="89.99",
            date="2024-02-20",
        )
        assert "Honda Civic" in result
        assert "50000" in result
        assert "Oil change" in result
        assert "89.99" in result
        assert "2024-02-20" in result


class TestOdometerConfirmation:
    """Unit tests for odometer confirmation messages."""

    def test_includes_vehicle_and_odometer(self) -> None:
        """Odometer confirmation includes vehicle and odometer."""
        result = get_text(
            "confirm_odometer",
            "en",
            vehicle="Ford Focus",
            odometer="75000",
            date="2024-03-10",
        )
        assert "Ford Focus" in result
        assert "75000" in result
        assert "2024-03-10" in result
