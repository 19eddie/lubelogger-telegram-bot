"""Card_Message lifecycle: the only module that sends, edits or deletes a card.

An operation is one message. It is opened once (Requirement 3.1) and then edited in place at every
step (Requirement 3.2), which keeps the chat clean and costs one Telegram call per step (NF-2.4).
Handlers pass rendered text and ready-made markup: this service owns no text and builds no keyboard.

Three Telegram realities are absorbed here so no handler has to:

* editing a message to content it already has raises ``BadRequest("message is not modified")``.
  That is not an error, it is a no-op, so it is swallowed and the same id is returned;
* any other :class:`~telegram.error.TelegramError` on an edit means the card is gone or unreachable.
  The content is then re-sent as a new message whose id the caller adopts as the new card
  (Requirement 3.7). This is why :meth:`CardService.update` returns an ``int``;
* deleting a user message can fail for reasons outside the Bot's control (age, permissions). It is
  logged at DEBUG and the flow continues silently (Requirement 3.6).

:meth:`CardService.consume_prompt_reply` is the **only** ``delete_message`` caller in the codebase
and is called only from the in-flow typed-value handlers. That is the structural guarantee for
Requirement 3.5 and NF-4.2: nothing else can delete a message.

Every log line here carries structural data only, never message content (NF-4.1).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

from bot.callbacks import CallbackAction, CallbackDecodeError, decode

if TYPE_CHECKING:
    from telegram import Bot, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

#: The parse mode of every card. Locale templates carry HTML, values are escaped by `formatters`.
CARD_PARSE_MODE = ParseMode.HTML

#: Substring identifying the "nothing changed" answer Telegram gives to a redundant edit.
_NOT_MODIFIED = "message is not modified"

#: The actions a terminated card may still offer (Requirements 6.10, 9.4, 3.9).
FOLLOW_UP_ACTIONS: frozenset[CallbackAction] = frozenset(
    {CallbackAction.LOG_ANOTHER, CallbackAction.LATEST_OPEN}
)


def _is_not_modified(error: BadRequest) -> bool:
    """True when `error` is Telegram reporting that the edit would change nothing."""
    return _NOT_MODIFIED in str(error).casefold()


def _is_follow_up_markup(markup: InlineKeyboardMarkup) -> bool:
    """True when every button of `markup` is a follow-up action.

    A step keyboard (cancel, save, edit, field picker, choices) fails this check, which is how
    :meth:`CardService.finalize` keeps Requirement 3.9 true whatever the caller passes.
    """
    for row in markup.inline_keyboard:
        for button in row:
            data = button.callback_data
            if not isinstance(data, str):
                return False
            try:
                callback = decode(data)
            except CallbackDecodeError:
                return False
            if callback.action not in FOLLOW_UP_ACTIONS:
                return False
    return True


class CardService:
    """Sends, edits and finalizes the single Card_Message of an operation."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def open(
        self,
        chat_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None,
    ) -> int:
        """Send the card of a starting flow and return the id the caller must store.

        The id goes into ``FlowState.card_message_id`` and identifies the card for the rest of the
        flow (Requirement 3.1).
        """
        message = await self._bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=CARD_PARSE_MODE,
        )
        logger.debug("card opened chat=%s message=%s", chat_id, message.message_id)
        return message.message_id

    async def update(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None,
    ) -> int:
        """Edit the card in place and return the id of the card the caller should keep.

        Returns `message_id` when the edit succeeds and when Telegram reports the content as
        unchanged. On any other :class:`~telegram.error.TelegramError` the same text and markup are
        sent as a new message and **its** id is returned, which the caller adopts as the new card
        (Requirement 3.7). No content is lost in either branch.
        """
        try:
            await self._bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                parse_mode=CARD_PARSE_MODE,
            )
        except BadRequest as error:
            if not _is_not_modified(error):
                return await self._resend(chat_id, message_id, text, markup, error)
            logger.debug(
                "card edit was a no-op chat=%s message=%s",
                chat_id,
                message_id,
            )
        except TelegramError as error:
            return await self._resend(chat_id, message_id, text, markup, error)
        return message_id

    async def finalize(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> int:
        """Edit the card to its terminal state, keeping only follow-up buttons.

        A save, a queue or a cancellation all end here. The markup is either absent or the
        follow-up keyboard of Requirements 6.10 and 9.4; anything else is dropped, so a terminated
        card can never keep a step keyboard alive (Requirement 3.9).
        """
        if markup is not None and not _is_follow_up_markup(markup):
            logger.warning(
                "dropping non follow-up markup on finalize chat=%s message=%s",
                chat_id,
                message_id,
            )
            markup = None
        return await self.update(chat_id, message_id, text, markup)

    async def strip_markup(self, chat_id: int, message_id: int) -> None:
        """Remove the buttons of a message, leaving its text intact (Requirement 7.3).

        Used when "🔁 Log another" opens a fresh card and the previous confirmation must stop
        offering its follow-up actions. A failure here is cosmetic: it is logged at DEBUG and
        never interrupts the new flow.
        """
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except TelegramError as error:
            logger.debug(
                "strip markup failed chat=%s message=%s error=%s",
                chat_id,
                message_id,
                type(error).__name__,
            )

    async def consume_prompt_reply(self, message: Message) -> None:
        """Delete a typed answer to a prompt of an active flow (Requirement 3.4).

        The only ``delete_message`` call site in the codebase, and only reachable from the in-flow
        typed-value handlers, which bounds deletions to prompt replies (Requirement 3.5, NF-4.2).
        Every :class:`~telegram.error.TelegramError` is swallowed at DEBUG level so a message that
        cannot be deleted never breaks the flow and never bothers the user (Requirement 3.6).
        """
        try:
            await self._bot.delete_message(
                chat_id=message.chat_id,
                message_id=message.message_id,
            )
        except TelegramError as error:
            logger.debug(
                "prompt reply delete failed chat=%s message=%s error=%s",
                message.chat_id,
                message.message_id,
                type(error).__name__,
            )

    async def _resend(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None,
        error: TelegramError,
    ) -> int:
        """Re-send the card content after a failed edit and return the new card id."""
        logger.info(
            "card edit failed, resending chat=%s message=%s error=%s",
            chat_id,
            message_id,
            type(error).__name__,
        )
        return await self.open(chat_id, text, markup)
