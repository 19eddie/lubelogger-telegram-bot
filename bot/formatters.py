"""Message rendering for every surface the bot shows.

Pure module: every function is synchronous, takes plain data plus a language code and returns a
string. No Telegram object, no network, no database, so a renderer test can be written with
literals alone (NF-1.2).

Two rules live here and nowhere else:

- every value coming from the user or from the LubeLogger API passes through :func:`esc` **exactly
  once** before it is interpolated, which is what keeps a description such as
  ``oil change <5000km`` from breaking HTML delivery (Requirement 11.7, NF-6.3);
- literal HTML markup (``<b>``, ``<i>``, ``<code>``) only ever appears inside a locale template,
  never inside a value, so a new language is still one JSON file (NF-3.1).

Number and date shapes are locale data too: the decimal separator, the group separator and the
date patterns are read from the ``fmt_*`` keys (NF-3.3), so no formatting decision is hardcoded
here either.

Layout is assembled from sections — a header, the collected values, a footer — joined by a blank
line, so a renderer added later reuses the same helpers instead of re-deriving the shape.
"""

from __future__ import annotations

import datetime as dt
import html
from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import TYPE_CHECKING

from bot.flows.definitions import FlowKind, MenuAction
from bot.flows.views import CardView, ConfirmationView, FieldEntry, SummaryView
from bot.i18n import get_text

if TYPE_CHECKING:
    from bot.models.records import GasRecord, OdometerRecord
    from bot.services.consumption import ConsumptionResult
    from bot.services.odometer_tracker import OdometerReference

__all__ = [
    "esc",
    "fmt_date",
    "fmt_date_short",
    "fmt_display",
    "fmt_int",
    "fmt_plain",
    "render_abandon_prompt",
    "render_card",
    "render_cancelled",
    "render_confirmation",
    "render_latest_fuel",
    "render_latest_odometer",
    "render_odometer_reference",
    "render_progress",
    "render_queued",
    "render_regression",
    "render_summary",
    "render_welcome",
]

_MIN_PRECISION = 28
_PRECISION_HEADROOM = 8
_GROUP_SIZE = 3
_SECTION_SEPARATOR = "\n\n"


# --------------------------------------------------------------------------------------
# Escaping and value formatting
# --------------------------------------------------------------------------------------


