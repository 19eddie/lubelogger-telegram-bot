"""Internationalization module with in-memory cache and English fallback."""

from __future__ import annotations

import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent / "locales"
_cache: dict[str, dict[str, str]] = {}


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
