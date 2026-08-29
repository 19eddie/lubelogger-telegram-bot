"""Unit tests for the core message renderers (bot/formatters.py)."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.flows.definitions import FIELDS, FlowKind, MenuAction, field_at, field_count
from bot.flows.views import CardView, ConfirmationView, FieldEntry, SummaryView
from bot.formatters import (
    esc,
    fmt_date,
    fmt_date_short,
    fmt_display,
    fmt_int,
    fmt_plain,
    render_abandon_prompt,
    render_cancelled,
    render_card,
    render_confirmation,
    render_latest_fuel,
    render_latest_odometer,
    render_odometer_reference,
    render_progress,
    render_queued,
    render_regression,
    render_summary,
    render_welcome,
)
from bot.i18n import available_locales, get_text
from bot.models.records import GasRecord, OdometerRecord
from bot.services.consumption import CONSUMPTION_UNIT, ConsumptionResult
from bot.services.odometer_tracker import OdometerReference

_REFERENCE = OdometerReference(value=45_230, on_date=dt.date(2025, 7, 12), source="gas")


def _entries() -> tuple[FieldEntry, ...]:
    return (
        FieldEntry(index=0, label_key="field_odometer", rendered_value="45.280"),
        FieldEntry(index=1, label_key="field_liters", rendered_value="42,5"),
    )


def _card(**overrides: object) -> CardView:
    defaults: dict[str, object] = {
        "kind": FlowKind.FUEL,
        "vehicle_name": "2019 Volvo V60",
        "collected": _entries(),
        "prompt_key": "ask_cost",
        "progress": (3, 4),
        "reference": None,
        "error_key": None,
    }
    defaults.update(overrides)
    return CardView(**defaults)  # type: ignore[arg-type]


# --- escaping -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("oil change <5000km", "oil change &lt;5000km"),
        ("a & b", "a &amp; b"),
        ("<b>bold</b>", "&lt;b&gt;bold&lt;/b&gt;"),
        ("", ""),
        ("⛽ 42", "⛽ 42"),
        (None, ""),
        (42, "42"),
    ],
)
def test_esc_escapes_once(raw: object, expected: str) -> None:
    assert esc(raw) == expected


def test_esc_is_not_applied_twice_by_the_renderers() -> None:
    """Requirement 11.7: a value is escaped exactly once, never double-encoded."""
    entry = FieldEntry(index=0, label_key="field_description", rendered_value="oil change <5000km")
    text = render_summary(SummaryView(FlowKind.SERVICE, "Van", (entry,)), "en")
    assert "oil change &lt;5000km" in text
    assert "&amp;lt;" not in text


# --- numbers and dates ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "small", "large"),
    [("en", "42.5", "1234.5"), ("it", "42,5", "1234,5")],
)
def test_fmt_plain_uses_the_locale_decimal_separator_without_grouping(
    lang: str, small: str, large: str
) -> None:
    assert fmt_plain(Decimal("42.5"), lang) == small
    assert fmt_plain(1234.5, lang) == large


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "1,234.50"), ("it", "1.234,50")],
)
def test_fmt_display_groups_and_fixes_the_decimals(lang: str, expected: str) -> None:
    assert fmt_display(Decimal("1234.5"), lang) == expected
    assert fmt_display(Decimal("1234.499"), lang) == expected


def test_fmt_display_rounds_half_up_and_honours_the_decimals_argument() -> None:
    assert fmt_display(Decimal("2.345"), "en") == "2.35"
    assert fmt_display(Decimal("2.345"), "en", decimals=0) == "2"
    assert fmt_display(Decimal("2.5"), "en", decimals=0) == "3"


def test_fmt_display_rejects_negative_decimals() -> None:
    with pytest.raises(ValueError, match="decimals"):
        fmt_display(Decimal("1"), "en", decimals=-1)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "45,230"), ("it", "45.230")],
)
def test_fmt_int_groups_with_the_locale_separator(lang: str, expected: str) -> None:
    assert fmt_int(45_230, lang) == expected


@pytest.mark.parametrize(
    ("value", "expected_en"),
    [(0, "0"), (999, "999"), (1_000, "1,000"), (-1_234_567, "-1,234,567")],
)
def test_fmt_int_boundaries(value: int, expected_en: str) -> None:
    assert fmt_int(value, "en") == expected_en


def test_fmt_plain_never_uses_scientific_notation() -> None:
    assert fmt_plain(Decimal("1E+3"), "en") == "1000"


def test_fmt_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        fmt_plain(Decimal("NaN"), "en")


@pytest.mark.parametrize(
    ("lang", "full", "short"),
    [("en", "07/12/2025", "07/12"), ("it", "12/07/2025", "12/07")],
)
def test_dates_follow_the_locale_pattern(lang: str, full: str, short: str) -> None:
    day = dt.date(2025, 7, 12)
    assert fmt_date(day, lang) == full
    assert fmt_date_short(day, lang) == short


# --- progress -------------------------------------------------------------------------


def test_render_progress_is_omitted_for_a_single_step_flow() -> None:
    """Requirement 4.2: one data-entry field means no Progress_Indicator."""
    assert render_progress(1, 1, "en") is None


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_progress_states_current_and_total(lang: str) -> None:
    rendered = render_progress(2, 4, lang)
    assert rendered is not None
    assert "2" in rendered
    assert "4" in rendered


# --- card -----------------------------------------------------------------------------


def test_render_card_shows_collected_values_progress_and_prompt() -> None:
    """Requirement 3.3: the card states what is collected, what is asked and where we are."""
    text = render_card(_card(), "en")
    assert get_text("card_title_fuel", "en") in text
    assert "2019 Volvo V60" in text
    assert "45.280" in text
    assert "42,5" in text
    assert get_text("ask_cost", "en") in text
    assert "3" in text and "4" in text


def test_render_card_of_a_single_field_flow_carries_no_progress_line() -> None:
    text = render_card(
        _card(kind=FlowKind.ODOMETER, collected=(), prompt_key="ask_odometer", progress=(1, 1)),
        "en",
    )
    assert get_text("card_progress", "en", current=1, total=1) not in text
    assert get_text("ask_odometer", "en") in text


def test_render_card_shows_the_reference_with_its_date_and_source() -> None:
    """Requirement 5.3: the reference names both the date and where it came from."""
    text = render_card(_card(reference=_REFERENCE), "en")
    assert "45,230" in text
    assert get_text("card_source_gas", "en") in text
    assert fmt_date_short(_REFERENCE.on_date, "en") in text  # type: ignore[arg-type]


def test_render_card_omits_the_reference_when_nothing_is_known() -> None:
    """Requirement 5.6: no local value means no reference line at all."""
    reference_line = get_text(
        "card_reference",
        "en",
        value=f"{fmt_int(_REFERENCE.value, 'en')} {get_text('fmt_unit_distance', 'en')}",
        source=get_text("card_source_gas", "en"),
        date=fmt_date_short(dt.date(2025, 7, 12), "en"),
    )

    assert reference_line in render_card(_card(reference=_REFERENCE), "en")
    assert reference_line not in render_card(_card(reference=None), "en")
    assert "45,230" not in render_card(_card(reference=None), "en")


def test_render_card_reference_without_a_date_uses_the_short_template() -> None:
    reference = OdometerReference(value=45_230, on_date=None, source="api")
    text = render_card(_card(reference=reference), "en")
    assert get_text("card_source_api", "en") in text
    assert "45,230" in text


def test_render_card_renders_the_validation_error_and_keeps_the_prompt() -> None:
    """Requirement 4.11: an invalid value re-renders the same step with a localized error."""
    text = render_card(_card(error_key="invalid_cost"), "en")
    assert get_text("invalid_cost", "en") in text
    assert get_text("ask_cost", "en") in text


def test_render_card_falls_back_to_the_localized_vehicle_label() -> None:
    """Requirement 13.6: an unnameable vehicle never renders as an untranslated placeholder."""
    for lang in ("en", "it"):
        text = render_card(_card(vehicle_name="   "), lang)
        assert get_text("vehicle_fallback_name", lang) in text


def test_render_card_escapes_api_and_user_values_once() -> None:
    entry = FieldEntry(index=0, label_key="field_description", rendered_value="a & b <c>")
    view = _card(kind=FlowKind.SERVICE, collected=(entry,), vehicle_name="Fiat <500>")
    text = render_card(view, "en")
    assert "a &amp; b &lt;c&gt;" in text
    assert "Fiat &lt;500&gt;" in text
    assert "&amp;amp;" not in text


def test_render_card_has_no_stray_blank_lines_when_nothing_is_collected() -> None:
    text = render_card(_card(collected=(), progress=(1, 4)), "en")
    assert "\n\n\n" not in text


# --- summary, regression, cancellation ------------------------------------------------


def test_render_summary_lists_every_collected_value() -> None:
    """Requirement 4.6: the Summary_State shows all of them, none missing."""
    text = render_summary(SummaryView(FlowKind.FUEL, "Van", _entries()), "en")
    assert get_text("card_summary_title", "en") in text
    for entry in _entries():
        assert entry.rendered_value in text
        assert get_text(entry.label_key, "en") in text


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_regression_states_both_values(lang: str) -> None:
    """Requirement 5.8: the warning names the entered value and the last known one."""
    text = render_regression(45_000, _REFERENCE, lang)
    assert fmt_int(45_000, lang) in text
    assert fmt_int(_REFERENCE.value, lang) in text
    assert get_text("fmt_unit_distance", lang) in text


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_cancelled_is_the_localized_notice(lang: str) -> None:
    assert render_cancelled(lang) == get_text("card_cancelled", lang)


# --- confirmations --------------------------------------------------------------------


def _confirmation(**overrides: object) -> ConfirmationView:
    defaults: dict[str, object] = {
        "kind": FlowKind.FUEL,
        "vehicle_name": "2019 Volvo V60",
        "on_date": dt.date(2025, 7, 12),
        "entries": (
            FieldEntry(index=0, label_key="field_odometer", rendered_value="45,280 km"),
            FieldEntry(index=1, label_key="field_liters", rendered_value="42.50 L"),
            FieldEntry(index=2, label_key="field_cost", rendered_value="78.90 €"),
            FieldEntry(index=3, label_key="field_full_tank", rendered_value="Yes"),
        ),
        "consumption": None,
    }
    defaults.update(overrides)
    return ConfirmationView(**defaults)  # type: ignore[arg-type]


def test_render_confirmation_names_the_vehicle_the_date_and_every_field() -> None:
    """Requirements 6.1, 6.4: the saved card lists the whole record under a real vehicle name."""
    view = _confirmation()
    text = render_confirmation(view, "en")
    assert get_text("card_saved_fuel", "en") in text
    assert "2019 Volvo V60" in text
    assert fmt_date(view.on_date, "en") in text
    for entry in view.entries:
        assert get_text(entry.label_key, "en") in text
        assert entry.rendered_value in text


@pytest.mark.parametrize(
    ("kind", "title_key"),
    [
        (FlowKind.SERVICE, "card_saved_service"),
        (FlowKind.ODOMETER, "card_saved_odometer"),
    ],
)
def test_render_confirmation_titles_follow_the_record_kind(kind: FlowKind, title_key: str) -> None:
    """Requirements 6.2, 6.3: each record kind gets its own confirmation."""
    text = render_confirmation(_confirmation(kind=kind), "en")
    assert get_text(title_key, "en") in text


def test_render_confirmation_shows_the_consumption_with_its_unit() -> None:
    """Requirement 6.5: a reported figure is shown as such, with its unit and no estimate label."""
    result = ConsumptionResult(value=Decimal("5.70"), unit=CONSUMPTION_UNIT, estimated=False)
    text = render_confirmation(_confirmation(consumption=result), "en")
    assert get_text("field_consumption", "en") in text
    assert "5.70" in text
    assert CONSUMPTION_UNIT in text
    assert (
        get_text("card_consumption_estimate", "en", value="5.70", unit=CONSUMPTION_UNIT) not in text
    )


def test_render_confirmation_labels_an_own_estimate_as_such() -> None:
    """Requirement 6.6: the bot's own figure is labelled an estimate."""
    result = ConsumptionResult(value=Decimal("6.12"), unit=CONSUMPTION_UNIT, estimated=True)
    text = render_confirmation(_confirmation(consumption=result), "en")
    assert get_text("card_consumption_estimate", "en", value="6.12", unit=CONSUMPTION_UNIT) in text


