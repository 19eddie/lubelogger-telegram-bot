"""Bot middleware (auth, etc.)."""

from bot.middleware.auth import create_auth_filter

__all__ = ["create_auth_filter"]
