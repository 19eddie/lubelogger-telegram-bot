"""Property-based tests for ConfigStore persistence and isolation."""

from __future__ import annotations

import os
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.config_store import ConfigStore
from bot.services.database import init_db

# Shared database path and initialization for all hypothesis examples
_DB_PATH = os.path.join(tempfile.gettempdir(), f"pbt_config_store_{os.getpid()}.db")
_DB_INITIALIZED = False


async def _get_store() -> ConfigStore:
    """Get a ConfigStore backed by a shared test database (initialized once)."""
    global _DB_INITIALIZED  # noqa: PLW0603
    if not _DB_INITIALIZED:
        if os.path.exists(_DB_PATH):
            os.unlink(_DB_PATH)
        await init_db(_DB_PATH)
        _DB_INITIALIZED = True
    return ConfigStore(_DB_PATH)


@settings(max_examples=100)
@given(
    user_id=st.integers(min_value=1, max_value=2**31),
    vehicle_id=st.integers(min_value=1, max_value=10000),
    language=st.sampled_from(["en", "it", "de", "fr", "es"]),
)
@pytest.mark.asyncio
async def test_property_config_persistence_roundtrip(
    user_id: int,
    vehicle_id: int,
    language: str,
) -> None:
    """For any user ID, vehicle ID, and language code, storing them in the
    ConfigStore and reading them back SHALL produce the same values.

    # Feature: lubelogger-telegram-bot, Property 4: Config persistence round-trip

    **Validates: Requirements 3.2, 3.4, 11.1, 11.2, 11.3, 11.4**
    """
    store = await _get_store()

    # Store vehicle and language
    await store.set_active_vehicle(user_id, vehicle_id)
    await store.set_language(user_id, language)

    # Read back and verify round-trip
    read_vehicle = await store.get_active_vehicle(user_id)
    read_language = await store.get_language(user_id)

    assert read_vehicle == vehicle_id
    assert read_language == language


@settings(max_examples=100)
@given(
    data=st.data(),
)
@pytest.mark.asyncio
async def test_property_multi_user_isolation(
    data: st.DataObject,
) -> None:
    """For any two distinct user IDs with independently set preferences,
    reading the config for one user SHALL return that user's values without
    being affected by the other user's stored values.

    # Feature: lubelogger-telegram-bot, Property 5: Multi-user config isolation

    **Validates: Requirements 11.4**
    """
    user_id_1 = data.draw(st.integers(min_value=1, max_value=2**31), label="user_id_1")
    user_id_2 = data.draw(
        st.integers(min_value=1, max_value=2**31).filter(lambda x: x != user_id_1),
        label="user_id_2",
    )
    vehicle_id_1 = data.draw(st.integers(min_value=1, max_value=10000), label="vehicle_id_1")
    vehicle_id_2 = data.draw(st.integers(min_value=1, max_value=10000), label="vehicle_id_2")
    language_1 = data.draw(st.sampled_from(["en", "it", "de", "fr", "es"]), label="language_1")
    language_2 = data.draw(st.sampled_from(["en", "it", "de", "fr", "es"]), label="language_2")

    store = await _get_store()

    # Set preferences for user 1
    await store.set_active_vehicle(user_id_1, vehicle_id_1)
    await store.set_language(user_id_1, language_1)

    # Set preferences for user 2
    await store.set_active_vehicle(user_id_2, vehicle_id_2)
    await store.set_language(user_id_2, language_2)

    # Read user 1 — should be unaffected by user 2
    assert await store.get_active_vehicle(user_id_1) == vehicle_id_1
    assert await store.get_language(user_id_1) == language_1

    # Read user 2 — should be unaffected by user 1
    assert await store.get_active_vehicle(user_id_2) == vehicle_id_2
    assert await store.get_language(user_id_2) == language_2
