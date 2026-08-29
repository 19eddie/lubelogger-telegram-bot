"""Property tests for ConfigStore persistence of the Active_Vehicle_Name."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.services.config_store import ConfigStore
from bot.services.database import init_db

# Names LubeLogger can produce: plain text, markup characters, emoji, and the empty
# string that means "never recorded".
_vehicle_names = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=60,
)


@st.composite
def _vehicle_lists(draw: st.DrawFn) -> tuple[list[tuple[int, str]], int]:
    """Draw a list of (vehicle_id, display_name) pairs plus the index of the chosen one."""
    ids = draw(
        st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=8, unique=True)
    )
    names = draw(st.lists(_vehicle_names, min_size=len(ids), max_size=len(ids)))
    vehicles = list(zip(ids, names, strict=True))
    chosen = draw(st.integers(min_value=0, max_value=len(vehicles) - 1))
    return vehicles, chosen


async def _roundtrip(
    vehicles: list[tuple[int, str]], chosen: int, user_id: int
) -> tuple[int | None, str | None, int | None, str | None]:
    """Persist the chosen vehicle in a fresh database and read it back twice.

    The second read goes through a brand-new ConfigStore over the same file,
    which stands in for reopening the database.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "config.db")
        await init_db(db_path)
        store = ConfigStore(db_path)

        vehicle_id, name = vehicles[chosen]
        await store.set_active_vehicle(user_id, vehicle_id, name)

        first_id = await store.get_active_vehicle(user_id)
        first_name = await store.get_active_vehicle_name(user_id)

        reopened = ConfigStore(db_path)
        return (
            first_id,
            first_name,
            await reopened.get_active_vehicle(user_id),
            await reopened.get_active_vehicle_name(user_id),
        )


@settings(max_examples=100, deadline=None)
@given(vehicles_and_choice=_vehicle_lists(), user_id=st.integers(min_value=1, max_value=10**12))
def test_property_vehicle_name_roundtrip(
    vehicles_and_choice: tuple[list[tuple[int, str]], int], user_id: int
) -> None:
    """# Feature: improve-ux, Property 33: The active vehicle name round-trips through persistence

    For any vehicle list and any vehicle chosen from it, persisting the selection stores both the
    identifier and the display name, and reading them back returns the display name of that
    vehicle, including after the database is reopened.

    Validates: Requirements 5.13, 8.6
    """
    vehicles, chosen = vehicles_and_choice
    expected_id, expected_name = vehicles[chosen]

    first_id, first_name, reopened_id, reopened_name = asyncio.run(
        _roundtrip(vehicles, chosen, user_id)
    )

    assert first_id == expected_id
    assert first_name == expected_name
    assert reopened_id == expected_id
    assert reopened_name == expected_name
