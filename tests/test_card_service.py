"""Property and unit tests for the Card_Message lifecycle (`bot.services.card_service`)."""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError, TimedOut

import bot as bot_package
from bot.callbacks import CallbackAction, encode, new_token
from bot.services.card_service import CARD_PARSE_MODE, CardService
from tests.conftest import FakeBot

# ---------------------------------------------------------------------------------------------
# Property 12: A failed card edit preserves the content and adopts the new message
# ---------------------------------------------------------------------------------------------

#: Card texts LubeLogger and users can produce: markup characters, emoji, empty strings.
_p12_texts = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=120,
)

#: Actions a card keyboard can carry, in-flow ones and follow-up ones alike.
_p12_actions = st.sampled_from(
    [
        CallbackAction.CANCEL,
        CallbackAction.SAVE,
        CallbackAction.EDIT,
        CallbackAction.FIELD,
        CallbackAction.KEEP,
        CallbackAction.CHOICE,
        CallbackAction.LOG_ANOTHER,
        CallbackAction.LATEST_OPEN,
    ]
)


@st.composite
def _p12_markups(draw: st.DrawFn) -> InlineKeyboardMarkup | None:
    """Draw a card keyboard, or ``None`` for a card without buttons."""
    if draw(st.booleans()):
        return None
    token = new_token()
    rows = draw(st.lists(st.lists(_p12_actions, min_size=1, max_size=3), min_size=1, max_size=3))
    keyboard = [
        [
            InlineKeyboardButton(text=f"b{row_index}{index}", callback_data=encode(action, token))
            for index, action in enumerate(row)
        ]
        for row_index, row in enumerate(rows)
    ]
    return InlineKeyboardMarkup(keyboard)


#: Telegram failures that are genuine edit failures, so the fallback of Requirement 3.7 applies.
_p12_edit_errors: st.SearchStrategy[Callable[[], TelegramError]] = st.sampled_from(
    [
        lambda: BadRequest("message to edit not found"),
        lambda: BadRequest("chat not found"),
        lambda: TelegramError("unexpected failure"),
        lambda: NetworkError("connection reset by peer"),
        lambda: TimedOut(),
        lambda: Forbidden("bot was blocked by the user"),
    ]
)

#: Spellings Telegram uses for the redundant-edit answer, which is a no-op and not a failure.
_p12_not_modified = st.sampled_from(
    [
        "message is not modified",
        "Message is not modified",
        "MESSAGE IS NOT MODIFIED",
        (
            "Bad Request: message is not modified: specified new message content and "
            "reply markup are exactly the same as a current content and reply markup "
            "of the message"
        ),
    ]
)


async def _p12_update_after_failure(
    text: str,
    markup: InlineKeyboardMarkup | None,
    error: TelegramError,
) -> tuple[FakeBot, int, int]:
    """Open a card, make the next edit fail with `error`, and update it once."""
    bot = FakeBot()
    service = CardService(bot)  # type: ignore[arg-type]
    chat_id = 4242

    original_id = await service.open(chat_id, "initial", None)
    bot.fail_next("edit_message_text", error)
    returned_id = await service.update(chat_id, original_id, text, markup)
    return bot, original_id, returned_id


@settings(max_examples=100, deadline=None)
@given(
    text=_p12_texts,
    markup=_p12_markups(),
    make_error=_p12_edit_errors,
    not_modified_message=_p12_not_modified,
)
def test_property_edit_failure_fallback(
    text: str,
    markup: InlineKeyboardMarkup | None,
    make_error: Callable[[], TelegramError],
    not_modified_message: str,
) -> None:
    """# Feature: improve-ux, Property 12: A failed card edit preserves the content and adopts the new message

    For any card text and markup, if `editMessageText` raises a Telegram error then a new message
    with the identical text and markup is sent and its identifier becomes the card identifier
    returned to the caller. A "message is not modified" answer is not such an error: it is
    swallowed, nothing is sent and the same identifier is returned.

    **Validates: Requirements 3.7**
    """  # noqa: E501 - the property tag is one line by convention
    # Branch 1: a genuine edit failure re-sends the content and hands back the new card id.
    bot, original_id, returned_id = asyncio.run(
        _p12_update_after_failure(text, markup, make_error())
    )

    assert bot.call_count("edit_message_text") == 1
    resends = [call for call in bot.calls_to("send_message") if not call.failed][1:]
    assert len(resends) == 1, "the failed edit must produce exactly one replacement message"
    resent = resends[0]
    assert resent.text == text
    assert resent.reply_markup == markup
    assert resent.parse_mode == CARD_PARSE_MODE
    assert returned_id == resent["_result_message_id"]
    assert returned_id != original_id
    assert bot.state(returned_id).text == text
    assert bot.state(returned_id).reply_markup == markup

    # Branch 2: "message is not modified" changes nothing and keeps the same card id.
    quiet_bot, quiet_original_id, quiet_returned_id = asyncio.run(
        _p12_update_after_failure(text, markup, BadRequest(not_modified_message))
    )

    assert quiet_bot.call_count("edit_message_text") == 1
    assert quiet_returned_id == quiet_original_id
    assert quiet_bot.call_count("send_message") == 1, "no replacement message may be sent"


