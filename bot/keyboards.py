"""Markup builders for every keyboard the bot can show.

Pure module: every function is synchronous, takes plain arguments plus a language code and
returns a Telegram markup object. No I/O, no globals, no Telegram ``Bot``, so a test can assert
the exact layout and the exact ``callback_data`` of every button without a network or a database
(NF-1.1).

Two invariants live here and nowhere else:

- every button belonging to a Conversation_Flow embeds that flow's Flow_Token, which is what lets
  the callback guard reject a tap coming from a superseded Card_Message (Requirements 1.11, 11.1);
- every screen reachable from the Options_Menu or from the Latest menu carries exactly one back
  button returning the message to its menu (Requirements 1.11, 10.3).

``callback_data`` never carries a field value (Requirement 11.3): a button that reuses a value,
such as "keep this odometer", travels as the *index* of the field, and the value itself is read
back from the flow state. The value may of course appear in the button *label*, which is exactly
what Requirements 4.8 and 4.10 ask for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.callbacks import NO_TOKEN, CallbackAction, encode
from bot.flows.definitions import FIELDS, FieldKind, FieldSpec, FlowKind, MenuAction
from bot.flows.views import FieldEntry
from bot.i18n import MENU_LABEL_KEYS, available_locales, get_text

__all__ = [
    "LatestTarget",
    "OptionsTarget",
    "VehicleChoice",
    "abandon_keyboard",
    "all_callback_data",
    "choice_keyboard",
    "confirmation_keyboard",
    "field_picker_keyboard",
    "flow_step_keyboard",
    "language_keyboard",
    "latest_menu_keyboard",
    "latest_record_keyboard",
    "locale_at",
    "locale_ordinal",
    "menu_action_at",
    "menu_action_ordinal",
    "menu_keyboard",
    "options_back_keyboard",
    "options_menu_keyboard",
    "regression_keyboard",
    "summary_keyboard",
    "vehicle_keyboard",
]

#: Display names of the locales shipped with the bot. A locale added as a JSON file with no entry
#: here still appears on the language keyboard, labelled with its uppercase code, so adding a
#: language remains a single-file operation (NF-3.4).
_LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}


class LatestTarget(IntEnum):
    """The ``arg`` of :attr:`CallbackAction.LATEST_OPEN`: which record the Latest menu shows."""

    FUEL = 0
    ODOMETER = 1


class OptionsTarget(IntEnum):
    """The ``arg`` of :attr:`CallbackAction.OPTIONS_OPEN`: which Options_Menu entry was picked."""

    VEHICLE = 0
    LANG = 1
    STATUS = 2
    QUEUE = 3


@dataclass(frozen=True, slots=True)
class VehicleChoice:
    """One selectable vehicle: its LubeLogger identifier and its display name.

    ``name`` is allowed to be empty, which is what ``Vehicle.display_name`` returns for a vehicle
    LubeLogger cannot name; :meth:`label` then falls back to the localized placeholder instead of
    an untranslated ``Vehicle #<id>`` (Requirement 13.6).
    """

    vehicle_id: int
    name: str = ""

    def label(self, lang: str) -> str:
        """Return the button text: the vehicle name, or the localized fallback when it has none."""
        name = self.name.strip()
        return name or get_text("vehicle_fallback_name", lang)


def menu_action_ordinal(action: MenuAction) -> int:
    """Return the ordinal a :class:`MenuAction` travels as in a ``callback_data`` argument."""
    return tuple(MenuAction).index(action)


def menu_action_at(ordinal: int) -> MenuAction:
    """Return the :class:`MenuAction` an ordinal stands for, raising ``IndexError`` when unknown."""
    actions = tuple(MenuAction)
    if ordinal < 0 or ordinal >= len(actions):
        raise IndexError(f"menu action ordinal {ordinal} out of range")
    return actions[ordinal]


def locale_ordinal(lang: str) -> int:
    """Return the ordinal of ``lang`` in the discovered locale list, raising ``ValueError``."""
    locales = available_locales()
    try:
        return locales.index(lang)
    except ValueError as exc:
        raise ValueError(f"unknown locale {lang!r}") from exc


def locale_at(ordinal: int) -> str:
    """Return the locale an ordinal stands for, raising ``IndexError`` when out of range."""
    locales = available_locales()
    if ordinal < 0 or ordinal >= len(locales):
        raise IndexError(f"locale ordinal {ordinal} out of range")
    return locales[ordinal]


def _language_label(code: str) -> str:
    """Return the name of a language in that language itself, falling back to its code."""
    return _LANGUAGE_LABELS.get(code, code.upper())


def _button(
    text: str, action: CallbackAction, token: str, arg: int | None = None
) -> InlineKeyboardButton:
    """Build one inline button from a label and an encoded action."""
    encoded_arg = None if arg is None else int(arg)
    return InlineKeyboardButton(text, callback_data=encode(action, token, encoded_arg))


def _cancel_row(token: str, lang: str) -> list[InlineKeyboardButton]:
    """Return the "✕ Cancel" row every in-flow keyboard carries (Requirement 4.3)."""
    return [_button(get_text("btn_cancel", lang), CallbackAction.CANCEL, token)]


def _back_row(action: CallbackAction, lang: str) -> list[InlineKeyboardButton]:
    """Return the single "↩ Back" row of a screen reached from a menu (Requirements 1.11, 10.3)."""
    return [_button(get_text("btn_back", lang), action, NO_TOKEN)]


def _field_ordinal(field: FieldSpec) -> int:
    """Return the index a field occupies in the flows that contain it.

    The field tables share one :class:`FieldSpec` instance across flows, and a shared field sits at
    the same position in each of them, so the index is well defined without knowing the flow kind.
    An ambiguity would mean the tables changed shape, and is reported rather than guessed.
    """
    positions = {
        index
        for specs in FIELDS.values()
        for index, spec in enumerate(specs)
        if spec.key == field.key
    }
    if not positions:
        raise ValueError(f"field {field.key!r} belongs to no flow")
    if len(positions) > 1:
        raise ValueError(f"field {field.key!r} has ambiguous positions {sorted(positions)}")
    return positions.pop()


def menu_keyboard(lang: str, *, placeholder_key: str | None = None) -> ReplyKeyboardMarkup:
    """Build the persistent navigation keyboard (Requirements 1.1, 1.2, 1.7).

    Writing actions occupy the first row, reading ones the second. ``is_persistent`` keeps the
    keyboard open, ``resize_keyboard`` keeps it compact, and ``one_time_keyboard`` is never set so
    the menu survives a tap. ``placeholder_key`` renders the ``input_field_placeholder`` hint of
    Requirement 3.8 and is omitted when no key is supplied.
    """
    labels = {action: get_text(key, lang) for action, key in MENU_LABEL_KEYS.items()}
    keyboard = [
        [
            KeyboardButton(labels[MenuAction.FUEL]),
            KeyboardButton(labels[MenuAction.SERVICE]),
            KeyboardButton(labels[MenuAction.ODOMETER]),
        ],
        [
            KeyboardButton(labels[MenuAction.LATEST]),
            KeyboardButton(labels[MenuAction.OPTIONS]),
        ],
    ]
    placeholder = get_text(placeholder_key, lang) if placeholder_key else None
    return ReplyKeyboardMarkup(
        keyboard,
        is_persistent=True,
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )


def flow_step_keyboard(
    token: str, field: FieldSpec, *, suggestion: int | None, lang: str
) -> InlineKeyboardMarkup:
    """Build the keyboard of one data-entry step (Requirements 4.3, 4.5, 4.10, 5.7).

    A closed-choice field is delegated to :func:`choice_keyboard`, so the field table alone decides
    whether a step is typed or tapped. ``suggestion`` is the value the bot already knows, offered as
    a "keep" button so an unchanged odometer needs no typing; the button carries the field index,
    never the value.
    """
    if field.kind is FieldKind.CHOICE:
        return choice_keyboard(token, field, lang)
    rows: list[list[InlineKeyboardButton]] = []
    if suggestion is not None:
        rows.append(
            [
                _button(
                    get_text("btn_keep", lang, value=suggestion),
                    CallbackAction.KEEP,
                    token,
                    _field_ordinal(field),
                )
            ]
        )
    rows.append(_cancel_row(token, lang))
    return InlineKeyboardMarkup(rows)


def choice_keyboard(token: str, field: FieldSpec, lang: str) -> InlineKeyboardMarkup:
    """Build the keyboard of a closed-choice step, one button per choice (Requirement 4.5)."""
    if not field.choices:
        raise ValueError(f"field {field.key!r} declares no choices")
    choices = [
        _button(get_text(choice_key, lang), CallbackAction.CHOICE, token, ordinal)
        for ordinal, choice_key in enumerate(field.choices)
    ]
    return InlineKeyboardMarkup([choices, _cancel_row(token, lang)])


def summary_keyboard(token: str, lang: str) -> InlineKeyboardMarkup:
    """Build the Summary_State keyboard: save, edit, cancel (Requirement 4.6)."""
    return InlineKeyboardMarkup(
        [
            [
                _button(get_text("btn_save", lang), CallbackAction.SAVE, token),
                _button(get_text("btn_edit", lang), CallbackAction.EDIT, token),
            ],
            _cancel_row(token, lang),
        ]
    )


def field_picker_keyboard(
    token: str, entries: Sequence[FieldEntry], lang: str
) -> InlineKeyboardMarkup:
    """Build the Field_Picker: one button per collected field (Requirement 4.8).

    Each label states the field name and its current value; the ``callback_data`` carries only the
    field index, so correcting a value never puts that value on the wire (Requirement 11.3).
    """
    rows = [
        [
            _button(
                get_text(
                    "btn_field",
                    lang,
                    label=get_text(entry.label_key, lang),
                    value=entry.rendered_value,
                ),
                CallbackAction.FIELD,
                token,
                entry.index,
            )
        ]
        for entry in entries
    ]
    rows.append(_cancel_row(token, lang))
    return InlineKeyboardMarkup(rows)


def regression_keyboard(token: str, lang: str) -> InlineKeyboardMarkup:
    """Build the odometer-regression gate: confirm, re-enter, cancel (Requirements 5.8, 5.10)."""
    return InlineKeyboardMarkup(
        [
            [
                _button(get_text("btn_odo_confirm", lang), CallbackAction.ODO_CONFIRM, token),
                _button(get_text("btn_odo_reenter", lang), CallbackAction.ODO_REENTER, token),
            ],
            _cancel_row(token, lang),
        ]
    )


def confirmation_keyboard(token: str, *, queued: bool, lang: str) -> InlineKeyboardMarkup:
    """Build the follow-up keyboard of a terminated flow (Requirements 6.10, 9.4).

    A saved record offers "🔁 Log another" and "📊 Latest"; a queued one offers "🔁 Log another"
    only, because the Latest menu would need the instance that is currently unreachable.
    ``LATEST_OPEN`` without an argument opens the Latest menu rather than one of its records.
    """
    row = [_button(get_text("btn_log_another", lang), CallbackAction.LOG_ANOTHER, token)]
    if not queued:
        row.append(_button(get_text("btn_latest", lang), CallbackAction.LATEST_OPEN, token))
    return InlineKeyboardMarkup([row])


def latest_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the Latest menu: last fuel and last odometer (Requirement 10.1)."""
    return InlineKeyboardMarkup(
        [
            [
                _button(
                    get_text("btn_latest_fuel", lang),
                    CallbackAction.LATEST_OPEN,
                    NO_TOKEN,
                    LatestTarget.FUEL,
                ),
                _button(
                    get_text("btn_latest_odometer", lang),
                    CallbackAction.LATEST_OPEN,
                    NO_TOKEN,
                    LatestTarget.ODOMETER,
                ),
            ]
        ]
    )


