## 2025-02-14 - Use SecretStr for sensitive configuration fields
**Vulnerability:** Application configuration stored sensitive credentials (bot token, API keys, basic auth passwords) as plain strings in the Pydantic settings model.
**Learning:** By using standard strings for credentials, Pydantic models might inadvertently leak secrets if the configuration object is logged, serialized, or exposed in an exception traceback.
**Prevention:** Use `SecretStr` from `pydantic` for sensitive configuration properties. This ensures the secrets are obfuscated when the model is represented as a string, and requires explicit calls to `.get_secret_value()` to extract the actual plain text, preventing accidental leakage.

## 2025-02-24 - [Sentinel Security Enhancement: Credential Masking in Config and Logs]
**Vulnerability:** Configuration secrets (`telegram_bot_token`, `lubelogger_api_key`, `lubelogger_password`) were stored as plain strings in the Pydantic `BotConfig` model, exposing them to leakage if a validation error occurs or the object is stringified via `repr`. In addition, `bot/services/lubelogger_client.py` only scrubbed the API key from API error responses but left the Basic Auth password unprotected.
**Learning:** Pydantic settings are prone to logging raw configuration values in validation errors or logging if they are not explicitly typed as `SecretStr`. Error response scrubbing must cover all potential authentication mechanisms (e.g. Basic Auth alongside API Key).
**Prevention:** Always use Pydantic's `SecretStr` for sensitive credential fields in configuration models. Ensure that custom response sanitization explicitly masks all known credential variables in use by the client.
