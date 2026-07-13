"""Property and unit tests for metrics module."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.metrics import compute_consumption


@settings(max_examples=100)
@given(
    liters=st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False),
    current_odometer=st.integers(min_value=2, max_value=999999),
    data=st.data(),
)
def test_property_consumption_metric_formula(
    liters: float, current_odometer: int, data: st.DataObject
) -> None:
    """Property 2: Consumption metric formula correctness.

    # Feature: telegram-ux-improvements, Property 2: Consumption metric formula correctness
    """
    previous_odometer = data.draw(st.integers(min_value=1, max_value=current_odometer - 1))

    result = compute_consumption(liters, current_odometer, previous_odometer)

    assert result is not None
    assert result > 0

    expected = liters / (current_odometer - previous_odometer) * 100
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_compute_consumption_normal_values() -> None:
    """Test consumption with typical fill-up values."""
    # 35L over 500km = 7.0 L/100km
    result = compute_consumption(35.0, 45500, 45000)
    assert result == pytest.approx(7.0)


def test_compute_consumption_returns_none_when_delta_zero() -> None:
    """Return None when current == previous odometer."""
    result = compute_consumption(35.0, 45000, 45000)
    assert result is None


def test_compute_consumption_returns_none_when_delta_negative() -> None:
    """Return None when current < previous (impossible but defensive)."""
    result = compute_consumption(35.0, 44000, 45000)
    assert result is None


def test_compute_consumption_raises_for_zero_liters() -> None:
    """Raise ValueError when liters is 0."""
    with pytest.raises(ValueError, match="Liters must be positive"):
        compute_consumption(0, 45000, 44000)


def test_compute_consumption_raises_for_negative_liters() -> None:
    """Raise ValueError when liters is negative."""
    with pytest.raises(ValueError, match="Liters must be positive"):
        compute_consumption(-5.0, 45000, 44000)
