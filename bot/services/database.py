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


async def init_db(db_path: str) -> None:
    """Initialize the database, creating all tables and indexes.

    Creates the parent directory if it does not exist, enables WAL mode
    for better concurrency, and executes the full schema.
    """
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(_SCHEMA)
        await db.commit()


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