# ---------------------------------------------------------------------------------------------
# Property 13: The only deleted messages are typed replies to bot prompts
# ---------------------------------------------------------------------------------------------

#: Chat the interleaving of Property 13 runs in.
_P13_CHAT_ID = 777

#: First id handed to a synthetic prompt reply. Kept below :data:`FIRST_MESSAGE_ID` so a reply id
#: can never be mistaken for a card id the FakeBot handed out.
_P13_FIRST_REPLY_ID = 1

#: The card operations and the prompt reply, interleaved freely by the property.
_p13_operations = st.sampled_from(["open", "update", "finalize", "strip_markup", "reply"])

#: Which Telegram call, if any, misbehaves during the run. Every branch of the service must keep
#: the deletion scope intact, including the resend fallback and the swallowed delete failure.
_p13_error_modes = st.sampled_from(
    ["none", "edit_fails", "edit_not_modified", "delete_fails", "strip_fails"]
)


def _p13_step_markup() -> InlineKeyboardMarkup:
    """A step keyboard, the markup an in-flow card carries."""
    token = new_token()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="cancel", callback_data=encode(CallbackAction.CANCEL, token))]]
    )


def _p13_follow_up_markup() -> InlineKeyboardMarkup:
    """A follow-up keyboard, the markup a terminated card may keep."""
    token = new_token()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="again", callback_data=encode(CallbackAction.LOG_ANOTHER, token)
                )
            ]
        ]
    )


def _p13_prompt_reply(message_id: int) -> Message:
    """A typed answer to a prompt, built like :meth:`FakeBot._message` builds its messages."""
    return Message(
        message_id=message_id,
        date=dt.datetime.now(tz=dt.UTC),
        chat=Chat(id=_P13_CHAT_ID, type=Chat.PRIVATE),
        text="42",
    )


def _p13_apply_error_mode(bot: FakeBot, mode: str) -> None:
    """Arm `bot` with the failure of `mode`, for every call it applies to."""
    if mode == "edit_fails":
        bot.fail_always("edit_message_text", NetworkError("connection reset by peer"))
    elif mode == "edit_not_modified":
        bot.fail_always("edit_message_text", BadRequest("message is not modified"))
    elif mode == "delete_fails":
        bot.fail_always("delete_message", BadRequest("message to delete not found"))
    elif mode == "strip_fails":
        bot.fail_always("edit_message_reply_markup", BadRequest("message to edit not found"))


async def _p13_drive(operations: list[str], error_mode: str) -> tuple[FakeBot, set[int], list[int]]:
    """Run `operations` against a fresh bot, returning it with the card ids and the consumed ids."""
    bot = FakeBot()
    _p13_apply_error_mode(bot, error_mode)
    service = CardService(bot)  # type: ignore[arg-type]

    card_id: int | None = None
    card_ids: set[int] = set()
    consumed: list[int] = []
    next_reply_id = _P13_FIRST_REPLY_ID

    for index, operation in enumerate(operations):
        if operation == "reply":
            message = _p13_prompt_reply(next_reply_id)
            next_reply_id += 1
            consumed.append(message.message_id)
            await service.consume_prompt_reply(message)
            continue
        if operation == "open" or card_id is None:
            card_id = await service.open(_P13_CHAT_ID, f"card {index}", _p13_step_markup())
        elif operation == "update":
            card_id = await service.update(
                _P13_CHAT_ID, card_id, f"card {index}", _p13_step_markup()
            )
        elif operation == "finalize":
            card_id = await service.finalize(
                _P13_CHAT_ID, card_id, f"done {index}", _p13_follow_up_markup()
            )
        else:  # strip_markup
            await service.strip_markup(_P13_CHAT_ID, card_id)
        card_ids.add(card_id)

    return bot, card_ids, consumed


