# Implementation Plan: LubeLogger Telegram Bot

## Overview

Build a Python async Telegram bot that interfaces with LubeLogger's REST API, enabling vehicle owners to register fuel fill-ups, service records, and odometer readings via short commands. The bot runs as a Docker container in polling mode with SQLite-backed offline resilience and multi-language support.

Implementation follows a bottom-up approach: scaffolding → config → models → database → services → handlers → wiring → tests → documentation → deployment.

## Tasks

- [x] 1. Project scaffolding and configuration
  - [x] 1.1 Create project structure and pyproject.toml
    - Create directory structure: `bot/`, `bot/handlers/`, `bot/services/`, `bot/middleware/`, `bot/models/`, `bot/locales/`, `tests/`
    - Create `pyproject.toml` with `uv` project config, dependencies (`python-telegram-bot[job-queue]`, `httpx`, `pydantic`, `pydantic-settings`, `aiosqlite`), dev dependencies (`pytest`, `hypothesis`, `pytest-asyncio`, `ruff`), ruff config, and pytest config
    - Create `__init__.py` files for all packages
    - Create `Dockerfile` (Python 3.11-slim base, uv install, copy source, CMD)
    - Create `docker-compose.yml` with bot service alongside LubeLogger, volume for SQLite, env vars
    - Create `.env.example` documenting all required environment variables
    - _Requirements: NF-2.1, NF-2.2, NF-2.3, NF-4.1, NF-4.2_

  - [x] 1.2 Implement application configuration module (`bot/config.py`)
    - Implement `BotConfig` class using `pydantic_settings.BaseSettings`
    - Fields: `telegram_bot_token`, `lubelogger_url`, `lubelogger_api_key`, `allowed_user_ids` (list[int] from comma-separated env), `queue_retry_interval` (default 300), `http_timeout` (default 10), `max_retry_attempts` (default 3), `db_path` (default "/data/bot.db")
    - Add startup validation that raises `ConfigurationError` for missing required vars
    - _Requirements: 1.3, 1.4, 2.2, 2.3, 12.1, 12.2, 12.3_

- [x] 2. Data models and custom exceptions
  - [x] 2.1 Create custom exception hierarchy (`bot/exceptions.py`)
    - Implement `BotError` base exception
    - Implement `ConfigurationError`, `ParseError` (with command + hint), `LubeLoggerUnreachableError`, `LubeLoggerApiError` (with status_code + message)
    - _Requirements: NF-4.1_

  - [x] 2.2 Create input data models (`bot/models/inputs.py`)
    - Implement `FuelInput`, `ServiceInput`, `OdometerInput` dataclasses for raw parsed user input
    - Fields as strings (pre-validation), with optional date and boolean flags
    - _Requirements: 4.2, 5.2, 6.1, 9.1, 9.2, 9.3_

  - [x] 2.3 Create Pydantic validation models (`bot/models/validators.py`)
    - Implement `GasRecordModel` with constraints: odometer gt=0, liters gt=0, cost ge=0, date default today
    - Implement `ServiceRecordModel` with constraints: odometer gt=0, cost ge=0, description min_length=1 + whitespace validator
    - Implement `OdometerRecordModel` with constraints: odometer gt=0, date default today
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.3, 5.4, 5.5, 5.6, 6.3, 6.4, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 2.4 Create API payload models (`bot/models/payloads.py`)
    - Implement `GasRecordPayload` with all-string fields matching LubeLogger format, `from_validated()` classmethod
    - Implement `ServiceRecordPayload` with all-string fields, `from_validated()` classmethod
    - Implement `OdometerRecordPayload` with all-string fields, `from_validated()` classmethod
    - _Requirements: 4.9, 5.7, 6.5_

  - [x] 2.5 Create API response and database models (`bot/models/responses.py`)
    - Implement `ApiResponse` model (success, message, data)
    - Implement `Vehicle` model with `display_name` property and `licensePlate` alias
    - Implement `QueueItem` model (id, user_id, vehicle_id, record_type, payload, status, retry_count, timestamps)
    - Implement `UserConfig` model (user_id, active_vehicle_id, language, updated_at)
    - _Requirements: 3.1, 8.1_

- [x] 3. Checkpoint - Verify models
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Database layer
  - [x] 4.1 Implement SQLite database initialization (`bot/services/database.py`)
    - Create async function to initialize database with schema (queue table + indexes, user_config table)
    - Use `aiosqlite` for async SQLite access
    - Implement `get_db()` context manager for connection management
    - _Requirements: 8.7, 11.1, NF-2.3_