def test_render_confirmation_omits_the_consumption_line_entirely_when_absent() -> None:
    """Requirement 6.9: no figure means no line, not a placeholder."""
    text = render_confirmation(_confirmation(consumption=None), "en")
    assert get_text("field_consumption", "en") not in text


def test_render_confirmation_falls_back_to_the_localized_vehicle_label() -> None:
    """Requirement 13.6: an unnameable vehicle still reads as a vehicle."""
    for lang in ("en", "it"):
        text = render_confirmation(_confirmation(vehicle_name=""), lang)
        assert get_text("vehicle_fallback_name", lang) in text


def test_render_queued_lists_the_same_values_and_states_the_automatic_sync() -> None:
    """Requirement 9.2: the queued card says the same things plus the sync notice."""
    view = _confirmation()
    queued = render_queued(view, "en")
    assert get_text("card_queued_fuel", "en") in queued
    assert get_text("card_queued_notice", "en") in queued
    for entry in view.entries:
        assert entry.rendered_value in queued
        assert get_text(entry.label_key, "en") in queued
    assert fmt_date(view.on_date, "en") in queued


def test_render_queued_never_shows_a_consumption_figure() -> None:
    """Requirement 9.3: a queued record carries no consumption, even when the view has one."""
    result = ConsumptionResult(value=Decimal("5.70"), unit=CONSUMPTION_UNIT, estimated=False)
    text = render_queued(_confirmation(consumption=result), "en")
    assert get_text("field_consumption", "en") not in text
    assert "5.70" not in text


