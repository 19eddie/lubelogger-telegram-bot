"""Property tests for payload serialization — all fields must be strings."""

# Feature: lubelogger-telegram-bot, Property 11: Payload serialization produces all-string fields

from __future__ import annotations

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.models.payloads import (
    GasRecordPayload,
    OdometerRecordPayload,
    ServiceRecordPayload,
    gas_payload_matches_record,
)
from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel

# --- Strategies ---

valid_date_st = st.dates(max_value=date.today()).map(lambda d: d.isoformat())
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


def test_gas_payload_omits_soc_without_user_data() -> None:
    """Gas payload does not invent EV state-of-charge values."""
    record = GasRecordModel(odometer=30, liters=30.0, cost=6.0, is_fill_to_full=False)

    data = GasRecordPayload.from_validated(record).model_dump(by_alias=True)

    assert "startingSoc" not in data
    assert "endingSoc" not in data


def test_gas_payload_serializes_date_and_missed_flag() -> None:
    """Gas payload preserves retroactive date and missed-fuel metadata aliases."""
    record = GasRecordModel(
        date="2024-01-15",
        odometer=45000,
        liters=42.5,
        cost=78.9,
        is_fill_to_full=True,
        missed_fuel_up=True,
    )

    data = GasRecordPayload.from_validated(record).model_dump(by_alias=True)

    assert data["date"] == "2024-01-15"
    assert data["missedFuelUp"] == "true"
    assert all(isinstance(value, str) for value in data.values())


def test_gas_payload_uses_comma_decimal_separator() -> None:
    """LubeLogger 1.5.x expects locale-formatted decimal strings."""
    record = GasRecordModel(
        date="2026-05-01",
        odometer=295637,
        liters=11.27,
        cost=18.02,
    )

    data = GasRecordPayload.from_validated(record).model_dump(by_alias=True)

    assert data["fuelConsumed"] == "11,27"
    assert data["cost"] == "18,02"


def test_lubelogger_decimal_formatter_avoids_float_artifacts() -> None:
    """Decimal conversion keeps values such as 0.1 and scientific notation exact."""
    values = [
        GasRecordModel(odometer=1, liters=0.1, cost=0.01),
        GasRecordModel(odometer=1, liters=1e-07, cost=100.0),
    ]

    payloads = [GasRecordPayload.from_validated(record) for record in values]

    assert payloads[0].fuel_consumed == "0,1"
    assert payloads[0].cost == "0,01"
    assert payloads[1].fuel_consumed == "0,0000001"
    assert payloads[1].cost == "100"


def test_gas_payload_matches_remote_locale_formats() -> None:
    """Fingerprint matching accepts server dot/comma formatting but rejects 1167."""
    payload = GasRecordPayload(
        date="2026-05-04",
        odometer="295950",
        fuel_consumed="11,67",
        cost="18,66",
        is_fill_to_full="true",
        missed_fuel_up="false",
    )
    remote_record = {
        "date": "2026-05-04",
        "odometer": "295950",
        "fuelConsumed": "11.67",
        "cost": "18.66",
        "isFillToFull": True,
        "missedFuelUp": False,
    }

    assert gas_payload_matches_record(payload, remote_record)
    assert not gas_payload_matches_record(
        payload,
        {**remote_record, "fuelConsumed": "1167"},
    )
