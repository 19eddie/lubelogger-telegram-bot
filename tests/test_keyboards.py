"""Tests for the keyboard builders (bot/keyboards.py)."""

from __future__ import annotations

from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.callbacks import (
    NO_TOKEN,
    TELEGRAM_CALLBACK_DATA_LIMIT,
    Callback,
    CallbackAction,
    decode,
    new_token,
)
from bot.flows.definitions import FieldKind, FlowKind, MenuAction, field_at, field_count
from bot.flows.views import FieldEntry
from bot.i18n import (
    MENU_LABEL_KEYS,
    available_locales,
    get_text,
    menu_label_index,
    resolve_menu_label,
)
from bot.keyboards import (
    VehicleChoice,
    abandon_keyboard,
    all_callback_data,
    choice_keyboard,
    confirmation_keyboard,
    field_picker_keyboard,
    flow_step_keyboard,
    language_keyboard,
    latest_record_keyboard,
    menu_action_ordinal,
    menu_keyboard,
    options_back_keyboard,
    regression_keyboard,
    summary_keyboard,
    vehicle_keyboard,
)

# =====================================================================================
# Property 4: In-flow keyboards carry the flow token, a cancel action, and no field values
# =====================================================================================

#: The two actions that return a menu-reachable screen to its menu (Requirements 1.11, 10.3).
_BACK_ACTIONS = frozenset({CallbackAction.LATEST_BACK, CallbackAction.OPTIONS_BACK})

#: Actions whose buttons carry no argument at all: they identify themselves and nothing else.
_ARGLESS_ACTIONS = frozenset(
    {
        CallbackAction.CANCEL,
        CallbackAction.SAVE,
        CallbackAction.EDIT,
        CallbackAction.ODO_CONFIRM,
        CallbackAction.ODO_REENTER,
        CallbackAction.ABANDON_NO,
    }
)


def _buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    """Flatten a markup into its buttons, row order preserved."""
    return [button for row in markup.inline_keyboard for button in row]


def _decoded(markup: InlineKeyboardMarkup) -> list[Callback]:
    """Decode the ``callback_data`` of every button of a markup."""
    return [decode(button.callback_data) for button in _buttons(markup)]


def _count(callbacks: Sequence[Callback], action: CallbackAction) -> int:
    """Return how many decoded callbacks request ``action``."""
    return sum(1 for callback in callbacks if callback.action is action)


@st.composite
def _flow_steps(draw: st.DrawFn) -> tuple[FlowKind, int]:
    """Draw a flow kind together with a valid step index inside that flow."""
    kind = draw(st.sampled_from(list(FlowKind)))
    index = draw(st.integers(min_value=0, max_value=field_count(kind) - 1))
    return kind, index


#: Flow_Tokens as the flow really produces them, plus the shortest and longest legal shapes.
_tokens = st.one_of(
    st.builds(new_token),
    st.sampled_from(["a", "Xk3-Zq_9"]),
)

#: The Last_Known_Odometer offered as a "keep" button, or its absence. Kept at four digits or
#: more so that a collision with a structural ordinal (a field index, a choice ordinal) is
#: impossible: the property is precisely that the value does *not* travel as the argument.
_suggestions = st.one_of(st.none(), st.integers(min_value=1_000, max_value=9_999_999))

#: Rendered field values as the formatters produce them: grouped integers, decimals with a
#: locale separator, and free text such as a service description. Never a bare small integer,
#: for the same reason as above.
_rendered_values = st.one_of(
    st.integers(min_value=1_000, max_value=9_999_999).map(lambda n: f"{n:,}".replace(",", ".")),
    st.tuples(
        st.integers(min_value=0, max_value=9_999), st.integers(min_value=0, max_value=99)
    ).map(lambda pair: f"{pair[0]},{pair[1]:02d}"),
    st.text(min_size=1, max_size=24).filter(lambda text: not text.strip().isdigit()),
)

#: Selectable vehicles, including one LubeLogger cannot name and one with a ten-digit id.
_vehicles = st.lists(
    st.builds(
        VehicleChoice,
        st.integers(min_value=1, max_value=9_999_999_999),
        st.text(max_size=16),
    ),
    min_size=1,
    max_size=4,
)


