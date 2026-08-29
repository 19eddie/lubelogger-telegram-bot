"""Locale completeness and key-convention tests.

Encodes Property 6 of the improve-ux design: locale files stay key-for-key identical, every key
the migrated modules reference exists with a non-empty value in every locale, field prompt keys
follow the ``ask_`` convention, and the deprecated pre-rework keys are gone.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.flows.definitions import FIELDS
from bot.i18n import (
    MENU_LABEL_KEYS,
    available_locales,
    clear_cache,
    get_keys,
    get_text,
)

#: Keys replaced by the ``ask_*`` convention of Requirement 13.5; none may survive in a locale.
DEPRECATED_KEYS = frozenset(
    {
        "prompt_odometer",
        "fuel_ask_odometer",
        "fuel_ask_liters",
        "fuel_ask_cost",
        "fuel_ask_full_tank",
        "service_prompt_odometer",
        "service_prompt_description",
        "service_prompt_cost",
    }
)

#: Modules whose literal ``get_text`` keys must resolve. Scanned only when they exist, so the
#: property grows with the feature instead of failing on modules not yet migrated.
_SCANNED_MODULES = (
    "bot/keyboards.py",
    "bot/formatters.py",
    "bot/services/command_registry.py",
)

_BOT_DIR = Path(__file__).resolve().parent.parent / "bot"


def _literal_get_text_keys(path: Path) -> set[str]:
    """Return every literal first argument of a ``get_text`` call in ``path``."""
    keys: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "get_text" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.add(first.value)
    return keys


def _referenced_keys() -> frozenset[str]:
    """Collect every locale key the field tables, the menu index and migrated modules reference."""
    keys: set[str] = set(MENU_LABEL_KEYS.values())
    for specs in FIELDS.values():
        for spec in specs:
            keys.update(
                {spec.prompt_key, spec.label_key, spec.placeholder_key, spec.error_key},
                spec.choices,
            )
    for relative in _SCANNED_MODULES:
        path = _BOT_DIR.parent / relative
        if path.exists():
            keys.update(_literal_get_text_keys(path))
    return frozenset(keys)


REFERENCED_KEYS = _referenced_keys()

#: Prefix each field-table key must carry, per the naming convention of Requirement 13.5.
_FIELD_KEY_PREFIXES = (
    ("prompt_key", "ask_"),
    ("label_key", "field_"),
    ("placeholder_key", "ph_"),
)

_locales = st.sampled_from(available_locales())
_referenced = st.sampled_from(sorted(REFERENCED_KEYS))


@settings(max_examples=100)
@given(lang_a=_locales, lang_b=_locales, key=_referenced)
def test_property_locale_key_parity(lang_a: str, lang_b: str, key: str) -> None:
    """# Feature: improve-ux, Property 6: Locale files are complete and follow the key convention

    Validates: Requirements 13.4, 13.5, NF-1.3, NF-3.1
    """
    keys_a = get_keys(lang_a)
    keys_b = get_keys(lang_b)

    # Any pair of supported locales exposes exactly the same keys.
    assert keys_a == keys_b, f"key sets differ between {lang_a} and {lang_b}"

    for lang, lang_keys in ((lang_a, keys_a), (lang_b, keys_b)):
        # Every referenced key exists in the locale itself, not only via the English fallback.
        assert key in lang_keys, f"key {key!r} missing from locale {lang}"
        assert get_text(key, lang=lang).strip(), f"key {key!r} is empty in locale {lang}"

        # No deprecated key survives.
        assert not (DEPRECATED_KEYS & lang_keys), f"deprecated keys present in locale {lang}"

    # Field-table keys follow the naming convention.
    for specs in FIELDS.values():
        for spec in specs:
            for attribute, prefix in _FIELD_KEY_PREFIXES:
                value = getattr(spec, attribute)
                assert value.startswith(prefix), (
                    f"{spec.key}.{attribute} = {value!r} does not start with {prefix!r}"
                )


class TestLocaleFilesUnit:
    """Deterministic checks over the whole locale set."""

    def setup_method(self) -> None:
        clear_cache()

    def test_every_locale_exposes_the_same_keys(self) -> None:
        locales = available_locales()
        assert len(locales) >= 2
        reference = get_keys(locales[0])
        for lang in locales[1:]:
            assert get_keys(lang) == reference

    def test_every_referenced_key_resolves_in_every_locale(self) -> None:
        missing = {
            (lang, key)
            for lang in available_locales()
            for key in REFERENCED_KEYS
            if key not in get_keys(lang) or not get_text(key, lang=lang).strip()
        }
        assert not missing

    @pytest.mark.parametrize("key", sorted(DEPRECATED_KEYS))
    def test_deprecated_keys_are_gone(self, key: str) -> None:
        for lang in available_locales():
            assert key not in get_keys(lang)
