"""Internationalization module with in-memory cache and English fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from bot.flows.definitions import MenuAction

logger = logging.getLogger(__name__)

_LOCALES_DIR = Path(__file__).parent / "locales"
_cache: dict[str, dict[str, str]] = {}

#: Locale key holding the label of each navigation-keyboard action.
MENU_LABEL_KEYS: Mapping[MenuAction, str] = MappingProxyType(
    {action: f"menu_{action.value}" for action in MenuAction}
)

_menu_index_cache: Mapping[str, MenuAction] | None = None


def _load(lang: str) -> dict[str, str]:
    """Load locale file for given language, caching the result."""
    if lang not in _cache:
        path = _LOCALES_DIR / f"{lang}.json"
        if path.exists():
            _cache[lang] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _cache[lang] = _load("en")
    return _cache[lang]


def get_text(key: str, lang: str = "en", **kwargs: str | int | float) -> str:
    """Get localized message with fallback to English. Supports {placeholder} formatting."""
    messages = _load(lang)
    template = messages.get(key) or _load("en").get(key, key)
    return template.format(**kwargs) if kwargs else template


def available_locales() -> tuple[str, ...]:
    """Return the language codes of every locale file, sorted for determinism.

    Discovery is done on the filesystem, so adding a language is adding a JSON file.
    """
    return tuple(sorted(path.stem for path in _LOCALES_DIR.glob("*.json")))


def get_keys(lang: str) -> frozenset[str]:
    """Return the set of message keys defined for ``lang``."""
    return frozenset(_load(lang))


def _normalize_label(text: str) -> str:
    """Normalize a menu label for comparison: trimmed and case-folded."""
    return text.strip().casefold()


def menu_label_index() -> Mapping[str, MenuAction]:
    """Return the closed allowlist mapping every normalized menu label to its action.

    The index covers the ``menu_*`` labels of *every* locale file, so a keyboard rendered in one
    language keeps resolving after the user switches language with ``/lang``. Built once and
    cached; call :func:`clear_cache` after adding a locale file at runtime.
    """
    global _menu_index_cache
    if _menu_index_cache is None:
        index: dict[str, MenuAction] = {}
        for lang in available_locales():
            messages = _load(lang)
            for action, key in MENU_LABEL_KEYS.items():
                label = messages.get(key)
                if not label:
                    continue
                normalized = _normalize_label(label)
                if not normalized:
                    continue
                existing = index.setdefault(normalized, action)
                if existing is not action:
                    logger.warning(
                        "menu label collision for key %s in locale %s: kept action %s",
                        key,
                        lang,
                        existing.value,
                    )
        _menu_index_cache = MappingProxyType(index)
    return _menu_index_cache


def resolve_menu_label(text: str) -> MenuAction | None:
    """Return the action a menu label stands for, or ``None`` when it is not a menu label."""
    normalized = _normalize_label(text)
    if not normalized:
        return None
    return menu_label_index().get(normalized)


def clear_cache() -> None:
    """Drop every cached locale payload and the menu-label index."""
    global _menu_index_cache
    _cache.clear()
    _menu_index_cache = None
