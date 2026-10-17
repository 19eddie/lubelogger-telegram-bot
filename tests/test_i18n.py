"""Unit tests for the i18n module."""

from __future__ import annotations

from string import Formatter

import pytest

from bot.i18n import _cache, _load, get_text, get_text_with_units
from bot.units import DISPLAY_UNITS_KEY, DisplayUnits

UNIT_KEYS = [
    "fuel_saved",
    "service_saved",
    "odometer_saved",
    "last_fuel",
    "last_km",
    "prompt_odometer",
    "fuel_ask_odometer",
    "fuel_ask_liters",
    "fuel_ask_cost",
    "service_prompt_odometer",
    "service_prompt_cost",
]


def _placeholders(template: str) -> set[str]:
    """Return the {placeholder} names used by a message template."""
    return {name for _, name, _, _ in Formatter().parse(template) if name}


class TestGetText:
    """Tests for get_text function."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _cache.clear()

    def test_returns_english_message_by_default(self) -> None:
        result = get_text("welcome")
        assert "Welcome" in result
        assert "/vehicle" in result

    def test_returns_italian_message(self) -> None:
        result = get_text("welcome", lang="it")
        assert "Benvenuto" in result

    def test_falls_back_to_english_for_unknown_language(self) -> None:
        result = get_text("welcome", lang="xx")
        assert "Welcome" in result

    def test_falls_back_to_english_for_missing_key_in_locale(self) -> None:
        # Italian has all keys, but if one were missing it should fall back to English
        result = get_text("welcome", lang="en")
        assert "Welcome" in result

    def test_returns_key_when_not_found_in_any_locale(self) -> None:
        result = get_text("nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"

    def test_formats_placeholders(self) -> None:
        result = get_text_with_units(
            {}, "fuel_saved", lang="en", liters="42.5", cost="78.90", odometer="45000"
        )
        assert result == "✓ Fuel record saved: 42.5 L @ €78.90, odo 45000 km"

    def test_formats_placeholders_italian(self) -> None:
        result = get_text_with_units(
            {}, "fuel_saved", lang="it", liters="42.5", cost="78.90", odometer="45000"
        )
        assert result == "✓ Rifornimento registrato: 42.5 L @ €78.90, odo 45000 km"

    def test_formats_configured_unit_labels(self) -> None:
        bot_data = {DISPLAY_UNITS_KEY: DisplayUnits(distance="mi", volume="gal", currency="$")}
        result = get_text_with_units(
            bot_data, "fuel_saved", lang="en", liters="12.5", cost="45.90", odometer="45000"
        )
        assert result == "✓ Fuel record saved: 12.5 gal @ $45.90, odo 45000 mi"

    @pytest.mark.parametrize("lang", ["en", "it"])
    @pytest.mark.parametrize("key", UNIT_KEYS)
    def test_unit_keys_use_unit_placeholders(self, key: str, lang: str) -> None:
        placeholders = _placeholders(_load(lang)[key])
        assert placeholders & {"distance_unit", "volume_unit", "currency"}

    def test_locales_share_keys_and_placeholders(self) -> None:
        english, italian = _load("en"), _load("it")
        assert english.keys() == italian.keys()
        for key, template in english.items():
            assert _placeholders(template) == _placeholders(italian[key]), key

    @pytest.mark.parametrize("lang", ["en", "it"])
    def test_locales_have_no_hardcoded_currency(self, lang: str) -> None:
        assert not [key for key, text in _load(lang).items() if "€" in text]

    def test_vehicle_selected_placeholder(self) -> None:
        result = get_text("vehicle_selected", lang="en", vehicle_name="2020 Toyota Yaris")
        assert "2020 Toyota Yaris" in result

    def test_lang_changed_placeholder(self) -> None:
        result = get_text("lang_changed", lang="en", language="Italian")
        assert "Italian" in result

    def test_queue_status_placeholder(self) -> None:
        result = get_text("queue_status", lang="en", pending_count="3")
        assert "3" in result

    def test_caching_loads_locale_once(self) -> None:
        _cache.clear()
        get_text("welcome", lang="en")
        assert "en" in _cache
        # Second call uses cache
        get_text("welcome", lang="en")
        assert "en" in _cache

    def test_all_required_keys_present_in_english(self) -> None:
        required_keys = [
            "welcome",
            "help_title",
            "help_section_general",
            "help_section_records",
            "help_section_status",
            "help_start",
            "help_help",
            "help_vehicle",
            "help_fuel",
            "help_usage_fuel",
            "help_service",
            "help_usage_service",
            "help_km",
            "help_usage_km",
            "help_last",
            "help_usage_last",
            "help_status",
            "help_queue",
            "help_lang",
            "help_cancel",
            "start_no_vehicle",
            "fuel_saved",
            "fuel_queued",
            "service_saved",
            "service_queued",
            "odometer_saved",
            "odometer_queued",
            "invalid_odometer",
            "invalid_liters",
            "invalid_cost",
            "invalid_date",
            "invalid_description",
            "usage_fuel",
            "usage_service",
            "usage_km",
            "vehicle_selected",
            "vehicle_prompt",
            "no_vehicle",
            "lubelogger_unreachable",
            "queue_status",
            "queue_empty",
            "queue_synced",
            "queue_failed",
            "status_ok",
            "status_offline",
            "lang_changed",
            "last_fuel_missed",
            "fuel_ask_date",
            "fuel_today_button",
            "fuel_ask_odometer",
            "fuel_ask_liters",
            "fuel_ask_cost",
            "fuel_ask_full_tank",
            "fuel_ask_missed",
            "fuel_yes_button",
            "fuel_no_button",
            "fuel_submitting",
        ]
        for key in required_keys:
            result = get_text(key, lang="en")
            assert result != key, f"Key '{key}' not found in English locale"

    def test_all_required_keys_present_in_italian(self) -> None:
        required_keys = [
            "welcome",
            "help_title",
            "help_section_general",
            "help_section_records",
            "help_section_status",
            "help_start",
            "help_help",
            "help_vehicle",
            "help_fuel",
            "help_usage_fuel",
            "help_service",
            "help_usage_service",
            "help_km",
            "help_usage_km",
            "help_last",
            "help_usage_last",
            "help_status",
            "help_queue",
            "help_lang",
            "help_cancel",
            "start_no_vehicle",
            "fuel_saved",
            "fuel_queued",
            "service_saved",
            "service_queued",
            "odometer_saved",
            "odometer_queued",
            "invalid_odometer",
            "invalid_liters",
            "invalid_cost",
            "invalid_date",
            "invalid_description",
            "usage_fuel",
            "usage_service",
            "usage_km",
            "vehicle_selected",
            "vehicle_prompt",
            "no_vehicle",
            "lubelogger_unreachable",
            "queue_status",
            "queue_empty",
            "queue_synced",
            "queue_failed",
            "status_ok",
            "status_offline",
            "lang_changed",
            "last_fuel_missed",
            "fuel_ask_date",
            "fuel_today_button",
            "fuel_ask_odometer",
            "fuel_ask_liters",
            "fuel_ask_cost",
            "fuel_ask_full_tank",
            "fuel_ask_missed",
            "fuel_yes_button",
            "fuel_no_button",
            "fuel_submitting",
        ]
        for key in required_keys:
            result = get_text(key, lang="it")
            assert result != key, f"Key '{key}' not found in Italian locale"
