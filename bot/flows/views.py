"""View models handed to the message renderers.

Every renderer in ``bot/formatters.py`` takes one of these frozen dataclasses instead of a
``FlowState``, a Telegram object or an API response. They carry plain data only — locale keys,
already-rendered value strings, ordinals — so a renderer test can be written with literals and
without a ``Bot``, a network call or a database (NF-1.2).

Rendering, not formatting, is what these views describe: ``FieldEntry.rendered_value`` is the
value already turned into a display string by the caller, so the renderer only has to escape and
interpolate it. Labels travel as locale keys, never as translated text, so one view renders in
every language.

Pure module: no I/O, no Telegram imports. ``OdometerReference`` is referenced under
``TYPE_CHECKING`` because its home module owns the ``vehicle_state`` table and pulls the database
layer in with it; the annotation is all this module needs.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bot.flows.definitions import FlowKind
from bot.services.consumption import ConsumptionResult

if TYPE_CHECKING:
    from bot.services.odometer_tracker import OdometerReference

__all__ = [
    "CardView",
    "ConfirmationView",
    "FieldEntry",
    "SummaryView",
]


@dataclass(frozen=True, slots=True)
class FieldEntry:
    """One collected field: its position, its label key and its rendered value.

    ``index`` is the field's position in the flow's field table, which is what the Field_Picker
    puts in the ``callback_data`` argument so that no field value ever travels in a callback
    (Requirement 11.3).
    """

    index: int
    label_key: str
    rendered_value: str


@dataclass(frozen=True, slots=True)
class CardView:
    """The state of an in-progress operation, as rendered on the Card_Message.

    ``progress`` is ``(current, total)`` counting data-entry steps, or ``None`` for a flow with a
    single field. ``reference`` is the Last_Known_Odometer line, absent when nothing is locally
    known. ``error_key`` holds the localized validation error of the last rejected value and is
    rendered once, then cleared by the flow.
    """

    kind: FlowKind
    vehicle_name: str
    collected: tuple[FieldEntry, ...]
    prompt_key: str
    progress: tuple[int, int] | None = None
    reference: OdometerReference | None = None
    error_key: str | None = None


@dataclass(frozen=True, slots=True)
class SummaryView:
    """Every collected value of a complete flow, awaiting save, edit or cancel."""

    kind: FlowKind
    vehicle_name: str
    entries: tuple[FieldEntry, ...]


@dataclass(frozen=True, slots=True)
class ConfirmationView:
    """A saved or queued record, as rendered after the flow ends.

    The same view feeds both renderings, which is what keeps a queued confirmation listing the
    same values as a saved one (Requirement 9.2). ``consumption`` is ``None`` whenever no figure is
    available, and the queued rendering never shows one at all (Requirement 9.3).
    """

    kind: FlowKind
    vehicle_name: str
    on_date: dt.date
    entries: tuple[FieldEntry, ...]
    consumption: ConsumptionResult | None = None
