"""Unit tests for the tolerant coercion helpers of `bot.models.loose`."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from bot.models.loose import (
    parse_loose_bool,
    parse_loose_date,
    parse_loose_int,
    parse_loose_number,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4.52, Decimal("4.52")),
        (Decimal("4.52"), Decimal("4.52")),
        (452, Decimal("452")),
        ("4.52", Decimal("4.52")),
        ("4,52", Decimal("4.52")),
        ("  4,52  ", Decimal("4.52")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("-4,52", Decimal("-4.52")),
        ("0", Decimal("0")),
    ],
)
def test_parse_loose_number_accepts_every_representation(value: object, expected: Decimal) -> None:
    """Every shape LubeLogger can emit for one decimal parses to the same value."""
    assert parse_loose_number(value) == expected


@pytest.mark.parametrize("value", ["", "   ", None, "abc", "4,5,2", True, False, float("inf")])
def test_parse_loose_number_returns_none_on_unusable_input(value: object) -> None:
    """An empty, malformed or non-numeric value degrades to None instead of raising."""
    assert parse_loose_number(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (45000, 45000),
        ("45000", 45000),
        ("45.000,0", 45000),
        (45000.0, 45000),
        ("45000.7", 45000),
        ("", None),
        (None, None),
        ("nope", None),
    ],
)
def test_parse_loose_int(value: object, expected: int | None) -> None:
    """Integer fields accept the loose numeric shapes and truncate any fraction."""
    assert parse_loose_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("True", True),
        ("False", False),
        ("true", True),
        ("false", False),
        (" TRUE ", True),
        ("1", True),
        ("0", False),
        (1, True),
        (0, False),
        (None, False),
        ("maybe", False),
    ],
)
def test_parse_loose_bool(value: object, expected: bool) -> None:
    """Boolean fields read every documented representation, unknowns read as False."""
    assert parse_loose_bool(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-07-12", date(2025, 7, 12)),
        ("2025-07-12T00:00:00", date(2025, 7, 12)),
        (date(2025, 7, 12), date(2025, 7, 12)),
        (datetime(2025, 7, 12, 8, 30), date(2025, 7, 12)),
        ("12.07.2025", date(2025, 7, 12)),
        ("12-07-2025", date(2025, 7, 12)),
        ("2025/07/12", date(2025, 7, 12)),
        ("", None),
        (None, None),
        ("32/13/2025", None),
    ],
)
def test_parse_loose_date(value: object, expected: date | None) -> None:
    """ISO comes first, then the culture formats, and unusable values give None."""
    assert parse_loose_date(value) == expected


def test_parse_loose_date_ambiguous_follows_day_first() -> None:
    """An ambiguous value such as 07/12/2025 is disambiguated by day_first."""
    assert parse_loose_date("07/12/2025", day_first=True) == date(2025, 12, 7)
    assert parse_loose_date("07/12/2025", day_first=False) == date(2025, 7, 12)


def test_parse_loose_date_unambiguous_ignores_day_first() -> None:
    """A day above twelve parses the same whichever order is preferred."""
    assert parse_loose_date("25/07/2025", day_first=True) == date(2025, 7, 25)
    assert parse_loose_date("25/07/2025", day_first=False) == date(2025, 7, 25)