def test_render_queued_escapes_values_once() -> None:
    entry = FieldEntry(index=0, label_key="field_description", rendered_value="oil & filter <x>")
    text = render_queued(
        _confirmation(kind=FlowKind.SERVICE, entries=(entry,), vehicle_name="Fiat <500>"), "en"
    )
    assert "oil &amp; filter &lt;x&gt;" in text
    assert "Fiat &lt;500&gt;" in text
    assert "&amp;amp;" not in text


# --- abandon prompt -------------------------------------------------------------------


@pytest.mark.parametrize("target", list(MenuAction))
@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_abandon_prompt_names_the_requested_destination(
    target: MenuAction, lang: str
) -> None:
    """Requirement 11.5: the confirmation says where the user asked to go."""
    text = render_abandon_prompt(target, lang)
    assert get_text(f"menu_{target.value}", lang) in text
    assert "{target}" not in text


# --- latest ---------------------------------------------------------------------------


def _gas_record(**overrides: object) -> GasRecord:
    payload: dict[str, object] = {
        "date": "2025-07-12",
        "odometer": 45_280,
        "fuelConsumed": "42.5",
        "cost": "78.9",
        "isFillToFull": True,
    }
    payload.update(overrides)
    return GasRecord.model_validate(payload)


def test_render_latest_fuel_shows_the_record_with_units() -> None:
    """Requirement 10.2: the record is rendered in place of the menu."""
    result = ConsumptionResult(value=Decimal("5.70"), unit=CONSUMPTION_UNIT, estimated=False)
    text = render_latest_fuel(_gas_record(), "2019 Volvo V60", result, "en")
    assert get_text("card_latest_fuel_title", "en") in text
    assert "2019 Volvo V60" in text
    assert "45,280" in text
    assert "42.50" in text
    assert "78.90" in text
    assert get_text("fmt_bool_true", "en") in text
    assert CONSUMPTION_UNIT in text


def test_render_latest_fuel_skips_the_fields_the_api_left_out() -> None:
    text = render_latest_fuel(
        _gas_record(cost=None, fuelConsumed=None, date=None), "Van", None, "en"
    )
    assert get_text("field_cost", "en") not in text
    assert get_text("field_liters", "en") not in text
    assert get_text("field_date", "en") not in text
    assert "45,280" in text


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_latest_fuel_states_when_there_is_no_record(lang: str) -> None:
    """Requirement 10.4: an empty result is stated, not left blank."""
    text = render_latest_fuel(None, "Van", None, lang)
    assert get_text("card_latest_empty", lang) in text
    assert get_text("card_latest_fuel_title", lang) in text


def test_render_latest_odometer_shows_date_and_value() -> None:
    record = OdometerRecord.model_validate({"date": "2025-07-12", "odometer": 45_280})
    text = render_latest_odometer(record, "Van", "en")
    assert get_text("card_latest_odometer_title", "en") in text
    assert fmt_date(dt.date(2025, 7, 12), "en") in text
    assert "45,280" in text


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_latest_odometer_states_when_there_is_no_record(lang: str) -> None:
    text = render_latest_odometer(None, "Van", lang)
    assert get_text("card_latest_empty", lang) in text


# --- odometer reference and welcome ---------------------------------------------------


def test_render_odometer_reference_matches_the_card_line() -> None:
    """Requirement 5.3: the reference is worded the same way inside and outside a flow."""
    rendered = render_odometer_reference(_REFERENCE, "en")
    assert rendered
    assert rendered in render_card(_card(reference=_REFERENCE), "en")


def test_render_odometer_reference_is_empty_when_nothing_is_known() -> None:
    """Requirement 5.6: an unknown reference renders as nothing at all."""
    assert render_odometer_reference(None, "en") == ""


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_welcome_without_a_vehicle_is_the_onboarding_text(lang: str) -> None:
    """Requirement 8.1: the first welcome explains the bot in at most three sentences."""
    text = render_welcome(None, lang)
    assert text == get_text("welcome_new", lang)
    assert text.count(".") <= 3


@pytest.mark.parametrize("lang", ["en", "it"])
def test_render_welcome_back_names_the_active_vehicle(lang: str) -> None:
    """Requirement 8.4: coming back, the message says which vehicle is active."""
    text = render_welcome("2019 Volvo V60", lang)
    assert "2019 Volvo V60" in text
    assert "{vehicle_name}" not in text


def test_render_welcome_back_falls_back_to_the_localized_label() -> None:
    """Requirement 13.6: an active vehicle without a name still reads as a vehicle."""
    for lang in ("en", "it"):
        assert get_text("vehicle_fallback_name", lang) in render_welcome("  ", lang)


def test_render_welcome_escapes_the_vehicle_name() -> None:
    assert "Fiat &lt;500&gt;" in render_welcome("Fiat <500>", "en")


# =====================================================================================
# Property 9: The Progress_Indicator counts only data-entry steps
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P9_LOCALES = st.sampled_from(available_locales())


@st.composite
def _p9_flow_steps(draw: st.DrawFn) -> tuple[FlowKind, int]:
    """Draw a flow kind together with a reachable data-entry step of that flow.

    The step is drawn in ``1..field_count(kind)``: the Summary_State is not a data-entry step, so
    it is deliberately outside the drawn range (Requirement 4.1).
    """
    kind = draw(st.sampled_from(list(FlowKind)))
    current = draw(st.integers(min_value=1, max_value=field_count(kind)))
    return kind, current


