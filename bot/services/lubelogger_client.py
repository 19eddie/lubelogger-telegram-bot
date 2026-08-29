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
from bot.models.records import (
    GasRecord,
    OdometerRecord,
    ServiceRecord,
    VehicleSnapshot,
)
from bot.models.responses import ApiResponse, Vehicle

logger = logging.getLogger(__name__)

VEHICLES_PATH = "/api/vehicles"
VEHICLE_INFO_PATH = "/api/vehicle/info"
GAS_RECORDS_PATH = "/api/vehicle/gasrecords"
SERVICE_RECORDS_PATH = "/api/vehicle/servicerecords"
ODOMETER_RECORDS_PATH = "/api/vehicle/odometerrecords"

#: Keys under which `/api/vehicle/info` may nest the vehicle object.
_VEHICLE_KEYS = ("vehicleData", "vehicle")


class LubeLoggerClient:
    """Async HTTP client for LubeLogger API with shared connection pool."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 10) -> None:
        # `culture-invariant` makes a modern instance answer with ISO dates and
        # JSON numbers / booleans instead of culture-formatted strings (design
        # finding F5). Older instances ignore the header, which is why the read
        # models keep parsing loosely (NF-6.1).
        headers: dict[str, str] = {"culture-invariant": "true"}
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
        response = await self._request(
            "POST",
            "/api/vehicle/gasrecords/add",
            params={"vehicleId": vehicle_id},
            json=record.model_dump(by_alias=True),
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
            json=record.model_dump(by_alias=True),
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
        response = await self._request("GET", VEHICLES_PATH)
        return [Vehicle.model_validate(v) for v in response.json()]

    async def get_vehicle_snapshots(self) -> list[VehicleSnapshot]:
        """Fetch every vehicle together with its last reported odometer.

        `/api/vehicle/info` reports, per vehicle, the maximum odometer across
        record types in a single call (design finding F6). An instance too old
        to expose it answers with an API error; in that case exactly one retry
        is issued against `/api/vehicles`, and those snapshots carry no
        odometer at all.

        Returns:
            One snapshot per vehicle. `last_reported_odometer` is `None`
            whenever the fallback was used or the value was absent.
        """
        try:
            response = await self._request("GET", VEHICLE_INFO_PATH)
        except LubeLoggerApiError:
            logger.info("vehicle info endpoint unavailable, falling back to the vehicle list")
            vehicles = await self.get_vehicles()
            return [
                VehicleSnapshot(vehicle=vehicle, last_reported_odometer=None)
                for vehicle in vehicles
            ]
        return [_snapshot_from_entry(entry) for entry in response.json()]

    async def get_gas_records(self, vehicle_id: int) -> list[GasRecord]:
        """Fetch every gas record of a vehicle.

        `useMPG` / `useUKMPG` are deliberately never sent, so the reported
        `fuelEconomy` stays volume per 100 distance units (finding F3).

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The gas records in the order the API returned them, which is sorted
            by date then odometer (finding F7).
        """
        response = await self._request(
            "GET",
            GAS_RECORDS_PATH,
            params={"vehicleId": vehicle_id},
        )
        return [GasRecord.model_validate(record) for record in response.json()]

    async def get_service_records(self, vehicle_id: int) -> list[ServiceRecord]:
        """Fetch every service record of a vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The service records in the order the API returned them.
        """
        response = await self._request(
            "GET",
            SERVICE_RECORDS_PATH,
            params={"vehicleId": vehicle_id},
        )
        return [ServiceRecord.model_validate(record) for record in response.json()]

    async def get_odometer_records(self, vehicle_id: int) -> list[OdometerRecord]:
        """Fetch every odometer record of a vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The odometer records in the order the API returned them; this
            endpoint applies no explicit ordering (finding F7), so callers fold
            the values instead of trusting the last one.
        """
        response = await self._request(
            "GET",
            ODOMETER_RECORDS_PATH,
            params={"vehicleId": vehicle_id},
        )
        return [OdometerRecord.model_validate(record) for record in response.json()]

    async def get_latest_odometer(self, vehicle_id: int) -> dict[str, str] | None:
        """Fetch the latest odometer record for a vehicle.

        Args:
            vehicle_id: The LubeLogger vehicle ID.

        Returns:
            The latest odometer record as a dict, or None if no records exist.
        """
        response = await self._request(
            "GET",
            ODOMETER_RECORDS_PATH,
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
            GAS_RECORDS_PATH,
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
            await self._request("GET", VEHICLES_PATH)
        except (LubeLoggerUnreachableError, LubeLoggerApiError):
            return False
        return True


def _snapshot_from_entry(entry: object) -> VehicleSnapshot:
    """Build a snapshot from one `/api/vehicle/info` entry.

    The vehicle object may be nested under `vehicleData` or be the entry
    itself, depending on the instance version, so both shapes are accepted
    (NF-6.1).

    Raises:
        LubeLoggerApiError: When the entry is not a JSON object.
    """
    if not isinstance(entry, dict):
        raise LubeLoggerApiError(200, "unexpected vehicle info payload")

    vehicle_data: dict[str, object] = entry
    for key in _VEHICLE_KEYS:
        nested = entry.get(key)
        if isinstance(nested, dict):
            vehicle_data = nested
            break

    return VehicleSnapshot(
        vehicle=Vehicle.model_validate(vehicle_data),
        last_reported_odometer=entry.get("lastReportedOdometer"),
    )
