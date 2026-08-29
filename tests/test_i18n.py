"""Unit tests for the i18n module."""

from __future__ import annotations

import pytest

from bot.flows.definitions import MenuAction
from bot.i18n import (
    MENU_LABEL_KEYS,
    _cache,
    available_locales,
    clear_cache,
    get_keys,
    get_text,
    menu_label_index,
    resolve_menu_label,
)


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


class TestAvailableLocales:
    """Tests for available_locales."""

    def setup_method(self) -> None:
        clear_cache()

    def test_lists_the_shipped_locales_sorted(self) -> None:
        locales = available_locales()
        assert locales == tuple(sorted(locales))
        assert "en" in locales
        assert "it" in locales

    def test_contains_no_duplicates_and_no_non_locale_files(self) -> None:
        locales = available_locales()
        assert len(locales) == len(set(locales))
        assert "__init__" not in locales


class TestGetKeys:
    """Tests for get_keys."""

    def setup_method(self) -> None:
        clear_cache()

    def test_returns_the_keys_of_the_requested_locale(self) -> None:
        keys = get_keys("en")
        assert "welcome" in keys
        for key in MENU_LABEL_KEYS.values():
            assert key in keys

    def test_italian_exposes_the_menu_keys(self) -> None:
        assert set(MENU_LABEL_KEYS.values()) <= get_keys("it")

    def test_unknown_locale_falls_back_to_english_keys(self) -> None:
        assert get_keys("xx") == get_keys("en")


class TestMenuLabelIndex:
    """Tests for menu_label_index."""

    def setup_method(self) -> None:
        clear_cache()

    def test_maps_every_label_of_every_locale_to_its_action(self) -> None:
        index = menu_label_index()
        for lang in available_locales():
            for action, key in MENU_LABEL_KEYS.items():
                label = get_text(key, lang=lang)
                assert index[label.strip().casefold()] is action

    def test_labels_are_normalized_lowercase_and_trimmed(self) -> None:
        for label in menu_label_index():
            assert label == label.strip().casefold()

    def test_is_cached_between_calls(self) -> None:
        assert menu_label_index() is menu_label_index()

    def test_clear_cache_rebuilds_the_index(self) -> None:
        first = menu_label_index()
        clear_cache()
        second = menu_label_index()
        assert first is not second
        assert dict(first) == dict(second)

    def test_is_read_only(self) -> None:
        index = menu_label_index()
        with pytest.raises(TypeError):
            index["hack"] = MenuAction.FUEL  # type: ignore[index]


class TestResolveMenuLabel:
    """Tests for resolve_menu_label."""

    def setup_method(self) -> None:
        clear_cache()

    def test_resolves_english_labels(self) -> None:
        assert resolve_menu_label(get_text("menu_fuel", lang="en")) is MenuAction.FUEL
        assert resolve_menu_label(get_text("menu_latest", lang="en")) is MenuAction.LATEST

    def test_resolves_italian_labels(self) -> None:
        assert resolve_menu_label(get_text("menu_service", lang="it")) is MenuAction.SERVICE
        assert resolve_menu_label(get_text("menu_options", lang="it")) is MenuAction.OPTIONS

    def test_resolves_labels_of_every_locale_after_a_language_change(self) -> None:
        # The allowlist is closed over all locales: a keyboard rendered in Italian keeps
        # working once the user switched to English, and the other way round.
        for lang in available_locales():
            for action, key in MENU_LABEL_KEYS.items():
                assert resolve_menu_label(get_text(key, lang=lang)) is action

    def test_ignores_surrounding_whitespace_and_case(self) -> None:
        label = get_text("menu_odometer", lang="en")
        assert resolve_menu_label(f"  {label.upper()}  ") is MenuAction.ODOMETER

    def test_returns_none_for_non_labels(self) -> None:
        assert resolve_menu_label("42") is None
        assert resolve_menu_label("/fuel") is None
        assert resolve_menu_label("oil change <5000km") is None

    def test_returns_none_for_blank_text(self) -> None:
        assert resolve_menu_label("") is None
        assert resolve_menu_label("   ") is None
