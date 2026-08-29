"""Consumption_Metric resolution: LubeLogger's own figure first, own estimate second.

Requirement 6.5 makes the figure LubeLogger computes authoritative, so the number
the Bot shows matches the web UI. Requirement 6.6 only applies when that figure is
missing, and then the value must be labelled an estimate, because LubeLogger
aggregates deferred partial fills across records while this module only ever looks
at the current and the previous one (design finding F4).

Design finding F2 is the reason `resolve` treats a non-positive reported value as
absent: LubeLogger yields `0` for the first record of a vehicle, for a missed
fuel-up, for a partial fill, for a non-positive odometer delta and for a
non-positive volume. Rendering that verbatim would print "0.0 L/100 km" on every
partial fill.

`None` is the whole of Requirement 6.9: the caller omits the line, it never
renders a placeholder.

Pure module: no I/O, no persistence, no Telegram, so both properties 15 and 16 are
provable from literals (NF-1.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

# The unit the Bot declares whenever it renders a consumption figure (NF-6.2).
# The Bot never sends `useMPG` / `useUKMPG`, so LubeLogger's own figure is volume
# per 100 distance units, the same shape as the estimate computed here (finding F3).
CONSUMPTION_UNIT = "L/100 km"

_CENTS = Decimal("0.01")
_HUNDRED = Decimal(100)
_MIN_PRECISION = 28
_PRECISION_HEADROOM = 8


@dataclass(frozen=True, slots=True)
class FuelPoint:
    """The part of a gas record that a consumption computation depends on."""

    odometer: int
    liters: Decimal
    is_fill_to_full: bool
    missed_fuel_up: bool


@dataclass(frozen=True, slots=True)
class ConsumptionResult:
    """A consumption figure, its unit, and whether the Bot computed it itself."""

    value: Decimal
    unit: str
    estimated: bool


def estimate(current: FuelPoint, previous: FuelPoint | None) -> ConsumptionResult | None:
    """Compute the Consumption_Metric from two fuel points, or return None.

    Returns a value only when every condition of Requirements 6.7 and 6.8 holds:
    a previous record exists, both records are fill-to-full, neither carries the
    missed-fuel-up flag, the odometer delta is strictly positive and the current
    volume is strictly positive. Otherwise the metric is omitted silently
    (Requirement 6.9).
    """
    if previous is None:
        return None
    if not (current.is_fill_to_full and previous.is_fill_to_full):
        return None
    if current.missed_fuel_up or previous.missed_fuel_up:
        return None

    delta = current.odometer - previous.odometer
    if delta <= 0:
        return None

    liters = _to_decimal(current.liters)
    if liters is None or liters <= 0:
        return None

    return ConsumptionResult(
        value=_per_hundred(liters, delta),
        unit=CONSUMPTION_UNIT,
        estimated=True,
    )


def resolve(
    reported: Decimal | float | None,
    current: FuelPoint,
    previous: FuelPoint | None,
) -> ConsumptionResult | None:
    """Prefer the figure LubeLogger reported, falling back to the own estimate.

    A strictly positive `reported` wins with `estimated=False` (Requirement 6.5).
    Anything else — `None`, zero, negative, unparsable — means "not available"
    (finding F2) and delegates to `estimate` (Requirement 6.6), which may itself
    return `None` (Requirement 6.9).
    """
    value = _to_decimal(reported)
    if value is not None and value > 0:
        return ConsumptionResult(value=value, unit=CONSUMPTION_UNIT, estimated=False)
    return estimate(current, previous)


def _per_hundred(liters: Decimal, delta: int) -> Decimal:
    """Return `liters / delta * 100` quantized to two decimals, half up.

    The precision is widened to the magnitude of the operand so that quantizing a
    large volume cannot signal instead of rounding.
    """
    with localcontext() as ctx:
        ctx.prec = max(_MIN_PRECISION, liters.adjusted() + _PRECISION_HEADROOM)
        raw = liters / Decimal(delta) * _HUNDRED
        return raw.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _to_decimal(value: Decimal | float | str | None) -> Decimal | None:
    """Coerce a reported figure to a finite Decimal, or return None.

    Floats go through `str` so that a value such as `5.7` keeps the decimal shape
    the API sent rather than its binary expansion. A NaN or an infinity is
    rejected here, because comparing them would signal.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        coerced = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return coerced if coerced.is_finite() else None
