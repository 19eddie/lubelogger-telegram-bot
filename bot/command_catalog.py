"""Central catalog of user-facing Telegram commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Metadata used to render and optionally expose one Telegram command."""

    name: str
    description_key: str
    usage_key: str | None = None
    section_key: str = "help_section_general"
    show_in_help: bool = True


COMMAND_CATALOG: tuple[CommandSpec, ...] = (
    CommandSpec("start", "help_start"),
    CommandSpec("help", "help_help"),
    CommandSpec("lang", "help_lang"),
    CommandSpec("cancel", "help_cancel"),
    CommandSpec("vehicle", "help_vehicle", section_key="help_section_records"),
    CommandSpec(
        "fuel",
        "help_fuel",
        usage_key="help_usage_fuel",
        section_key="help_section_records",
    ),
    CommandSpec(
        "service",
        "help_service",
        usage_key="help_usage_service",
        section_key="help_section_records",
    ),
    CommandSpec(
        "km",
        "help_km",
        usage_key="help_usage_km",
        section_key="help_section_records",
    ),
    CommandSpec(
        "last", "help_last", usage_key="help_usage_last", section_key="help_section_status"
    ),
    CommandSpec("status", "help_status", section_key="help_section_status"),
    CommandSpec("queue", "help_queue", section_key="help_section_status"),
)