@settings(max_examples=100)
@given(
    step=_flow_steps(),
    token=_tokens,
    suggestion=_suggestions,
    values=st.lists(_rendered_values, min_size=1, max_size=4),
    target=st.sampled_from(list(MenuAction)),
    vehicles=_vehicles,
    lang=st.sampled_from(list(available_locales())),
    queued=st.booleans(),
)
def test_property_inflow_keyboard_invariants(
    step: tuple[FlowKind, int],
    token: str,
    suggestion: int | None,
    values: list[str],
    target: MenuAction,
    vehicles: list[VehicleChoice],
    lang: str,
    queued: bool,
) -> None:
    """Property 4: In-flow keyboards carry the flow token, a cancel action, and no field values.

    # Feature: improve-ux, Property 4: In-flow keyboards carry the flow token, a cancel action, and no field values
    **Validates: Requirements 1.11, 4.3, 4.5, 4.10, 5.7, 6.10, 9.4, 10.3, 11.1**
    """  # noqa: E501 - the property tag is one line by convention
    kind, index = step
    field = field_at(kind, index)
    entries = tuple(
        FieldEntry(
            index=position,
            label_key=field_at(kind, position).label_key,
            rendered_value=values[position % len(values)],
        )
        for position in range(field_count(kind))
    )
    field_values = {entry.rendered_value for entry in entries}
    if suggestion is not None:
        field_values.add(str(suggestion))

    step_markup = flow_step_keyboard(token, field, suggestion=suggestion, lang=lang)
    inflow = {
        "step": step_markup,
        "summary": summary_keyboard(token, lang),
        "picker": field_picker_keyboard(token, entries, lang),
        "regression": regression_keyboard(token, lang),
        "abandon": abandon_keyboard(token, target, lang),
    }

    allowed_args = {
        CallbackAction.KEEP: {index},
        CallbackAction.FIELD: {entry.index for entry in entries},
        CallbackAction.CHOICE: set(range(len(field.choices))),
        CallbackAction.ABANDON_YES: {menu_action_ordinal(target)},
    }

    for name, markup in inflow.items():
        callbacks = _decoded(markup)
        assert callbacks, f"{name} keyboard has no buttons"

        # Requirements 1.11, 11.1: every in-flow button carries this flow's token.
        assert {callback.token for callback in callbacks} == {token}, name
        assert all(callback.in_flow for callback in callbacks), name

        # Requirement 4.3: exactly one cancel, and no menu back button inside a flow.
        assert _count(callbacks, CallbackAction.CANCEL) == 1, name
        assert not [c for c in callbacks if c.action in _BACK_ACTIONS], name

        for callback in callbacks:
            if callback.action in _ARGLESS_ACTIONS:
                assert callback.arg is None, (name, callback.action)
                continue
            # Requirement 11.3: the argument is a structural ordinal, never a field value.
            assert callback.arg in allowed_args[callback.action], (name, callback.action)
            rendered_arg = str(callback.arg)
            for value in field_values:
                assert value not in rendered_arg, (name, value)

    step_callbacks = _decoded(step_markup)
    if field.kind is FieldKind.CHOICE:
        # Requirement 4.5: one distinct button per choice, plus the cancel row.
        choices = [c for c in step_callbacks if c.action is CallbackAction.CHOICE]
        assert len(choices) == len(field.choices)
        assert {c.arg for c in choices} == set(range(len(field.choices)))
        assert len({button.text for button in _buttons(step_markup)}) == len(_buttons(step_markup))
        assert step_markup == choice_keyboard(token, field, lang)
        assert _count(step_callbacks, CallbackAction.KEEP) == 0
    else:
        # Requirements 4.10, 5.7: the suggestion is offered as a keep button carrying the index.
        expected_keep = 0 if suggestion is None else 1
        assert _count(step_callbacks, CallbackAction.KEEP) == expected_keep
        if suggestion is not None:
            keep = next(c for c in step_callbacks if c.action is CallbackAction.KEEP)
            assert keep.arg == index
            # The value may appear in the label, and only there (Requirement 4.10).
            labels = [button.text for button in _buttons(step_markup)]
            assert any(str(suggestion) in label for label in labels)

    # Requirements 6.10, 9.4: a saved confirmation offers Latest, a queued one does not.
    confirmation = confirmation_keyboard(token, queued=queued, lang=lang)
    confirmation_callbacks = _decoded(confirmation)
    assert {callback.token for callback in confirmation_callbacks} == {token}
    expected_actions = (
        [CallbackAction.LOG_ANOTHER]
        if queued
        else [CallbackAction.LOG_ANOTHER, CallbackAction.LATEST_OPEN]
    )
    assert [callback.action for callback in confirmation_callbacks] == expected_actions
    assert _count(confirmation_callbacks, CallbackAction.CANCEL) == 0

    # Requirements 1.11, 10.3: every screen reached from a menu carries exactly one back button.
    menu_reachable = {
        "latest_record": (latest_record_keyboard(lang), CallbackAction.LATEST_BACK),
        "options_back": (options_back_keyboard(lang), CallbackAction.OPTIONS_BACK),
        "vehicle": (vehicle_keyboard(vehicles, lang), CallbackAction.OPTIONS_BACK),
        "language": (language_keyboard(lang), CallbackAction.OPTIONS_BACK),
    }
    for name, (markup, back_action) in menu_reachable.items():
        callbacks = _decoded(markup)
        backs = [callback for callback in callbacks if callback.action in _BACK_ACTIONS]
        assert len(backs) == 1, name
        assert backs[0].action is back_action, name
        assert backs[0].token == NO_TOKEN, name
        assert all(callback.token == NO_TOKEN for callback in callbacks), name

    vehicle_callbacks = [
        callback
        for callback in _decoded(vehicle_keyboard(vehicles, lang))
        if callback.action is CallbackAction.VEHICLE_SET
    ]
    assert [callback.arg for callback in vehicle_callbacks] == [
        choice.vehicle_id for choice in vehicles
    ]

    language_callbacks = [
        callback
        for callback in _decoded(language_keyboard(lang))
        if callback.action is CallbackAction.LANG_SET
    ]
    assert [callback.arg for callback in language_callbacks] == list(
        range(len(available_locales()))
    )


