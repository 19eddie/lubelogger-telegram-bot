"""Unit tests for the SQLite schema migration mechanism.

Covers Requirements 5.5 (per-vehicle odometer persistence) and NF-2.5 (the only locally
persisted vehicle information is the active vehicle id, its name and its last odometer).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from bot.services.database import _LATEST_VERSION, init_db

# The schema exactly as it existed before migration 1, used to build a legacy database.
_PRE_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN ('gas', 'service', 'odometer')),
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_created ON queue(created_at);

CREATE TABLE IF NOT EXISTS user_config (
    user_id INTEGER PRIMARY KEY,
    active_vehicle_id INTEGER,
    language TEXT NOT NULL DEFAULT 'en',
    updated_at TEXT NOT NULL
);
"""

_EXPECTED_USER_CONFIG_COLUMNS = {
    "user_id",
    "active_vehicle_id",
    "language",
    "updated_at",
    "active_vehicle_name",
}

_EXPECTED_VEHICLE_STATE_COLUMNS = {
    "vehicle_id",
    "last_odometer",
    "last_odometer_date",
    "last_odometer_source",
    "updated_at",
}


async def _create_legacy_db(db_path: str) -> None:
    """Create a database with the pre-migration schema and user_version = 0."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_PRE_MIGRATION_SCHEMA)
        await db.commit()


async def _columns(db_path: str, table: str) -> set[str]:
    """Return the column names of a table."""
    async with aiosqlite.connect(db_path) as db, db.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {row[1] for row in rows}


async def _tables(db_path: str) -> set[str]:
    """Return the names of every user table."""
    async with (
        aiosqlite.connect(db_path) as db,
        db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return {row[0] for row in rows}


async def _schema_snapshot(db_path: str) -> list[tuple[str, str, str | None]]:
    """Return a stable snapshot of every schema object, for equality comparison."""
    async with (
        aiosqlite.connect(db_path) as db,
        db.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ) as cur,
    ):
        rows = await cur.fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


async def _user_version(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db, db.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def test_legacy_database_gains_column_and_table(tmp_path: Path) -> None:
    """A pre-migration database gains active_vehicle_name and the vehicle_state table."""
    db_path = str(tmp_path / "legacy.db")
    await _create_legacy_db(db_path)

    assert "active_vehicle_name" not in await _columns(db_path, "user_config")
    assert "vehicle_state" not in await _tables(db_path)
    assert await _user_version(db_path) == 0

    await init_db(db_path)

    assert "active_vehicle_name" in await _columns(db_path, "user_config")
    assert "vehicle_state" in await _tables(db_path)
    assert await _user_version(db_path) == _LATEST_VERSION


async def test_existing_user_config_rows_stay_intact(tmp_path: Path) -> None:
    """Migrating preserves existing user_config rows and defaults the new column to ''."""
    db_path = str(tmp_path / "legacy_rows.db")
    await _create_legacy_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            "INSERT INTO user_config (user_id, active_vehicle_id, language, updated_at) "
            "VALUES (?, ?, ?, ?)",
            [
                (1, 42, "en", "2025-01-01T00:00:00"),
                (2, None, "it", "2025-01-02T00:00:00"),
            ],
        )
        await db.commit()

    await init_db(db_path)

    async with (
        aiosqlite.connect(db_path) as db,
        db.execute(
            "SELECT user_id, active_vehicle_id, language, updated_at, active_vehicle_name "
            "FROM user_config ORDER BY user_id"
        ) as cur,
    ):
        rows = await cur.fetchall()

    assert rows == [
        (1, 42, "en", "2025-01-01T00:00:00", ""),
        (2, None, "it", "2025-01-02T00:00:00", ""),
    ]


async def test_queue_rows_survive_the_migration(tmp_path: Path) -> None:
    """Queued records in a legacy database are untouched by the migration."""
    db_path = str(tmp_path / "legacy_queue.db")
    await _create_legacy_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO queue (user_id, vehicle_id, record_type, payload, status, "
            "retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 42, "gas", '{"odometer": 1000}', "pending", 0, "2025-01-01", "2025-01-01"),
        )
        await db.commit()

    await init_db(db_path)

    async with (
        aiosqlite.connect(db_path) as db,
        db.execute("SELECT user_id, vehicle_id, record_type, payload, status FROM queue") as cur,
    ):
        rows = await cur.fetchall()

    assert rows == [(1, 42, "gas", '{"odometer": 1000}', "pending")]


async def test_second_init_db_is_a_noop(tmp_path: Path) -> None:
    """Running init_db twice changes neither the schema, the version, nor the data."""
    db_path = str(tmp_path / "twice.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO user_config (user_id, active_vehicle_id, language, updated_at, "
            "active_vehicle_name) VALUES (?, ?, ?, ?, ?)",
            (7, 3, "it", "2025-02-01T00:00:00", "Panda"),
        )
        await db.execute(
            "INSERT INTO vehicle_state (vehicle_id, last_odometer, last_odometer_date, "
            "last_odometer_source, updated_at) VALUES (?, ?, ?, ?, ?)",
            (3, 45230, "2025-02-01", "fuel", "2025-02-01T00:00:00"),
        )
        await db.commit()

    before_schema = await _schema_snapshot(db_path)
    before_version = await _user_version(db_path)

    await init_db(db_path)

    assert await _schema_snapshot(db_path) == before_schema
    assert await _user_version(db_path) == before_version == _LATEST_VERSION

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT user_id, active_vehicle_id, language, active_vehicle_name FROM user_config"
        ) as cur:
            config_rows = await cur.fetchall()
        async with db.execute(
            "SELECT vehicle_id, last_odometer, last_odometer_source FROM vehicle_state"
        ) as cur:
            state_rows = await cur.fetchall()

    assert config_rows == [(7, 3, "it", "Panda")]
    assert state_rows == [(3, 45230, "fuel")]


async def test_migrated_schema_has_exactly_the_expected_columns(tmp_path: Path) -> None:
    """The migrated schema exposes exactly the expected columns, and nothing more (NF-2.5)."""
    db_path = str(tmp_path / "fresh.db")
    await init_db(db_path)

    assert await _columns(db_path, "user_config") == _EXPECTED_USER_CONFIG_COLUMNS
    assert await _columns(db_path, "vehicle_state") == _EXPECTED_VEHICLE_STATE_COLUMNS
    assert await _tables(db_path) == {"queue", "user_config", "vehicle_state"}


async def test_fresh_and_migrated_databases_have_the_same_schema(tmp_path: Path) -> None:
    """A legacy database migrated up is indistinguishable from a freshly created one."""
    fresh_path = str(tmp_path / "a_fresh.db")
    migrated_path = str(tmp_path / "b_migrated.db")

    await init_db(fresh_path)
    await _create_legacy_db(migrated_path)
    await init_db(migrated_path)

    fresh_tables = await _tables(fresh_path)
    assert fresh_tables == await _tables(migrated_path)
    for table in sorted(fresh_tables):
        assert await _columns(fresh_path, table) == await _columns(migrated_path, table)
    assert await _user_version(fresh_path) == await _user_version(migrated_path)


async def test_vehicle_state_is_keyed_by_vehicle(tmp_path: Path) -> None:
    """vehicle_state holds one row per vehicle: a second insert for the same id conflicts."""
    db_path = str(tmp_path / "keyed.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO vehicle_state (vehicle_id, last_odometer, last_odometer_date, "
            "last_odometer_source, updated_at) VALUES (?, ?, ?, ?, ?)",
            (5, 100, None, "bot", "2025-03-01T00:00:00"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO vehicle_state (vehicle_id, last_odometer, "
            "last_odometer_date, last_odometer_source, updated_at) VALUES (?, ?, ?, ?, ?)",
            (5, 200, "2025-03-02", "odometer", "2025-03-02T00:00:00"),
        )
        await db.commit()
        async with db.execute(
            "SELECT vehicle_id, last_odometer, last_odometer_source FROM vehicle_state"
        ) as cur:
            rows = await cur.fetchall()

    assert rows == [(5, 200, "odometer")]
