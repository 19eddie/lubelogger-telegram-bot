"""Application configuration module using pydantic-settings."""

from __future__ import annotations

from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings
from pydantic_settings.sources.base import PydanticBaseSettingsSource
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource
from pydantic_settings.sources.providers.env import EnvSettingsSource

from bot.exceptions import ConfigurationError


def _parse_comma_ids(value: object) -> object:
    """Parse a comma-separated string of integers into a list."""
    if isinstance(value, str):
        return [int(x.strip()) for x in value.split(",") if x.strip()]
    return value


class _CommaSplitEnvSource(EnvSettingsSource):
    """Custom env source that parses comma-separated integers for list fields."""

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: object,
        value_is_complex: bool,
    ) -> object:
        """Override to handle comma-separated integer lists."""
        if field_name == "allowed_user_ids":
            return _parse_comma_ids(value)
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _CommaSplitDotEnvSource(DotEnvSettingsSource):
    """Custom dotenv source that parses comma-separated integers for list fields."""

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: object,
        value_is_complex: bool,
    ) -> object:
        """Override to handle comma-separated integer lists."""
        if field_name == "allowed_user_ids":
            return _parse_comma_ids(value)
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class BotConfig(BaseSettings):
    """Bot configuration loaded from environment variables."""

    telegram_bot_token: str = Field(min_length=1)
    lubelogger_url: str = Field(min_length=1)
    lubelogger_api_key: str = ""
    lubelogger_username: str = ""
    lubelogger_password: str = ""
    allowed_user_ids: list[int] = Field(min_length=1)
    queue_retry_interval: int = Field(default=300, gt=0)
    http_timeout: int = Field(default=10, gt=0)
    max_retry_attempts: int = Field(default=3, gt=0)
    db_path: str = "/data/bot.db"

    model_config = ConfigDict(env_prefix="", env_file=".env")

    @model_validator(mode="after")
    def basic_credentials_are_complete(self) -> Self:
        """Require both Basic Auth fields when legacy auth is configured."""
        if bool(self.lubelogger_username) != bool(self.lubelogger_password):
            raise ValueError("LUBELOGGER_USERNAME and LUBELOGGER_PASSWORD must be set together")
        return self

    @field_validator("allowed_user_ids")
    @classmethod
    def allowed_ids_must_be_positive(cls, value: list[int]) -> list[int]:
        """Reject an empty or invalid whitelist."""
        if any(user_id <= 0 for user_id in value):
            raise ValueError("ALLOWED_USER_IDS must contain positive Telegram user IDs")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use custom env/dotenv sources that handle comma-separated user IDs."""
        # Get env_file from the pre-configured dotenv source
        env_file = getattr(dotenv_settings, "env_file", None)
        return (
            init_settings,
            _CommaSplitEnvSource(settings_cls),
            _CommaSplitDotEnvSource(settings_cls, env_file=env_file),
            file_secret_settings,
        )


def load_config() -> BotConfig:
    """Load and validate configuration from environment variables.

    Raises:
        ConfigurationError: If required or invalid configuration is found.
    """
    try:
        return BotConfig()  # type: ignore[call-arg]
    except Exception as exc:
        raise ConfigurationError(f"Invalid or missing configuration: {exc}") from exc
