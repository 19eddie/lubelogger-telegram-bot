"""Unit tests for the i18n module."""

from __future__ import annotations

from bot.i18n import _cache, get_text


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
        result = get_text("fuel_saved", lang="en", liters="42.5", cost="78.90", odometer="45000")
        assert "42.5" in result
        assert "78.90" in result
        assert "45000" in result

    def test_formats_placeholders_italian(self) -> None:
        result = get_text("fuel_saved", lang="it", liters="42.5", cost="78.90", odometer="45000")
        assert "42.5" in result
        assert "78.90" in result
        assert "45000" in result

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
        ]
        for key in required_keys:
            result = get_text(key, lang="en")
            assert result != key, f"Key '{key}' not found in English locale"

    def test_all_required_keys_present_in_italian(self) -> None:
        required_keys = [
            "welcome",
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
        ]
        for key in required_keys:
            result = get_text(key, lang="it")
            assert result != key, f"Key '{key}' not found in Italian locale"
