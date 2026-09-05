"""Offline queue service backed by SQLite for resilient record submission."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from bot.exceptions import LubeLoggerApiError, LubeLoggerResponseError, LubeLoggerUnreachableError
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
    """Result of a queue flush operation.

    The ``sent_items`` and ``failed_items`` lists carry the queue items whose
    status changed during this flush, so callers can notify the submitting user.
    """

    sent: int
    failed: int
    remaining: int
    sent_items: list[QueueItem] = field(default_factory=list)
    failed_items: list[QueueItem] = field(default_factory=list)


class QueueService:
    """Manages an offline queue of records waiting to be sent to LubeLogger.

    Records are persisted in SQLite and processed in FIFO order. When LubeLogger
    is unreachable, processing stops. On API errors, retry count is incremented
    and items are marked failed after max_retries attempts.
    """

    def __init__(self, db_path: str, max_retries: int = 3) -> None:
        self._db_path = db_path
        self.max_retries = max_retries
        self._flush_lock = asyncio.Lock()

    async def enqueue(self, user_id: int, vehicle_id: int, record_type: str, payload: str) -> int:
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
                "SELECT * FROM queue WHERE status = 'pending' ORDER BY id ASC",
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

    async def _is_already_synced(self, client: LubeLoggerClient, item: QueueItem) -> bool:
        """Check whether a queued gas record already exists remotely."""
        if item.record_type != "gas":
            return False

        payload_data = json.loads(item.payload)
        payload = GasRecordPayload.model_validate(payload_data)
        return await client.gas_record_exists(item.vehicle_id, payload)

    async def flush(self, client: LubeLoggerClient) -> FlushResult:
        """Flush pending records with one in-process worker at a time."""
        async with self._flush_lock:
            return await self._flush_locked(client)

    async def _flush_locked(self, client: LubeLoggerClient) -> FlushResult:
        """Process pending records after acquiring the flush lock."""
        pending = await self.get_pending()
        sent_items: list[QueueItem] = []
        failed_items: list[QueueItem] = []
        for item in pending:
            try:
                if await self._is_already_synced(client, item):
                    await self.mark_sent(item.id)
                    sent_items.append(item)
                    continue
            except LubeLoggerUnreachableError:
                logger.warning("LubeLogger unreachable during queue reconciliation, stopping")
                break
            except LubeLoggerApiError as exc:
                logger.warning(
                    "Could not reconcile queue item %d before retry: status=%d",
                    item.id,
                    exc.status_code,
                )
                continue
            except LubeLoggerResponseError as exc:
                logger.warning(
                    "Could not reconcile queue item %d before retry: %s",
                    item.id,
                    exc.message,
                )
                continue
            except (ValidationError, ValueError) as exc:
                logger.error("Invalid queued payload for item %d: %s", item.id, exc)
                await self.mark_failed(item.id)
                failed_items.append(item)
                continue

            try:
                await self._send_item(client, item)
                await self.mark_sent(item.id)
                sent_items.append(item)
            except LubeLoggerUnreachableError:
                logger.warning("LubeLogger unreachable during flush, stopping")
                break
            except LubeLoggerApiError as exc:
                logger.warning("API error for queue item %d: %s", item.id, exc.message)
                new_count = await self.increment_retry(item.id)
                if new_count >= self.max_retries:
                    await self.mark_failed(item.id)
                    failed_items.append(item)
            except LubeLoggerResponseError as exc:
                logger.warning(
                    "Unknown response for queue item %d; leaving pending: %s",
                    item.id,
                    exc.message,
                )
            except (ValidationError, ValueError) as exc:
                logger.error("Invalid payload for queue item %d: %s", item.id, exc)
                await self.mark_failed(item.id)
                failed_items.append(item)
        sent, failed = len(sent_items), len(failed_items)
        return FlushResult(
            sent=sent,
            failed=failed,
            remaining=len(pending) - sent - failed,
            sent_items=sent_items,
            failed_items=failed_items,
        )

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
            raise ValueError(f"Unknown record type in queue: {item.record_type}")
