"""Property-based tests for Pydantic validation models."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel

# --- Strategies for valid inputs ---

valid_odometer = st.integers(min_value=1, max_value=999999)
valid_liters = st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False)
valid_cost = st.floats(min_value=0.0, max_value=99999.99, allow_nan=False, allow_infinity=False)
valid_description = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Zs")),
).filter(lambda s: s.strip() != "")


# --- Strategies for invalid inputs ---

invalid_odometer = st.integers(max_value=0)
invalid_liters = st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)
invalid_cost = st.floats(max_value=-0.01, allow_nan=False, allow_infinity=False)
whitespace_only_description = st.from_regex(r"^\s+$", fullmatch=True)


# --- Property 9: Validation acceptance of valid inputs ---


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    liters=valid_liters,
    cost=valid_cost,
)
def test_property_validation_accepts_valid_gas_record(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 9: Validation acceptance of valid inputs (GasRecordModel).

    For any record where odometer > 0, liters > 0, and cost >= 0,
    the validator accepts without error.

    # Feature: lubelogger-telegram-bot, Property 9: Validation acceptance of valid inputs

    **Validates: Requirements 10.5, 10.7**
    """
    record = GasRecordModel(odometer=odometer, liters=liters, cost=cost)
    assert record.odometer == odometer
    assert record.liters == liters
    assert record.cost == cost


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    description=valid_description,
    cost=valid_cost,
)
def test_property_validation_accepts_valid_service_record(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 9: Validation acceptance of valid inputs (ServiceRecordModel).

    For any record where odometer > 0, description is non-empty non-whitespace,
    and cost >= 0, the validator accepts without error.

    # Feature: lubelogger-telegram-bot, Property 9: Validation acceptance of valid inputs

    **Validates: Requirements 10.5, 10.7**
    """
    record = ServiceRecordModel(odometer=odometer, description=description, cost=cost)
    assert record.odometer == odometer
    assert record.description == description.strip()
    assert record.cost == cost


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
)
def test_property_validation_accepts_valid_odometer_record(
    odometer: int,
) -> None:
    """Property 9: Validation acceptance of valid inputs (OdometerRecordModel).

    For any record where odometer > 0, the validator accepts without error.

    # Feature: lubelogger-telegram-bot, Property 9: Validation acceptance of valid inputs

    **Validates: Requirements 10.5, 10.7**
    """
    record = OdometerRecordModel(odometer=odometer)
    assert record.odometer == odometer


# --- Property 10: Validation rejection of invalid inputs ---


@settings(max_examples=100)
@given(
    odometer=invalid_odometer,
    liters=valid_liters,
    cost=valid_cost,
)
def test_property_validation_rejects_invalid_gas_odometer(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (GasRecordModel - odometer).

    For any gas record where odometer <= 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.1, 10.6, 10.7**
    """
    try:
        GasRecordModel(odometer=odometer, liters=liters, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "odometer" in error_fields


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    liters=invalid_liters,
    cost=valid_cost,
)
def test_property_validation_rejects_invalid_gas_liters(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (GasRecordModel - liters).

    For any gas record where liters <= 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.2, 10.6, 10.7**
    """
    try:
        GasRecordModel(odometer=odometer, liters=liters, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "liters" in error_fields


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    liters=valid_liters,
    cost=invalid_cost,
)
def test_property_validation_rejects_invalid_gas_cost(
    odometer: int,
    liters: float,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (GasRecordModel - cost).

    For any gas record where cost < 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.3, 10.6, 10.7**
    """
    try:
        GasRecordModel(odometer=odometer, liters=liters, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "cost" in error_fields


@settings(max_examples=100)
@given(
    odometer=invalid_odometer,
    description=valid_description,
    cost=valid_cost,
)
def test_property_validation_rejects_invalid_service_odometer(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (ServiceRecordModel - odometer).

    For any service record where odometer <= 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.1, 10.6, 10.7**
    """
    try:
        ServiceRecordModel(odometer=odometer, description=description, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "odometer" in error_fields


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    description=whitespace_only_description,
    cost=valid_cost,
)
def test_property_validation_rejects_invalid_service_description(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (ServiceRecordModel - description).

    For any service record where description is whitespace-only, the validator raises
    ValidationError naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.4, 10.6, 10.7**
    """
    try:
        ServiceRecordModel(odometer=odometer, description=description, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "description" in error_fields


@settings(max_examples=100)
@given(
    odometer=valid_odometer,
    description=valid_description,
    cost=invalid_cost,
)
def test_property_validation_rejects_invalid_service_cost(
    odometer: int,
    description: str,
    cost: float,
) -> None:
    """Property 10: Validation rejection of invalid inputs (ServiceRecordModel - cost).

    For any service record where cost < 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.3, 10.6, 10.7**
    """
    try:
        ServiceRecordModel(odometer=odometer, description=description, cost=cost)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "cost" in error_fields


@settings(max_examples=100)
@given(
    odometer=invalid_odometer,
)
def test_property_validation_rejects_invalid_odometer_record(
    odometer: int,
) -> None:
    """Property 10: Validation rejection of invalid inputs (OdometerRecordModel).

    For any odometer record where odometer <= 0, the validator raises ValidationError
    naming the offending field.

    # Feature: lubelogger-telegram-bot, Property 10: Validation rejection of invalid inputs

    **Validates: Requirements 10.1, 10.6, 10.7**
    """
    try:
        OdometerRecordModel(odometer=odometer)
        raise AssertionError("ValidationError was not raised")
    except ValidationError as e:
        error_fields = [err["loc"][0] for err in e.errors()]
        assert "odometer" in error_fields