# =====================================================================================
# Property 7: Menu_Labels are localized and resolvable across locales
# =====================================================================================

#: The layout Requirement 1.2 fixes: writing actions on the first row, reading ones on the second.
_MENU_LAYOUT: tuple[tuple[MenuAction, ...], ...] = (
    (MenuAction.FUEL, MenuAction.SERVICE, MenuAction.ODOMETER),
    (MenuAction.LATEST, MenuAction.OPTIONS),
)

#: Locale keys of the configuration actions Requirement 1.13 keeps off the Menu_Keyboard.
_CONFIG_LABEL_KEYS = ("btn_options_vehicle", "btn_options_lang")


def _menu_rows(markup: ReplyKeyboardMarkup) -> list[list[str]]:
    """Return the button texts of a reply markup, row structure preserved."""
    return [[button.text for button in row] for row in markup.keyboard]


def _has_emoji(label: str) -> bool:
    """True when the label carries at least one pictographic character beside its text."""
    return any(not character.isascii() and not character.isalpha() for character in label)


def _has_word(label: str) -> bool:
    """True when the label carries at least one alphabetic word beside its emoji."""
    return any(word.isalpha() for word in label.split())


@settings(max_examples=100)
@given(
    render_lang=st.sampled_from(list(available_locales())),
    switch_lang=st.sampled_from(list(available_locales())),
    placeholder_key=st.one_of(st.none(), st.just("ph_odometer")),
)
def test_property_menu_label_resolution(
    render_lang: str, switch_lang: str, placeholder_key: str | None
) -> None:
    """Property 7: Menu_Labels are localized and resolvable across locales.

    # Feature: improve-ux, Property 7: Menu_Labels are localized and resolvable across locales
    **Validates: Requirements 1.2, 1.5, 1.6, 1.7, 1.13, NF-3.2**
    """
    rows = _menu_rows(menu_keyboard(render_lang, placeholder_key=placeholder_key))

    # Requirement 1.2: five buttons, three then two, writing actions before reading ones.
    assert [len(row) for row in rows] == [3, 2]
    labels = [label for row in rows for label in row]
    assert len(set(labels)) == 5

    for row, actions in zip(rows, _MENU_LAYOUT, strict=True):
        for label, action in zip(row, actions, strict=True):
            # Requirement 1.2: the label is the localized text of that action, in that position.
            assert label == get_text(MENU_LABEL_KEYS[action], render_lang)

            # Requirement 1.7: an emoji plus a text word, in every locale.
            assert _has_emoji(label), (render_lang, label)
            assert _has_word(label), (render_lang, label)

            # Requirements 1.5, 1.6, NF-3.2: the label rendered before a language change still
            # resolves to its own action once the user has switched to ``switch_lang``.
            assert resolve_menu_label(label) is action, (render_lang, switch_lang, label)
            for variant in (f"  {label} ", label.upper(), label.lower()):
                assert resolve_menu_label(variant) is action, (variant, switch_lang)

            # NF-3.2 stated the other way round: the label of the language switched *to* resolves
            # to the same action as the one the keyboard was rendered with.
            switched = get_text(MENU_LABEL_KEYS[action], switch_lang)
            assert resolve_menu_label(switched) is action, (switch_lang, switched)

    # Requirement 1.6: the allowlist spans every locale, not only the rendered one.
    index = menu_label_index()
    assert set(index.values()) == set(MenuAction)
    for lang in available_locales():
        for action, key in MENU_LABEL_KEYS.items():
            assert resolve_menu_label(get_text(key, lang)) is action, (lang, key)

    # Requirement 1.13: configuration actions live in the Options_Menu, never on the menu keyboard,
    # and their labels are not part of the resolvable set.
    for key in _CONFIG_LABEL_KEYS:
        for lang in (render_lang, switch_lang):
            config_label = get_text(key, lang)
            assert config_label not in labels, (lang, key)
            assert resolve_menu_label(config_label) is None, (lang, key)

    vehicle_labels = {
        button.text
        for button in _buttons(vehicle_keyboard([VehicleChoice(1, "Panda")], render_lang))
    }
    language_labels = {button.text for button in _buttons(language_keyboard(render_lang))}
    assert not vehicle_labels & set(labels)
    assert not language_labels & set(labels)

    # Anything the user types that is not a Menu_Label stays unresolved (Requirement 1.6).
    assert resolve_menu_label("") is None
    assert resolve_menu_label("   ") is None
    assert resolve_menu_label("45000") is None