@settings(max_examples=100)
@given(
    step=_p9_flow_steps(),
    lang=_P9_LOCALES,
    single_step_total=st.integers(min_value=-3, max_value=1),
)
def test_property_progress_indicator(
    step: tuple[FlowKind, int], lang: str, single_step_total: int
) -> None:
    """Property 9: The Progress_Indicator counts only data-entry steps.

    # Feature: improve-ux, Property 9: The Progress_Indicator counts only data-entry steps
    **Validates: Requirements 4.1, 4.2**
    """
    kind, current = step
    total = field_count(kind)
    rendered = render_progress(current, total, lang)

    # Requirement 4.2: no indicator exactly when the flow has a single data-entry field, which is
    # the odometer flow; a flow with more fields always gets one.
    assert (rendered is None) is (total <= 1)
    assert render_progress(current, single_step_total, lang) is None

    if rendered is None:
        assert total == 1
        return

    # Requirement 4.1: both numbers are rendered through the locale template, the current step
    # stays inside the data-entry range, and the total is the field count of the flow.
    assert rendered == get_text("card_progress", lang, current=current, total=total)
    assert str(current) in rendered
    assert str(total) in rendered
    assert 1 <= current <= total == field_count(kind)

    # Requirement 4.1 stated the other way round: counting the Summary_State would raise the total
    # by one, and that is never what the indicator says.
    assert rendered != get_text("card_progress", lang, current=current, total=total + 1)

    # Requirement 4.1: along a normal collection sequence the current step advances strictly, one
    # rendering per data-entry field and no rendering beyond the last one.
    sequence = [render_progress(index, total, lang) for index in range(1, total + 1)]
    assert sequence == [
        get_text("card_progress", lang, current=index, total=total) for index in range(1, total + 1)
    ]
    assert len(set(sequence)) == total
    for index, text in enumerate(sequence, start=1):
        assert text is not None
        assert str(index) in text


# =====================================================================================
# Property 10: The card always shows what has been collected and what is being asked
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P10_LOCALES = st.sampled_from(available_locales())

#: Values as the flow hands them to the view: already rendered, and deliberately including HTML
#: metacharacters, an emoji, a blank and an empty string. None of them collides with locale text,
#: so a value can never be mistaken for a prompt or an error.
_P10_VALUES = st.sampled_from(
    [
        "45.280",
        "42,5",
        "78,90 €",
        "0",
        "",
        "   ",
        "oil change <5000km",
        'tyres "front" & rear',
        "🚗 filled up",
    ]
)

#: A named vehicle, an unnameable one, and one carrying markup.
_P10_VEHICLES = st.sampled_from(["2019 Volvo V60", "Fiat <500>", "Škoda & Co", "", "   "])

_P10_SOURCES = st.sampled_from(["gas", "service", "odometer", "bot", "api"])

_P10_REFERENCES = st.builds(
    OdometerReference,
    value=st.integers(min_value=0, max_value=2_000_000),
    on_date=st.one_of(
        st.none(),
        st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)),
    ),
    source=_P10_SOURCES,
)


@st.composite
def _p10_cards(draw: st.DrawFn) -> CardView:
    """Draw a ``CardView`` the flow could actually build.

    The collected entries are the prefix of the flow's field table that precedes the prompted
    field, which is exactly what a flow holds mid-collection, and the prompt key is the prompted
    field's own ``ask_`` key. Progress, reference and error are each drawn present or absent, so
    the four combinations the card has to render are all reachable.
    """
    kind = draw(st.sampled_from(list(FlowKind)))
    total = field_count(kind)
    current = draw(st.integers(min_value=1, max_value=total))
    collected = tuple(
        FieldEntry(
            index=index,
            label_key=field_at(kind, index).label_key,
            rendered_value=draw(_P10_VALUES),
        )
        for index in range(current - 1)
    )
    prompted = field_at(kind, current - 1)
    return CardView(
        kind=kind,
        vehicle_name=draw(_P10_VEHICLES),
        collected=collected,
        prompt_key=prompted.prompt_key,
        progress=draw(st.sampled_from([None, (current, total)])),
        reference=draw(st.one_of(st.none(), _P10_REFERENCES)),
        error_key=draw(st.one_of(st.none(), st.just(prompted.error_key))),
    )


@settings(max_examples=100)
@given(view=_p10_cards(), lang=_P10_LOCALES)
def test_property_card_contains_collected(view: CardView, lang: str) -> None:
    """Property 10: The card always shows what has been collected and what is being asked.

    # Feature: improve-ux, Property 10: The card always shows what has been collected and what
    # is being asked
    **Validates: Requirements 3.3, 4.11**
    """
    text = render_card(view, lang)

    # Requirement 3.3: the flow is named and the vehicle is stated, an unnameable one through the
    # localized fallback rather than a blank.
    assert get_text(f"card_title_{view.kind.value}", lang) in text
    expected_vehicle = view.vehicle_name.strip() or get_text("vehicle_fallback_name", lang)
    assert esc(expected_vehicle) in text

    # Requirement 3.3: every collected value is on the card, paired with its own localized label
    # and escaped exactly once — escaping it twice would show the entity, not the character.
    for entry in view.collected:
        escaped = esc(entry.rendered_value)
        assert (
            get_text("card_line", lang, label=get_text(entry.label_key, lang), value=escaped)
            in text
        )
        if escaped != entry.rendered_value:
            assert esc(escaped) not in text

    # Requirement 3.3: the prompt for the current field is always there, whatever else the card
    # happens to carry.
    assert get_text(view.prompt_key, lang) in text

    # Requirement 3.3 together with 4.2: the Progress_Indicator is rendered whenever the flow
    # supplies a counter with more than one data-entry step, and no counter line appears otherwise.
    expected_progress = render_progress(*view.progress, lang) if view.progress else None
    if expected_progress is not None:
        assert view.progress is not None and view.progress[1] > 1
        assert expected_progress in text
    else:
        current, total = view.progress or (1, 1)
        assert get_text("card_progress", lang, current=current, total=total) not in text

    # Requirement 5.3 as the card sees it: the reference line is worded exactly as
    # render_odometer_reference words it, and is absent when nothing is locally known (5.6).
    reference_line = render_odometer_reference(view.reference, lang)
    if view.reference is None:
        assert reference_line == ""
    else:
        assert reference_line and reference_line in text
        assert get_text(f"card_source_{view.reference.source}", lang) in text

    # Requirement 4.11: a rejected value adds the localized error and keeps the prompt, so the
    # same step is re-rendered; with no error the card carries no error text at all.
    if view.error_key is not None:
        assert get_text(view.error_key, lang) in text
        assert get_text(view.prompt_key, lang) in text
        assert render_card(replace(view, error_key=None), lang) != text
    else:
        for spec in FIELDS[view.kind]:
            assert get_text(spec.error_key, lang) not in text

    # The sections are joined without a stray blank line, however few of them are present.
    assert "\n\n\n" not in text


# =====================================================================================
# Property 22: Summary_State lists every collected value
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P22_LOCALES = st.sampled_from(available_locales())

