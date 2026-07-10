"""Property-based test for API key non-leakage.

# Feature: lubelogger-telegram-bot, Property 3: API key non-leakage

**Validates: Requirements 2.4, NF-3.1, NF-3.2**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bot.exceptions import LubeLoggerApiError, LubeLoggerUnreachableError
from bot.services.lubelogger_client import LubeLoggerClient

# Strategy: generate API key strings using ASCII letters, digits, and safe punctuation.
# Minimum size 8 avoids trivial false-positive substring matches (e.g., single digits
# matching memory addresses in repr). Real API keys are typically 16+ chars.
api_key_strategy = st.text(
    min_size=8,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_.",
    ).filter(lambda c: ord(c) < 128),
)


@settings(max_examples=100, deadline=None)
@given(api_key=api_key_strategy)
@pytest.mark.asyncio
async def test_property_api_key_non_leakage(api_key: str) -> None:
    """For any API key string and any error condition or formatted message produced by
    the system, the output string SHALL NOT contain the raw API key value.

    # Feature: lubelogger-telegram-bot, Property 3: API key non-leakage
    """
    client = LubeLoggerClient(
        base_url="http://localhost:8080",
        api_key=api_key,
        timeout=5,
    )

    # 1. Verify repr() of the client does not leak the key
    client_repr = repr(client)
    assert api_key not in client_repr, (
        f"API key leaked in client repr: {client_repr}"
    )

    # 2. Simulate connection error and verify key is not in error string
    with patch.object(
        client._client, "request", new_callable=AsyncMock
    ) as mock_request:
        mock_request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(LubeLoggerUnreachableError) as exc_info:
            await client.get_vehicles()
        error_str = str(exc_info.value)
        assert api_key not in error_str, (
            f"API key leaked in LubeLoggerUnreachableError: {error_str}"
        )

    # 3. Simulate API error (non-2xx response) and verify key is not in error string
    mock_response = httpx.Response(
        status_code=401,
        text="Unauthorized",
        request=httpx.Request("GET", "http://localhost:8080/api/vehicles"),
    )
    with patch.object(
        client._client, "request", new_callable=AsyncMock
    ) as mock_request:
        mock_request.return_value = mock_response
        with pytest.raises(LubeLoggerApiError) as exc_info:
            await client.get_vehicles()
        error_str = str(exc_info.value)
        assert api_key not in error_str, (
            f"API key leaked in LubeLoggerApiError: {error_str}"
        )

    await client.close()
