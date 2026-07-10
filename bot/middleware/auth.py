"""Authorization filter for restricting bot access to whitelisted users."""

from __future__ import annotations

from telegram.ext import filters


def create_auth_filter(allowed_user_ids: list[int]) -> filters.User:
    """Create a filter that only allows messages from whitelisted user IDs.

    Messages from users not in the list are silently ignored — no response
    is sent and no message content is logged (requirement NF-3.3).
    """
    return filters.User(user_id=allowed_user_ids)
