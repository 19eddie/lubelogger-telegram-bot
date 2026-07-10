"""Property-based tests for the CommandParser service."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.models.inputs import FuelInput, OdometerInput, ServiceInput
from bot.services.command_parser import CommandParser


@settings(max_examples=100)
@given(
    odometer=st.integers(min_value=1, max_value=999999),
    liters=st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False),
    cost=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
def test_property_command_parsing_roundtrip_fuel(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 6: Command parsing round-trip (fuel).

    For any valid FuelInput, formatting then parsing produces equivalent record.

    # Feature: lubelogger-telegram-bot, Property 6: Command parsing round-trip

    **Validates: Requirements 9.1, 9.6**
    """
    liters = round(liters, 2)
    cost = round(cost, 2)

    original = FuelInput(
        odometer=str(odometer),
        liters=str(liters),
        cost=str(cost),
    )
    formatted = CommandParser.format_fuel(original)
    parsed = CommandParser.parse_fuel(formatted)

    assert float(parsed.odometer) == float(original.odometer)
    assert float(parsed.liters) == float(original.liters)
    assert float(parsed.cost) == float(original.cost)


@settings(max_examples=100)
@given(
    odometer=st.integers(min_value=1, max_value=999999),
    description=st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    ).filter(lambda s: s.strip() != "" and '"' not in s),
    cost=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
def test_property_command_parsing_roundtrip_service(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 6: Command parsing round-trip (service).

    For any valid ServiceInput, formatting then parsing produces equivalent record.

    # Feature: lubelogger-telegram-bot, Property 6: Command parsing round-trip

    **Validates: Requirements 9.1, 9.6**
    """
    cost = round(cost, 2)

    original = ServiceInput(
        odometer=str(odometer),
        description=description,
        cost=str(cost),
    )
    formatted = CommandParser.format_service(original)
    parsed = CommandParser.parse_service(formatted)

    assert float(parsed.odometer) == float(original.odometer)
    assert parsed.description == original.description
    assert float(parsed.cost) == float(original.cost)


@settings(max_examples=100)
@given(
    odometer=st.integers(min_value=1, max_value=999999),
)
def test_property_command_parsing_roundtrip_odometer(
    odometer: int,
) -> None:
    """Property 6: Command parsing round-trip (odometer).

    For any valid OdometerInput, formatting then parsing produces equivalent record.

    # Feature: lubelogger-telegram-bot, Property 6: Command parsing round-trip

    **Validates: Requirements 9.1, 9.6**
    """
    original = OdometerInput(odometer=str(odometer))
    formatted = CommandParser.format_odometer(original)
    parsed = CommandParser.parse_odometer(formatted)

    assert float(parsed.odometer) == float(original.odometer)


@settings(max_examples=100)
@given(
    value=st.floats(min_value=0.1, max_value=99999.99, allow_nan=False, allow_infinity=False),
)
def test_property_decimal_separator_normalization(
    value: float,
) -> None:
    """Property 7: Decimal separator normalization.

    Both `45.2` and `45,2` parse to same numeric value.

    # Feature: lubelogger-telegram-bot, Property 7: Decimal separator normalization

    **Validates: Requirements 9.5**
    """
    value = round(value, 2)
    dot_str = str(value)
    comma_str = dot_str.replace(".", ",")

    normalized_from_dot = CommandParser.normalize_decimal(dot_str)
    normalized_from_comma = CommandParser.normalize_decimal(comma_str)

    assert float(normalized_from_dot) == float(normalized_from_comma)


@settings(max_examples=100)
@given(
    odometer=st.integers(min_value=1, max_value=999999),
    liters=st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False),
    cost=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
def test_property_fuel_argument_parsing(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 8: Fuel command argument parsing.

    For any positive integer odometer, positive float liters, non-negative float cost,
    formatting as space-separated and parsing produces FuelInput with those values.

    # Feature: lubelogger-telegram-bot, Property 8: Fuel command argument parsing

    **Validates: Requirements 9.1, 9.5, 9.6**
    """
    liters = round(liters, 2)
    cost = round(cost, 2)

    args_str = f"{odometer} {liters} {cost}"
    result = CommandParser.parse_fuel(args_str)

    assert float(result.odometer) == odometer
    assert float(result.liters) == liters
    assert float(result.cost) == cost
