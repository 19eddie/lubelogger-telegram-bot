"""Unit tests for the renderer view models (bot/flows/views.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from bot.flows.definitions import FlowKind
from bot.flows.views import CardView, ConfirmationView, FieldEntry, SummaryView
from bot.services.consumption import CONSUMPTION_UNIT, ConsumptionResult
from bot.services.odometer_tracker import OdometerReference

_ENTRY = FieldEntry(index=0, label_key="field_odometer", rendered_value="45.280")


def _card() -> CardView:
    return CardView(
        kind=FlowKind.FUEL,
        vehicle_name="2019 Volvo V60",
        collected=(_ENTRY,),
        prompt_key="ask_liters",
        progress=(2, 4),
        reference=OdometerReference(value=45_230, on_date=dt.date(2025, 7, 12), source="gas"),
    )


def test_views_are_built_from_literals_alone() -> None:
    """NF-1.2: a renderer test needs no Bot, no network and no database."""
    card = _card()
    assert card.collected[0].rendered_value == "45.280"
    assert card.progress == (2, 4)
    assert card.error_key is None

    summary = SummaryView(kind=FlowKind.SERVICE, vehicle_name="Van", entries=(_ENTRY,))
    assert summary.entries == (_ENTRY,)

    confirmation = ConfirmationView(
        kind=FlowKind.FUEL,
        vehicle_name="Van",
        on_date=dt.date(2025, 7, 12),
        entries=(_ENTRY,),
        consumption=ConsumptionResult(value=Decimal("6.10"), unit=CONSUMPTION_UNIT, estimated=True),
    )
    assert confirmation.consumption is not None
    assert confirmation.consumption.unit == CONSUMPTION_UNIT


def test_optional_parts_default_to_absent() -> None:
    card = CardView(
        kind=FlowKind.ODOMETER,
        vehicle_name="Van",
        collected=(),
        prompt_key="ask_odometer",
    )
    assert card.progress is None
    assert card.reference is None
    assert card.error_key is None

    confirmation = ConfirmationView(
        kind=FlowKind.ODOMETER,
        vehicle_name="Van",
        on_date=dt.date(2025, 7, 12),
        entries=(),
    )
    assert confirmation.consumption is None


@pytest.mark.parametrize(
    ("view", "attribute", "value"),
    [
        (_ENTRY, "rendered_value", "0"),
        (_card(), "vehicle_name", "other"),
        (SummaryView(kind=FlowKind.FUEL, vehicle_name="Van", entries=()), "entries", ()),
        (
            ConfirmationView(
                kind=FlowKind.FUEL,
                vehicle_name="Van",
                on_date=dt.date(2025, 7, 12),
                entries=(),
            ),
            "consumption",
            None,
        ),
    ],
)
def test_views_are_immutable(view: object, attribute: str, value: object) -> None:
    with pytest.raises(AttributeError):
        setattr(view, attribute, value)


def test_collections_are_tuples_so_a_view_cannot_be_mutated_through_them() -> None:
    card = _card()
    assert isinstance(card.collected, tuple)
    with pytest.raises(TypeError):
        card.collected[0] = _ENTRY  # type: ignore[index]