#: Values as the flow hands them to the summary: already rendered strings, deliberately covering
#: HTML metacharacters, an emoji, a blank, an empty string and repeated values, so a duplicated
#: value cannot hide a dropped entry. No value carries a newline, which the flow never produces
#: for a single field and which would make a line indistinguishable from two.
_P22_VALUES = st.sampled_from(
    [
        "45.280",
        "42,5",
        "78,90 €",
        "0",
        "",
        "   ",
        "oil change <5000km",
        'tyres "front" & rear',
        "🚗 filled up",
        "Yes",
    ]
)

#: A named vehicle, an unnameable one, and ones carrying markup.
_P22_VEHICLES = st.sampled_from(["2019 Volvo V60", "Fiat <500>", "Škoda & Co", "", "   "])


@st.composite
def _p22_summaries(draw: st.DrawFn) -> SummaryView:
    """Draw the ``SummaryView`` a completed flow of some kind would build.

    Summary_State is only reached once every field has been collected, so the entries are the whole
    field table of the drawn kind, in order, each carrying its own label key and a drawn rendered
    value (Requirement 4.6).
    """
    kind = draw(st.sampled_from(list(FlowKind)))
    entries = tuple(
        FieldEntry(
            index=index,
            label_key=field_at(kind, index).label_key,
            rendered_value=draw(_P22_VALUES),
        )
        for index in range(field_count(kind))
    )
    return SummaryView(kind=kind, vehicle_name=draw(_P22_VEHICLES), entries=entries)


@settings(max_examples=100)
@given(view=_p22_summaries(), lang=_P22_LOCALES)
def test_property_summary_completeness(view: SummaryView, lang: str) -> None:
    """Property 22: Summary_State lists every collected value.

    # Feature: improve-ux, Property 22: Summary_State lists every collected value
    **Validates: Requirements 4.6**
    """
    text = render_summary(view, lang)

    # Requirement 4.6: the summary announces itself as the pre-save check, in the user's language.
    assert get_text("card_summary_title", lang) in text

    # Requirement 4.6: the record is attributed to a vehicle, an unnameable one through the
    # localized fallback rather than an empty line.
    expected_vehicle = view.vehicle_name.strip() or get_text("vehicle_fallback_name", lang)
    assert (
        get_text(
            "card_line",
            lang,
            label=get_text("field_vehicle", lang),
            value=esc(expected_vehicle),
        )
        in text
    )

    # Requirement 4.6: every collected value is listed as a full line, with its own localized
    # label and its value escaped exactly once — escaping twice would show the entity instead of
    # the character the user typed.
    for entry in view.entries:
        escaped = esc(entry.rendered_value)
        assert (
            get_text("card_line", lang, label=get_text(entry.label_key, lang), value=escaped)
            in text
        )
        if escaped != entry.rendered_value:
            assert esc(escaped) not in text

    # Requirement 4.6: nothing is dropped and nothing is invented, whatever the flow kind. The
    # rendered lines are exactly the title, the vehicle and one line per field of the kind, so a
    # value repeated across two fields still costs two lines.
    lines = [line for line in text.split("\n") if line]
    assert len(lines) == len(view.entries) + 2
    assert len(view.entries) == field_count(view.kind)
    assert [entry.label_key for entry in view.entries] == [
        spec.label_key for spec in FIELDS[view.kind]
    ]

    # Requirement 4.6 the other way round: losing any single entry is visible, so the check above
    # cannot be satisfied by a renderer that silently swallows one.
    for dropped in range(len(view.entries)):
        remaining = view.entries[:dropped] + view.entries[dropped + 1 :]
        assert render_summary(replace(view, entries=remaining), lang) != text

    # The sections are joined without a stray blank line.
    assert "\n\n\n" not in text


# =====================================================================================
# Property 17: A confirmation names the vehicle and lists every field of its record type
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P17_LOCALES = st.sampled_from(available_locales())

#: Values as the submitter hands them to the confirmation: already rendered with their unit, and
#: deliberately covering HTML metacharacters, an emoji, a blank, an empty string and repeated
#: values, so a duplicated value cannot hide a dropped field. No value carries a newline, which
#: would make one line indistinguishable from two.
_P17_VALUES = st.sampled_from(
    [
        "45,280 km",
        "42.50 L",
        "78.90 €",
        "0",
        "",
        "   ",
        "oil change <5000km",
        'tyres "front" & rear',
        "🚗 filled up",
        "Yes",
    ]
)

#: A named vehicle as the persisted Active_Vehicle_Name carries it, one that cannot be named at
#: all, and ones carrying markup (Requirements 6.4, 13.6).
_P17_VEHICLES = st.sampled_from(["2019 Volvo V60", "Fiat <500>", "Škoda & Co", "", "   "])

#: Both consumption sources: LubeLogger's own figure and the Bot's estimate, each with the unit it
#: travels with, so the unit is never assumed by the renderer (Requirement 6.6).
_P17_CONSUMPTIONS = st.builds(
    ConsumptionResult,
    value=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99.99"), places=2),
    unit=st.sampled_from([CONSUMPTION_UNIT, "L/100 mi"]),
    estimated=st.booleans(),
)


@st.composite
def _p17_confirmations(draw: st.DrawFn) -> ConfirmationView:
    """Draw the ``ConfirmationView`` a saved record of some kind would build.

    A confirmation is only rendered once the whole record exists, so the entries are the complete
    field table of the drawn kind, in order, each carrying its own label key and a drawn rendered
    value: odometer, litres, cost and full-tank for fuel; odometer, description and cost for
    service; odometer alone for an odometer record (Requirements 6.1, 6.2, 6.3). The consumption is
    drawn present or absent, so both branches of Requirement 6.9 are reachable.
    """
    kind = draw(st.sampled_from(list(FlowKind)))
    entries = tuple(
        FieldEntry(
            index=index,
            label_key=field_at(kind, index).label_key,
            rendered_value=draw(_P17_VALUES),
        )
        for index in range(field_count(kind))
    )
    return ConfirmationView(
        kind=kind,
        vehicle_name=draw(_P17_VEHICLES),
        on_date=draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31))),
        entries=entries,
        consumption=draw(st.one_of(st.none(), _P17_CONSUMPTIONS)),
    )


