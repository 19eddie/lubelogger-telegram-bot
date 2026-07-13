"""Tests for the LubeLogger HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.services.lubelogger_client import LubeLoggerClient


@pytest.fixture
def client() -> LubeLoggerClient:
    """Create a LubeLoggerClient instance for testing."""
    return LubeLoggerClient(
        base_url="http://localhost:8080",
        api_key="test-secret-key-12345",
        timeout=5,
    )


@pytest.fixture
def gas_payload() -> GasRecordPayload:
    """Create a sample gas record payload."""
    return GasRecordPayload(
        date="2024-01-15",
        odometer="45000",
        fuel_consumed="42.5",
        cost="78.90",
        is_fill_to_full="true",
        missed_fuel_up="false",
    )


@pytest.fixture
def service_payload() -> ServiceRecordPayload:
    """Create a sample service record payload."""
    return ServiceRecordPayload(
        date="2024-01-15",
        odometer="45000",
        description="Oil change",
        cost="120.00",
    )


@pytest.fixture
def odometer_payload() -> OdometerRecordPayload:
    """Create a sample odometer record payload."""
    return OdometerRecordPayload(
        date="2024-01-15",
        odometer="45000",
    )


class TestClientHeaders:
    """Tests that the client sends the correct API key header."""

    def test_client_sets_api_key_header(self, client: LubeLoggerClient) -> None:
        """The client should include x-api-key in the shared httpx client headers."""
        assert client._client.headers["x-api-key"] == "test-secret-key-12345"

    def test_client_sets_base_url(self, client: LubeLoggerClient) -> None:
        """The client should configure the base URL."""
        assert str(client._client.base_url) == "http://localhost:8080"

    def test_client_sets_timeout(self, client: LubeLoggerClient) -> None:
        """The client should configure the timeout."""
        assert client._client.timeout.connect == 5


class TestConnectionErrors:
    """Tests that connection errors raise LubeLoggerUnreachableError."""

    async def test_connect_error_raises_unreachable(self, client: LubeLoggerClient) -> None:
        """ConnectError should be wrapped in LubeLoggerUnreachableError."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")
            with pytest.raises(LubeLoggerUnreachableError):
                await client.get_vehicles()

    async def test_timeout_error_raises_unreachable(self, client: LubeLoggerClient) -> None:
        """TimeoutException should be wrapped in LubeLoggerUnreachableError."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Request timed out")
            with pytest.raises(LubeLoggerUnreachableError):
                await client.get_vehicles()


class TestApiErrors:
    """Tests that non-success HTTP responses raise LubeLoggerApiError."""

    async def test_non_success_raises_api_error(self, client: LubeLoggerClient) -> None:
        """Non-2xx response should raise LubeLoggerApiError with status code."""
        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            with pytest.raises(LubeLoggerApiError) as exc_info:
                await client.get_vehicles()
            assert exc_info.value.status_code == 500

    async def test_404_raises_api_error(self, client: LubeLoggerClient) -> None:
        """404 response should raise LubeLoggerApiError."""
        mock_response = httpx.Response(
            status_code=404,
            text="Not Found",
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            with pytest.raises(LubeLoggerApiError) as exc_info:
                await client.get_vehicles()
            assert exc_info.value.status_code == 404


class TestApiKeyNonLeakage:
    """Tests that the API key never appears in error messages."""

    async def test_api_key_not_in_unreachable_error(self, client: LubeLoggerClient) -> None:
        """API key must not appear in LubeLoggerUnreachableError message."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")
            with pytest.raises(LubeLoggerUnreachableError) as exc_info:
                await client.get_vehicles()
            assert "test-secret-key-12345" not in str(exc_info.value)

    async def test_api_key_not_in_api_error(self, client: LubeLoggerClient) -> None:
        """API key must not appear in LubeLoggerApiError message."""
        mock_response = httpx.Response(
            status_code=401,
            text="Unauthorized",
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            with pytest.raises(LubeLoggerApiError) as exc_info:
                await client.get_vehicles()
            assert "test-secret-key-12345" not in str(exc_info.value)


class TestAddGasRecord:
    """Tests for the add_gas_record method."""

    async def test_add_gas_record_success(
        self, client: LubeLoggerClient, gas_payload: GasRecordPayload
    ) -> None:
        """Successful gas record submission returns ApiResponse."""
        mock_response = httpx.Response(
            status_code=200,
            json={"success": True, "message": "Gas Record Added"},
            request=httpx.Request("POST", "http://localhost:8080/api/vehicle/gasrecords/add"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.add_gas_record(1, gas_payload)
            assert result.success is True
            assert result.message == "Gas Record Added"
            # Verify correct endpoint and params
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert call_args[0][1] == "/api/vehicle/gasrecords/add"
            assert call_args[1]["params"] == {"vehicleId": 1}


class TestAddServiceRecord:
    """Tests for the add_service_record method."""

    async def test_add_service_record_success(
        self, client: LubeLoggerClient, service_payload: ServiceRecordPayload
    ) -> None:
        """Successful service record submission returns ApiResponse."""
        mock_response = httpx.Response(
            status_code=200,
            json={"success": True, "message": "Service Record Added"},
            request=httpx.Request("POST", "http://localhost:8080/api/vehicle/servicerecords/add"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.add_service_record(1, service_payload)
            assert result.success is True
            assert result.message == "Service Record Added"
            call_args = mock_request.call_args
            assert call_args[0][1] == "/api/vehicle/servicerecords/add"


class TestAddOdometerRecord:
    """Tests for the add_odometer_record method."""

    async def test_add_odometer_record_success(
        self, client: LubeLoggerClient, odometer_payload: OdometerRecordPayload
    ) -> None:
        """Successful odometer record submission returns ApiResponse."""
        mock_response = httpx.Response(
            status_code=200,
            json={"success": True, "message": "Odometer Record Added"},
            request=httpx.Request("POST", "http://localhost:8080/api/vehicle/odometerrecords/add"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.add_odometer_record(1, odometer_payload)
            assert result.success is True
            assert result.message == "Odometer Record Added"
            call_args = mock_request.call_args
            assert call_args[0][1] == "/api/vehicle/odometerrecords/add"


class TestGetVehicles:
    """Tests for the get_vehicles method."""

    async def test_get_vehicles_returns_list(self, client: LubeLoggerClient) -> None:
        """get_vehicles returns a list of Vehicle objects."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {
                    "id": 1,
                    "year": 2020,
                    "make": "Toyota",
                    "model": "Yaris",
                    "licensePlate": "AB123",
                },
                {
                    "id": 2,
                    "year": 2018,
                    "make": "Fiat",
                    "model": "Punto",
                    "licensePlate": "CD456",
                },
            ],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            vehicles = await client.get_vehicles()
            assert len(vehicles) == 2
            assert vehicles[0].id == 1
            assert vehicles[0].make == "Toyota"
            assert vehicles[1].id == 2
            assert vehicles[1].make == "Fiat"

    async def test_get_vehicles_empty(self, client: LubeLoggerClient) -> None:
        """get_vehicles returns empty list when no vehicles exist."""
        mock_response = httpx.Response(
            status_code=200,
            json=[],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            vehicles = await client.get_vehicles()
            assert vehicles == []


class TestGetLatestOdometer:
    """Tests for the get_latest_odometer method."""

    async def test_get_latest_odometer_returns_last(self, client: LubeLoggerClient) -> None:
        """get_latest_odometer returns the last record from the list."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {"date": "2024-01-10", "odometer": "44000"},
                {"date": "2024-01-15", "odometer": "45000"},
            ],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicle/odometerrecords"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.get_latest_odometer(1)
            assert result == {"date": "2024-01-15", "odometer": "45000"}

    async def test_get_latest_odometer_returns_none_when_empty(
        self, client: LubeLoggerClient
    ) -> None:
        """get_latest_odometer returns None when no records exist."""
        mock_response = httpx.Response(
            status_code=200,
            json=[],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicle/odometerrecords"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.get_latest_odometer(1)
            assert result is None


class TestGetLatestGasRecord:
    """Tests for the get_latest_gas_record method."""

    async def test_get_latest_gas_record_returns_last(self, client: LubeLoggerClient) -> None:
        """get_latest_gas_record returns the last record from the list."""
        mock_response = httpx.Response(
            status_code=200,
            json=[
                {"date": "2024-01-10", "odometer": "44000", "fuelConsumed": "40"},
                {"date": "2024-01-15", "odometer": "45000", "fuelConsumed": "42.5"},
            ],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicle/gasrecords"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.get_latest_gas_record(1)
            assert result == {"date": "2024-01-15", "odometer": "45000", "fuelConsumed": "42.5"}

    async def test_get_latest_gas_record_returns_none_when_empty(
        self, client: LubeLoggerClient
    ) -> None:
        """get_latest_gas_record returns None when no records exist."""
        mock_response = httpx.Response(
            status_code=200,
            json=[],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicle/gasrecords"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.get_latest_gas_record(1)
            assert result is None


class TestHealthCheck:
    """Tests for the health_check method."""

    async def test_health_check_returns_true_on_success(self, client: LubeLoggerClient) -> None:
        """health_check returns True when API is reachable."""
        mock_response = httpx.Response(
            status_code=200,
            json=[],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            assert await client.health_check() is True

    async def test_health_check_returns_false_on_connection_error(
        self, client: LubeLoggerClient
    ) -> None:
        """health_check returns False when API is unreachable."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")
            assert await client.health_check() is False

    async def test_health_check_returns_false_on_api_error(self, client: LubeLoggerClient) -> None:
        """health_check returns False when API returns error."""
        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            assert await client.health_check() is False
