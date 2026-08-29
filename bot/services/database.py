"""SQLite database initialization and connection management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

_SCHEMA = """
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

_ADD_VEHICLE_NAME = (
    "ALTER TABLE user_config ADD COLUMN active_vehicle_name TEXT NOT NULL DEFAULT ''"
)

_VEHICLE_STATE = """
CREATE TABLE IF NOT EXISTS vehicle_state (
    vehicle_id INTEGER PRIMARY KEY,
    last_odometer INTEGER NOT NULL,
    last_odometer_date TEXT,
    last_odometer_source TEXT NOT NULL DEFAULT 'bot',
    updated_at TEXT NOT NULL
)
"""

# Ordered schema migrations, applied when PRAGMA user_version is lower than their version.
_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = ((1, (_ADD_VEHICLE_NAME, _VEHICLE_STATE)),)

_LATEST_VERSION = max(version for version, _ in _MIGRATIONS)


async def _current_version(db: aiosqlite.Connection) -> int:
    """Return the schema version recorded in PRAGMA user_version (0 on a legacy database)."""
    async with db.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


async def _apply_migrations(db: aiosqlite.Connection) -> None:
    """Apply every migration newer than the recorded version, in order, in one transaction."""
    version = await _current_version(db)
    if version >= _LATEST_VERSION:
        return

    await db.execute("BEGIN")
    try:
        for target, statements in _MIGRATIONS:
            if target <= version:
                continue
            for statement in statements:
                await db.execute(statement)
        # PRAGMA cannot be parameterized; the value is an int literal from _MIGRATIONS.
        await db.execute(f"PRAGMA user_version = {_LATEST_VERSION:d}")
    except Exception:
        await db.rollback()
        raise
    await db.commit()


async def init_db(db_path: str) -> None:
    """Initialize the database, creating all tables and indexes.

    Creates the parent directory if it does not exist, enables WAL mode
    for better concurrency, executes the base schema and then applies any
    pending schema migration. Idempotent: running it twice on the same file
    changes nothing.
    """
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(_SCHEMA)
        await db.commit()
        await _apply_migrations(db)


@asynccontextmanager
async def get_db(db_path: str) -> AsyncIterator[aiosqlite.Connection]:
    """Async context manager that yields a configured aiosqlite connection.

    Sets row_factory to aiosqlite.Row for dict-like row access.
    """
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
