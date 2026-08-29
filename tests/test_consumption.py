"""Unit tests for the consumption service (bot/services/consumption.py).

Property tests 15 and 16 live in tasks 5.4 and 5.5; these cover the concrete
examples and the edge cases that make finding F2 visible.
"""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.consumption import (
    CONSUMPTION_UNIT,
    FuelPoint,
    estimate,
    resolve,
)


def point(
    odometer: int,
    liters: str = "40",
    *,
    full: bool = True,
    missed: bool = False,
) -> FuelPoint:
    """Build a fuel point, full-tank and without a missed fuel-up by default."""
    return FuelPoint(
        odometer=odometer,
        liters=Decimal(liters),
        is_fill_to_full=full,
        missed_fuel_up=missed,
    )


def test_estimate_computes_liters_per_hundred_kilometres() -> None:
    result = estimate(point(45500, "42.5"), point(45000))
    assert result is not None
    assert result.value == Decimal("8.50")
    assert result.unit == CONSUMPTION_UNIT
    assert result.estimated is True


def test_estimate_quantizes_to_two_decimals_half_up() -> None:
    # 40 / 601 * 100 = 6.655574... -> 6.66
    result = estimate(point(45601, "40"), point(45000))
    assert result is not None
    assert result.value == Decimal("6.66")


def test_estimate_returns_none_without_a_previous_record() -> None:
    assert estimate(point(45500), None) is None


def test_estimate_returns_none_when_either_record_is_a_partial_fill() -> None:
    assert estimate(point(45500, full=False), point(45000)) is None
    assert estimate(point(45500), point(45000, full=False)) is None


def test_estimate_returns_none_when_either_record_missed_a_fuel_up() -> None:
    assert estimate(point(45500, missed=True), point(45000)) is None
    assert estimate(point(45500), point(45000, missed=True)) is None


def test_estimate_returns_none_on_a_non_positive_odometer_delta() -> None:
    assert estimate(point(45000), point(45000)) is None
    assert estimate(point(44900), point(45000)) is None


def test_estimate_returns_none_on_a_non_positive_volume() -> None:
    assert estimate(point(45500, "0"), point(45000)) is None
    assert estimate(point(45500, "-5"), point(45000)) is None


def test_resolve_prefers_a_positive_reported_value() -> None:
    result = resolve(Decimal("7.31"), point(45500, "42.5"), point(45000))
    assert result is not None
    assert result.value == Decimal("7.31")
    assert result.unit == CONSUMPTION_UNIT
    assert result.estimated is False


def test_resolve_accepts_a_reported_float_and_string() -> None:
    for reported in (7.3, "7.3"):
        result = resolve(reported, point(45500), point(45000))  # type: ignore[arg-type]
        assert result is not None
        assert result.value == Decimal("7.3")
        assert result.estimated is False


def test_resolve_treats_a_reported_zero_as_absent_and_estimates() -> None:
    # Finding F2: zero means "not available", never zero consumption.
    for reported in (Decimal("0"), Decimal("0.00"), "0", 0, -1.5):
        result = resolve(reported, point(45500, "42.5"), point(45000))  # type: ignore[arg-type]
        assert result is not None
        assert result.value == Decimal("8.50")
        assert result.estimated is True


def test_resolve_returns_none_when_reported_is_absent_and_conditions_fail() -> None:
    assert resolve(None, point(45500), None) is None
    assert resolve(Decimal("0"), point(45500, full=False), point(45000)) is None


def test_resolve_ignores_an_unparsable_reported_value() -> None:
    assert resolve("n/a", point(45500), None) is None  # type: ignore[arg-type]
    assert resolve(float("nan"), point(45500), None) is None
    assert resolve(float("inf"), point(45500), None) is None


# ---------------------------------------------------------------------------
# Property 15: The Consumption_Metric is produced only when every condition holds
# ---------------------------------------------------------------------------