# =====================================================================================
# Unit tests: Menu_Keyboard flags and callback_data budget
# Requirements 1.1 (persistent flags), 3.8 (input placeholder), NF-1.4 (64-byte budget)
# =====================================================================================

#: The placeholder keys the typed steps of the flows use (Requirement 3.8).
_PLACEHOLDER_KEYS = ("ph_odometer", "ph_liters", "ph_cost", "ph_description")

#: How many buttons the keyboard module can produce. Counted once, so a keyboard added without a
#: budget check and a keyboard silently dropped both show up as a failure.
_EXPECTED_CALLBACK_COUNT = 67


def test_menu_keyboard_sets_persistent_flags() -> None:
    """Requirement 1.1: the menu keyboard is persistent, compact, and never one-shot."""
    markup = menu_keyboard("en")

    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.is_persistent is True
    assert markup.resize_keyboard is True
    # A one-time keyboard would collapse after the first tap, defeating Requirements 1.1 and 1.4.
    assert not markup.one_time_keyboard


def test_menu_keyboard_flags_hold_in_every_locale() -> None:
    """Requirement 1.1: the flags do not depend on the rendered language."""
    for lang in available_locales():
        markup = menu_keyboard(lang)
        assert markup.is_persistent is True, lang
        assert markup.resize_keyboard is True, lang
        assert not markup.one_time_keyboard, lang


def test_menu_keyboard_omits_placeholder_without_key() -> None:
    """Requirement 3.8: with no key supplied the placeholder is left unset, not blank."""
    for lang in available_locales():
        assert menu_keyboard(lang).input_field_placeholder is None, lang
        assert menu_keyboard(lang, placeholder_key=None).input_field_placeholder is None, lang


def test_menu_keyboard_renders_localized_placeholder() -> None:
    """Requirement 3.8: a supplied key renders as the localized hint of that key."""
    for lang in available_locales():
        for key in _PLACEHOLDER_KEYS:
            markup = menu_keyboard(lang, placeholder_key=key)
            assert markup.input_field_placeholder == get_text(key, lang), (lang, key)
            # The hint is a real string, not the key echoed back by a missing translation.
            assert markup.input_field_placeholder != key, (lang, key)


def test_menu_keyboard_placeholder_does_not_disturb_layout() -> None:
    """Requirements 1.2, 3.8: the hint changes the input field only, never the buttons."""
    plain = menu_keyboard("en")
    hinted = menu_keyboard("en", placeholder_key="ph_odometer")

    assert _menu_rows(hinted) == _menu_rows(plain)
    assert hinted.is_persistent is True
    assert not hinted.one_time_keyboard


def test_all_callback_data_within_telegram_limit() -> None:
    """NF-1.4: every callback_data the module can emit fits in 64 UTF-8 bytes, in every locale."""
    assert TELEGRAM_CALLBACK_DATA_LIMIT == 64

    for lang in available_locales():
        data = all_callback_data(lang)
        assert data, lang
        for value in data:
            size = len(value.encode("utf-8"))
            assert 0 < size <= TELEGRAM_CALLBACK_DATA_LIMIT, (lang, value, size)


def test_all_callback_data_decodes() -> None:
    """Requirement 11.1: every emitted callback_data round-trips through the decoder."""
    for lang in available_locales():
        for value in all_callback_data(lang):
            callback = decode(value)
            assert isinstance(callback.action, CallbackAction), (lang, value)


def test_all_callback_data_is_locale_independent() -> None:
    """NF-1.4: the enumeration covers the same buttons in every locale.

    ``callback_data`` carries ordinals only, never labels, so switching locale cannot change the
    strings; a difference here would mean a label leaked onto the wire (Requirement 11.3).
    """
    per_locale = {lang: all_callback_data(lang) for lang in available_locales()}
    reference = per_locale["en"]

    assert len(reference) == _EXPECTED_CALLBACK_COUNT
    for lang, data in per_locale.items():
        assert data == reference, lang
