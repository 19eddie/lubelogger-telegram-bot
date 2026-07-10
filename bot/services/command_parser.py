"""Command argument parsing for Telegram bot commands."""

from __future__ import annotations

import re

from bot.exceptions import ParseError
from bot.models.inputs import FuelInput, OdometerInput, ServiceInput


class CommandParser:
    """Parses command arguments into typed input objects."""

    @staticmethod
    def normalize_decimal(value: str) -> str:
        """Replace comma with dot for decimal separator.

        Examples:
            "45,2" → "45.2"
            "45.2" → "45.2"
            "100" → "100"
        """
        return value.replace(",", ".")

    @staticmethod
    def parse_fuel(args: str) -> FuelInput:
        """Parse fuel command arguments: <odometer> <liters> <cost>.

        Args:
            args: Space-separated string with three numeric values.

        Returns:
            FuelInput with normalized decimal values.

        Raises:
            ParseError: If arguments don't match expected format.
        """
        parts = args.strip().split()
        if len(parts) != 3:
            raise ParseError(
                command="/fuel",
                hint="Usage: /fuel <odometer> <liters> <cost>",
            )

        odometer_raw, liters_raw, cost_raw = parts

        odometer = CommandParser.normalize_decimal(odometer_raw)
        liters = CommandParser.normalize_decimal(liters_raw)
        cost = CommandParser.normalize_decimal(cost_raw)

        # Validate that all values are numeric
        for label, value in [("odometer", odometer), ("liters", liters), ("cost", cost)]:
            try:
                float(value)
            except ValueError:
                raise ParseError(
                    command="/fuel",
                    hint=f"Usage: /fuel <odometer> <liters> <cost> — '{label}' must be a number",
                )

        return FuelInput(odometer=odometer, liters=liters, cost=cost)

    @staticmethod
    def parse_service(args: str) -> ServiceInput:
        """Parse service command arguments: <odometer> "<description>" <cost>.

        The description can be quoted (with double quotes) or a single unquoted word.

        Args:
            args: String with odometer, quoted/unquoted description, and cost.

        Returns:
            ServiceInput with normalized decimal values.

        Raises:
            ParseError: If arguments don't match expected format.
        """
        text = args.strip()
        if not text:
            raise ParseError(
                command="/service",
                hint='Usage: /service <odometer> "<description>" <cost>',
            )

        # Try to match: <odometer> "<description>" <cost>
        quoted_pattern = re.compile(r'^(\S+)\s+"([^"]+)"\s+(\S+)$')
        match = quoted_pattern.match(text)

        if not match:
            # Try unquoted single-word description: <odometer> <description> <cost>
            parts = text.split()
            if len(parts) != 3:
                raise ParseError(
                    command="/service",
                    hint='Usage: /service <odometer> "<description>" <cost>',
                )
            odometer_raw, description, cost_raw = parts
        else:
            odometer_raw = match.group(1)
            description = match.group(2)
            cost_raw = match.group(3)

        odometer = CommandParser.normalize_decimal(odometer_raw)
        cost = CommandParser.normalize_decimal(cost_raw)

        # Validate numeric fields
        try:
            float(odometer)
        except ValueError:
            raise ParseError(
                command="/service",
                hint='Usage: /service <odometer> "<description>" <cost>'
                " — 'odometer' must be a number",
            )

        try:
            float(cost)
        except ValueError:
            raise ParseError(
                command="/service",
                hint='Usage: /service <odometer> "<description>" <cost>'
                " — 'cost' must be a number",
            )

        return ServiceInput(odometer=odometer, description=description, cost=cost)

    @staticmethod
    def parse_odometer(args: str) -> OdometerInput:
        """Parse odometer command arguments: <odometer>.

        Args:
            args: Single numeric value string.

        Returns:
            OdometerInput with normalized decimal value.

        Raises:
            ParseError: If argument is not a valid number.
        """
        text = args.strip()
        if not text:
            raise ParseError(
                command="/km",
                hint="Usage: /km <odometer>",
            )

        parts = text.split()
        if len(parts) != 1:
            raise ParseError(
                command="/km",
                hint="Usage: /km <odometer>",
            )

        odometer = CommandParser.normalize_decimal(parts[0])

        try:
            float(odometer)
        except ValueError:
            raise ParseError(
                command="/km",
                hint="Usage: /km <odometer> — value must be a number",
            )

        return OdometerInput(odometer=odometer)

    @staticmethod
    def format_fuel(record: FuelInput) -> str:
        """Format a FuelInput back into command argument string.

        Args:
            record: The fuel input to format.

        Returns:
            Space-separated string: "<odometer> <liters> <cost>"
        """
        return f"{record.odometer} {record.liters} {record.cost}"

    @staticmethod
    def format_service(record: ServiceInput) -> str:
        """Format a ServiceInput back into command argument string.

        Args:
            record: The service input to format.

        Returns:
            Formatted string: '<odometer> "<description>" <cost>'
        """
        return f'{record.odometer} "{record.description}" {record.cost}'

    @staticmethod
    def format_odometer(record: OdometerInput) -> str:
        """Format an OdometerInput back into command argument string.

        Args:
            record: The odometer input to format.

        Returns:
            The odometer value as a string.
        """
        return record.odometer