@settings(max_examples=100)
@given(view=_p17_confirmations(), lang=_P17_LOCALES)
def test_property_confirmation_completeness(view: ConfirmationView, lang: str) -> None:
    """Property 17: A confirmation names the vehicle and lists every field of its record type.

    # Feature: improve-ux, Property 17: A confirmation names the vehicle and lists every field of
    # its record type
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    """
    text = render_confirmation(view, lang)

    # Requirements 6.1, 6.2, 6.3: the confirmation announces the kind of record that was saved,
    # and only that kind.
    assert get_text(f"card_saved_{view.kind.value}", lang) in text
    for other in FlowKind:
        if other is not view.kind:
            assert get_text(f"card_saved_{other.value}", lang) not in text

    # Requirement 6.4: the vehicle is named from the persisted Active_Vehicle_Name as a full line,
    # an unnameable one through the localized fallback rather than a blank or a numeric id.
    expected_vehicle = view.vehicle_name.strip() or get_text("vehicle_fallback_name", lang)
    assert (
        get_text(
            "card_line",
            lang,
            label=get_text("field_vehicle", lang),
            value=esc(expected_vehicle),
        )
        in text
    )
    if not view.vehicle_name.strip():
        assert get_text("vehicle_fallback_name", lang) in text

    # Requirements 6.1, 6.2, 6.3: the date of the record is stated, with the locale pattern.
    assert (
        get_text(
            "card_line",
            lang,
            label=get_text("field_date", lang),
            value=esc(fmt_date(view.on_date, lang)),
        )
        in text
    )

    # Requirements 6.1, 6.2, 6.3: every field of the record kind is listed as a full line, with
    # its own localized label and its value escaped exactly once — escaping twice would show the
    # entity instead of the character.
    for entry in view.entries:
        escaped = esc(entry.rendered_value)
        assert (
            get_text("card_line", lang, label=get_text(entry.label_key, lang), value=escaped)
            in text
        )
        if escaped != entry.rendered_value:
            assert esc(escaped) not in text

    # Requirements 6.1, 6.2, 6.3: the listed fields are exactly the field table of the kind, in
    # order — nothing dropped, nothing invented.
    assert [entry.label_key for entry in view.entries] == [
        spec.label_key for spec in FIELDS[view.kind]
    ]

    # Requirements 6.6, 6.9: the consumption line appears exactly when there is a figure, states
    # the unit that figure carries, and uses the estimate template only for the Bot's own value.
    if view.consumption is None:
        assert get_text("field_consumption", lang) not in text
    else:
        template = "card_consumption_estimate" if view.consumption.estimated else "card_consumption"
        assert (
            get_text(
                "card_line",
                lang,
                label=get_text("field_consumption", lang),
                value=get_text(
                    template,
                    lang,
                    value=fmt_display(view.consumption.value, lang),
                    unit=esc(view.consumption.unit),
                ),
            )
            in text
        )
        assert esc(view.consumption.unit) in text
        if not view.consumption.estimated:
            assert (
                get_text(
                    "card_consumption_estimate",
                    lang,
                    value=fmt_display(view.consumption.value, lang),
                    unit=esc(view.consumption.unit),
                )
                not in text
            )

    # Requirements 6.1, 6.2, 6.3 by line count: the title, the vehicle, the date, one line per
    # field and the consumption line only when there is one, so a value repeated across two fields
    # still costs two lines.
    lines = [line for line in text.split("\n") if line]
    assert len(lines) == len(view.entries) + 3 + (0 if view.consumption is None else 1)

    # The same requirements the other way round: losing any single field is visible, so the checks
    # above cannot be satisfied by a renderer that silently swallows one.
    for dropped in range(len(view.entries)):
        remaining = view.entries[:dropped] + view.entries[dropped + 1 :]
        assert render_confirmation(replace(view, entries=remaining), lang) != text

    # The sections are joined without a stray blank line.
    assert "\n\n\n" not in text


# =====================================================================================
# Property 24: A queued confirmation lists the same values as a saved one
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P24_LOCALES = st.sampled_from(available_locales())


@settings(max_examples=100)
@given(view=_p17_confirmations(), consumption=_P17_CONSUMPTIONS, lang=_P24_LOCALES)
def test_property_queued_matches_saved(
    view: ConfirmationView, consumption: ConsumptionResult, lang: str
) -> None:
    """Property 24: A queued confirmation lists the same values as a saved one.

    # Feature: improve-ux, Property 24: A queued confirmation lists the same values as a saved one
    **Validates: Requirements 9.2, 9.3**
    """
    queued = render_queued(view, lang)
    saved = render_confirmation(view, lang)
    queued_lines = [line for line in queued.split("\n") if line]

    # Requirement 9.2: the two renderings differ in their title only — the queued one says the
    # record is waiting, and never claims it was saved, in any locale or for any other kind.
    assert queued_lines[0] == get_text(f"card_queued_{view.kind.value}", lang)
    for other in FlowKind:
        assert get_text(f"card_saved_{other.value}", lang) not in queued
        if other is not view.kind:
            assert get_text(f"card_queued_{other.value}", lang) not in queued

    # Requirement 9.2: the body is the very same body a saved confirmation without a consumption
    # figure carries — same vehicle line, same date line, same field lines, in the same order.
    saved_without_consumption = [
        line
        for line in render_confirmation(replace(view, consumption=None), lang).split("\n")
        if line
    ]
    assert queued_lines[1:-1] == saved_without_consumption[1:]

    # Requirement 9.2 line by line: the vehicle, an unnameable one through the localized fallback,
    # the record date with the locale pattern, and every field of the kind with its own label and
    # its value escaped exactly once.
    expected_vehicle = view.vehicle_name.strip() or get_text("vehicle_fallback_name", lang)
    assert (
        get_text(
            "card_line",
            lang,
            label=get_text("field_vehicle", lang),
            value=esc(expected_vehicle),
        )
        in queued
    )
    assert (
        get_text(
            "card_line",
            lang,
            label=get_text("field_date", lang),
            value=esc(fmt_date(view.on_date, lang)),
        )
        in queued
    )
    for entry in view.entries:
        escaped = esc(entry.rendered_value)
        line = get_text("card_line", lang, label=get_text(entry.label_key, lang), value=escaped)
        assert line in queued
        assert line in saved
        if escaped != entry.rendered_value:
            assert esc(escaped) not in queued

    # Requirement 9.2: the queued rendering adds the automatic-sync notice, and adds nothing else
    # — the title, the vehicle, the date, one line per field and the notice, so a value repeated
    # across two fields still costs two lines.
    assert queued_lines[-1] == get_text("card_queued_notice", lang)
    assert len(queued_lines) == len(view.entries) + 4

    # Requirement 9.3: no consumption figure is ever shown, whatever the view carries. Rendering
    # the same view with a figure and without one produces the identical text, which is stronger
    # than the absence of the label alone.
    assert render_queued(replace(view, consumption=consumption), lang) == queued
    assert render_queued(replace(view, consumption=None), lang) == queued
    assert get_text("field_consumption", lang) not in queued
    for template in ("card_consumption", "card_consumption_estimate"):
        assert (
            get_text(
                template,
                lang,
                value=fmt_display(consumption.value, lang),
                unit=esc(consumption.unit),
            )
            not in queued
        )

    # Requirement 9.2 the other way round: losing any single field is visible, so the parity checks
    # above cannot be satisfied by a renderer that silently swallows one.
    for dropped in range(len(view.entries)):
        remaining = view.entries[:dropped] + view.entries[dropped + 1 :]
        assert render_queued(replace(view, entries=remaining), lang) != queued

    # The sections are joined without a stray blank line.
    assert "\n\n\n" not in queued


