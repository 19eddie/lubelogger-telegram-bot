"""Shared conversation utilities — progress, in-place editing, summary."""

from __future__ import annotations

from telegram import Message, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from bot.i18n import get_text


def format_progress(current_step: int, total_steps: int) -> str:
    """Format a progress indicator string like 'Step 2/4'.

    Args:
        current_step: Current step number (1-based).
        total_steps: Total number of steps in the flow.

    Returns:
        Formatted string e.g. "📍 Step 2/4"

    Raises:
        ValueError: If current_step < 1 or current_step > total_steps.
    """
    if current_step < 1 or current_step > total_steps:
        raise ValueError(
            f"current_step must be between 1 and total_steps ({total_steps}), got {current_step}"
        )
    return f"📍 Step {current_step}/{total_steps}"


def format_summary(fields: dict[str, str], lang: str) -> str:
    """Format a summary message listing all collected field values.

    Args:
        fields: Ordered dict of {label: value} pairs to display.
        lang: User's language code.

    Returns:
        Formatted multi-line summary string with title header and all field values included.
    """
    title = get_text("summary_title", lang)
    lines = [title, ""]
    for label, value in fields.items():
        lines.append(f"• {label}: {value}")
    return "\n".join(lines)


async def send_or_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    reply_markup: object | None = None,
    message_key: str = "last_bot_message_id",
) -> Message:
    """Edit the previous bot message in-place, or send a new one if editing fails.

    Stores the sent/edited message ID in context.user_data[message_key] for
    subsequent edits.

    Args:
        update: The Telegram update.
        context: The callback context.
        text: The message text to display.
        reply_markup: Optional keyboard markup.
        message_key: Key in user_data to store the message ID.

    Returns:
        The sent or edited Message object.
    """
    chat_id = update.effective_chat.id  # type: ignore[union-attr]
    previous_message_id = context.user_data.get(message_key)  # type: ignore[union-attr]

    if previous_message_id:
        try:
            msg = await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=previous_message_id,
                text=text,
                reply_markup=reply_markup,
            )
            # edit_message_text may return True if no changes detected
            if isinstance(msg, Message):
                context.user_data[message_key] = msg.message_id  # type: ignore[index]
                return msg
        except (BadRequest, TimedOut):
            pass

    # Fall back to sending a new message
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )
    context.user_data[message_key] = msg.message_id  # type: ignore[index]
    return msg
