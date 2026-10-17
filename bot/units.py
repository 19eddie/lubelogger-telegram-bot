"""Display labels for distances, fuel quantities and costs shown in bot messages.

The labels are cosmetic: values are sent to LubeLogger exactly as the user types them and are
never converted, so the labels should match the units configured in LubeLogger.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_DISTANCE_UNIT = "km"
DEFAULT_VOLUME_UNIT = "L"
DEFAULT_CURRENCY_SYMBOL = "€"

DISPLAY_UNITS_KEY = "display_units"


@dataclass(frozen=True, slots=True)
class DisplayUnits:
    """Unit labels used to fill the unit placeholders of localized messages."""

    distance: str = DEFAULT_DISTANCE_UNIT
    volume: str = DEFAULT_VOLUME_UNIT
    currency: str = DEFAULT_CURRENCY_SYMBOL


def get_display_units(bot_data: Mapping[str, object]) -> DisplayUnits:
    """Return the configured display units, or the defaults when none are stored."""
    units = bot_data.get(DISPLAY_UNITS_KEY)
    return units if isinstance(units, DisplayUnits) else DisplayUnits()
