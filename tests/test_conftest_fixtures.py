"""Self-tests for the shared fixtures (NF-1.1, NF-1.2)."""

from __future__ import annotations

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from bot import i18n
from bot.services.config_store import ConfigStore
from tests.conftest import FIRST_MESSAGE_ID, FakeBot

_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("ok", callback_data="x")]])


async def test_send_message_returns_incrementing_ids(fake_bot: FakeBot) -> None:
    first = await fake_bot.send_message(chat_id=7, text="a", parse_mode="HTML")
    second = await fake_bot.send_message(chat_id=7, text="b")

    assert first.message_id == FIRST_MESSAGE_ID
    assert second.message_id == FIRST_MESSAGE_ID + 1
    assert fake_bot.sent_message_ids == [first.message_id, second.message_id]


async def test_calls_record_the_full_payload(fake_bot: FakeBot) -> None:
    await fake_bot.send_message(chat_id=7, text="card", parse_mode="HTML", reply_markup=_MARKUP)

    call = fake_bot.last_call("send_message")
    assert (call.chat_id, call.text, call.parse_mode) == (7, "card", "HTML")
    assert call.reply_markup is _MARKUP
    assert fake_bot.call_count("send_message") == 1


async def test_edit_updates_the_stored_message_state(fake_bot: FakeBot) -> None:
    sent = await fake_bot.send_message(chat_id=7, text="one")
    await fake_bot.edit_message_text(
        text="two", chat_id=7, message_id=sent.message_id, reply_markup=_MARKUP
    )

    state = fake_bot.state(sent.message_id)
    assert state.text == "two"
    assert state.reply_markup is _MARKUP
    assert fake_bot.texts("edit_message_text") == ["two"]


async def test_strip_markup_and_delete_are_visible(fake_bot: FakeBot) -> None:
    sent = await fake_bot.send_message(chat_id=7, text="one", reply_markup=_MARKUP)
    await fake_bot.edit_message_reply_markup(chat_id=7, message_id=sent.message_id)
    assert fake_bot.state(sent.message_id).reply_markup is None

    await fake_bot.delete_message(chat_id=7, message_id=sent.message_id)
    assert fake_bot.deleted_message_ids == [sent.message_id]
    assert fake_bot.state(sent.message_id).deleted is True


async def test_answer_callback_query_and_set_my_commands_record_their_payloads(
    fake_bot: FakeBot,
) -> None:
    await fake_bot.answer_callback_query(callback_query_id="cq1", text="expired", show_alert=True)
    await fake_bot.set_my_commands([("fuel", "Log fuel")], language_code="it")

    answer = fake_bot.last_call("answer_callback_query")
    assert (answer.callback_query_id, answer.text, answer.show_alert) == ("cq1", "expired", True)
    assert fake_bot.last_call("set_my_commands")["language_code"] == "it"


async def test_failure_on_one_call_only(fake_bot: FakeBot) -> None:
    fake_bot.fail_next("edit_message_text", BadRequest("message is not modified"))

    with pytest.raises(BadRequest, match="not modified"):
        await fake_bot.edit_message_text(text="x", chat_id=7, message_id=1)
    await fake_bot.edit_message_text(text="y", chat_id=7, message_id=1)

    assert fake_bot.call_count("edit_message_text") == 2
    assert fake_bot.calls_to("edit_message_text")[0]["_failed"] is True


async def test_failure_always_and_clear(fake_bot: FakeBot) -> None:
    fake_bot.fail_always("edit_message_text", TelegramError("boom"))

    for _ in range(3):
        with pytest.raises(TelegramError):
            await fake_bot.edit_message_text(text="x", chat_id=7, message_id=1)

    fake_bot.clear_failures("edit_message_text")
    assert await fake_bot.edit_message_text(text="x", chat_id=7, message_id=1)


async def test_failure_on_nth_call(fake_bot: FakeBot) -> None:
    fake_bot.fail("send_message", TelegramError("boom"), on_call=2)

    await fake_bot.send_message(chat_id=7, text="a")
    with pytest.raises(TelegramError):
        await fake_bot.send_message(chat_id=7, text="b")
    await fake_bot.send_message(chat_id=7, text="c")

    assert fake_bot.call_count("send_message") == 3
    assert fake_bot.sent_message_ids == [FIRST_MESSAGE_ID, FIRST_MESSAGE_ID + 1]


def test_unknown_method_is_rejected(fake_bot: FakeBot) -> None:
    with pytest.raises(ValueError, match="unknown Bot method"):
        fake_bot.fail("send_photo", TelegramError("boom"))


async def test_temp_db_is_usable_and_isolated(temp_db: str) -> None:
    store = ConfigStore(temp_db)
    assert await store.get_active_vehicle(1) is None
    await store.set_active_vehicle(1, 42, "Van")
    assert await store.get_active_vehicle_name(1) == "Van"


def test_clean_locales_clears_the_cache(clean_locales: None) -> None:
    assert i18n.get_text("menu_fuel", "en")
    i18n.clear_cache()
    assert i18n.get_text("menu_fuel", "en")
