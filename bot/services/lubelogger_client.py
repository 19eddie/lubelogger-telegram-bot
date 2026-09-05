"""HTTP client for LubeLogger REST API."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

import httpx
from pydantic import ValidationError

from bot.exceptions import (
    LubeLoggerApiError,
    LubeLoggerResponseError,
    LubeLoggerUnreachableError,
)
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
    gas_payload_matches_record,
)
from bot.models.responses import ApiResponse, Vehicle

logger = logging.getLogger(__name__)

_MAX_ERROR_BODY_LENGTH = 2_000
_PRIVATE_TEXT_FIELDS = frozenset({"description", "notes", "tags"})
_SENSITIVE_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "password", "secret", "token", "x_api_key"}
)
_SENSITIVE_VALUE_RE = re.compile(
    r'(?i)(["\']?(?:x-api-key|api[_-]?key|authorization|token|password|secret)'
    r'["\']?\s*[:=]\s*["\']?)[^,"\'}\s]+'
)


def _is_sensitive_key(key: str) -> bool:
    """Return whether a mapping key may contain a credential."""
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS


def _sanitize_params(
    params: dict[str, str | int] | None,
) -> dict[str, str | int] | None:
    """Redact credential-like query parameters before logging."""
    if params is None:
        return None
    return {key: "[REDACTED]" if _is_sensitive_key(key) else value for key, value in params.items()}


def _sanitize_payload(payload: dict[str, str] | None) -> dict[str, str] | None:
    """Keep diagnostic payload fields while omitting free-text and credential fields."""
    if payload is None:
        return None
    return {
        key: "[OMITTED]" if key.lower() in _PRIVATE_TEXT_FIELDS or _is_sensitive_key(key) else value
        for key, value in payload.items()
    }


def _sanitize_response_body(body: str, api_key: str) -> str:
    """Redact credentials and cap an API error body before logging or raising."""
    sanitized = body.replace(api_key, "[REDACTED]") if api_key else body
    sanitized = _SENSITIVE_VALUE_RE.sub(r"\1[REDACTED]", sanitized)
    if len(sanitized) > _MAX_ERROR_BODY_LENGTH:
        sanitized = sanitized[:_MAX_ERROR_BODY_LENGTH] + "...[truncated]"
    return sanitized or "<empty>"


def _decode_api_response(response: httpx.Response) -> ApiResponse:
    """Decode a successful write response or classify it as unknown state."""
    try:
        data = response.json()
        return ApiResponse.model_validate(data)
    except (ValueError, TypeError, ValidationError) as exc:
        logger.error("Invalid LubeLogger write response: error=%s", type(exc).__name__)
        raise LubeLoggerResponseError("LubeLogger returned an invalid write response") from exc


def _decode_record_list(response: httpx.Response, path: str) -> list[dict[str, object]]:
    """Decode a list response and reject malformed remote data safely."""
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        logger.error(
            "Invalid LubeLogger record response: path=%s error=%s",
            path,
            type(exc).__name__,
        )
        raise LubeLoggerResponseError("LubeLogger returned invalid record data") from exc

    if not isinstance(data, list) or any(not isinstance(record, Mapping) for record in data):
        logger.error("Invalid LubeLogger record response shape: path=%s", path)
        raise LubeLoggerResponseError("LubeLogger returned invalid record data")
    return [dict(record) for record in data]


class LubeLoggerClient:
    """Async HTTP client for LubeLogger API with shared connection pool."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 10,
        *,
        username: str = "",
        password: str = "",
    ) -> None:
        if bool(username) != bool(password):
            raise ValueError("username and password must be set together")

        headers: dict[str, str] = {"culture-invariant": "true"}
        auth: httpx.BasicAuth | None = None
        if username and password:
            auth = httpx.BasicAuth(username, password)
        elif api_key:
            headers["x-api-key"] = api_key
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            auth=auth,
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
        safe_params = _sanitize_params(params)
        safe_payload = _sanitize_payload(json)
        try:
            response = await self._client.request(method, path, params=params, json=json)
        except httpx.RequestError as exc:
            logger.error(
                "LubeLogger unreachable: method=%s path=%s params=%s error=%s",
                method,
                path,
                safe_params,
                type(exc).__name__,
            )
            raise LubeLoggerUnreachableError("Unable to connect to LubeLogger") from exc

        if not response.is_success:
            error_body = _sanitize_response_body(response.text, self._api_key)
            logger.error(
                "LubeLogger API error: status=%d method=%s path=%s params=%s "
                "payload=%s response_body=%s",
                response.status_code,
                method,
                path,
                safe_params,
                safe_payload,
                error_body,
            )
            raise LubeLoggerApiError(response.status_code, error_body)

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
        return _decode_api_response(response)

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
        return _decode_api_response(response)

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
        return _decode_api_response(response)

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

    async def get_gas_records(self, vehicle_id: int) -> list[dict[str, object]]:
        """Fetch all gas records for a vehicle for reconciliation and display."""
        path = "/api/vehicle/gasrecords"
        response = await self._request("GET", path, params={"vehicleId": vehicle_id})
        return _decode_record_list(response, path)

    async def get_latest_gas_record(self, vehicle_id: int) -> dict[str, object] | None:
        """Fetch the latest gas record for a vehicle."""
        records = await self.get_gas_records(vehicle_id)
        return records[-1] if records else None

    async def gas_record_exists(self, vehicle_id: int, payload: GasRecordPayload) -> bool:
        """Check whether any remote gas record matches the payload fingerprint."""
        records = await self.get_gas_records(vehicle_id)
        return any(gas_payload_matches_record(payload, record) for record in records)

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