def latest_record_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the keyboard of a record shown from the Latest menu: one back button (Req 10.3)."""
    return InlineKeyboardMarkup([_back_row(CallbackAction.LATEST_BACK, lang)])


def options_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the Options_Menu: vehicle, language, status, queue (Requirement 1.9)."""
    return InlineKeyboardMarkup(
        [
            [
                _button(
                    get_text("btn_options_vehicle", lang),
                    CallbackAction.OPTIONS_OPEN,
                    NO_TOKEN,
                    OptionsTarget.VEHICLE,
                ),
                _button(
                    get_text("btn_options_lang", lang),
                    CallbackAction.OPTIONS_OPEN,
                    NO_TOKEN,
                    OptionsTarget.LANG,
                ),
            ],
            [
                _button(
                    get_text("btn_options_status", lang),
                    CallbackAction.OPTIONS_OPEN,
                    NO_TOKEN,
                    OptionsTarget.STATUS,
                ),
                _button(
                    get_text("btn_options_queue", lang),
                    CallbackAction.OPTIONS_OPEN,
                    NO_TOKEN,
                    OptionsTarget.QUEUE,
                ),
            ],
        ]
    )


def options_back_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the keyboard of a screen reached from the Options_Menu: one back button (Req 1.11)."""
    return InlineKeyboardMarkup([_back_row(CallbackAction.OPTIONS_BACK, lang)])


def vehicle_keyboard(vehicles: Sequence[VehicleChoice], lang: str) -> InlineKeyboardMarkup:
    """Build the vehicle-selection keyboard, one row per vehicle plus a back button.

    An unnameable vehicle is labelled with the localized fallback (Requirement 13.6). The back
    button is what makes the screen compliant with Requirement 1.11 when it is reached from the
    Options_Menu; during onboarding it simply leads to the Options_Menu as well.
    """
    rows = [
        [
            _button(
                choice.label(lang),
                CallbackAction.VEHICLE_SET,
                NO_TOKEN,
                choice.vehicle_id,
            )
        ]
        for choice in vehicles
    ]
    rows.append(_back_row(CallbackAction.OPTIONS_BACK, lang))
    return InlineKeyboardMarkup(rows)


def language_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the language-selection keyboard from the discovered locales, plus a back button.

    Each locale travels as its ordinal in :func:`bot.i18n.available_locales`, so a language is
    still one JSON file away (NF-3.4).
    """
    rows = [
        [_button(_language_label(code), CallbackAction.LANG_SET, NO_TOKEN, ordinal)]
        for ordinal, code in enumerate(available_locales())
    ]
    rows.append(_back_row(CallbackAction.OPTIONS_BACK, lang))
    return InlineKeyboardMarkup(rows)