# =====================================================================================
# Property 28: Every interpolated value is escaped exactly once
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P28_LOCALES = st.sampled_from(available_locales())

#: Values exactly as a user types them or as LubeLogger returns them: every HTML metacharacter on
#: its own and combined, a full tag attempt, a value that already looks escaped, an emoji, a blank
#: and an empty string. ``oil change <5000km`` is the description that used to break delivery
#: (Requirement 11.7); ``&amp; already escaped`` is what tells escaping once apart from escaping
#: twice, since a literal ``&amp;`` typed by a user must still be escaped.
_P28_VALUES = st.sampled_from(
    [
        "45.280",
        "",
        "   ",
        "oil change <5000km",
        "<b>bold</b>",
        "5 > 4 < 6",
        "a & b",
        'tyres "front" & rear',
        "&amp; already escaped",
        "🚗 filled up ⛽",
    ]
)

#: Vehicle names as the API and the persisted Active_Vehicle_Name carry them, including markup, a
#: quoted one, an emoji and the unnameable cases that render through the localized fallback.
_P28_VEHICLES = st.sampled_from(
    [
        "2019 Volvo V60",
        "Fiat <500>",
        "Škoda & Co",
        'The "Van"',
        "🚙 Panda",
        "",
        "   ",
    ]
)

#: The unit travels with the consumption figure and is interpolated like any other value, so it is
#: drawn including a markup-carrying spelling (Requirement 6.6).
_P28_UNITS = st.sampled_from([CONSUMPTION_UNIT, "L/100 mi", "km/L <&>"])

#: Placeholders standing in for every interpolated value. They are markup-free, non-blank and
#: absent from every locale file, so rendering a view twice — once with the real values, once with
#: the placeholders — isolates what a value contributes from what the locale template contributes.
_P28_VEHICLE_SENTINEL = "P28VEHICLEEND"
_P28_UNIT_SENTINEL = "P28UNITEND"


def _p28_value_sentinel(index: int) -> str:
    """Return the placeholder of the field at ``index``, unique and prefix-free."""
    return f"P28VALUE{index}END"


def _p28_entries(kind: FlowKind, values: tuple[str, ...]) -> tuple[FieldEntry, ...]:
    """Build the collected entries of ``kind`` from already-rendered values, in field order."""
    return tuple(
        FieldEntry(index=index, label_key=field_at(kind, index).label_key, rendered_value=value)
        for index, value in enumerate(values)
    )


@st.composite
def _p28_cases(draw: st.DrawFn) -> tuple[FlowKind, str, tuple[str, ...], str, bool]:
    """Draw a flow kind, a vehicle name, one value per field of that kind, a unit and its source.

    One draw feeds every renderer of the property, so the same value is checked wherever it can be
    interpolated: on the card, in the summary, on a saved and on a queued confirmation, on the two
    Latest renderings and in the welcome message.
    """
    kind = draw(st.sampled_from(list(FlowKind)))
    values = tuple(draw(_P28_VALUES) for _ in range(field_count(kind)))
    return kind, draw(_P28_VEHICLES), values, draw(_P28_UNITS), draw(st.booleans())


@settings(max_examples=100)
@given(case=_p28_cases(), lang=_P28_LOCALES)
def test_property_html_escaping(
    case: tuple[FlowKind, str, tuple[str, ...], str, bool], lang: str
) -> None:
    """Property 28: Every interpolated value is escaped exactly once.

    # Feature: improve-ux, Property 28: Every interpolated value is escaped exactly once
    **Validates: Requirements 11.7, NF-6.3**
    """
    kind, vehicle, values, unit, estimated = case
    consumption = ConsumptionResult(value=Decimal("5.70"), unit=unit, estimated=estimated)
    sentinel_consumption = replace(consumption, unit=_P28_UNIT_SENTINEL)
    sentinels = tuple(_p28_value_sentinel(index) for index in range(len(values)))

    # What each placeholder stands for. An unnameable vehicle stands for the localized fallback,
    # because that is the text the renderer interpolates in its place (Requirement 13.6).
    substitutions = {
        _P28_VEHICLE_SENTINEL: vehicle.strip() or get_text("vehicle_fallback_name", lang),
        _P28_UNIT_SENTINEL: unit,
        **dict(zip(sentinels, values, strict=True)),
    }
    vehicle_value = substitutions[_P28_VEHICLE_SENTINEL]

    entries = _p28_entries(kind, values)
    sentinel_entries = _p28_entries(kind, sentinels)
    prompted = field_at(kind, field_count(kind) - 1)
    steps = (field_count(kind), field_count(kind))

    card = CardView(
        kind=kind,
        vehicle_name=vehicle,
        collected=entries[:-1],
        prompt_key=prompted.prompt_key,
        progress=steps,
    )
    summary = SummaryView(kind=kind, vehicle_name=vehicle, entries=entries)
    confirmation = ConfirmationView(
        kind=kind,
        vehicle_name=vehicle,
        on_date=dt.date(2025, 7, 12),
        entries=entries,
        consumption=consumption,
    )
    gas = GasRecord.model_validate(
        {
            "date": "2025-07-12",
            "odometer": 45_280,
            "fuelConsumed": "42.5",
            "cost": "78.9",
            "isFillToFull": True,
        }
    )
    odometer = OdometerRecord.model_validate({"date": "2025-07-12", "odometer": 45_280})

    collected = tuple(entry.rendered_value for entry in card.collected)

    # Every renderer that interpolates a user-sourced or API-sourced value, paired with the same
    # rendering built from the placeholders and with the values it is expected to carry.
    cases = (
        (
            render_card(card, lang),
            render_card(
                replace(
                    card,
                    vehicle_name=_P28_VEHICLE_SENTINEL,
                    collected=sentinel_entries[:-1],
                ),
                lang,
            ),
            (vehicle_value, *collected),
        ),
        (
            render_summary(summary, lang),
            render_summary(
                replace(summary, vehicle_name=_P28_VEHICLE_SENTINEL, entries=sentinel_entries), lang
            ),
            (vehicle_value, *values),
        ),
        (
            render_confirmation(confirmation, lang),
            render_confirmation(
                replace(
                    confirmation,
                    vehicle_name=_P28_VEHICLE_SENTINEL,
                    entries=sentinel_entries,
                    consumption=sentinel_consumption,
                ),
                lang,
            ),
            (vehicle_value, *values, unit),
        ),
        (
            render_queued(confirmation, lang),
            render_queued(
                replace(
                    confirmation,
                    vehicle_name=_P28_VEHICLE_SENTINEL,
                    entries=sentinel_entries,
                    consumption=sentinel_consumption,
                ),
                lang,
            ),
            (vehicle_value, *values),
        ),
        (
            render_latest_fuel(gas, vehicle, consumption, lang),
            render_latest_fuel(gas, _P28_VEHICLE_SENTINEL, sentinel_consumption, lang),
            (vehicle_value, unit),
        ),
        (
            render_latest_odometer(odometer, vehicle, lang),
            render_latest_odometer(odometer, _P28_VEHICLE_SENTINEL, lang),
            (vehicle_value,),
        ),
        (
            render_welcome(vehicle, lang),
            render_welcome(_P28_VEHICLE_SENTINEL, lang),
            (vehicle_value,),
        ),
    )

    for rendered, skeleton, present in cases:
        # Requirement 11.7: a value contributes exactly its escaped form and nothing else. The
        # skeleton carries the locale template with its literal markup, so substituting each
        # placeholder with the escaped value it stands for has to reproduce the rendering byte for
        # byte — a value escaped twice, escaped not at all, or interpolated anywhere else would
        # make the two texts differ.
        expected = skeleton
        for sentinel, raw in substitutions.items():
            expected = expected.replace(sentinel, esc(raw))
        assert rendered == expected

        # NF-6.3: literal HTML comes from the locale template only. The placeholders carry no
        # markup, so every angle bracket in the rendering is one the template put there: a value
        # can never open or close a tag, whatever the user typed or the API returned.
        assert rendered.count("<") == skeleton.count("<")
        assert rendered.count(">") == skeleton.count(">")

        for raw in present:
            escaped = esc(raw)

            # Requirement 11.7: the value is present in its escaped form, and undoing that one
            # escaping returns exactly what came in — nothing is lost and nothing is added.
            assert escaped in rendered
            unescaped = escaped.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            assert unescaped == raw

            if escaped != raw:
                # Requirement 11.7: a value carrying a metacharacter is escaped once, never
                # twice — the double form would show the entity instead of the character — and
                # its raw form never reaches the message.
                assert esc(escaped) not in rendered
                assert raw not in rendered


