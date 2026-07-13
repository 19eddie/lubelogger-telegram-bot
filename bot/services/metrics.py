"""Pure computation of fuel consumption metrics."""

from __future__ import annotations


def compute_consumption(
    liters: float,
    current_odometer: int,
    previous_odometer: int,
) -> float | None:
    """Compute fuel consumption in L/100km.

    Formula: liters / (current_odometer - previous_odometer) * 100

    Args:
        liters: Liters of fuel filled.
        current_odometer: Current odometer reading in km.
        previous_odometer: Previous odometer reading in km.

    Returns:
        Consumption in L/100km, or None if the delta is zero or negative.

    Raises:
        ValueError: If liters <= 0.
    """
    if liters <= 0:
        raise ValueError("Liters must be positive")
    delta = current_odometer - previous_odometer
    if delta <= 0:
        return None
    return liters / delta * 100
