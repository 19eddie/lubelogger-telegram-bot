"""Unit tests for the flow field tables (bot/flows/definitions.py)."""

from __future__ import annotations

import pytest

from bot.flows.definitions import (
    FIELDS,
    FieldKind,
    FlowKind,
    field_at,
    field_count,
    field_index,
)


def test_field_tables_have_the_expected_keys_in_order() -> None:
    assert [f.key for f in FIELDS[FlowKind.FUEL]] == [
        "odometer",
        "liters",
        "cost",
        "is_fill_to_full",
    ]
    assert [f.key for f in FIELDS[FlowKind.SERVICE]] == ["odometer", "description", "cost"]
    assert [f.key for f in FIELDS[FlowKind.ODOMETER]] == ["odometer"]


def test_field_count_matches_the_table_length() -> None:
    assert field_count(FlowKind.FUEL) == 4
    assert field_count(FlowKind.SERVICE) == 3
    assert field_count(FlowKind.ODOMETER) == 1


def test_full_tank_is_a_closed_choice_field() -> None:
    full_tank = field_at(FlowKind.FUEL, field_index(FlowKind.FUEL, "is_fill_to_full"))
    assert full_tank.kind is FieldKind.CHOICE
    assert full_tank.choices == ("btn_yes", "btn_no")


def test_non_choice_fields_carry_no_choices() -> None:
    for specs in FIELDS.values():
        for spec in specs:
            if spec.kind is not FieldKind.CHOICE:
                assert spec.choices == ()


def test_field_at_and_field_index_are_inverse() -> None:
    for kind, specs in FIELDS.items():
        for index, spec in enumerate(specs):
            assert field_at(kind, index) is spec
            assert field_index(kind, spec.key) == index


def test_field_at_rejects_out_of_range_indexes() -> None:
    with pytest.raises(IndexError):
        field_at(FlowKind.ODOMETER, 1)
    with pytest.raises(IndexError):
        field_at(FlowKind.FUEL, -1)


def test_field_index_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError):
        field_index(FlowKind.ODOMETER, "liters")


def test_field_specs_are_immutable() -> None:
    spec = field_at(FlowKind.FUEL, 0)
    with pytest.raises(AttributeError):
        spec.key = "other"  # type: ignore[misc]


def test_module_imports_nothing_from_the_bot_package() -> None:
    """The i18n index imports MenuAction, so this module must stay import-cycle free."""
    import ast
    import inspect

    import bot.flows.definitions as definitions

    tree = ast.parse(inspect.getsource(definitions))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if name.startswith("bot")]
