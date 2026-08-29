"""Tolerant coercion helpers for values read from LubeLogger.

LubeLogger serializes the same field differently depending on its
`LUBELOGGER_INVARIANT_API` setting: a decimal can arrive as the JSON number
`4.52`, as the string `"4.52"` or as the culture-dependent string `"4,52"`,
booleans as `true` or `"True"`, dates as `2025-07-12` or `12/07/2025`
(design finding F5). These helpers accept every shape and return `None`
instead of raising when a value cannot be understood, so that an unexpected
representation degrades a single field instead of breaking a whole read
(NF-6.1).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

_TRUE_STRINGS = frozenset({"true", "1"})
_FALSE_STRINGS = frozenset({"false", "0"})

_DAY_FIRST_FORMATS = ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d")
_MONTH_FIRST_FORMATS = ("%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d")


def parse_loose_number(value: object) -> Decimal | None:
    """Coerce a LubeLogger numeric field to `Decimal`, or `None` when unusable.

    Numeric values pass through. Strings are stripped, empty ones yield `None`,
    and separators are resolved: when both `,` and `.` occur the last of the two
    is the decimal separator and the other is dropped as grouping; when only one
    occurs it is the decimal separator.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value)) if isfinite(value) else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    text = _normalize_separators(text)
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_loose_int(value: object) -> int | None:
    """Coerce a LubeLogger integer field to `int`, or `None` when unusable.

    Accepts every representation `parse_loose_number` accepts; a fractional part
    is truncated, since LubeLogger stores odometers as whole units.
    """
    number = parse_loose_number(value)
    if number is None or not number.is_finite():
        return None
    return int(number)


def parse_loose_bool(value: object) -> bool:
    """Coerce a LubeLogger boolean field to `bool`.

    Accepts `True`/`False`, `"True"`/`"False"`, `"true"`/`"false"`, `"1"`/`"0"`
    and `1`/`0`. Anything else, including `None`, reads as `False`.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
    return False


def parse_loose_date(value: object, *, day_first: bool = True) -> date | None:
    """Coerce a LubeLogger date field to `date`, or `None` when unusable.

    ISO `yyyy-MM-dd` (and ISO datetimes) are tried first, then the culture
    formats `%d/%m/%Y`, `%m/%d/%Y`, `%d.%m.%Y`, `%d-%m-%Y`, `%Y/%m/%d`, ordered
    so that an ambiguous value such as `07/12/2025` follows `day_first`.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    formats = _DAY_FIRST_FORMATS if day_first else _MONTH_FIRST_FORMATS
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_separators(text: str) -> str:
    """Turn a culture-dependent decimal string into an invariant one."""
    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma == -1 and last_dot == -1:
        return text
    if last_comma > last_dot:
        return text.replace(".", "").replace(",", ".")
    return text.replace(",", "")
