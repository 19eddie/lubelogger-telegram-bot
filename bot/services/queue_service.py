"""Offline queue service backed by SQLite for resilient record submission."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.models.responses import QueueItem
from bot.services.database import get_db

if TYPE_CHECKING:
    from bot.services.lubelogger_client import LubeLoggerClient

logger = logging.getLogger(__name__)


@dataclass
class FlushResult:
    """Result of a queue flush operation."""

    sent: int
    failed: int
    remaining: int


class QueueService:
    """Manages an offline queue of records waiting to be sent to LubeLogger.

    Records are persisted in SQLite and processed in FIFO order. When LubeLogger
    is unreachable, processing stops. On API errors, retry count is incremented
    and items are marked failed after max_retries attempts.
    """

    def __init__(self, db_path: str, max_retries: int = 3) -> None:
        self._db_path = db_path
        self.max_retries = max_retries

    async def enqueue(
        self, user_id: int, vehicle_id: int, record_type: str, payload: str
    ) -> int:
        """Add a record to the offline queue.

        Args:
            user_id: Telegram user ID who submitted the record.
            vehicle_id: Target LubeLogger vehicle ID.
            record_type: One of 'gas', 'service', 'odometer'.
            payload: JSON-serialized payload model.

        Returns:
            The ID of the newly created queue item.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO queue (user_id, vehicle_id, record_type, payload,
                   status, retry_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)""",
                (user_id, vehicle_id, record_type, payload, now, now),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_pending(self) -> list[QueueItem]:
        """Retrieve all pending queue items in FIFO order (oldest first).

        Returns:
            List of QueueItem objects ordered by creation time ascending.
        """
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM queue WHERE status = 'pending' ORDER BY created_at ASC",
            )
            rows = await cursor.fetchall()
            return [
                QueueItem(
                    id=row["id"],
                    user_id=row["user_id"],
                    vehicle_id=row["vehicle_id"],
                    record_type=row["record_type"],
                    payload=row["payload"],
                    status=row["status"],
                    retry_count=row["retry_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    async def mark_sent(self, item_id: int) -> None:
        """Mark a queue item as successfully sent.

        Args:
            item_id: The queue item ID to update.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                "UPDATE queue SET status = 'sent', updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            await db.commit()

    async def mark_failed(self, item_id: int) -> None:
        """Mark a queue item as permanently failed.

        Args:
            item_id: The queue item ID to update.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                "UPDATE queue SET status = 'failed', updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            await db.commit()

    async def increment_retry(self, item_id: int) -> int:
        """Increment the retry count for a queue item.

        Args:
            item_id: The queue item ID to update.

        Returns:
            The new retry count after incrementing.
        """
        now = datetime.now(UTC).isoformat()
        async with get_db(self._db_path) as db:
            await db.execute(
                "UPDATE queue SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT retry_count FROM queue WHERE id = ?",
                (item_id,),
            )
            row = await cursor.fetchone()
            return row["retry_count"]  # type: ignore[index]

    async def get_pending_count(self) -> dict[str, int]:
        """Get the count of pending records grouped by record type.

        Returns:
            A dictionary mapping record_type to count of pending items.
        """
        async with get_db(self._db_path) as db:
            cursor = await db.execute(
                """SELECT record_type, COUNT(*) as count
                FROM queue WHERE status = 'pending'
                GROUP BY record_type""",
            )
            rows = await cursor.fetchall()
            return {row["record_type"]: row["count"] for row in rows}

    async def flush(self, client: LubeLoggerClient) -> FlushResult:
        """Process all pending queue items in FIFO order.

        Sends each item to LubeLogger. On success, marks as sent. On API error,
        increments retry count and marks as failed if max retries reached.
        Stops processing entirely if LubeLogger becomes unreachable.

        Args:
            client: The LubeLogger HTTP client to use for sending.

        Returns:
            A FlushResult with counts of sent, failed, and remaining items.
        """
        pending = await self.get_pending()
        sent, failed = 0, 0
        for item in pending:
            try:
                await self._send_item(client, item)
                await self.mark_sent(item.id)
                sent += 1
            except LubeLoggerUnreachableError:
                logger.warning("LubeLogger unreachable during flush, stopping")
                break
            except LubeLoggerApiError as exc:
                logger.warning(
                    "API error for queue item %d: %s", item.id, exc.message
                )
                new_count = await self.increment_retry(item.id)
                if new_count >= self.max_retries:
                    await self.mark_failed(item.id)
                    failed += 1
        return FlushResult(sent=sent, failed=failed, remaining=len(pending) - sent - failed)

    async def _send_item(self, client: LubeLoggerClient, item: QueueItem) -> None:
        """Reconstruct the payload and send it via the appropriate client method.

        Args:
            client: The LubeLogger HTTP client.
            item: The queue item containing record_type and serialized payload.

        Raises:
            LubeLoggerUnreachableError: If LubeLogger is unreachable.
            LubeLoggerApiError: If the API returns a non-success response.
        """
        payload_data = json.loads(item.payload)

        if item.record_type == "gas":
            record = GasRecordPayload.model_validate(payload_data)
            await client.add_gas_record(item.vehicle_id, record)
        elif item.record_type == "service":
            record = ServiceRecordPayload.model_validate(payload_data)
            await client.add_service_record(item.vehicle_id, record)
        elif item.record_type == "odometer":
            record = OdometerRecordPayload.model_validate(payload_data)
            await client.add_odometer_record(item.vehicle_id, record)
        else:
            logger.error("Unknown record type in queue: %s", item.record_type)
