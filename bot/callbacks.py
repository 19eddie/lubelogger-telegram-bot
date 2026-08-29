"""Codec for the `callback_data` of every inline button.

Pure module: no I/O, no globals beyond the action table, nothing imported from the
rest of the bot package, so both keyboards and handlers can depend on it freely.

The grammar is::

    callback_data := action ":" token [ ":" arg ]
    action        := 2 * ASCII-lower            # a CallbackAction value
    token         := flow-token | "-"           # "-" outside a flow
    flow-token    := secrets.token_urlsafe(6)   # 8 URL-safe base64 characters
    arg           := 1*10 DIGIT                 # ordinal or server-side entity id

Only three kinds of payload ever reach `arg`: a field index, a choice ordinal, or an
identifier the server already knows (vehicle id, locale ordinal). A field *value*
never travels in `callback_data` (Requirement 11.3): the value behind a button such
as "keep this odometer" is read back from the flow state, keyed by the field index.

All characters are ASCII, so the worst case is 2 + 1 + 8 + 1 + 10 = 22 bytes, well
inside :data:`TELEGRAM_CALLBACK_DATA_LIMIT`.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum

#: Telegram rejects a `callback_data` longer than this many UTF-8 bytes.
TELEGRAM_CALLBACK_DATA_LIMIT = 64

#: Token placeholder for buttons that do not belong to a flow (menus, options, latest).
NO_TOKEN = "-"

_SEPARATOR = ":"
_TOKEN_BYTES = 6
_MAX_ARG_DIGITS = 10


class CallbackAction(StrEnum):
    """The closed set of actions an inline button can request.

    Values are two ASCII-lowercase letters so that the byte budget stays provable.
    """

    CANCEL = "cx"
    SAVE = "sv"
    EDIT = "ed"
    FIELD = "fp"
    """arg = field index"""
    KEEP = "kp"
    """arg = field index, reuse the suggested value"""
    CHOICE = "ch"
    """arg = choice ordinal (full tank yes/no)"""
    ODO_CONFIRM = "oc"
    ODO_REENTER = "oe"
    LOG_ANOTHER = "la"
    LATEST_OPEN = "lo"
    """arg = 0 fuel, 1 odometer"""
    LATEST_BACK = "lb"
    OPTIONS_OPEN = "oo"
    """arg = 0 vehicle, 1 lang, 2 status, 3 queue"""
    OPTIONS_BACK = "ob"
    VEHICLE_SET = "vs"
    """arg = vehicle id"""
    LANG_SET = "ls"
    """arg = locale ordinal"""
    ABANDON_YES = "ay"
    """arg = MenuAction ordinal"""
    ABANDON_NO = "an"


class CallbackDecodeError(ValueError):
    """Raised when a `callback_data` string does not follow the grammar."""

    def __init__(self, data: str, hint: str) -> None:
        self.data = data
        self.hint = hint
        super().__init__(f"Invalid callback_data: {hint}")


@dataclass(frozen=True, slots=True)
class Callback:
    """A decoded `callback_data` payload."""

    action: CallbackAction
    token: str = NO_TOKEN
    arg: int | None = None

    @property
    def in_flow(self) -> bool:
        """True when the button belongs to a flow, i.e. it carries a Flow_Token."""
        return self.token != NO_TOKEN


def new_token() -> str:
    """Return a fresh Flow_Token: 8 URL-safe base64 characters, unguessable."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def encode(action: CallbackAction, token: str = NO_TOKEN, arg: int | None = None) -> str:
    """Render `action`, `token` and optional `arg` as `callback_data`.

    Raises:
        ValueError: when the token is empty or contains the separator, or when the
            argument is negative or wider than the ten digits of the byte budget.
    """
    if not token:
        raise ValueError("callback token must not be empty")
    if _SEPARATOR in token:
        raise ValueError(f"callback token must not contain {_SEPARATOR!r}")
    if arg is None:
        return f"{action.value}{_SEPARATOR}{token}"
    if isinstance(arg, bool) or not isinstance(arg, int):
        raise ValueError("callback arg must be an int")
    if arg < 0:
        raise ValueError("callback arg must not be negative")
    rendered = str(arg)
    if len(rendered) > _MAX_ARG_DIGITS:
        raise ValueError(f"callback arg must fit in {_MAX_ARG_DIGITS} digits")
    return f"{action.value}{_SEPARATOR}{token}{_SEPARATOR}{rendered}"


def decode(data: str) -> Callback:
    """Parse `callback_data` back into a :class:`Callback`.

    Raises:
        CallbackDecodeError: when the string is not `action ":" token [ ":" arg ]`
            with a known action and a decimal argument.
    """
    parts = data.split(_SEPARATOR)
    if len(parts) not in (2, 3):
        raise CallbackDecodeError(data, "expected 'action:token' or 'action:token:arg'")
    raw_action, token = parts[0], parts[1]
    try:
        action = CallbackAction(raw_action)
    except ValueError as exc:
        raise CallbackDecodeError(data, f"unknown action {raw_action!r}") from exc
    if not token:
        raise CallbackDecodeError(data, "empty token")
    if len(parts) == 2:
        return Callback(action=action, token=token, arg=None)
    raw_arg = parts[2]
    if not raw_arg.isascii() or not raw_arg.isdigit():
        raise CallbackDecodeError(data, f"arg {raw_arg!r} is not a decimal number")
    if len(raw_arg) > _MAX_ARG_DIGITS:
        raise CallbackDecodeError(data, f"arg {raw_arg!r} exceeds {_MAX_ARG_DIGITS} digits")
    return Callback(action=action, token=token, arg=int(raw_arg))
