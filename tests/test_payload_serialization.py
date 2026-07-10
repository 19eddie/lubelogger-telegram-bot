"""Property tests for payload serialization — all fields must be strings."""

# Feature: lubelogger-telegram-bot, Property 11: Payload serialization produces all-string fields

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
)
from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel

# --- Strategies ---

valid_date_st = st.dates().map(lambda d: d.isoformat())
positive_int_st = st.integers(min_value=1, max_value=10_000_000)
positive_float_st = st.floats(
    min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)
non_negative_float_st = st.floats(
    min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)
description_st = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z"), exclude_characters="\x00"),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip() != "")


gas_record_st = st.builds(
    GasRecordModel,
    date=valid_date_st,
    odometer=positive_int_st,
    liters=positive_float_st,
    cost=non_negative_float_st,
    is_fill_to_full=st.booleans(),
    missed_fuel_up=st.booleans(),
)

service_record_st = st.builds(
    ServiceRecordModel,
    date=valid_date_st,
    odometer=positive_int_st,
    description=description_st,
    cost=non_negative_float_st,
)

odometer_record_st = st.builds(
    OdometerRecordModel,
    date=valid_date_st,
    odometer=positive_int_st,
)


# --- Property Test ---


@settings(max_examples=100)
@given(record=gas_record_st)
def test_property_payload_all_strings_gas(record: GasRecordModel) -> None:
    """Validates: Requirements 4.9

    For any valid GasRecordModel, converting via from_validated() produces
    an object where every field value is a string.
    """
    payload = GasRecordPayload.from_validated(record)
    data = payload.model_dump(by_alias=True)
    for key, value in data.items():
        assert isinstance(value, str), (
            f"Field '{key}' has type {type(value).__name__}, expected str"
        )


@settings(max_examples=100)
@given(record=service_record_st)
def test_property_payload_all_strings_service(record: ServiceRecordModel) -> None:
    """Validates: Requirements 5.7

    For any valid ServiceRecordModel, converting via from_validated() produces
    an object where every field value is a string.
    """
    payload = ServiceRecordPayload.from_validated(record)
    data = payload.model_dump(by_alias=True)
    for key, value in data.items():
        assert isinstance(value, str), (
            f"Field '{key}' has type {type(value).__name__}, expected str"
        )


@settings(max_examples=100)
@given(record=odometer_record_st)
def test_property_payload_all_strings_odometer(record: OdometerRecordModel) -> None:
    """Validates: Requirements 6.5

    For any valid OdometerRecordModel, converting via from_validated() produces
    an object where every field value is a string.
    """
    payload = OdometerRecordPayload.from_validated(record)
    data = payload.model_dump(by_alias=True)
    for key, value in data.items():
        assert isinstance(value, str), (
            f"Field '{key}' has type {type(value).__name__}, expected str"
        )


@settings(max_examples=100)
@given(
    record=st.one_of(gas_record_st, service_record_st, odometer_record_st),
)
def test_property_payload_all_strings(
    record: GasRecordModel | ServiceRecordModel | OdometerRecordModel,
) -> None:
    """Validates: Requirements 4.9, 5.7, 6.5

    For any valid GasRecordModel, ServiceRecordModel, or OdometerRecordModel,
    converting via from_validated() produces an object where every field value is a string.
    """
    if isinstance(record, GasRecordModel):
        payload = GasRecordPayload.from_validated(record)
    elif isinstance(record, ServiceRecordModel):
        payload = ServiceRecordPayload.from_validated(record)
    else:
        payload = OdometerRecordPayload.from_validated(record)

    data = payload.model_dump(by_alias=True)
    for key, value in data.items():
        assert isinstance(value, str), (
            f"Field '{key}' has type {type(value).__name__}, expected str"
        )
