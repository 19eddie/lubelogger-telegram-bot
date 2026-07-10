"""Smoke test for ConfigStore to verify basic functionality."""

from __future__ import annotations

import os
import tempfile

import pytest

from bot.services.config_store import ConfigStore
from bot.services.database import init_db


@pytest.fixture
async def store() -> ConfigStore:
    """Create a ConfigStore backed by a temporary database."""
    tmp = os.path.join(tempfile.gettempdir(), "test_config_store_smoke.db")
    if os.path.exists(tmp):
        os.unlink(tmp)
    await init_db(tmp)
    yield ConfigStore(tmp)
    if os.path.exists(tmp):
        os.unlink(tmp)


async def test_get_active_vehicle_returns_none_for_unknown_user(store: ConfigStore) -> None:
    result = await store.get_active_vehicle(12345)
    assert result is None


async def test_get_language_returns_en_for_unknown_user(store: ConfigStore) -> None:
    lang = await store.get_language(12345)
    assert lang == "en"


async def test_set_and_get_active_vehicle(store: ConfigStore) -> None:
    await store.set_active_vehicle(12345, 42)
    result = await store.get_active_vehicle(12345)
    assert result == 42


async def test_set_and_get_language(store: ConfigStore) -> None:
    await store.set_language(12345, "it")
    lang = await store.get_language(12345)
    assert lang == "it"


async def test_vehicle_preserved_after_language_change(store: ConfigStore) -> None:
    await store.set_active_vehicle(12345, 42)
    await store.set_language(12345, "it")
    result = await store.get_active_vehicle(12345)
    assert result == 42


async def test_language_preserved_after_vehicle_change(store: ConfigStore) -> None:
    await store.set_language(12345, "it")
    await store.set_active_vehicle(12345, 99)
    lang = await store.get_language(12345)
    assert lang == "it"


async def test_multi_user_isolation(store: ConfigStore) -> None:
    await store.set_active_vehicle(12345, 99)
    await store.set_language(12345, "it")
    await store.set_active_vehicle(99999, 7)
    await store.set_language(99999, "en")

    assert await store.get_active_vehicle(12345) == 99
    assert await store.get_language(12345) == "it"
    assert await store.get_active_vehicle(99999) == 7
    assert await store.get_language(99999) == "en"
