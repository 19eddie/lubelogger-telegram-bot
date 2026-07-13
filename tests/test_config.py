"""Tests for the application configuration module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from bot.config import BotConfig, load_config
from bot.exceptions import ConfigurationError


class TestBotConfig:
    """BotConfig loads and validates environment variables."""

    def _env(self, **overrides: str) -> dict[str, str]:
        """Build a minimal valid env dict."""
        base = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "LUBELOGGER_URL": "http://lubelogger:8080",
            "LUBELOGGER_API_KEY": "test-key-123",
            "ALLOWED_USER_IDS": "111,222,333",
        }
        base.update(overrides)
        return base

    def test_loads_required_fields(self) -> None:
        env = self._env()
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.telegram_bot_token == "123456:ABC-DEF"
        assert config.lubelogger_url == "http://lubelogger:8080"
        assert config.lubelogger_api_key == "test-key-123"
        assert config.allowed_user_ids == [111, 222, 333]

    def test_default_values(self) -> None:
        env = self._env()
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.queue_retry_interval == 300
        assert config.http_timeout == 10
        assert config.max_retry_attempts == 3
        assert config.db_path == "/data/bot.db"

    def test_overrides_defaults(self) -> None:
        env = self._env(
            QUEUE_RETRY_INTERVAL="60",
            HTTP_TIMEOUT="30",
            MAX_RETRY_ATTEMPTS="5",
            DB_PATH="/custom/path.db",
        )
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.queue_retry_interval == 60
        assert config.http_timeout == 30
        assert config.max_retry_attempts == 5
        assert config.db_path == "/custom/path.db"

    def test_single_allowed_user_id(self) -> None:
        env = self._env(ALLOWED_USER_IDS="42")
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.allowed_user_ids == [42]


class TestLoadConfig:
    """load_config() wraps BotConfig with ConfigurationError."""

    def test_raises_configuration_error_on_missing_vars(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "bot.config.BotConfig.model_config",
                {**BotConfig.model_config, "env_file": None},
            ),
        ):
            with pytest.raises(ConfigurationError):
                load_config()

    def test_returns_config_on_valid_env(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "tok",
            "LUBELOGGER_URL": "http://localhost:8080",
            "LUBELOGGER_API_KEY": "key",
            "ALLOWED_USER_IDS": "1,2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.telegram_bot_token == "tok"
        assert config.allowed_user_ids == [1, 2]