# =====================================================================================
# Property 30: Decimal separators round-trip in every locale
# =====================================================================================

#: Every locale file on disk, so a language added later joins the property automatically.
_P30_LOCALES = st.sampled_from(available_locales())

#: Decimal values covering integers, fractional numbers, zero, negative values and many decimal
#: places — all finite, since ``fmt_plain`` rejects non-finite values.
_P30_DECIMALS = st.decimals(
    min_value=Decimal("-999999.999999"),
    max_value=Decimal("999999.999999"),
    allow_nan=False,
    allow_infinity=False,
    places=6,
)


@settings(max_examples=100)
@given(value=_P30_DECIMALS, lang=_P30_LOCALES)
def test_property_decimal_roundtrip(value: Decimal, lang: str) -> None:
    """Property 30: Decimal separators round-trip in every locale.

    # Feature: improve-ux, Property 30: Decimal separators round-trip in every locale
    **Validates: Requirements 12.4, NF-3.3**
    """
    formatted = fmt_plain(value, lang)

    # Round-trip: replace the locale decimal separator back with '.' and parse as Decimal.
    dec_sep = get_text("fmt_decimal_sep", lang)
    if dec_sep != ".":
        normalized = formatted.replace(dec_sep, ".")
    else:
        normalized = formatted

    recovered = Decimal(normalized)

    # The recovered value must be numerically equal to the original.
    assert recovered == value, (
        f"Round-trip failed for {value!r} in locale {lang!r}: "
        f"formatted={formatted!r}, normalized={normalized!r}, recovered={recovered!r}"
    )


# =====================================================================================
# Property 34: An unnameable vehicle falls back to a localized label
# =====================================================================================

#: Every locale file on disk.
_P34_LOCALES = st.sampled_from(available_locales())

#: Strings that are "unnameable": empty, whitespace-only, or tab/newline variants.
_P34_UNNAMEABLE = st.sampled_from(["", "   ", "\t", "\n", "  \t  "])


@settings(max_examples=100)
@given(vehicle_name=_P34_UNNAMEABLE, lang=_P34_LOCALES)
def test_property_vehicle_fallback_localized(vehicle_name: str, lang: str) -> None:
    """Property 34: An unnameable vehicle falls back to a localized label.

    # Feature: improve-ux, Property 34: An unnameable vehicle falls back to a localized label
    **Validates: Requirements 13.6**
    """
    fallback = get_text("vehicle_fallback_name", lang)

    # --- render_card ---
    card_view = CardView(
        kind=FlowKind.FUEL,
        vehicle_name=vehicle_name,
        collected=(),
        prompt_key="ask_odometer",
        progress=(1, 4),
    )
    card_text = render_card(card_view, lang)
    assert fallback in card_text
    assert vehicle_name.strip() not in card_text or vehicle_name.strip() == ""

    # --- render_summary ---
    summary_view = SummaryView(
        kind=FlowKind.FUEL,
        vehicle_name=vehicle_name,
        entries=(),
    )
    summary_text = render_summary(summary_view, lang)
    assert fallback in summary_text

    # --- render_confirmation ---
    confirmation_view = ConfirmationView(
        kind=FlowKind.FUEL,
        vehicle_name=vehicle_name,
        on_date=dt.date(2025, 1, 15),
        entries=(),
    )
    confirmation_text = render_confirmation(confirmation_view, lang)
    assert fallback in confirmation_text

    # --- render_queued ---
    queued_text = render_queued(confirmation_view, lang)
    assert fallback in queued_text

    # --- render_latest_fuel ---
    gas_record = GasRecord.model_validate({"odometer": 10_000, "isFillToFull": True})
    fuel_text = render_latest_fuel(gas_record, vehicle_name, None, lang)
    assert fallback in fuel_text

    # --- render_latest_odometer ---
    odo_record = OdometerRecord.model_validate({"odometer": 10_000})
    odo_text = render_latest_odometer(odo_record, vehicle_name, lang)
    assert fallback in odo_text

    # --- render_welcome (non-None means welcome-back, not onboarding) ---
    welcome_text = render_welcome(vehicle_name, lang)
    assert fallback in welcome_text
