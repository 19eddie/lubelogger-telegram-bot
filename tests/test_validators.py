"""Tests for Pydantic validation models."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel


class TestGasRecordModel:
    """Tests for GasRecordModel validation."""

    def test_valid_gas_record(self) -> None:
        record = GasRecordModel(odometer=45000, liters=42.5, cost=78.90)
        assert record.odometer == 45000
        assert record.liters == 42.5
        assert record.cost == 78.90
        assert record.is_fill_to_full is True
        assert record.missed_fuel_up is False

    def test_default_date_is_today(self) -> None:
        record = GasRecordModel(odometer=100, liters=10.0, cost=20.0)
        assert record.date == date.today().isoformat()

    def test_custom_date(self) -> None:
        record = GasRecordModel(odometer=100, liters=10.0, cost=20.0, date="2024-01-15")
        assert record.date == "2024-01-15"

    def test_rejects_zero_odometer(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            GasRecordModel(odometer=0, liters=10.0, cost=20.0)
        assert "odometer" in str(exc_info.value)

    def test_rejects_negative_odometer(self) -> None:
        with pytest.raises(ValidationError):
            GasRecordModel(odometer=-1, liters=10.0, cost=20.0)

    def test_rejects_zero_liters(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            GasRecordModel(odometer=100, liters=0, cost=20.0)
        assert "liters" in str(exc_info.value)

    def test_rejects_negative_liters(self) -> None:
        with pytest.raises(ValidationError):
            GasRecordModel(odometer=100, liters=-5.0, cost=20.0)

    def test_accepts_zero_cost(self) -> None:
        record = GasRecordModel(odometer=100, liters=10.0, cost=0)
        assert record.cost == 0.0

    def test_rejects_negative_cost(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            GasRecordModel(odometer=100, liters=10.0, cost=-1.0)
        assert "cost" in str(exc_info.value)

    def test_coerces_string_values(self) -> None:
        record = GasRecordModel(odometer="100", liters="42.5", cost="78.9")  # type: ignore[arg-type]
        assert record.odometer == 100
        assert record.liters == 42.5
        assert record.cost == 78.9


class TestServiceRecordModel:
    """Tests for ServiceRecordModel validation."""

    def test_valid_service_record(self) -> None:
        record = ServiceRecordModel(odometer=50000, description="Oil change", cost=45.0)
        assert record.odometer == 50000
        assert record.description == "Oil change"
        assert record.cost == 45.0

    def test_default_date_is_today(self) -> None:
        record = ServiceRecordModel(odometer=100, description="Test", cost=0)
        assert record.date == date.today().isoformat()

    def test_rejects_zero_odometer(self) -> None:
        with pytest.raises(ValidationError):
            ServiceRecordModel(odometer=0, description="Test", cost=0)

    def test_rejects_negative_cost(self) -> None:
        with pytest.raises(ValidationError):
            ServiceRecordModel(odometer=100, description="Test", cost=-1.0)

    def test_accepts_zero_cost(self) -> None:
        record = ServiceRecordModel(odometer=100, description="Test", cost=0)
        assert record.cost == 0.0

    def test_rejects_empty_description(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ServiceRecordModel(odometer=100, description="", cost=0)
        assert "description" in str(exc_info.value)

    def test_rejects_whitespace_only_description(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ServiceRecordModel(odometer=100, description="   ", cost=0)
        assert "description" in str(exc_info.value)

    def test_strips_description_whitespace(self) -> None:
        record = ServiceRecordModel(odometer=100, description="  Oil change  ", cost=0)
        assert record.description == "Oil change"


class TestOdometerRecordModel:
    """Tests for OdometerRecordModel validation."""

    def test_valid_odometer_record(self) -> None:
        record = OdometerRecordModel(odometer=75000)
        assert record.odometer == 75000

    def test_default_date_is_today(self) -> None:
        record = OdometerRecordModel(odometer=100)
        assert record.date == date.today().isoformat()

    def test_custom_date(self) -> None:
        record = OdometerRecordModel(odometer=100, date="2024-06-01")
        assert record.date == "2024-06-01"

    def test_rejects_zero_odometer(self) -> None:
        with pytest.raises(ValidationError):
            OdometerRecordModel(odometer=0)

    def test_rejects_negative_odometer(self) -> None:
        with pytest.raises(ValidationError):
            OdometerRecordModel(odometer=-100)

    def test_coerces_string_odometer(self) -> None:
        record = OdometerRecordModel(odometer="500")  # type: ignore[arg-type]
        assert record.odometer == 500
