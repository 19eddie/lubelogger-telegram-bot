"""Property and unit tests for conversation utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.conversation import format_progress, format_summary, send_or_edit


@settings(max_examples=100)
@given(
    total_steps=st.integers(min_value=1, max_value=20),
    data=st.data(),
)
def test_property_progress_indicator_format(total_steps: int, data: st.DataObject) -> None:
    """Property 1: Progress indicator formatting.

    # Feature: telegram-ux-improvements, Property 1: Progress indicator formatting

    **Validates: Requirements 4.1**
    """
    current_step = data.draw(st.integers(min_value=1, max_value=total_steps))
    result = format_progress(current_step, total_steps)
    assert result == f"📍 Step {current_step}/{total_steps}"


@settings(max_examples=100)
@given(
    fields=st.dictionaries(
        st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N", "P", "S"))),
        st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "P", "S"))),
        min_size=1,
        max_size=10,
    ),
)
def test_property_summary_message_completeness(fields: dict[str, str]) -> None:
    """Property 3: Summary message completeness.

    # Feature: telegram-ux-improvements, Property 3: Summary message completeness

    **Validates: Requirements 4.4**
    """
    result = format_summary(fields, "en")

    for value in fields.values():
        assert value in result


class TestFormatProgress:
    """Unit tests for format_progress."""

    def test_first_step(self) -> None:
        """Format progress for step 1 of 4."""
        assert format_progress(1, 4) == "📍 Step 1/4"

    def test_last_step(self) -> None:
        """Format progress for last step."""
        assert format_progress(4, 4) == "📍 Step 4/4"

    def test_single_step(self) -> None:
        """Format progress for single-step flow."""
        assert format_progress(1, 1) == "📍 Step 1/1"

    def test_raises_for_zero_current(self) -> None:
        """Raise ValueError when current_step is 0."""
        with pytest.raises(ValueError):
            format_progress(0, 4)

    def test_raises_for_current_exceeds_total(self) -> None:
        """Raise ValueError when current_step > total_steps."""
        with pytest.raises(ValueError):
            format_progress(5, 4)


class TestFormatSummary:
    """Unit tests for format_summary."""

    def test_single_field(self) -> None:
        """Summary with one field."""
        result = format_summary({"Odometer": "45000 km"}, "en")
        assert "45000 km" in result

    def test_multiple_fields(self) -> None:
        """Summary with multiple fields shows all values."""
        fields = {"Vehicle": "Toyota", "Odometer": "45000", "Liters": "35"}
        result = format_summary(fields, "en")
        assert "Toyota" in result
        assert "45000" in result
        assert "35" in result

    def test_includes_title(self) -> None:
        """Summary starts with the localized title."""
        result = format_summary({"Key": "Value"}, "en")
        assert "Summary" in result or "📋" in result


class TestSendOrEdit:
    """Unit tests for send_or_edit."""

    async def test_sends_new_message_when_no_previous(self) -> None:
        """Send a new message when no previous message ID stored."""
        update = MagicMock()
        update.effective_chat.id = 123

        context = MagicMock()
        context.user_data = {}

        sent_msg = MagicMock()
        sent_msg.message_id = 456
        context.bot.send_message = AsyncMock(return_value=sent_msg)
        context.bot.edit_message_text = AsyncMock()

        await send_or_edit(update, context, "Hello")

        context.bot.send_message.assert_called_once()
        assert context.user_data["last_bot_message_id"] == 456

    async def test_edits_previous_message(self) -> None:
        """Edit the previous message when ID is stored."""
        from telegram import Message

        update = MagicMock()
        update.effective_chat.id = 123

        context = MagicMock()
        context.user_data = {"last_bot_message_id": 100}

        edited_msg = MagicMock(spec=Message)
        edited_msg.message_id = 100
        context.bot.edit_message_text = AsyncMock(return_value=edited_msg)

        await send_or_edit(update, context, "Updated")

        context.bot.edit_message_text.assert_called_once()
        assert context.user_data["last_bot_message_id"] == 100

    async def test_falls_back_to_send_on_bad_request(self) -> None:
        """Fall back to send_message when edit raises BadRequest."""
        from telegram.error import BadRequest

        update = MagicMock()
        update.effective_chat.id = 123

        context = MagicMock()
        context.user_data = {"last_bot_message_id": 100}

        context.bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message not modified"))

        sent_msg = MagicMock()
        sent_msg.message_id = 200
        context.bot.send_message = AsyncMock(return_value=sent_msg)

        await send_or_edit(update, context, "Fallback")

        context.bot.send_message.assert_called_once()
        assert context.user_data["last_bot_message_id"] == 200
