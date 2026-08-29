"""Field tables for the unified record flow.

Pure module: it imports nothing from the rest of the bot package, in particular nothing from
``bot.i18n``. That is what lets ``bot.i18n`` import :class:`MenuAction` for the menu-label index
without creating a circular import. Every user-visible string is referenced here by locale key
only, never by value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class FlowKind(StrEnum):
    """The record kind a guided flow collects."""

    FUEL = "fuel"
    SERVICE = "service"
    ODOMETER = "odometer"


class FieldKind(StrEnum):
    """How a field's value is entered and validated."""

    INT = "int"
    DECIMAL = "decimal"
    TEXT = "text"
    CHOICE = "choice"


class MenuAction(StrEnum):
    """The five actions reachable from the persistent navigation keyboard."""

    FUEL = "fuel"
    SERVICE = "service"
    ODOMETER = "odometer"
    LATEST = "latest"
    OPTIONS = "options"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One data-entry step of a flow, described by locale keys only."""

    key: str
    kind: FieldKind
    prompt_key: str
    label_key: str
    placeholder_key: str
    error_key: str
    choices: tuple[str, ...] = field(default=())


_ODOMETER = FieldSpec(
    key="odometer",
    kind=FieldKind.INT,
    prompt_key="ask_odometer",
    label_key="field_odometer",
    placeholder_key="ph_odometer",
    error_key="invalid_odometer",
)

_LITERS = FieldSpec(
    key="liters",
    kind=FieldKind.DECIMAL,
    prompt_key="ask_liters",
    label_key="field_liters",
    placeholder_key="ph_liters",
    error_key="invalid_liters",
)

_COST = FieldSpec(
    key="cost",
    kind=FieldKind.DECIMAL,
    prompt_key="ask_cost",
    label_key="field_cost",
    placeholder_key="ph_cost",
    error_key="invalid_cost",
)

_FULL_TANK = FieldSpec(
    key="is_fill_to_full",
    kind=FieldKind.CHOICE,
    prompt_key="ask_full_tank",
    label_key="field_full_tank",
    placeholder_key="ph_full_tank",
    error_key="invalid_full_tank",
    choices=("btn_yes", "btn_no"),
)

_DESCRIPTION = FieldSpec(
    key="description",
    kind=FieldKind.TEXT,
    prompt_key="ask_description",
    label_key="field_description",
    placeholder_key="ph_description",
    error_key="invalid_description",
)

FIELDS: Mapping[FlowKind, tuple[FieldSpec, ...]] = {
    FlowKind.FUEL: (_ODOMETER, _LITERS, _COST, _FULL_TANK),
    FlowKind.SERVICE: (_ODOMETER, _DESCRIPTION, _COST),
    FlowKind.ODOMETER: (_ODOMETER,),
}


def field_count(kind: FlowKind) -> int:
    """Return the number of data-entry steps of a flow."""
    return len(FIELDS[kind])


def field_at(kind: FlowKind, index: int) -> FieldSpec:
    """Return the field at ``index``, raising ``IndexError`` when out of range."""
    fields = FIELDS[kind]
    if index < 0 or index >= len(fields):
        raise IndexError(f"field index {index} out of range for flow {kind.value}")
    return fields[index]


def field_index(kind: FlowKind, key: str) -> int:
    """Return the position of the field named ``key``, raising ``ValueError`` when absent."""
    for index, spec in enumerate(FIELDS[kind]):
        if spec.key == key:
            return index
    raise ValueError(f"unknown field {key!r} for flow {kind.value}")
