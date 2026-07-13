"""HTTP client for LubeLogger REST API."""

from __future__ import annotations

import logging

import httpx

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.models.responses import ApiResponse, Vehicle

logger = logging.getLogger(__name__)


class LubeLoggerClient:
    """Async HTTP client for LubeLogger API with shared connection pool."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 10) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request with unified error handling.

        Raises:
            LubeLoggerUnreachableError: On connection or timeout errors.
            LubeLoggerApiError: On non-2xx responses.
        """
        try:
            response = await self._client.request(method, path, params=params, json=json)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error("LubeLogger unreachable: %s", type(exc).__name__)
            raise LubeLoggerUnreachableError("Unable to connect to LubeLogger") from exc

        if not response.is_success:
            logger.error(
                "LubeLogger API error: status=%d path=%s",
                response.status_code,
                path,
            )
            raise LubeLoggerApiError(response.status_code, response.text)

        return response

    async def add_gas_record(self, vehicle_id: int, record: GasRecordPayload) -> ApiResponse:
        """Add a gas record for the given vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.
            record: The gas record payload to submit.

        Returns:
            The API response indicating success.
        """
        payload = record.model_dump(by_alias=True)
        logger.info("Gas record payload: %s", payload)
        response = await self._request(
            "POST",
            "/api/vehicle/gasrecords/add",
            params={"vehicleId": vehicle_id},
            json=payload,
        )
        return ApiResponse.model_validate(response.json())

    async def add_service_record(
        self, vehicle_id: int, record: ServiceRecordPayload
    ) -> ApiResponse:
        """Add a service record for the given vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.
            record: The service record payload to submit.

        Returns:
            The API response indicating success.
        """
        response = await self._request(
            "POST",
            "/api/vehicle/servicerecords/add",
            params={"vehicleId": vehicle_id},
            json=record.model_dump(by_alias=True, exclude_defaults=True),
        )
        return ApiResponse.model_validate(response.json())

    async def add_odometer_record(
        self, vehicle_id: int, record: OdometerRecordPayload
    ) -> ApiResponse:
        """Add an odometer record for the given vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.
            record: The odometer record payload to submit.

        Returns:
            The API response indicating success.
        """
        response = await self._request(
            "POST",
            "/api/vehicle/odometerrecords/add",
            params={"vehicleId": vehicle_id},
            json=record.model_dump(by_alias=True),
        )
        return ApiResponse.model_validate(response.json())

    async def get_vehicles(self) -> list[Vehicle]:
        """Fetch all vehicles from LubeLogger.

        Returns:
            A list of Vehicle objects.
        """
        response = await self._request("GET", "/api/vehicles")
        return [Vehicle.model_validate(v) for v in response.json()]

    async def get_latest_odometer(self, vehicle_id: int) -> dict[str, str] | None:
        """Fetch the latest odometer record for a vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The latest odometer record as a dict, or None if no records exist.
        """
        response = await self._request(
            "GET",
            "/api/vehicle/odometerrecords",
            params={"vehicleId": vehicle_id},
        )
        records = response.json()
        if not records:
            return None
        return records[-1]

    async def get_latest_gas_record(self, vehicle_id: int) -> dict[str, str] | None:
        """Fetch the latest gas record for a vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The latest gas record as a dict, or None if no records exist.
        """
        response = await self._request(
            "GET",
            "/api/vehicle/gasrecords",
            params={"vehicleId": vehicle_id},
        )
        records = response.json()
        if not records:
            return None
        return records[-1]

    async def health_check(self) -> bool:
        """Check if LubeLogger is reachable.

        Returns:
            True if the API is reachable, False otherwise.
        """
        try:
            await self._request("GET", "/api/vehicles")
        except (LubeLoggerUnreachableError, LubeLoggerApiError):
            return False
        return True