@st.composite
def _fuel_pairs(draw: st.DrawFn) -> tuple[FuelPoint, FuelPoint | None]:
    """Draw a current point plus an optional previous one.

    Half of the examples satisfy every condition of Requirement 6.7 by construction, half
    are drawn freely, so both sides of the "if and only if" get a fair share of the run:
    unconstrained draws almost never line up all five conditions at once.
    """
    volumes = st.decimals(
        min_value=Decimal("-50"),
        max_value=Decimal("500"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    positive_volumes = st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("500"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    previous_odometer = draw(st.integers(min_value=1_000, max_value=1_000_000))

    if draw(st.booleans()):
        delta = draw(st.integers(min_value=1, max_value=5_000))
        return (
            FuelPoint(
                odometer=previous_odometer + delta,
                liters=draw(positive_volumes),
                is_fill_to_full=True,
                missed_fuel_up=False,
            ),
            FuelPoint(
                odometer=previous_odometer,
                liters=draw(positive_volumes),
                is_fill_to_full=True,
                missed_fuel_up=False,
            ),
        )

    delta = draw(st.integers(min_value=-100, max_value=5_000))
    current = FuelPoint(
        odometer=previous_odometer + delta,
        liters=draw(volumes),
        is_fill_to_full=draw(st.booleans()),
        missed_fuel_up=draw(st.booleans()),
    )
    previous = FuelPoint(
        odometer=previous_odometer,
        liters=draw(volumes),
        is_fill_to_full=draw(st.booleans()),
        missed_fuel_up=draw(st.booleans()),
    )
    return current, (previous if draw(st.booleans()) else None)


@given(_fuel_pairs())
@settings(max_examples=100)
def test_property_consumption_conditions(pair: tuple[FuelPoint, FuelPoint | None]) -> None:
    """# Feature: improve-ux, Property 15: The Consumption_Metric is produced only when every condition holds

    For any pair of fuel points, `estimate` returns a value if and only if a previous record
    exists, both records have the full-tank flag set, neither has the missed-fuel-up flag set,
    the odometer delta is strictly positive and the current volume is strictly positive; and
    when it returns a value, that value equals the volume divided by the delta multiplied by
    one hundred, quantized to two decimals.

    Validates: Requirements 6.7, 6.8, NF-1.5
    """  # noqa: E501 - the property tag is one line by convention
    current, previous = pair

    expected_value = (
        previous is not None
        and current.is_fill_to_full
        and previous.is_fill_to_full
        and not current.missed_fuel_up
        and not previous.missed_fuel_up
        and current.odometer - previous.odometer > 0
        and current.liters > 0
    )

    result = estimate(current, previous)

    assert (result is not None) == expected_value
    if result is None:
        return

    assert previous is not None
    # Recomputed exactly with rationals, so the expectation does not borrow the
    # module's own rounding path.
    exact = Fraction(current.liters) * 100 / (current.odometer - previous.odometer)
    expected = Decimal(math.floor(exact * 100 + Fraction(1, 2))) / Decimal(100)

    assert result.value == expected
    assert result.value.as_tuple().exponent == -2
    assert result.unit == CONSUMPTION_UNIT
    assert result.estimated is True


# ---------------------------------------------------------------------------
# Property 16: The reported fuel economy wins, and a non-positive one is treated as absent
# ---------------------------------------------------------------------------


@st.composite
def _reported_values(draw: st.DrawFn) -> tuple[Decimal | float | str | None, Decimal | None]:
    """Draw a reported fuel economy plus the value it must win with, or None.

    The second element is the expectation, produced by the generator rather than by
    re-deriving the module's coercion inside the test: a Decimal when the drawn value
    is a strictly positive figure, `None` when it must be treated as absent
    (non-positive, missing, non-finite or unparsable).
    """
    positive = st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("200"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    non_positive = st.decimals(
        min_value=Decimal("-200"),
        max_value=Decimal("0"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    kind = draw(
        st.sampled_from(
            [
                "positive_decimal",
                "positive_float",
                "positive_string",
                "non_positive_decimal",
                "non_positive_float",
                "non_positive_string",
                "none",
                "non_finite",
                "unparsable",
            ]
        )
    )

    if kind == "positive_decimal":
        value = draw(positive)
        return value, value
    if kind == "positive_float":
        value = draw(positive)
        return float(value), value
    if kind == "positive_string":
        value = draw(positive)
        return str(value), value
    if kind == "non_positive_decimal":
        return draw(non_positive), None
    if kind == "non_positive_float":
        return float(draw(non_positive)), None
    if kind == "non_positive_string":
        return str(draw(non_positive)), None
    if kind == "none":
        return None, None
    if kind == "non_finite":
        return draw(st.sampled_from([float("nan"), float("inf"), float("-inf")])), None
    return draw(st.sampled_from(["n/a", "", "   ", "abc", "1,5", "--3", "7.3 L"])), None


@given(_reported_values(), _fuel_pairs())
@settings(max_examples=100)
def test_property_consumption_source_preference(
    reported: tuple[Decimal | float | str | None, Decimal | None],
    pair: tuple[FuelPoint, FuelPoint | None],
) -> None:
    """# Feature: improve-ux, Property 16: The reported fuel economy wins, and a non-positive one is treated as absent

    For any reported fuel economy value and any pair of fuel points, `resolve` returns the
    reported value with `estimated` false when the reported value is strictly positive, and
    otherwise returns exactly what `estimate` returns for that pair — including `None`, so the
    caller has no consumption line to render and never a placeholder. Whenever a value exists,
    it carries the declared unit.

    Validates: Requirements 6.5, 6.6, 6.9, NF-6.2
    """  # noqa: E501 - the property tag is one line by convention
    value, expected_win = reported
    current, previous = pair

    baseline = estimate(current, previous)
    result = resolve(value, current, previous)

    if expected_win is not None:
        # Requirement 6.5: LubeLogger's own figure is authoritative and unmodified.
        assert result is not None
        assert result.value == expected_win
        assert result.estimated is False
    else:
        # Finding F2 plus Requirements 6.6 and 6.9: indistinguishable from no figure at all.
        assert result == baseline

    # NF-6.2: a rendered figure always states its unit.
    if result is not None:
        assert result.unit == CONSUMPTION_UNIT
