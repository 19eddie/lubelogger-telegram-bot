"""Backward compatibility property tests.

# Feature: improve-ux
"""

from __future__ import annotations

import re

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from bot.models.validators import GasRecordModel, OdometerRecordModel, ServiceRecordModel
from bot.services.command_parser import CommandParser, parse_vehicle_override


@settings(max_examples=100)
@given(
    vehicle_id=st.integers(min_value=1, max_value=999999),
    args=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"), whitelist_characters=" .,/-"
        ),
        min_size=0,
        max_size=60,
    ),
)
def test_property_vehicle_override_roundtrip(vehicle_id: int, args: str) -> None:
    """Property 31: The vehicle override is extracted without disturbing the other arguments.

    **Validates: Requirements 12.3**

    # Feature: improve-ux, Property 31: vehicle override roundtrip
    """
    # Ensure args doesn't accidentally contain --vehicle <digits>
    assume(not re.search(r"--vehicle\s+\d+", args))

    # Build an input with --vehicle <id> injected
    full = f"--vehicle {vehicle_id} {args}"

    extracted_id, remaining = parse_vehicle_override(full)

    # The id is correctly extracted
    assert extracted_id == vehicle_id

    # The remaining text contains the original args (whitespace-normalized)
    original_tokens = args.split()
    remaining_tokens = remaining.split()
    assert remaining_tokens == original_tokens

    # Without --vehicle, returns None and text unchanged
    no_override_id, no_override_remaining = parse_vehicle_override(args)
    assert no_override_id is None
    assert no_override_remaining == args


@settings(max_examples=100)
@given(
    odometer=st.integers(min_value=1, max_value=999999),
    liters=st.floats(min_value=0.1, max_value=999.9, allow_nan=False, allow_infinity=False),
    cost=st.floats(min_value=0.0, max_value=9999.9, allow_nan=False, allow_infinity=False),
    is_full=st.booleans(),
)
def test_property_inline_matches_guided(
    odometer: int, liters: float, cost: float, is_full: bool
) -> None:
    """Property 32: Inline-argument mode and guided mode agree.

    Both paths build the same values dict that RecordSubmitter.submit() accepts.

    **Validates: Requirements 12.1, 12.2**

    # Feature: improve-ux, Property 32: inline matches guided
    """
    # --- Fuel: inline path builds values ---
    args_str = f"{odometer} {liters:.2f} {cost:.2f}"
    fuel_input = CommandParser.parse_fuel(args_str)

    inline_values = {
        "odometer": int(float(fuel_input.odometer)),
        "liters": float(fuel_input.liters),
        "cost": float(fuel_input.cost),
        "is_fill_to_full": is_full,
        "missed_fuel_up": False,
    }

    # Guided path would collect the same individual values
    guided_values = {
        "odometer": odometer,
        "liters": round(liters, 2),
        "cost": round(cost, 2),
        "is_fill_to_full": is_full,
        "missed_fuel_up": False,
    }

    # Both must produce valid models (which is what RecordSubmitter does)
    inline_model = GasRecordModel(**inline_values)
    guided_model = GasRecordModel(**guided_values)

    # Both models produce equivalent payloads
    assert inline_model.odometer == guided_model.odometer
    assert inline_model.liters == guided_model.liters
    assert inline_model.cost == guided_model.cost
    assert inline_model.is_fill_to_full == guided_model.is_fill_to_full
    assert inline_model.missed_fuel_up == guided_model.missed_fuel_up

    # --- Service: inline path builds values ---
    description = "TestService"
    svc_args_str = f'{odometer} "{description}" {cost:.2f}'
    svc_input = CommandParser.parse_service(svc_args_str)

    inline_svc_values = {
        "odometer": int(float(svc_input.odometer)),
        "description": svc_input.description,
        "cost": float(svc_input.cost),
    }

    guided_svc_values = {
        "odometer": odometer,
        "description": description,
        "cost": round(cost, 2),
    }

    inline_svc_model = ServiceRecordModel(**inline_svc_values)
    guided_svc_model = ServiceRecordModel(**guided_svc_values)

    assert inline_svc_model.odometer == guided_svc_model.odometer
    assert inline_svc_model.description == guided_svc_model.description
    assert inline_svc_model.cost == guided_svc_model.cost

    # --- Odometer: inline path builds values ---
    odo_args_str = str(odometer)
    odo_input = CommandParser.parse_odometer(odo_args_str)

    inline_odo_values = {"odometer": int(float(odo_input.odometer))}
    guided_odo_values = {"odometer": odometer}

    inline_odo_model = OdometerRecordModel(**inline_odo_values)
    guided_odo_model = OdometerRecordModel(**guided_odo_values)

    assert inline_odo_model.odometer == guided_odo_model.odometer
