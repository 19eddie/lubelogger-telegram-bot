"""Tests for the application configuration module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.config import BotConfig, load_config
from bot.exceptions import ConfigurationError
from bot.units import DisplayUnits


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.config.BotConfig.model_config",
        {**BotConfig.model_config, "env_file": None},
    )


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
        assert config.telegram_bot_token.get_secret_value() == "123456:ABC-DEF"
        assert config.lubelogger_url == "http://lubelogger:8080"
        assert config.lubelogger_api_key.get_secret_value() == "test-key-123"
        assert config.lubelogger_username == ""
        assert config.lubelogger_password.get_secret_value() == ""
        assert config.allowed_user_ids == [111, 222, 333]

    def test_default_values(self) -> None:
        env = self._env()
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.queue_retry_interval == 300
        assert config.http_timeout == 60
        assert config.max_retry_attempts == 3
        assert config.db_path == "/data/bot.db"
        assert config.distance_unit == "km"
        assert config.volume_unit == "L"
        assert config.currency_symbol == "€"
        assert config.display_units == DisplayUnits()

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

    def test_basic_auth_credentials_are_supported(self) -> None:
        env = self._env(LUBELOGGER_USERNAME="user", LUBELOGGER_PASSWORD="pass")
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.lubelogger_username == "user"
        assert config.lubelogger_password.get_secret_value() == "pass"

    def test_config_secrets_masked_in_repr(self) -> None:
        env = self._env(
            TELEGRAM_BOT_TOKEN="secret-token-123",
            LUBELOGGER_API_KEY="secret-api-key",
            LUBELOGGER_USERNAME="user",
            LUBELOGGER_PASSWORD="secret-password",
        )
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
            config_repr = repr(config)
            config_str = str(config)

        assert "secret-token-123" not in config_repr
        assert "secret-api-key" not in config_repr
        assert "secret-password" not in config_repr

        assert "secret-token-123" not in config_str
        assert "secret-api-key" not in config_str
        assert "secret-password" not in config_str

    def test_config_validation_error_masks_secrets(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "secret-token-123",
            "LUBELOGGER_URL": "http://lubelogger:8080",
            "LUBELOGGER_API_KEY": "secret-api-key",
            "LUBELOGGER_USERNAME": "user",
            "LUBELOGGER_PASSWORD": "secret-password",
            "ALLOWED_USER_IDS": "-1",  # This will cause a validation error
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                load_config()

        error_msg = str(exc_info.value)
        assert "secret-token-123" not in error_msg
        assert "secret-api-key" not in error_msg
        assert "secret-password" not in error_msg

    def test_basic_auth_credentials_must_be_paired(self) -> None:
        env = self._env(LUBELOGGER_USERNAME="user")
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="must be set together"):
                BotConfig()  # type: ignore[call-arg]

    def test_unit_labels_can_be_overridden(self) -> None:
        env = self._env(DISTANCE_UNIT="mi", VOLUME_UNIT="gal", CURRENCY_SYMBOL="$")
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.display_units == DisplayUnits(distance="mi", volume="gal", currency="$")

    def test_unit_labels_are_stripped(self) -> None:
        env = self._env(DISTANCE_UNIT="  mi  ", VOLUME_UNIT=" US gal ")
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.distance_unit == "mi"
        assert config.volume_unit == "US gal"

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("DISTANCE_UNIT", ""),
            ("VOLUME_UNIT", "   "),
            ("CURRENCY_SYMBOL", "x" * 11),
        ],
    )
    def test_invalid_unit_labels_are_rejected(self, name: str, value: str) -> None:
        env = self._env(**{name: value})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match=name):
                BotConfig()  # type: ignore[call-arg]

    def test_multiline_unit_label_is_rejected(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True):
            with pytest.raises(ValueError, match="DISTANCE_UNIT"):
                BotConfig(distance_unit="m\ni")  # type: ignore[call-arg]

    def test_reads_utf8_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        lines = [f"{key}={value}" for key, value in self._env(CURRENCY_SYMBOL="£").items()]
        env_file.write_text("\n".join(lines), encoding="utf-8")
        monkeypatch.setattr(
            "bot.config.BotConfig.model_config",
            {**BotConfig.model_config, "env_file": str(env_file)},
        )
        with patch.dict(os.environ, {}, clear=True):
            config = BotConfig()  # type: ignore[call-arg]
        assert config.currency_symbol == "£"


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

    def test_raises_configuration_error_on_invalid_unit_label(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "tok",
            "LUBELOGGER_URL": "http://localhost:8080",
            "ALLOWED_USER_IDS": "1",
            "VOLUME_UNIT": "",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigurationError, match="VOLUME_UNIT"):
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
        assert config.telegram_bot_token.get_secret_value() == "tok"
        assert config.allowed_user_ids == [1, 2]
