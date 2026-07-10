"""User configuration persistence backed by SQLite."""

from __future__ import annotations

from datetime import UTC, datetime

from bot.services.database import get_db


class ConfigStore:
    """Stores per-user preferences (active vehicle, language) in SQLite.

    Each user is identified by their Telegram user ID. Preferences survive
    bot restarts because they are persisted to the local SQLite database.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def get_active_vehicle(self, user_id: int) -> int | None:
        """Return the active vehicle ID for the given user, or None if not set."""
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                "SELECT active_vehicle_id FROM user_config WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return row["active_vehicle_id"]

    async def set_active_vehicle(self, user_id: int, vehicle_id: int) -> None:
        """Store the active vehicle ID for the given user (upsert)."""
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO user_config
                (user_id, active_vehicle_id, language, updated_at)
                VALUES (
                    ?,
                    ?,
                    COALESCE(
                        (SELECT language FROM user_config WHERE user_id = ?),
                        'en'
                    ),
                    ?
                )""",
                (user_id, vehicle_id, user_id, now),
            )
            await db.commit()

    async def get_language(self, user_id: int) -> str:
        """Return the language preference for the given user, defaulting to 'en'."""
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                "SELECT language FROM user_config WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return "en"
            return row["language"]

    async def set_language(self, user_id: int, language: str) -> None:
        """Store the language preference for the given user (upsert)."""
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO user_config
                (user_id, active_vehicle_id, language, updated_at)
                VALUES (
                    ?,
                    (SELECT active_vehicle_id FROM user_config WHERE user_id = ?),
                    ?,
                    ?
                )""",
                (user_id, user_id, language, now),
            )
            await db.commit()