- [x] 5. Service layer
  - [x] 5.1 Implement Config Store (`bot/services/config_store.py`)
    - Implement `ConfigStore` class with async methods: `get_active_vehicle`, `set_active_vehicle`, `get_language`, `set_language`
    - Store per-user preferences keyed by Telegram user ID in SQLite
    - Load preferences on startup
    - _Requirements: 3.2, 3.4, 11.1, 11.2, 11.3, 11.4, NF-5.5_

  - [x] 5.2 Write property tests for Config Store
    - **Property 4: Config persistence round-trip**
    - **Property 5: Multi-user config isolation**
    - **Validates: Requirements 3.2, 3.4, 11.1, 11.2, 11.3, 11.4**

  - [x] 5.3 Implement LubeLogger HTTP client (`bot/services/lubelogger_client.py`)
    - Implement `LubeLoggerClient` with shared `httpx.AsyncClient` and `x-api-key` header
    - Methods: `add_gas_record`, `add_service_record`, `add_odometer_record`, `get_vehicles`, `get_latest_odometer`, `get_latest_gas_record`, `health_check`
    - Raise `LubeLoggerUnreachableError` on timeout/connection, `LubeLoggerApiError` on non-success
    - Ensure API key never appears in logs or error messages
    - _Requirements: 2.1, 2.4, 4.9, 4.10, 5.7, 5.8, 6.5, 6.6, 7.1, 7.2, 7.3, NF-1.3, NF-3.1_

  - [x] 5.4 Write property test for API key non-leakage
    - **Property 3: API key non-leakage**
    - **Validates: Requirements 2.4, NF-3.1, NF-3.2**

  - [x] 5.5 Implement Queue Service (`bot/services/queue_service.py`)
    - Implement `QueueService` class with: `enqueue`, `get_pending`, `mark_sent`, `mark_failed`, `increment_retry`, `get_pending_count`, `flush`
    - FIFO ordering (oldest first) via ORDER BY created_at
    - Retry logic: stop processing on unreachable, increment count on API error, mark failed at max_retry_attempts
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 5.6 Write property tests for Queue Service
    - **Property 12: Queue FIFO ordering**
    - **Property 13: Queue enqueue-dequeue consistency**
    - **Property 14: Queue retry exhaustion marks failure**
    - **Validates: Requirements 8.1, 8.4, 8.5, 8.7, 8.8**

  - [x] 5.7 Implement Command Parser (`bot/services/command_parser.py`)
    - Implement `CommandParser` with static methods: `parse_fuel`, `parse_service`, `parse_odometer`, `normalize_decimal`, `format_fuel`, `format_service`, `format_odometer`
    - Accept both dot and comma as decimal separators
    - Handle quoted description for service records
    - Raise `ParseError` with usage hint on invalid format
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 5.8 Write property tests for Command Parser
    - **Property 6: Command parsing round-trip**
    - **Property 7: Decimal separator normalization**
    - **Property 8: Fuel command argument parsing**
    - **Validates: Requirements 9.1, 9.5, 9.6**

- [x] 6. Checkpoint - Verify service layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Internationalization and auth
  - [x] 7.1 Implement i18n module (`bot/i18n.py`) and locale files
    - Create `bot/locales/en.json` with all user-facing message keys (welcome, confirmations, errors, usage hints)
    - Create `bot/locales/it.json` with Italian translations
    - Implement `get_text(key, lang, **kwargs)` with in-memory cache, English fallback, and `{placeholder}` formatting
    - _Requirements: NF-5.1, NF-5.2, NF-5.3, NF-5.4_

  - [x] 7.2 Implement auth middleware (`bot/middleware/auth.py`)
    - Create `create_auth_filter(allowed_user_ids)` function returning `filters.User` instance
    - Unauthorized users silently ignored (no response, no content logging)
    - _Requirements: 1.1, 1.2, NF-3.3_

  - [x] 7.3 Write property tests for auth filter and whitelist parsing
    - **Property 1: Auth filter correctness**
    - **Property 2: Whitelist parsing round-trip**
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 8. Telegram handlers
  - [x] 8.1 Implement vehicle handler (`bot/handlers/vehicle.py`)
    - `/vehicle` command: query LubeLogger for vehicles, present inline keyboard
    - Callback query handler: store selection in ConfigStore, confirm to user
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 8.2 Implement fuel handler (`bot/handlers/fuel.py`)
    - `/fuel` with args: parse → validate → submit → confirm or queue
    - `/fuel` without args: start conversation flow (odometer → liters → cost → full-tank flag)
    - Support `--vehicle <id>` override
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 3.5_

  - [x] 8.3 Implement service handler (`bot/handlers/service.py`)
    - `/service` with args: parse → validate → submit → confirm or queue
    - `/service` without args: start conversation flow (odometer → description → cost)
    - Support `--vehicle <id>` override
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 3.5_

  - [x] 8.4 Implement odometer handler (`bot/handlers/odometer.py`)
    - `/km` with arg: parse → validate → submit → confirm or queue
    - `/km` without arg: prompt for odometer reading
    - Support `--vehicle <id>` override
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 3.5_

  - [x] 8.5 Implement query handler (`bot/handlers/query.py`)
    - `/last fuel`: fetch and display latest gas record
    - `/last km`: fetch and display latest odometer record
    - `/status`: check LubeLogger reachability + queue status
    - `/queue`: display pending record count and types
    - Handle unreachable LubeLogger with user-friendly message
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.6_

  - [x] 8.6 Implement settings handler (`bot/handlers/settings.py`)
    - `/lang`: present language options, persist selection in ConfigStore
    - `/start`: welcome message, prompt vehicle selection if no active vehicle
    - _Requirements: 12.4, NF-5.5_