def esc(value: object) -> str:
    """Escape a value for HTML parse mode, exactly once.

    ``quote=False`` because every interpolation happens in message text, never in an attribute,
    so quoting would only make a quoted description harder to read. ``None`` renders as the empty
    string rather than as ``"None"``: an absent value has no text.
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def fmt_plain(value: Decimal | float, lang: str) -> str:
    """Render a number with the locale decimal separator and no grouping.

    Used wherever the value is meant to be read back, retyped or parsed again, which is why the
    group separator is left out: the loose parser treats a lone separator as decimal, so the
    output round-trips in every locale (Requirement 12.4, NF-3.3).
    """
    return _apply_separators(_digits(_to_decimal(value)), lang, group=False)


def fmt_display(value: Decimal | float, lang: str, *, decimals: int = 2) -> str:
    """Render a number for display: fixed decimals, grouped integer part.

    ``decimals`` is the count of fractional digits, rounded half up.
    """
    if decimals < 0:
        raise ValueError(f"decimals must not be negative, got {decimals}")
    return _apply_separators(_digits(_quantize(_to_decimal(value), decimals)), lang, group=True)


def fmt_int(value: int, lang: str) -> str:
    """Render an integer with the locale group separator, e.g. ``45,230`` / ``45.230``."""
    return _apply_separators(str(int(value)), lang, group=True)


def fmt_date(value: dt.date, lang: str) -> str:
    """Render a full date with the locale pattern from ``fmt_date``."""
    return _format_date(value, get_text("fmt_date", lang))


def fmt_date_short(value: dt.date, lang: str) -> str:
    """Render a day/month date with the locale pattern from ``fmt_date_short``.

    Used by the odometer reference line, where the year adds noise more often than information
    (Requirement 5.3).
    """
    return _format_date(value, get_text("fmt_date_short", lang))


# --------------------------------------------------------------------------------------
# Flow renderers
# --------------------------------------------------------------------------------------


def render_progress(current: int, total: int, lang: str) -> str | None:
    """Render the Progress_Indicator, or ``None`` for a single-step flow.

    Returning ``None`` when ``total <= 1`` is how Requirement 4.2 is honoured without a per-flow
    special case: the odometer flow has one data-entry field, so it simply gets no indicator. The
    count covers data-entry steps only, never the Summary_State (Requirement 4.1).
    """
    if total <= 1:
        return None
    return get_text("card_progress", lang, current=current, total=total)


def render_card(view: CardView, lang: str) -> str:
    """Render the Card_Message of an in-progress operation (Requirements 3.3, 4.11).

    The card always states what has been collected so far, the current prompt and, when the flow
    has more than one field, the Progress_Indicator. The odometer reference is shown whenever the
    flow supplies one, and is omitted entirely when nothing is locally known (Requirement 5.6).
    ``error_key`` renders the localized validation error of the last rejected value, so an invalid
    entry re-renders the same step instead of ending the flow (Requirement 4.11).
    """
    header = [_title_line(view.kind, lang), _vehicle_line(view.vehicle_name, lang)]
    progress = render_progress(*view.progress, lang) if view.progress else None
    if progress:
        header.append(progress)

    footer: list[str] = []
    reference = _reference_line(view.reference, lang)
    if reference:
        footer.append(reference)
    if view.error_key:
        footer.append(get_text(view.error_key, lang))
    footer.append(get_text(view.prompt_key, lang))

    return _sections(header, _entry_lines(view.collected, lang), footer)


def render_summary(view: SummaryView, lang: str) -> str:
    """Render the Summary_State, listing every collected value (Requirement 4.6)."""
    header = [get_text("card_summary_title", lang), _vehicle_line(view.vehicle_name, lang)]
    return _sections(header, _entry_lines(view.entries, lang))


def render_regression(entered: int, reference: OdometerReference, lang: str) -> str:
    """Render the odometer-regression warning, stating both values (Requirement 5.8).

    The wording asks for a confirmation and offers to enter the value again; it never says the
    value is refused, because a lower reading is always acceptable once confirmed
    (Requirements 5.9, 5.10).
    """
    return get_text(
        "card_regression",
        lang,
        entered=_distance(entered, lang),
        reference=_distance(reference.value, lang),
    )


def render_cancelled(lang: str) -> str:
    """Render the final text of a cancelled operation (Requirements 4.4, 4.12)."""
    return get_text("card_cancelled", lang)


def render_confirmation(view: ConfirmationView, lang: str) -> str:
    """Render a saved record (Requirements 6.1, 6.2, 6.3).

    The vehicle name comes from the view, which the flow fills from the persisted
    Active_Vehicle_Name, so a confirmation names a real vehicle even when LubeLogger is
    unreachable (Requirement 6.4). The record kind decides the title and the fields listed, both of
    which come from the view rather than from a per-kind branch here.

    The consumption line is appended only when a figure exists, and states the unit that figure
    carries; when ``view.consumption`` is ``None`` the line is absent altogether, with no
    placeholder and no warning (Requirements 6.6, 6.9).
    """
    return _sections(
        _confirmation_header(f"card_saved_{view.kind.value}", view, lang),
        [*_entry_lines(view.entries, lang), *_consumption_lines(view.consumption, lang)],
    )


def render_queued(view: ConfirmationView, lang: str) -> str:
    """Render a record enqueued because LubeLogger is unreachable (Requirement 9.2).

    Built from the same view and the same line builders as :func:`render_confirmation`, which is
    what keeps a queued rendering listing the same values as a saved one. It adds the
    automatic-sync notice and never shows a consumption figure, whatever the view carries
    (Requirement 9.3).
    """
    return _sections(
        _confirmation_header(f"card_queued_{view.kind.value}", view, lang),
        _entry_lines(view.entries, lang),
        [get_text("card_queued_notice", lang)],
    )


def render_abandon_prompt(target: MenuAction, lang: str) -> str:
    """Ask whether to discard the flow in progress and go to ``target`` (Requirement 11.5)."""
    return get_text(
        "card_abandon_prompt",
        lang,
        target=esc(get_text(f"menu_{target.value}", lang)),
    )


def render_latest_fuel(
    record: GasRecord | None,
    vehicle_name: str,
    consumption: ConsumptionResult | None,
    lang: str,
) -> str:
    """Render the last fuel record, or the empty notice (Requirements 10.2, 10.4).

    Every field the record actually carries is listed; a field LubeLogger left out is skipped
    rather than rendered as an empty value, because the read models make every field optional
    (NF-6.1). The consumption line follows the same rule as on a confirmation.
    """
    if record is None:
        return _sections(
            [get_text("card_latest_fuel_title", lang)],
            [get_text("card_latest_empty", lang)],
        )
    return _sections(
        _record_header("card_latest_fuel_title", vehicle_name, record.date, lang),
        [*_gas_lines(record, lang), *_consumption_lines(consumption, lang)],
    )


def render_latest_odometer(record: OdometerRecord | None, vehicle_name: str, lang: str) -> str:
    """Render the last odometer reading, or the empty notice (Requirements 10.2, 10.4)."""
    if record is None:
        return _sections(
            [get_text("card_latest_odometer_title", lang)],
            [get_text("card_latest_empty", lang)],
        )
    values = []
    if record.odometer is not None:
        values.append(_escaped_line("field_odometer", _distance(record.odometer, lang), lang))
    return _sections(
        _record_header("card_latest_odometer_title", vehicle_name, record.date, lang),
        values,
    )


def render_odometer_reference(reference: OdometerReference | None, lang: str) -> str:
    """Render the Last_Known_Odometer line, empty when nothing is known (Req 5.3, 5.6).

    Delegates to the very same builder the card uses, so the reference cannot be worded one way
    inside a flow and another way outside it.
    """
    return _reference_line(reference, lang)


def render_welcome(vehicle_name: str | None, lang: str) -> str:
    """Render the /start message: the onboarding welcome or the welcome-back (Req 8.1, 8.4).

    ``None`` means no active vehicle is persisted, which is the onboarding case. A name that is
    present but blank means an active vehicle the API cannot name, so it renders through the
    localized fallback (Requirement 13.6) instead of leaving the sentence dangling.

    The unreachable case of Requirement 8.5 is not a welcome variant: the caller has no vehicle
    list to offer and renders ``lubelogger_unreachable`` / ``welcome_unreachable`` instead.
    """
    if vehicle_name is None:
        return get_text("welcome_new", lang)
    return get_text("welcome_back", lang, vehicle_name=esc(_vehicle_name(vehicle_name, lang)))


# --------------------------------------------------------------------------------------
# Shared line builders
#
# Every renderer added later — the confirmation, latest, options and welcome ones — builds its
# text out of these, so the card, the summary and the confirmations cannot drift apart.
# --------------------------------------------------------------------------------------


def _title_line(kind: FlowKind, lang: str) -> str:
    """Return the card title of a flow kind, e.g. ``card_title_fuel``."""
    return get_text(f"card_title_{kind.value}", lang)


def _line(label_key: str, value: str, lang: str) -> str:
    """Return one ``label: value`` line, with the value already escaped by the caller."""
    return get_text("card_line", lang, label=get_text(label_key, lang), value=value)


def _vehicle_line(vehicle_name: str, lang: str) -> str:
    """Return the vehicle line, falling back to the localized label when unnameable (Req 13.6)."""
    return _line("field_vehicle", esc(_vehicle_name(vehicle_name, lang)), lang)


def _vehicle_name(vehicle_name: str, lang: str) -> str:
    """Return the vehicle name, or the localized fallback when there is none."""
    return vehicle_name.strip() or get_text("vehicle_fallback_name", lang)


def _entry_lines(entries: Sequence[FieldEntry], lang: str) -> list[str]:
    """Return one line per collected field, each value escaped exactly once."""
    return [_line(entry.label_key, esc(entry.rendered_value), lang) for entry in entries]


def _escaped_line(label_key: str, value: str, lang: str) -> str:
    """Return one ``label: value`` line, escaping the value here so callers cannot forget."""
    return _line(label_key, esc(value), lang)


def _date_line(value: dt.date, lang: str) -> str:
    """Return the record date line, rendered with the locale date pattern."""
    return _escaped_line("field_date", fmt_date(value, lang), lang)


def _confirmation_header(title_key: str, view: ConfirmationView, lang: str) -> list[str]:
    """Return the title, vehicle and date lines shared by the saved and queued renderings."""
    return [
        get_text(title_key, lang),
        _vehicle_line(view.vehicle_name, lang),
        _date_line(view.on_date, lang),
    ]


def _record_header(
    title_key: str, vehicle_name: str, on_date: dt.date | None, lang: str
) -> list[str]:
    """Return the header of a record read back from the API, whose date may be missing."""
    header = [get_text(title_key, lang), _vehicle_line(vehicle_name, lang)]
    if on_date is not None:
        header.append(_date_line(on_date, lang))
    return header


def _consumption_lines(result: ConsumptionResult | None, lang: str) -> list[str]:
    """Return the consumption line, or no line at all when there is no figure.

    The unit travels with the figure rather than being assumed here, so a reported value and an
    own estimate both state what they are measured in (Requirement 6.6). An estimate uses its own
    template, which is where the "estimate" wording lives. No figure means no line, no placeholder
    and no warning (Requirement 6.9).
    """
    if result is None:
        return []
    template = "card_consumption_estimate" if result.estimated else "card_consumption"
    value = get_text(
        template,
        lang,
        value=fmt_display(result.value, lang),
        unit=esc(result.unit),
    )
    return [_line("field_consumption", value, lang)]


def _gas_lines(record: GasRecord, lang: str) -> list[str]:
    """Return one line per field a gas record carries, skipping the ones it does not."""
    lines: list[str] = []
    if record.odometer is not None:
        lines.append(_escaped_line("field_odometer", _distance(record.odometer, lang), lang))
    if record.fuel_consumed is not None:
        lines.append(_escaped_line("field_liters", _volume(record.fuel_consumed, lang), lang))
    if record.cost is not None:
        lines.append(_escaped_line("field_cost", _currency(record.cost, lang), lang))
    lines.append(_escaped_line("field_full_tank", _boolean(record.is_fill_to_full, lang), lang))
    return lines


def _reference_line(reference: OdometerReference | None, lang: str) -> str:
    """Return the Last_Known_Odometer line, or the empty string when nothing is known.

    Shared with the public ``render_odometer_reference``: the card needs the very same line
    (Requirements 5.3, 5.6).
    """
    if reference is None:
        return ""
    value = _distance(reference.value, lang)
    source = get_text(f"card_source_{reference.source}", lang)
    if reference.on_date is None:
        return get_text("card_reference_nodate", lang, value=value, source=source)
    return get_text(
        "card_reference",
        lang,
        value=value,
        source=source,
        date=fmt_date_short(reference.on_date, lang),
    )


def _distance(value: int, lang: str) -> str:
    """Return a grouped odometer value followed by the locale distance unit."""
    return f"{fmt_int(value, lang)} {get_text('fmt_unit_distance', lang)}"


def _volume(value: Decimal, lang: str) -> str:
    """Return a volume followed by the locale volume unit, e.g. ``42.50 L``."""
    return f"{fmt_display(value, lang)} {get_text('fmt_unit_volume', lang)}"


def _currency(value: Decimal, lang: str) -> str:
    """Return an amount followed by the locale currency symbol, e.g. ``78.90 €``.

    The symbol trails the amount in every locale, the way it does for distance and volume, so one
    line shape covers every unit. The known limitation that amounts are always rendered in euro
    regardless of the LubeLogger instance configuration is documented in the README (NF-5.2).
    """
    return f"{fmt_display(value, lang)} {get_text('fmt_unit_currency', lang)}"


def _boolean(value: bool, lang: str) -> str:
    """Return the localized Yes/No of a flag, read from the ``fmt_bool_*`` keys."""
    return get_text("fmt_bool_true" if value else "fmt_bool_false", lang)


def _sections(*sections: Iterable[str]) -> str:
    """Join groups of lines: a newline inside a group, a blank line between groups.

    Empty groups disappear, so a flow with nothing collected yet shows no stray blank line.
    """
    rendered = ["\n".join(line for line in section if line) for section in sections]
    return _SECTION_SEPARATOR.join(block for block in rendered if block)


# --------------------------------------------------------------------------------------
# Number and date primitives
# --------------------------------------------------------------------------------------


def _to_decimal(value: Decimal | float | str) -> Decimal:
    """Coerce a number to a finite ``Decimal``.

    Floats go through ``str`` so that ``42.5`` keeps the shape it was written in rather than its
    binary expansion. A non-finite or unparsable value is a programming error, not a rendering
    case, so it is reported instead of being printed.
    """
    if isinstance(value, bool):
        raise TypeError("a boolean is not a number to format")
    try:
        coerced = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"cannot format {value!r} as a number") from exc
    if not coerced.is_finite():
        raise ValueError(f"cannot format the non-finite value {value!r}")
    return coerced


def _quantize(value: Decimal, decimals: int) -> Decimal:
    """Round a decimal to ``decimals`` fractional digits, half up.

    The precision follows the magnitude of the operand, so quantizing a large value rounds
    instead of signalling.
    """
    with localcontext() as ctx:
        ctx.prec = max(_MIN_PRECISION, abs(value.adjusted()) + decimals + _PRECISION_HEADROOM)
        return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _digits(value: Decimal) -> str:
    """Return the plain digits of a decimal, never in scientific notation."""
    return format(value, "f")


def _apply_separators(digits: str, lang: str, *, group: bool) -> str:
    """Rewrite plain ``-1234.5`` digits with the locale separators."""
    sign = "-" if digits.startswith("-") else ""
    unsigned = digits.lstrip("-")
    integer, _, fraction = unsigned.partition(".")
    if group:
        integer = _group(integer, get_text("fmt_group_sep", lang))
    if not fraction:
        return f"{sign}{integer}"
    return f"{sign}{integer}{get_text('fmt_decimal_sep', lang)}{fraction}"


def _group(integer: str, separator: str) -> str:
    """Insert ``separator`` every three digits, counting from the right."""
    if not separator or len(integer) <= _GROUP_SIZE:
        return integer
    chunks = []
    for end in range(len(integer), 0, -_GROUP_SIZE):
        chunks.append(integer[max(end - _GROUP_SIZE, 0) : end])
    return separator.join(reversed(chunks))


def _format_date(value: dt.date, pattern: str) -> str:
    """Render a date with a locale ``strftime`` pattern.

    The directives the locales use are expanded here rather than by ``strftime``, because C
    library behaviour for early years and for zero padding is platform-dependent while a rendered
    date must not be. Any other directive falls back to ``strftime``, and an ISO date is the last
    resort, so an exotic pattern degrades instead of raising.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char != "%" or index + 1 >= len(pattern):
            out.append(char)
            index += 1
            continue
        directive = pattern[index + 1]
        expanded = _expand_directive(value, directive)
        if expanded is None:
            return _strftime(value, pattern)
        out.append(expanded)
        index += 2
    return "".join(out)


def _expand_directive(value: dt.date, directive: str) -> str | None:
    """Expand one ``strftime`` directive, or return ``None`` when it is not handled here."""
    match directive:
        case "d":
            return f"{value.day:02d}"
        case "m":
            return f"{value.month:02d}"
        case "Y":
            return f"{value.year:04d}"
        case "y":
            return f"{value.year % 100:02d}"
        case "%":
            return "%"
        case _:
            return None


def _strftime(value: dt.date, pattern: str) -> str:
    """Delegate to ``strftime``, degrading to the ISO form when the platform refuses."""
    try:
        return value.strftime(pattern)
    except (ValueError, OverflowError):
        return value.isoformat()
