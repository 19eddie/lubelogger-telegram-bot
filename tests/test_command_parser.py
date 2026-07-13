"""Tests for the CommandParser service."""

from __future__ import annotations

import pytest

from bot.exceptions import ParseError
from bot.models.inputs import FuelInput, OdometerInput, ServiceInput
from bot.services.command_parser import CommandParser


class TestNormalizeDecimal:
    """Tests for decimal normalization."""

    def test_comma_replaced_with_dot(self) -> None:
        assert CommandParser.normalize_decimal("45,2") == "45.2"

    def test_dot_unchanged(self) -> None:
        assert CommandParser.normalize_decimal("45.2") == "45.2"

    def test_integer_unchanged(self) -> None:
        assert CommandParser.normalize_decimal("100") == "100"

    def test_multiple_commas(self) -> None:
        assert CommandParser.normalize_decimal("1,000,5") == "1.000.5"


class TestParseFuel:
    """Tests for fuel command parsing."""

    def test_basic_parsing(self) -> None:
        result = CommandParser.parse_fuel("45000 42.5 78.90")
        assert result == FuelInput(odometer="45000", liters="42.5", cost="78.90")

    def test_comma_decimal(self) -> None:
        result = CommandParser.parse_fuel("45000 42,5 78,90")
        assert result == FuelInput(odometer="45000", liters="42.5", cost="78.90")

    def test_mixed_separators(self) -> None:
        result = CommandParser.parse_fuel("45000 42.5 78,90")
        assert result == FuelInput(odometer="45000", liters="42.5", cost="78.90")

    def test_too_few_arguments(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            CommandParser.parse_fuel("45000 42.5")
        assert exc_info.value.command == "/fuel"

    def test_too_many_arguments(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            CommandParser.parse_fuel("45000 42.5 78.90 extra")
        assert exc_info.value.command == "/fuel"

    def test_non_numeric_value(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            CommandParser.parse_fuel("45000 abc 78.90")
        assert exc_info.value.command == "/fuel"

    def test_empty_string(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_fuel("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_fuel("   ")


class TestParseService:
    """Tests for service command parsing."""

    def test_quoted_description(self) -> None:
        result = CommandParser.parse_service('50000 "Oil change" 45,50')
        assert result == ServiceInput(odometer="50000", description="Oil change", cost="45.50")

    def test_unquoted_single_word(self) -> None:
        result = CommandParser.parse_service("50000 Brakes 120.00")
        assert result == ServiceInput(odometer="50000", description="Brakes", cost="120.00")

    def test_comma_decimal_cost(self) -> None:
        result = CommandParser.parse_service('50000 "Tire rotation" 30,00')
        assert result == ServiceInput(odometer="50000", description="Tire rotation", cost="30.00")

    def test_empty_string(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            CommandParser.parse_service("")
        assert exc_info.value.command == "/service"

    def test_too_few_arguments(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_service("50000")

    def test_non_numeric_odometer(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_service('abc "Oil change" 45.50')

    def test_non_numeric_cost(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_service('50000 "Oil change" abc')


class TestParseOdometer:
    """Tests for odometer command parsing."""

    def test_basic_parsing(self) -> None:
        result = CommandParser.parse_odometer("45000")
        assert result == OdometerInput(odometer="45000")

    def test_decimal_value(self) -> None:
        result = CommandParser.parse_odometer("45000.5")
        assert result == OdometerInput(odometer="45000.5")

    def test_comma_decimal(self) -> None:
        result = CommandParser.parse_odometer("45000,5")
        assert result == OdometerInput(odometer="45000.5")

    def test_empty_string(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            CommandParser.parse_odometer("")
        assert exc_info.value.command == "/km"

    def test_multiple_values(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_odometer("45000 50000")

    def test_non_numeric(self) -> None:
        with pytest.raises(ParseError):
            CommandParser.parse_odometer("abc")


class TestFormatFuel:
    """Tests for fuel formatting."""

    def test_basic_format(self) -> None:
        record = FuelInput(odometer="45000", liters="42.5", cost="78.9")
        assert CommandParser.format_fuel(record) == "45000 42.5 78.9"


class TestFormatService:
    """Tests for service formatting."""

    def test_basic_format(self) -> None:
        record = ServiceInput(odometer="50000", description="Oil change", cost="45.5")
        assert CommandParser.format_service(record) == '50000 "Oil change" 45.5'


class TestFormatOdometer:
    """Tests for odometer formatting."""

    def test_basic_format(self) -> None:
        record = OdometerInput(odometer="45000")
        assert CommandParser.format_odometer(record) == "45000"


class TestRoundTrip:
    """Tests for parse → format → parse round-trip."""

    def test_fuel_round_trip(self) -> None:
        original = FuelInput(odometer="45000", liters="42.5", cost="78.9")
        formatted = CommandParser.format_fuel(original)
        parsed = CommandParser.parse_fuel(formatted)
        assert parsed.odometer == original.odometer
        assert parsed.liters == original.liters
        assert parsed.cost == original.cost

    def test_service_round_trip(self) -> None:
        original = ServiceInput(odometer="50000", description="Oil change", cost="45.5")
        formatted = CommandParser.format_service(original)
        parsed = CommandParser.parse_service(formatted)
        assert parsed.odometer == original.odometer
        assert parsed.description == original.description
        assert parsed.cost == original.cost

    def test_odometer_round_trip(self) -> None:
        original = OdometerInput(odometer="45000")
        formatted = CommandParser.format_odometer(original)
        parsed = CommandParser.parse_odometer(formatted)
        assert parsed.odometer == original.odometer
