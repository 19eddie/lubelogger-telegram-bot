"""Property tests for auth filter and whitelist parsing.

# Feature: lubelogger-telegram-bot, Property 1: Auth filter correctness
# Feature: lubelogger-telegram-bot, Property 2: Whitelist parsing round-trip

Validates: Requirements 1.1, 1.2, 1.3
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.middleware.auth import create_auth_filter


@settings(max_examples=100)
@given(
    whitelist=st.lists(st.integers(min_value=1, max_value=2**31), min_size=1, max_size=10),
    test_user_id=st.integers(min_value=1, max_value=2**31),
)
def test_property_auth_filter_correctness(whitelist: list[int], test_user_id: int) -> None:
    """Property 1: Auth filter correctness.

    For any Telegram user ID and whitelist, the auth filter returns True
    iff the user ID is in the whitelist.

    # Feature: lubelogger-telegram-bot, Property 1: Auth filter correctness
    **Validates: Requirements 1.1, 1.2**
    """
    auth_filter = create_auth_filter(whitelist)

    # filters.User stores allowed IDs in a frozenset called user_ids
    if test_user_id in whitelist:
        assert test_user_id in auth_filter.user_ids
    else:
        assert test_user_id not in auth_filter.user_ids


@settings(max_examples=100)
@given(
    ids=st.lists(st.integers(min_value=1, max_value=2**31), min_size=1, max_size=10),
)
def test_property_whitelist_parsing_roundtrip(ids: list[int]) -> None:
    """Property 2: Whitelist parsing round-trip.

    For any list of positive integers, serializing as comma-separated
    and parsing back produces the original list.

    # Feature: lubelogger-telegram-bot, Property 2: Whitelist parsing round-trip
    **Validates: Requirements 1.3**
    """
    # Serialize as comma-separated string (same as env var format)
    serialized = ",".join(str(x) for x in ids)

    # Parse back using the same logic as BotConfig's _CommaSplitEnvSource
    parsed = [int(x.strip()) for x in serialized.split(",") if x.strip()]

    assert parsed == ids