def _p13_delete_message_call_sites() -> set[tuple[str, str]]:
    """Every ``delete_message`` call site in the ``bot`` package as (module path, function name)."""
    package_root = Path(bot_package.__file__).resolve().parent
    sites: set[tuple[str, str]] = set()

    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing: dict[ast.AST, str] = {}

        def annotate(node: ast.AST, scope: str, into: dict[ast.AST, str]) -> None:
            for child in ast.iter_child_nodes(node):
                child_scope = (
                    child.name
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    else scope
                )
                into[child] = child_scope
                annotate(child, child_scope, into)

        annotate(tree, "<module>", enclosing)
        module = path.relative_to(package_root.parent).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Attribute) and target.attr == "delete_message":
                sites.add((module, enclosing.get(node, "<module>")))

    return sites


@settings(max_examples=100, deadline=None)
@given(
    operations=st.lists(_p13_operations, min_size=1, max_size=12),
    error_mode=_p13_error_modes,
)
def test_property_deleted_set_equals_prompt_replies(operations: list[str], error_mode: str) -> None:
    """# Feature: improve-ux, Property 13: The only deleted messages are typed replies to bot prompts

    For any interleaving of card operations and prompt replies, the message identifiers the service
    asks Telegram to delete are exactly the identifiers handed to `consume_prompt_reply`, in that
    order. A card is never deleted, whichever branch the card operations take, and the structural
    guarantee holds too: `consume_prompt_reply` is the only `delete_message` call site of the
    package, so no other code path can delete anything.

    **Validates: Requirements 3.4, 3.5, NF-4.2**
    """  # noqa: E501 - the property tag is one line by convention
    bot, card_ids, consumed = asyncio.run(_p13_drive(operations, error_mode))

    deleted = bot.deleted_message_ids
    assert deleted == consumed, "deletions must match the consumed prompt replies exactly"
    assert bot.call_count("delete_message") == len(consumed), "one delete per consumed reply"
    assert set(deleted).isdisjoint(card_ids), "a card must never be deleted"
    assert set(deleted).isdisjoint(set(bot.sent_message_ids)), "no bot-sent message may be deleted"
    assert all(call.chat_id == _P13_CHAT_ID for call in bot.calls_to("delete_message"))

    assert _p13_delete_message_call_sites() == {
        ("bot/services/card_service.py", "consume_prompt_reply")
    }


# ---------------------------------------------------------------------------------------------
# Unit tests: the error branches of the card service (Requirements 3.6, 3.9)
# ---------------------------------------------------------------------------------------------

#: Chat the unit tests below run in.
_UNIT_CHAT_ID = 9001

#: Root logger of the package. Every card log line lands under it, so DEBUG capture here sees
#: whatever `bot.services.card_service` emits (NF-4.1 is asserted against the captured text).
_UNIT_LOGGER = "bot"

#: A message id below :data:`tests.conftest.FIRST_MESSAGE_ID`, so a prompt reply can never collide
#: with a card id the FakeBot handed out.
_UNIT_REPLY_ID = 7

#: The exact answer Telegram gives to an edit that would change nothing.
_UNIT_NOT_MODIFIED = (
    "Bad Request: message is not modified: specified new message content and reply markup are "
    "exactly the same as a current content and reply markup of the message"
)


def _unit_step_markup() -> InlineKeyboardMarkup:
    """A step keyboard: cancel plus save, the markup an in-flow card carries."""
    token = new_token()
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text="save", callback_data=encode(CallbackAction.SAVE, token))],
            [
                InlineKeyboardButton(
                    text="cancel", callback_data=encode(CallbackAction.CANCEL, token)
                )
            ],
        ]
    )


def _unit_follow_up_markup() -> InlineKeyboardMarkup:
    """A follow-up keyboard: log another plus latest, the only markup a terminated card may keep."""
    token = new_token()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="again", callback_data=encode(CallbackAction.LOG_ANOTHER, token)
                ),
                InlineKeyboardButton(
                    text="latest", callback_data=encode(CallbackAction.LATEST_OPEN, token)
                ),
            ]
        ]
    )


def _unit_mixed_markup() -> InlineKeyboardMarkup:
    """A keyboard mixing a follow-up action with a step action, which finalize must reject."""
    token = new_token()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="again", callback_data=encode(CallbackAction.LOG_ANOTHER, token)
                )
            ],
            [
                InlineKeyboardButton(
                    text="cancel", callback_data=encode(CallbackAction.CANCEL, token)
                )
            ],
        ]
    )


def _unit_prompt_reply(text: str) -> Message:
    """A typed answer to a prompt, carrying `text` as its content."""
    return Message(
        message_id=_UNIT_REPLY_ID,
        date=dt.datetime.now(tz=dt.UTC),
        chat=Chat(id=_UNIT_CHAT_ID, type=Chat.PRIVATE),
        text=text,
    )


