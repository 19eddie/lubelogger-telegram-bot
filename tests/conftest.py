"""Shared test fixtures: a recording FakeBot, a temporary database and locale isolation.

NF-1.1 / NF-1.2: the flow, card, menu and command layers must be assertable without a network and
without a real ``telegram.Bot``. :class:`FakeBot` records every outgoing call with its full payload,
hands out incrementing message ids and can be told to fail a given method, so tests can count calls,
inspect texts and markup, and exercise the Telegram error branches.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from telegram import Chat, Message

from bot import i18n
from bot.services.database import init_db

#: Every Bot method :class:`FakeBot` knows about. Anything else is a typo in a test.
SUPPORTED_METHODS: tuple[str, ...] = (
    "send_message",
    "edit_message_text",
    "edit_message_reply_markup",
    "delete_message",
    "answer_callback_query",
    "set_my_commands",
)

#: First message id handed out by :meth:`FakeBot.send_message`.
FIRST_MESSAGE_ID = 1000

#: Marker key added to a recorded call whose method raised an injected failure.
FAILED_KEY = "_failed"

#: Key holding the message id a successful ``send_message`` handed out.
RESULT_ID_KEY = "_result_message_id"


@dataclass(frozen=True)
class RecordedCall:
    """One recorded Bot call: the method name plus the full keyword payload it was given."""

    method: str
    kwargs: Mapping[str, object]

    @property
    def chat_id(self) -> object:
        return self.kwargs.get("chat_id")

    @property
    def message_id(self) -> object:
        return self.kwargs.get("message_id")

    @property
    def text(self) -> object:
        return self.kwargs.get("text")

    @property
    def reply_markup(self) -> object:
        return self.kwargs.get("reply_markup")

    @property
    def parse_mode(self) -> object:
        return self.kwargs.get("parse_mode")

    @property
    def callback_query_id(self) -> object:
        return self.kwargs.get("callback_query_id")

    @property
    def show_alert(self) -> object:
        return self.kwargs.get("show_alert")

    @property
    def failed(self) -> bool:
        """True when the call raised an injected failure instead of completing."""
        return bool(self.kwargs.get(FAILED_KEY, False))

    def __getitem__(self, key: str) -> object:
        """Read any payload field, including the ones without a named property."""
        return self.kwargs[key]

    def __contains__(self, key: str) -> bool:
        return key in self.kwargs


@dataclass
class MessageState:
    """The content :class:`FakeBot` currently holds for a message id."""

    chat_id: object
    text: str | None = None
    reply_markup: object = None
    parse_mode: object = None
    deleted: bool = False


@dataclass
class _Failure:
    """A queued failure: which call number it hits and how many times it may fire."""

    error: BaseException
    on_call: int | None
    remaining: int | None

    def matches(self, call_number: int) -> bool:
        if self.remaining is not None and self.remaining <= 0:
            return False
        return self.on_call is None or self.on_call == call_number


@dataclass
class FakeBot:
    """Recording stand-in for ``telegram.Bot``.

    Records every call with its full payload, keeps the current text and markup per message id,
    assigns incrementing message ids from :meth:`send_message` and returns ``telegram.Message``
    objects, so callers that store ``message.message_id`` (the card service) work unchanged.
    """

    calls: list[RecordedCall] = field(default_factory=list)
    messages: dict[int, MessageState] = field(default_factory=dict)
    _counts: Counter[str] = field(default_factory=Counter)
    _failures: dict[str, list[_Failure]] = field(default_factory=dict)
    _next_message_id: int = FIRST_MESSAGE_ID

    # ------------------------------------------------------------------ failure injection

    def fail(
        self,
        method: str,
        error: BaseException,
        *,
        on_call: int | None = None,
        times: int | None = None,
    ) -> None:
        """Make ``method`` raise ``error``.

        ``on_call`` is the 1-based call number to hit; ``None`` means every call. ``times`` caps
        how often the failure fires and defaults to once when ``on_call`` is given, unlimited
        otherwise. Failures are checked in registration order.
        """
        self._check_method(method)
        limit = times if times is not None else (1 if on_call is not None else None)
        self._failures.setdefault(method, []).append(
            _Failure(error=error, on_call=on_call, remaining=limit)
        )

    def fail_next(self, method: str, error: BaseException) -> None:
        """Make the next call to ``method`` raise ``error``, and only that call."""
        self.fail(method, error, on_call=self._counts[method] + 1)

    def fail_always(self, method: str, error: BaseException) -> None:
        """Make every call to ``method`` raise ``error``."""
        self.fail(method, error)

    def clear_failures(self, method: str | None = None) -> None:
        """Drop the queued failures of ``method``, or of every method when omitted."""
        if method is None:
            self._failures.clear()
        else:
            self._check_method(method)
            self._failures.pop(method, None)

    # ------------------------------------------------------------------ inspection helpers

    def calls_to(self, method: str) -> list[RecordedCall]:
        """Every recorded call to ``method``, in order, failed attempts included."""
        self._check_method(method)
        return [call for call in self.calls if call.method == method]

    def call_count(self, method: str) -> int:
        """How many times ``method`` was called, failed calls included."""
        self._check_method(method)
        return self._counts[method]

    def last_call(self, method: str) -> RecordedCall:
        """The most recent call to ``method``. Fails the test when there is none."""
        recorded = self.calls_to(method)
        assert recorded, f"no {method} call was recorded"
        return recorded[-1]

    def texts(self, method: str = "send_message") -> list[object]:
        """The ``text`` payload of every call to ``method``."""
        return [call.text for call in self.calls_to(method)]

    def state(self, message_id: int) -> MessageState:
        """The content currently held for ``message_id``. Fails the test when unknown."""
        assert message_id in self.messages, f"message {message_id} was never sent"
        return self.messages[message_id]

    @property
    def deleted_message_ids(self) -> list[object]:
        """The message ids ``delete_message`` was called with, in order."""
        return [call.message_id for call in self.calls_to("delete_message")]

    @property
    def sent_message_ids(self) -> list[object]:
        """The message ids handed out by the successful ``send_message`` calls, in order."""
        return [call[RESULT_ID_KEY] for call in self.calls_to("send_message") if not call.failed]

    def reset(self) -> None:
        """Forget every call, message and queued failure, keeping the id counter monotone."""
        self.calls.clear()
        self.messages.clear()
        self._counts.clear()
        self._failures.clear()

    # ------------------------------------------------------------------ Bot surface

    async def send_message(
        self,
        chat_id: int | str | None = None,
        text: str | None = None,
        **kwargs: object,
    ) -> Message:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text, **kwargs}
        self._enter("send_message", payload)
        message_id = self._next_message_id
        self._next_message_id += 1
        self.messages[message_id] = MessageState(
            chat_id=chat_id,
            text=text,
            reply_markup=kwargs.get("reply_markup"),
            parse_mode=kwargs.get("parse_mode"),
        )
        payload[RESULT_ID_KEY] = message_id
        self._record("send_message", payload)
        return self._message(message_id, chat_id, text, kwargs.get("reply_markup"))

    async def edit_message_text(
        self,
        text: str | None = None,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        **kwargs: object,
    ) -> Message | bool:
        payload: dict[str, object] = {
            "text": text,
            "chat_id": chat_id,
            "message_id": message_id,
            **kwargs,
        }
        self._enter("edit_message_text", payload)
        self._record("edit_message_text", payload)
        if message_id is None:
            return True
        state = self.messages.setdefault(message_id, MessageState(chat_id=chat_id))
        state.text = text
        state.reply_markup = kwargs.get("reply_markup")
        state.parse_mode = kwargs.get("parse_mode")
        return self._message(message_id, chat_id, text, state.reply_markup)

    async def edit_message_reply_markup(
        self,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        **kwargs: object,
    ) -> Message | bool:
        payload: dict[str, object] = {"chat_id": chat_id, "message_id": message_id, **kwargs}
        self._enter("edit_message_reply_markup", payload)
        self._record("edit_message_reply_markup", payload)
        if message_id is None:
            return True
        state = self.messages.setdefault(message_id, MessageState(chat_id=chat_id))
        state.reply_markup = kwargs.get("reply_markup")
        return self._message(message_id, chat_id, state.text, state.reply_markup)

    async def delete_message(
        self,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        **kwargs: object,
    ) -> bool:
        payload: dict[str, object] = {"chat_id": chat_id, "message_id": message_id, **kwargs}
        self._enter("delete_message", payload)
        self._record("delete_message", payload)
        if message_id is not None and message_id in self.messages:
            self.messages[message_id].deleted = True
        return True

    async def answer_callback_query(
        self,
        callback_query_id: str | None = None,
        text: str | None = None,
        show_alert: bool = False,
        **kwargs: object,
    ) -> bool:
        payload: dict[str, object] = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
            **kwargs,
        }
        self._enter("answer_callback_query", payload)
        self._record("answer_callback_query", payload)
        return True

    async def set_my_commands(
        self,
        commands: Sequence[object] | None = None,
        **kwargs: object,
    ) -> bool:
        payload: dict[str, object] = {"commands": commands, **kwargs}
        self._enter("set_my_commands", payload)
        self._record("set_my_commands", payload)
        return True

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _check_method(method: str) -> None:
        if method not in SUPPORTED_METHODS:
            raise ValueError(f"unknown Bot method {method!r}; known: {SUPPORTED_METHODS}")

    def _enter(self, method: str, payload: Mapping[str, object]) -> None:
        """Count the call and raise the queued failure, recording the attempt when it fires."""
        self._counts[method] += 1
        call_number = self._counts[method]
        for failure in self._failures.get(method, []):
            if not failure.matches(call_number):
                continue
            if failure.remaining is not None:
                failure.remaining -= 1
            self.calls.append(RecordedCall(method=method, kwargs={**payload, FAILED_KEY: True}))
            raise failure.error

    def _record(self, method: str, payload: Mapping[str, object]) -> None:
        self.calls.append(RecordedCall(method=method, kwargs=dict(payload)))

    @staticmethod
    def _message(
        message_id: int,
        chat_id: int | str | None,
        text: str | None,
        reply_markup: object,
    ) -> Message:
        chat = Chat(id=int(chat_id) if chat_id is not None else 0, type=Chat.PRIVATE)
        return Message(
            message_id=message_id,
            date=dt.datetime.now(tz=dt.UTC),
            chat=chat,
            text=text,
            reply_markup=reply_markup,  # type: ignore[arg-type]
        )


@pytest.fixture
def fake_bot() -> FakeBot:
    """A fresh recording bot, with no queued failures and no recorded calls."""
    return FakeBot()


@pytest.fixture
async def temp_db(tmp_path: Path) -> AsyncIterator[str]:
    """Path to an initialized, migrated SQLite database, unique per test."""
    db_path = str(tmp_path / "bot.db")
    await init_db(db_path)
    yield db_path


@pytest.fixture
def clean_locales() -> Iterator[None]:
    """Isolate the i18n caches: dropped before and after the test."""
    i18n.clear_cache()
    yield
    i18n.clear_cache()