- [x] 9. Checkpoint - Verify handlers
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Application wiring and entry point
  - [x] 10.1 Implement main entry point (`bot/main.py`)
    - Load and validate config (exit non-zero on failure with log)
    - Initialize database (create tables if not exist)
    - Create shared `httpx.AsyncClient` and `LubeLoggerClient`
    - Create `QueueService` and `ConfigStore` instances
    - Build `Application` with auth filter applied to all handlers
    - Register all command handlers and conversation handlers
    - Set up job_queue for queue retry (every 5 min)
    - Log startup info (LubeLogger URL without key, number of allowed users)
    - Start polling
    - _Requirements: 1.3, 1.4, 2.2, 2.3, 8.3, 12.1, 12.2, 12.3, NF-1.3, NF-2.4_

- [x] 11. Validation and payload property tests
  - [x] 11.1 Write property tests for validation models
    - **Property 9: Validation acceptance of valid inputs**
    - **Property 10: Validation rejection of invalid inputs**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7**

  - [x] 11.2 Write property test for payload serialization
    - **Property 11: Payload serialization produces all-string fields**
    - **Validates: Requirements 4.9, 5.7, 6.5**

- [x] 12. Unit and integration tests
  - [x] 12.1 Write unit tests for LubeLogger client
    - Test x-api-key header inclusion on all requests
    - Test `LubeLoggerUnreachableError` on timeout/connection failure
    - Test `LubeLoggerApiError` on non-success status codes
    - Mock httpx responses
    - _Requirements: 2.1, 2.4_

  - [x] 12.2 Write unit tests for handlers and i18n
    - Test conversation flow initiation (fuel, service, odometer without args)
    - Test default date/flag values
    - Test welcome message and vehicle selection prompt
    - Test locale fallback (missing key → English)
    - Test placeholder formatting
    - _Requirements: 4.1, 4.6, 4.7, 4.8, 5.1, 5.6, 6.2, 6.4, 12.4, NF-5.1_

  - [x] 12.3 Write integration tests for end-to-end command flows
    - Test full fuel command → mock LubeLogger → verify confirmation
    - Test offline flow: command → unreachable → queue → flush → verify send
    - Test vehicle selection: `/vehicle` → mock API → select → verify persistence
    - Test unauthorized user message is silently dropped
    - _Requirements: 1.1, 4.9, 4.10, 8.1, 8.2, 8.4_

- [x] 13. Checkpoint - Full test suite green
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Documentation and deployment
  - [x] 14.1 Write README.md
    - Concise intro: problem solved, key strengths (offline resilience, quick entry, Docker-ready)
    - Quick Start section (5 steps or fewer)
    - Commands Reference section with usage examples for each command
    - Configuration section documenting all environment variables
    - Docker Compose section showing bot alongside LubeLogger
    - Architecture section (brief overview for contributors)
    - Contributing section with development setup instructions (`uv sync`, `uv run pytest`, `uv run ruff check`)
    - Written in English with clear, engaging tone for open-source discovery
    - _Requirements: NF-4.4, NF-4.5_

  - [x] 14.2 Verify Docker build and deployment
    - Ensure `Dockerfile` builds successfully
    - Ensure `docker-compose.yml` is valid and services start correctly
    - Verify SQLite volume mount works for persistence
    - Verify no exposed ports (polling mode only)
    - _Requirements: NF-2.1, NF-2.2, NF-2.3, NF-2.4, NF-3.4_

- [x] 15. Final checkpoint - Complete verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and default values
- The bot uses Python 3.11+ with full type annotations, `uv` for package management, `ruff` for linting
- All I/O operations use async/await with `httpx.AsyncClient` and `aiosqlite`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5"] },
    { "id": 3, "tasks": ["4.1", "7.1"] },
    { "id": 4, "tasks": ["5.1", "5.3", "5.7", "7.2"] },
    { "id": 5, "tasks": ["5.2", "5.4", "5.5", "5.8", "7.3"] },
    { "id": 6, "tasks": ["5.6", "8.1", "8.5", "8.6"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 8, "tasks": ["10.1"] },
    { "id": 9, "tasks": ["11.1", "11.2", "12.1", "12.2"] },
    { "id": 10, "tasks": ["12.3"] },
    { "id": 11, "tasks": ["14.1", "14.2"] }
  ]
}
```
