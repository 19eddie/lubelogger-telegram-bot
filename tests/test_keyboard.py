"""Unit tests for keyboard builders."""

from __future__ import annotations

from bot.services.keyboard import (
    cancel_keyboard,
    confirmation_inline_keyboard,
    main_menu_keyboard,
    summary_inline_keyboard,
)


class TestMainMenuKeyboard:
    """Tests for main_menu_keyboard."""

    def test_returns_three_buttons_english(self) -> None:
        """English keyboard has 3 buttons with correct emoji labels."""
        kb = main_menu_keyboard("en")
        buttons = kb.keyboard[0]
        assert len(buttons) == 3
        assert "⛽" in buttons[0].text
        assert "🔧" in buttons[1].text
        assert "📊" in buttons[2].text

    def test_returns_three_buttons_italian(self) -> None:
        """Italian keyboard has 3 buttons with correct localized labels."""
        kb = main_menu_keyboard("it")
        buttons = kb.keyboard[0]
        assert len(buttons) == 3
        assert "⛽" in buttons[0].text
        assert "🔧" in buttons[1].text
        assert "📊" in buttons[2].text

    def test_resize_keyboard_enabled(self) -> None:
        """Keyboard has resize_keyboard=True."""
        kb = main_menu_keyboard("en")
        assert kb.resize_keyboard is True


class TestCancelKeyboard:
    """Tests for cancel_keyboard."""

    def test_returns_single_cancel_button(self) -> None:
        """Cancel keyboard has exactly one button."""
        kb = cancel_keyboard("en")
        assert len(kb.keyboard) == 1
        assert len(kb.keyboard[0]) == 1
        assert "❌" in kb.keyboard[0][0].text

    def test_resize_keyboard_enabled(self) -> None:
        """Cancel keyboard has resize_keyboard=True."""
        kb = cancel_keyboard("en")
        assert kb.resize_keyboard is True


class TestSummaryInlineKeyboard:
    """Tests for summary_inline_keyboard."""

    def test_returns_three_inline_buttons(self) -> None:
        """Summary inline keyboard has 3 buttons."""
        kb = summary_inline_keyboard("en")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 3

    def test_correct_callback_data(self) -> None:
        """Buttons have correct callback_data."""
        kb = summary_inline_keyboard("en")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_data = [btn.callback_data for btn in buttons]
        assert "summary_save" in callback_data
        assert "summary_edit" in callback_data
        assert "summary_cancel" in callback_data


class TestConfirmationInlineKeyboard:
    """Tests for confirmation_inline_keyboard."""

    def test_returns_two_inline_buttons(self) -> None:
        """Confirmation inline keyboard has 2 buttons."""
        kb = confirmation_inline_keyboard("fuel", "en")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 2

    def test_correct_callback_data_fuel(self) -> None:
        """Fuel confirmation has correct callback_data."""
        kb = confirmation_inline_keyboard("fuel", "en")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_data = [btn.callback_data for btn in buttons]
        assert "confirm_log_another:fuel" in callback_data
        assert "confirm_history" in callback_data

    def test_correct_callback_data_service(self) -> None:
        """Service confirmation has correct callback_data."""
        kb = confirmation_inline_keyboard("service", "en")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_data = [btn.callback_data for btn in buttons]
        assert "confirm_log_another:service" in callback_data
