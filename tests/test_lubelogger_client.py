"""Tests for the LubeLogger HTTP client."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.services.lubelogger_client import (
    GAS_RECORDS_PATH,
    ODOMETER_RECORDS_PATH,
    SERVICE_RECORDS_PATH,
    VEHICLE_INFO_PATH,
    VEHICLES_PATH,
    LubeLoggerClient,
)


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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")
            with pytest.raises(LubeLoggerUnreachableError):
                await client.get_vehicles()

    async def test_timeout_error_raises_unreachable(self, client: LubeLoggerClient) -> None:
        """TimeoutException should be wrapped in LubeLoggerUnreachableError."""
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            with pytest.raises(LubeLoggerApiError) as exc_info:
                await client.get_vehicles()
            assert exc_info.value.status_code == 404


class TestApiKeyNonLeakage:
    """Tests that the API key never appears in error messages."""

    async def test_api_key_not_in_unreachable_error(self, client: LubeLoggerClient) -> None:
        """API key must not appear in LubeLoggerUnreachableError message."""
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "POST", "http://localhost:8080/api/vehicle/gasrecords/add"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "POST", "http://localhost:8080/api/vehicle/servicerecords/add"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "POST", "http://localhost:8080/api/vehicle/odometerrecords/add"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
                    "id": 1, "year": 2020, "make": "Toyota",
                    "model": "Yaris", "licensePlate": "AB123",
                },
                {
                    "id": 2, "year": 2018, "make": "Fiat",
                    "model": "Punto", "licensePlate": "CD456",
                },
            ],
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "GET", "http://localhost:8080/api/vehicle/odometerrecords"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "GET", "http://localhost:8080/api/vehicle/odometerrecords"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "GET", "http://localhost:8080/api/vehicle/gasrecords"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
            request=httpx.Request(
                "GET", "http://localhost:8080/api/vehicle/gasrecords"
            ),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
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
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            assert await client.health_check() is True

    async def test_health_check_returns_false_on_connection_error(
        self, client: LubeLoggerClient
    ) -> None:
        """health_check returns False when API is unreachable."""
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")
            assert await client.health_check() is False

    async def test_health_check_returns_false_on_api_error(
        self, client: LubeLoggerClient
    ) -> None:
        """health_check returns False when API returns error."""
        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
        )
        with patch.object(
            client._client, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            assert await client.health_check() is False


# ---------------------------------------------------------------------------
# Task 3.4 client extensions: invariant header, snapshots, record readers
# ---------------------------------------------------------------------------


def _install_transport(
    client: LubeLoggerClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """Route the client through a mock transport, recording every request.

    The client's own `httpx.AsyncClient` is kept, so default headers and
    parameter handling are exercised exactly as in production.
    """
    recorded: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    client._client._transport = httpx.MockTransport(recording_handler)
    return recorded


def _json_handler(routes: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler answering 200 with JSON per path, 404 for unknown paths."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, text="Not Found")

    return handler


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    """Simulate an instance that cannot be reached at all."""
    raise httpx.ConnectError("Connection refused", request=request)


VEHICLE_ONE = {
    "id": 1,
    "year": 2020,
    "make": "Toyota",
    "model": "Yaris",
    "licensePlate": "AB123",
}
VEHICLE_TWO = {
    "id": 2,
    "year": 2018,
    "make": "Fiat",
    "model": "Punto",
    "licensePlate": "CD456",
}


class TestInvariantHeader:
    """The `culture-invariant` header is a client-wide invariant (finding F5)."""

    def test_invariant_header_in_default_headers(self, client: LubeLoggerClient) -> None:
        """The shared httpx client carries the invariant header."""
        assert client._client.headers["culture-invariant"] == "true"

    def test_invariant_header_set_without_api_key(self) -> None:
        """The header is present even when no API key is configured."""
        anonymous = LubeLoggerClient(base_url="http://localhost:8080", api_key="")
        assert anonymous._client.headers["culture-invariant"] == "true"
        assert "x-api-key" not in anonymous._client.headers

    async def test_invariant_header_present_on_every_request(
        self, client: LubeLoggerClient, gas_payload: GasRecordPayload
    ) -> None:
        """Every request the client issues carries the invariant header."""
        recorded = _install_transport(
            client,
            _json_handler(
                {
                    VEHICLES_PATH: [],
                    VEHICLE_INFO_PATH: [],
                    GAS_RECORDS_PATH: [],
                    SERVICE_RECORDS_PATH: [],
                    ODOMETER_RECORDS_PATH: [],
                    "/api/vehicle/gasrecords/add": {"success": True, "message": "ok"},
                }
            ),
        )

        await client.get_vehicles()
        await client.get_vehicle_snapshots()
        await client.get_gas_records(1)
        await client.get_service_records(1)
        await client.get_odometer_records(1)
        await client.get_latest_gas_record(1)
        await client.get_latest_odometer(1)
        await client.add_gas_record(1, gas_payload)

        assert len(recorded) == 8
        assert all(request.headers["culture-invariant"] == "true" for request in recorded)


class TestGetVehicleSnapshots:
    """Tests for `get_vehicle_snapshots` and its single fallback."""

    async def test_snapshots_parse_odometer(self, client: LubeLoggerClient) -> None:
        """`lastReportedOdometer` is parsed, from a flat or a nested entry."""
        recorded = _install_transport(
            client,
            _json_handler(
                {
                    VEHICLE_INFO_PATH: [
                        {**VEHICLE_ONE, "lastReportedOdometer": 45000},
                        {"vehicleData": VEHICLE_TWO, "lastReportedOdometer": "12.345,0"},
                        {
                            "id": 3,
                            "year": 2015,
                            "make": "Opel",
                            "model": "Corsa",
                            "licensePlate": "EF789",
                        },
                    ]
                }
            ),
        )

        snapshots = await client.get_vehicle_snapshots()

        assert [request.url.path for request in recorded] == [VEHICLE_INFO_PATH]
        assert [snapshot.vehicle.id for snapshot in snapshots] == [1, 2, 3]
        assert snapshots[0].last_reported_odometer == 45000
        # A culture-formatted value still reads as an integer (NF-6.1).
        assert snapshots[1].last_reported_odometer == 12345
        assert snapshots[1].vehicle.make == "Fiat"
        assert snapshots[2].last_reported_odometer is None

    async def test_info_error_falls_back_once(self, client: LubeLoggerClient) -> None:
        """A 404 on the info endpoint triggers exactly one retry on /api/vehicles."""
        recorded = _install_transport(client, _json_handler({VEHICLES_PATH: [VEHICLE_ONE]}))

        snapshots = await client.get_vehicle_snapshots()

        assert [request.url.path for request in recorded] == [VEHICLE_INFO_PATH, VEHICLES_PATH]
        assert len(snapshots) == 1
        assert snapshots[0].vehicle.id == 1
        assert snapshots[0].last_reported_odometer is None

    async def test_fallback_failure_raises(self, client: LubeLoggerClient) -> None:
        """When the fallback also fails, the error surfaces after two requests."""
        recorded = _install_transport(client, lambda request: httpx.Response(500, text="boom"))

        with pytest.raises(LubeLoggerApiError):
            await client.get_vehicle_snapshots()

        assert [request.url.path for request in recorded] == [VEHICLE_INFO_PATH, VEHICLES_PATH]

    async def test_unreachable_does_not_fall_back(self, client: LubeLoggerClient) -> None:
        """A transport failure is not an API error, so no retry is issued."""
        recorded = _install_transport(client, _unreachable_handler)

        with pytest.raises(LubeLoggerUnreachableError):
            await client.get_vehicle_snapshots()

        assert [request.url.path for request in recorded] == [VEHICLE_INFO_PATH]

    async def test_non_object_entry_raises(self, client: LubeLoggerClient) -> None:
        """An entry that is not a JSON object is reported as an API error."""
        _install_transport(client, _json_handler({VEHICLE_INFO_PATH: ["not-an-object"]}))

        with pytest.raises(LubeLoggerApiError):
            await client.get_vehicle_snapshots()


class TestRecordReaders:
    """Tests for the typed record readers added in task 3.4."""

    async def test_gas_records_parse_loose_values(self, client: LubeLoggerClient) -> None:
        """Gas records parse both invariant and culture-formatted payloads."""
        _install_transport(
            client,
            _json_handler(
                {
                    GAS_RECORDS_PATH: [
                        {
                            "date": "2024-01-10",
                            "odometer": "44000",
                            "fuelConsumed": "40.00",
                            "cost": "70.00",
                            "fuelEconomy": "6.50",
                            "isFillToFull": "True",
                            "missedFuelUp": "False",
                            "unknownFutureField": 1,
                        },
                        {
                            "date": "15/01/2024",
                            "odometer": 45000,
                            "fuelConsumed": "42,5",
                            "cost": "78,90",
                            "fuelEconomy": 0,
                            "isFillToFull": True,
                            "missedFuelUp": False,
                        },
                    ]
                }
            ),
        )

        records = await client.get_gas_records(1)

        assert len(records) == 2
        assert records[0].odometer == 44000
        assert records[0].fuel_economy == Decimal("6.50")
        assert records[0].is_fill_to_full is True
        assert records[0].missed_fuel_up is False
        assert records[1].date == dt.date(2024, 1, 15)
        assert records[1].fuel_consumed == Decimal("42.5")
        assert records[1].cost == Decimal("78.90")
        assert records[1].fuel_economy == Decimal("0")

    async def test_readers_send_only_vehicle_id(self, client: LubeLoggerClient) -> None:
        """No unit-conversion parameter is ever sent (finding F3)."""
        recorded = _install_transport(
            client,
            _json_handler(
                {
                    GAS_RECORDS_PATH: [],
                    SERVICE_RECORDS_PATH: [],
                    ODOMETER_RECORDS_PATH: [],
                }
            ),
        )

        await client.get_gas_records(3)
        await client.get_service_records(3)
        await client.get_odometer_records(3)
        await client.get_latest_gas_record(3)
        await client.get_latest_odometer(3)

        assert len(recorded) == 5
        for request in recorded:
            assert dict(request.url.params) == {"vehicleId": "3"}
            assert "useMPG" not in request.url.query.decode()
            assert "useUKMPG" not in request.url.query.decode()

    async def test_service_records_parse(self, client: LubeLoggerClient) -> None:
        """Service records parse description and cost."""
        _install_transport(
            client,
            _json_handler(
                {
                    SERVICE_RECORDS_PATH: [
                        {
                            "date": "2024-01-15",
                            "odometer": 45000,
                            "description": "Oil change <5000km",
                            "cost": "120,00",
                        }
                    ]
                }
            ),
        )

        records = await client.get_service_records(1)

        assert len(records) == 1
        assert records[0].description == "Oil change <5000km"
        assert records[0].cost == Decimal("120.00")

    async def test_odometer_records_parse(self, client: LubeLoggerClient) -> None:
        """Odometer records parse the odometer and the initial odometer."""
        _install_transport(
            client,
            _json_handler(
                {
                    ODOMETER_RECORDS_PATH: [
                        {"date": "2024-01-15", "odometer": 45000, "initialOdometer": 44000},
                        {"date": "10/01/2024", "odometer": "44000"},
                    ]
                }
            ),
        )

        records = await client.get_odometer_records(1)

        assert [record.odometer for record in records] == [45000, 44000]
        assert records[0].initial_odometer == 44000
        assert records[1].date == dt.date(2024, 1, 10)
        assert records[1].initial_odometer is None


class TestApiKeyNeverLogged:
    """The API key stays out of logs and errors on the new code paths (NF-4.3)."""

    async def test_api_key_absent_on_fallback_failure(
        self, client: LubeLoggerClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The snapshot fallback logs status and path only, never the key."""
        _install_transport(client, lambda request: httpx.Response(500, text="boom"))

        with caplog.at_level(logging.DEBUG, logger="bot"):
            with pytest.raises(LubeLoggerApiError) as exc_info:
                await client.get_vehicle_snapshots()

        assert "test-secret-key-12345" not in str(exc_info.value)
        assert caplog.records
        for record in caplog.records:
            assert "test-secret-key-12345" not in record.getMessage()

    async def test_api_key_absent_when_unreachable(
        self, client: LubeLoggerClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unreachable instance logs the exception type only."""
        _install_transport(client, _unreachable_handler)

        with caplog.at_level(logging.DEBUG, logger="bot"):
            with pytest.raises(LubeLoggerUnreachableError) as exc_info:
                await client.get_gas_records(1)

        assert "test-secret-key-12345" not in str(exc_info.value)
        for record in caplog.records:
            assert "test-secret-key-12345" not in record.getMessage()