def abandon_keyboard(token: str, target: MenuAction, lang: str) -> InlineKeyboardMarkup:
    """Build the abandon prompt shown when a Menu_Label arrives as data (Requirements 11.5, 11.6).

    Confirming carries the requested action forward as an ordinal, declining returns to the state
    the flow came from, and cancelling ends the flow like every other step (Requirement 4.3).
    """
    return InlineKeyboardMarkup(
        [
            [
                _button(
                    get_text("btn_abandon_yes", lang),
                    CallbackAction.ABANDON_YES,
                    token,
                    menu_action_ordinal(target),
                ),
                _button(get_text("btn_abandon_no", lang), CallbackAction.ABANDON_NO, token),
            ],
            _cancel_row(token, lang),
        ]
    )


def all_callback_data(lang: str) -> list[str]:
    """Return the ``callback_data`` of every button this module can produce, for the budget test.

    The helper exists so the 64-byte bound of NF-1.4 can be checked by enumeration rather than by
    reflection. It uses a full-length Flow_Token and a ten-digit vehicle identifier, which is the
    worst case the grammar allows.
    """
    token = "Xk3-Zq_9"
    vehicles = [VehicleChoice(1, "Panda"), VehicleChoice(9_999_999_999, "")]
    entries = tuple(
        FieldEntry(index=index, label_key=spec.label_key, rendered_value="1.234,56")
        for index, spec in enumerate(FIELDS[FlowKind.FUEL])
    )

    markups: list[InlineKeyboardMarkup] = [
        summary_keyboard(token, lang),
        field_picker_keyboard(token, entries, lang),
        regression_keyboard(token, lang),
        confirmation_keyboard(token, queued=False, lang=lang),
        confirmation_keyboard(token, queued=True, lang=lang),
        latest_menu_keyboard(lang),
        latest_record_keyboard(lang),
        options_menu_keyboard(lang),
        options_back_keyboard(lang),
        vehicle_keyboard(vehicles, lang),
        language_keyboard(lang),
    ]
    for specs in FIELDS.values():
        for spec in specs:
            markups.append(flow_step_keyboard(token, spec, suggestion=None, lang=lang))
            if spec.kind is not FieldKind.CHOICE:
                markups.append(flow_step_keyboard(token, spec, suggestion=999_999, lang=lang))
    markups.extend(abandon_keyboard(token, action, lang) for action in MenuAction)

    data: list[str] = []
    for markup in markups:
        for row in markup.inline_keyboard:
            data.extend(button.callback_data for button in row)
    return data
