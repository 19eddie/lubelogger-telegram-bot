"""Keyboard builder — persistent Reply keyboards and Inline keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.i18n import get_text


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Build the persistent main menu Reply keyboard.

    Returns a 1-row keyboard with: ⛽ Fuel, 🔧 Service, 📊 History
    """
    buttons = [
        [
            get_text("keyboard_fuel", lang),
            get_text("keyboard_service", lang),
            get_text("keyboard_history", lang),
        ]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def cancel_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Build the single-button cancel Reply keyboard for use during conversations."""
    buttons = [[get_text("keyboard_cancel", lang)]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def summary_inline_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the Save / Edit / Cancel inline keyboard for summary messages."""
    buttons = [
        [
            InlineKeyboardButton(get_text("summary_save", lang), callback_data="summary_save"),
            InlineKeyboardButton(get_text("summary_edit", lang), callback_data="summary_edit"),
            InlineKeyboardButton(get_text("summary_cancel", lang), callback_data="summary_cancel"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def confirmation_inline_keyboard(record_type: str, lang: str) -> InlineKeyboardMarkup:
    """Build the 'Log another' / 'History' inline keyboard for confirmations."""
    buttons = [
        [
            InlineKeyboardButton(
                get_text("btn_log_another", lang),
                callback_data=f"confirm_log_another:{record_type}",
            ),
            InlineKeyboardButton(get_text("btn_history", lang), callback_data="confirm_history"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)
