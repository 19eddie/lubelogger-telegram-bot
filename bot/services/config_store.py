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

    async def get_active_vehicle_name(self, user_id: int) -> str | None:
        """Return the persisted display name of the user's active vehicle.

        Returns None when the user has no stored configuration. An empty
        string means the name has never been recorded, which callers treat
        as "unknown" and replace with a localized fallback label.
        """
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                "SELECT active_vehicle_name FROM user_config WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return row["active_vehicle_name"]

    async def set_active_vehicle(
        self, user_id: int, vehicle_id: int, name: str | None = None
    ) -> None:
        """Store the active vehicle ID for the given user (upsert).

        When `name` is given it is persisted as the Active_Vehicle_Name; when
        it is omitted, any previously stored name is preserved. The language
        preference is never touched.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            if name is None:
                await db.execute(
                    """INSERT INTO user_config
                    (user_id, active_vehicle_id, active_vehicle_name, language, updated_at)
                    VALUES (?, ?, '', 'en', ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        active_vehicle_id = excluded.active_vehicle_id,
                        updated_at = excluded.updated_at""",
                    (user_id, vehicle_id, now),
                )
            else:
                await db.execute(
                    """INSERT INTO user_config
                    (user_id, active_vehicle_id, active_vehicle_name, language, updated_at)
                    VALUES (?, ?, ?, 'en', ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        active_vehicle_id = excluded.active_vehicle_id,
                        active_vehicle_name = excluded.active_vehicle_name,
                        updated_at = excluded.updated_at""",
                    (user_id, vehicle_id, name, now),
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
        """Store the language preference for the given user (upsert).

        The active vehicle and its persisted name are left untouched.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                """INSERT INTO user_config
                (user_id, active_vehicle_id, active_vehicle_name, language, updated_at)
                VALUES (?, NULL, '', ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    language = excluded.language,
                    updated_at = excluded.updated_at""",
                (user_id, language, now),
            )
            await db.commit()

    async def get_all_languages(self) -> dict[int, str]:
        """Return the stored language preference of every known user.

        Used by the command registry to register per-chat command
        descriptions in the language each user actually chose.
        """
        async with get_db(self._db_path) as db:
            cursor = await db.execute("SELECT user_id, language FROM user_config")
            rows = await cursor.fetchall()
        return {row["user_id"]: row["language"] for row in rows}