async def test_not_modified_edit_is_swallowed_and_keeps_the_card_id(fake_bot: FakeBot) -> None:
    """A redundant edit is a no-op: nothing is sent, nothing raises, the card id is unchanged."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    markup = _unit_step_markup()
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", markup)
    fake_bot.fail_next("edit_message_text", BadRequest(_UNIT_NOT_MODIFIED))

    returned_id = await service.update(_UNIT_CHAT_ID, card_id, "step 1", markup)

    assert returned_id == card_id
    assert fake_bot.call_count("edit_message_text") == 1
    assert fake_bot.call_count("send_message") == 1, "a no-op edit must not send a message"
    assert fake_bot.state(card_id).text == "step 1"
    assert fake_bot.state(card_id).reply_markup == markup


async def test_delete_failure_is_logged_at_debug_and_never_raises(
    fake_bot: FakeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed prompt-reply deletion logs at DEBUG, logs no content, and does not raise."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    secret = "45123 oil change <secret>"
    reply = _unit_prompt_reply(secret)
    fake_bot.fail_next("delete_message", BadRequest("message can't be deleted"))

    with caplog.at_level(logging.DEBUG, logger=_UNIT_LOGGER):
        await service.consume_prompt_reply(reply)

    assert fake_bot.call_count("delete_message") == 1
    failures = [
        record for record in caplog.records if "prompt reply delete failed" in record.getMessage()
    ]
    assert len(failures) == 1, "the swallowed failure must leave exactly one trace"
    assert failures[0].levelno == logging.DEBUG
    assert secret not in caplog.text, "message content must never reach the logs (NF-4.1)"
    assert "BadRequest" in failures[0].getMessage(), "the error type is the only detail logged"


async def test_finalize_drops_a_step_keyboard(
    fake_bot: FakeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Finalizing with a step keyboard leaves the card with no markup and warns about it."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", _unit_step_markup())

    with caplog.at_level(logging.DEBUG, logger=_UNIT_LOGGER):
        returned_id = await service.finalize(_UNIT_CHAT_ID, card_id, "saved", _unit_step_markup())

    assert returned_id == card_id
    assert fake_bot.last_call("edit_message_text").reply_markup is None
    assert fake_bot.state(card_id).reply_markup is None
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "dropping non follow-up markup" in warnings[0].getMessage()
    assert "saved" not in warnings[0].getMessage(), "the warning carries no card content (NF-4.1)"


async def test_finalize_drops_a_mixed_keyboard(fake_bot: FakeBot) -> None:
    """One step button is enough to disqualify the whole keyboard from surviving finalize."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", _unit_step_markup())

    await service.finalize(_UNIT_CHAT_ID, card_id, "cancelled", _unit_mixed_markup())

    assert fake_bot.state(card_id).reply_markup is None


async def test_finalize_keeps_the_follow_up_keyboard(fake_bot: FakeBot) -> None:
    """The follow-up keyboard is the one markup a terminated card keeps, text and mode intact."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", _unit_step_markup())
    follow_up = _unit_follow_up_markup()

    returned_id = await service.finalize(_UNIT_CHAT_ID, card_id, "saved", follow_up)

    assert returned_id == card_id
    assert fake_bot.state(card_id).reply_markup == follow_up
    assert fake_bot.state(card_id).text == "saved"
    assert fake_bot.state(card_id).parse_mode == CARD_PARSE_MODE


async def test_finalize_without_markup_leaves_no_keyboard(fake_bot: FakeBot) -> None:
    """A cancellation finalizes with no markup at all and warns about nothing."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", _unit_step_markup())

    await service.finalize(_UNIT_CHAT_ID, card_id, "cancelled")

    assert fake_bot.state(card_id).reply_markup is None


async def test_finalize_after_a_failed_edit_still_drops_the_step_keyboard(
    fake_bot: FakeBot,
) -> None:
    """The resend fallback of a finalize carries the sanitized markup, not the caller's."""
    service = CardService(fake_bot)  # type: ignore[arg-type]
    card_id = await service.open(_UNIT_CHAT_ID, "step 1", _unit_step_markup())
    fake_bot.fail_next("edit_message_text", NetworkError("connection reset by peer"))

    returned_id = await service.finalize(_UNIT_CHAT_ID, card_id, "saved", _unit_step_markup())

    assert returned_id != card_id
    assert fake_bot.state(returned_id).reply_markup is None
    assert fake_bot.state(returned_id).text == "saved"
