# Implementation Plan: Improve UX

## Overview

Rework the interaction model into a persistent navigation keyboard plus one self-updating
Card_Message per operation, driven by a single unified `ConversationHandler`, with smart defaults
from the vehicle's own history, a summary/confirmation step with single-field editing, richer
post-save feedback, and the six defect fixes of Requirement 13.

Implementation is bottom-up so that no task depends on code that does not exist yet:
dependency bump and locale/key foundations, SQLite migration and local state, loose read models and
client extensions, callback codec, pure modules (keyboards, formatters, consumption), CardService and
RecordSubmitter, the unified flow, offline path, menu/onboarding/command registry, Options and Latest
menus, backward compatibility and defect fixes, wiring, test updates, documentation.

Language: Python 3.11+, full type annotations, `uv` for dependencies, `ruff` for lint and format,
`pytest` + `hypothesis` for tests. All property tests use `@settings(max_examples=100)` and carry the
tag `# Feature: improve-ux, Property N: <title>` in the test docstring.

## Tasks

- [x] 1. Foundations: dependencies, field tables, locale keys
  - [x] 1.1 Bump python-telegram-bot to `>=21.0`
    - In `pyproject.toml`, change `python-telegram-bot[job-queue]>=20.0` to `>=21.0`
    - `is_persistent` on `ReplyKeyboardMarkup` requires Bot API 6.4 support, which landed in
      python-telegram-bot 20.1; pin to 21.x to stay on a supported line
    - Refresh the lockfile with `uv sync` and confirm the existing suite still imports
    - _Requirements: 1.1_

  - [x] 1.2 Create the field-table module (`bot/flows/definitions.py`)
    - Create the `bot/flows/` package with `__init__.py`
    - Define `FlowKind` (FUEL, SERVICE, ODOMETER), `FieldKind` (INT, DECIMAL, TEXT, CHOICE),
      `MenuAction` (fuel, service, odometer, latest, options), frozen `FieldSpec`
      (key, kind, prompt_key, label_key, placeholder_key, error_key, choices)
    - Define `FIELDS`: fuel = odometer, liters, cost, is_fill_to_full; service = odometer,
      description, cost; odometer = odometer. Full tank is `CHOICE`
    - Implement `field_count`, `field_at`, `field_index`
    - Pure module: no imports from `bot.i18n`, so the i18n index can import `MenuAction` without a cycle
    - _Requirements: 4.1, 4.2, 4.5, 13.5_

  - [x] 1.3 Rewrite the locale files under the new key convention
    - In `bot/locales/en.json` and `bot/locales/it.json`, add every new key with the design prefixes:
      `ask_`, `ph_`, `field_`, `btn_`, `menu_`, `card_`, `alert_`, `cmd_`, `fmt_`, plus
      `vehicle_fallback_name`, `lang_prompt`, and the queued/saved confirmation templates
    - Delete the deprecated `prompt_odometer`, `fuel_ask_odometer`, `fuel_ask_liters`,
      `fuel_ask_cost`, `fuel_ask_full_tank`, `service_prompt_odometer`,
      `service_prompt_description`, `service_prompt_cost`
    - Keep both files key-for-key identical; HTML markup only inside templates, never in values
    - `menu_*` labels each carry an emoji plus a text word: fuel, service, odometer, latest, options
    - _Requirements: 1.7, 13.4, 13.5, NF-3.1, NF-3.3_

  - [x] 1.4 Extend the i18n module (`bot/i18n.py`)
    - Add `available_locales()`, `get_keys(lang)`, `menu_label_index()` (cached, built from the five
      `menu_*` keys of every locale file, normalized with `strip().casefold()`), `resolve_menu_label(text)`
    - The index is the closed allowlist: a label rendered in one locale keeps resolving after `/lang`
    - _Requirements: 1.6, 11.5, NF-3.2, NF-3.4_

  - [x] 1.5 Write property test for locale completeness and key convention
    - **Property 6: Locale files are complete and follow the key convention**
    - `tests/test_i18n_parity.py::test_property_locale_key_parity`
    - **Validates: Requirements 13.4, 13.5, NF-1.3, NF-3.1**

- [x] 2. Local persistence: migration, active vehicle name, odometer tracker
  - [x] 2.1 Add the schema migration mechanism (`bot/services/database.py`)
    - Keep `executescript(_SCHEMA)` for the base tables, then read `PRAGMA user_version`
    - Define `_MIGRATIONS` and apply, in order and in one transaction, every migration whose version
      is greater than `user_version`, then set `PRAGMA user_version` to the latest
    - Migration 1: `ALTER TABLE user_config ADD COLUMN active_vehicle_name TEXT NOT NULL DEFAULT ''`
      and `CREATE TABLE IF NOT EXISTS vehicle_state (vehicle_id INTEGER PRIMARY KEY,
      last_odometer INTEGER NOT NULL, last_odometer_date TEXT,
      last_odometer_source TEXT NOT NULL DEFAULT 'bot', updated_at TEXT NOT NULL)`
    - Idempotent: a second `init_db` on the same file must change nothing
    - _Requirements: 5.5, NF-2.5_

  - [x] 2.2 Write unit tests for the migration
    - `tests/test_database_migration.py`: a database created with the pre-migration schema gains the
      column and the table, existing `user_config` rows stay intact, a second `init_db` is a no-op,
      and the migrated schema contains exactly the expected columns and nothing more
    - _Requirements: 5.5, NF-2.5_

  - [x] 2.3 Persist the Active_Vehicle_Name (`bot/services/config_store.py`)
    - Add `get_active_vehicle_name(user_id)`, accept an optional `name` on `set_active_vehicle`,
      preserving the stored name when it is omitted, and add `get_all_languages()` returning
      `{user_id: language}` for the command registry
    - _Requirements: 5.13, 6.4, 8.6, NF-2.5_

  - [x] 2.4 Write property test for active vehicle name persistence
    - **Property 33: The active vehicle name round-trips through persistence**
    - `tests/test_config_store.py::test_property_vehicle_name_roundtrip`
    - **Validates: Requirements 5.13, 8.6**

  - [x] 2.5 Implement the odometer tracker (`bot/services/odometer_tracker.py`)
    - Frozen `OdometerReference(value, on_date, source)` and the pure `fold(current, candidate)`
      returning `candidate` only when its value is strictly greater
    - `OdometerTracker` with `get_reference` (local read, never network), `observe`,
      `observe_snapshot`, `observe_records`, all writing `vehicle_state` keyed by vehicle
    - `get_reference` returns `None` when nothing is known locally
    - _Requirements: 5.4, 5.5, 5.6, NF-2.3, NF-2.5_

  - [x] 2.6 Write property test for the odometer fold
    - **Property 1: Last_Known_Odometer fold is maximal and order-independent**
    - `tests/test_odometer_tracker.py::test_property_odometer_fold_is_max`
    - **Validates: Requirements 5.4**

  - [x] 2.7 Write property test for persisted odometer monotonicity
    - **Property 2: Persisted Last_Known_Odometer never decreases**
    - `tests/test_odometer_tracker.py::test_property_odometer_monotonic`
    - **Validates: Requirements 5.5**

- [x] 3. Loose read models and LubeLogger client extensions
  - [x] 3.1 Implement the tolerant coercion helpers (`bot/models/loose.py`)
    - `parse_loose_number`, `parse_loose_int`, `parse_loose_bool`, `parse_loose_date(day_first=True)`
    - Numbers: pass through numerics; for strings strip, return `None` on empty, and treat the last of
      `,`/`.` as the decimal separator when both occur
    - Booleans accept `True/False`, `"True"/"False"`, `"true"/"false"`, `"1"/"0"`, `1/0`
    - Dates try ISO first, then `%d/%m/%Y`, `%m/%d/%Y`, `%d.%m.%Y`, `%d-%m-%Y`, `%Y/%m/%d`,
      ordered by `day_first`
    - _Requirements: 12.4, NF-6.1_

  - [x] 3.2 Implement the read models (`bot/models/records.py`)
    - `LooseRecord` base with `populate_by_name=True`, `extra="allow"`; `GasRecord` (including
      `fuel_economy` aliased `fuelEconomy`, `is_fill_to_full`, `missed_fuel_up`), `ServiceRecord`,
      `OdometerRecord`, `VehicleSnapshot(vehicle, last_reported_odometer)`
    - Wire the loose parsers as `mode="before"` field validators
    - In `bot/models/responses.py`, change `Vehicle.display_name` to return `""` when no name can be
      built, so the caller can substitute a localized fallback
    - _Requirements: 13.6, NF-6.1, NF-6.3_

  - [x] 3.3 Write property test for loose parsing equivalence
    - **Property 29: Every representation LubeLogger can emit parses to the same value**
    - `tests/test_records_parsing.py::test_property_loose_parsing_equivalence`
    - **Validates: Requirements NF-6.1**

  - [x] 3.4 Extend the LubeLogger client (`bot/services/lubelogger_client.py`)
    - Send `culture-invariant: true` in the default headers
    - Add `get_vehicle_snapshots()` targeting `/api/vehicle/info`, falling back once to
      `/api/vehicles` on `LubeLoggerApiError` and returning snapshots with
      `last_reported_odometer=None`
    - Add `get_gas_records`, `get_service_records`, `get_odometer_records` returning the read models
    - Never send `useMPG` / `useUKMPG`, so the reported figure stays volume per 100 distance units
    - Keep `get_latest_gas_record` / `get_latest_odometer` for the untouched `/last` path
    - _Requirements: 5.11, 6.5, NF-2.1, NF-2.2, NF-6.1, NF-6.2_

  - [x] 3.5 Write unit tests for the new client methods
    - `tests/test_lubelogger_client.py`: the invariant header is present on every request, the
      `/api/vehicle/info` 404 fallback issues exactly one retry against `/api/vehicles`, snapshots
      parse `lastReportedOdometer`, and the API key still never appears in logs or errors
    - _Requirements: 5.11, NF-4.3, NF-6.1_

- [ ] 4. Checkpoint - Foundations, persistence and read models
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Callback codec and Consumption_Metric
  - [x] 5.1 Implement the callback_data codec (`bot/callbacks.py`)
    - `CallbackAction` StrEnum with the two-letter values of the design, `NO_TOKEN = "-"`,
      `TELEGRAM_CALLBACK_DATA_LIMIT = 64`
    - `new_token()` via `secrets.token_urlsafe(6)`, `encode(action, token, arg)`,
      `decode(data) -> Callback(action, token, arg)`
    - Grammar `action ":" token [ ":" arg ]`; `arg` carries only ordinals or server-side entity ids,
      never a field value
    - _Requirements: 11.1, 11.3_

  - [x] 5.2 Write property test for the callback codec
    - **Property 3: callback_data round-trips and stays within 64 bytes**
    - `tests/test_callbacks.py::test_property_callback_data_roundtrip_and_budget`
    - **Validates: Requirements 11.3, NF-1.4**

  - [x] 5.3 Implement the consumption service (`bot/services/consumption.py`)
    - `CONSUMPTION_UNIT = "L/100 km"`, frozen `FuelPoint` and `ConsumptionResult(value, unit, estimated)`
    - `estimate(current, previous)` returning `None` unless a previous record exists, both records are
      fill-to-full, neither has missed-fuel-up, the odometer delta is strictly positive and the volume
      is strictly positive; otherwise `liters / delta * 100` quantized to two decimals, `estimated=True`
    - `resolve(reported, current, previous)` preferring a strictly positive reported value with
      `estimated=False`, and otherwise delegating to `estimate` — a reported `0` means "not available"
      (design finding F2), never zero consumption
    - _Requirements: 6.5, 6.6, 6.7, 6.8, 6.9, NF-1.5, NF-6.2_

  - [x] 5.4 Write property test for the consumption conditions
    - **Property 15: The Consumption_Metric is produced only when every condition holds**
    - `tests/test_consumption.py::test_property_consumption_conditions`
    - **Validates: Requirements 6.7, 6.8, NF-1.5**

  - [x] 5.5 Write property test for the consumption source preference
    - **Property 16: The reported fuel economy wins, and a non-positive one is treated as absent**
    - `tests/test_consumption.py::test_property_consumption_source_preference`
    - **Validates: Requirements 6.5, 6.6, 6.9, NF-6.2**

- [x] 6. Keyboard builders
  - [x] 6.1 Implement the keyboard module (`bot/keyboards.py`)
    - Pure synchronous builders returning Telegram markup from plain arguments:
      `menu_keyboard`, `flow_step_keyboard`, `choice_keyboard`, `summary_keyboard`,
      `field_picker_keyboard`, `regression_keyboard`, `confirmation_keyboard`,
      `latest_menu_keyboard`, `latest_record_keyboard`, `options_menu_keyboard`,
      `options_back_keyboard`, `vehicle_keyboard`, `language_keyboard`, `abandon_keyboard`,
      plus the `all_callback_data(lang)` test helper
    - `menu_keyboard`: three write buttons on row one, Latest and Options on row two,
      `is_persistent=True`, `resize_keyboard=True`, optional `input_field_placeholder` from a locale key,
      `one_time_keyboard` never set
    - `confirmation_keyboard(queued=False)` yields Log another + Latest; `queued=True` yields
      Log another only
    - Every in-flow button embeds the Flow_Token; every screen reachable from Options or Latest
      carries exactly one back button
    - _Requirements: 1.1, 1.2, 1.7, 1.9, 1.11, 3.8, 4.3, 4.5, 4.6, 4.8, 4.10, 5.7, 6.10, 9.4, 10.1, 10.3, 11.1, 11.3, NF-1.1_

  - [x] 6.2 Write property test for in-flow keyboard invariants
    - **Property 4: In-flow keyboards carry the flow token, a cancel action, and no field values**
    - `tests/test_keyboards.py::test_property_inflow_keyboard_invariants`
    - **Validates: Requirements 1.11, 4.3, 4.5, 4.10, 5.7, 6.10, 9.4, 10.3, 11.1**

  - [x] 6.3 Write property test for Menu_Label resolution
    - **Property 7: Menu_Labels are localized and resolvable across locales**
    - `tests/test_keyboards.py::test_property_menu_label_resolution`
    - **Validates: Requirements 1.2, 1.5, 1.6, 1.7, 1.13, NF-3.2**

  - [x] 6.4 Write unit tests for the Menu_Keyboard flags and callback budget
    - `tests/test_keyboards.py`: `is_persistent` and `resize_keyboard` are set, the placeholder is
      rendered only when a key is supplied, and every string of `all_callback_data(lang)` stays within
      64 UTF-8 bytes in every locale
    - _Requirements: 1.1, 3.8, NF-1.4_

- [x] 7. Message rendering
  - [x] 7.1 Implement the view dataclasses (`bot/flows/views.py`)
    - Frozen `FieldEntry`, `CardView`, `SummaryView`, `ConfirmationView` holding plain data only, so
      renderers are callable from a test with literals
    - _Requirements: NF-1.2_

  - [x] 7.2 Implement the core formatters (`bot/formatters.py`)
    - `esc` (single `html.escape`), `fmt_plain`, `fmt_display`, `fmt_int`, `fmt_date`,
      `fmt_date_short`, all reading separators and date patterns from the `fmt_*` locale keys
    - `render_progress` returning `None` when the flow has a single data-entry field,
      `render_card`, `render_summary`, `render_regression`, `render_cancelled`
    - Every value from a user or from the API passes through `esc` exactly once; literal HTML lives
      only in the locale templates
    - _Requirements: 3.3, 4.1, 4.2, 4.4, 4.6, 4.11, 5.8, 11.7, NF-1.2, NF-3.3, NF-6.3_

  - [x] 7.3 Implement the confirmation, latest, options and welcome renderers (`bot/formatters.py`)
    - `render_confirmation`, `render_queued`, `render_abandon_prompt`, `render_latest_fuel`,
      `render_latest_odometer`, `render_odometer_reference` (empty string on `None`), `render_welcome`
    - Confirmations name the vehicle from the persisted Active_Vehicle_Name and list every field of
      their record kind; the consumption line is omitted entirely when there is no value, and states
      its unit when there is one; the queued rendering lists the same values plus the automatic-sync
      notice and never a consumption figure
    - Unnameable vehicles render through `vehicle_fallback_name`
    - _Requirements: 5.3, 5.6, 6.1, 6.2, 6.3, 6.4, 6.6, 6.9, 8.1, 8.4, 9.2, 9.3, 10.4, 10.5, 13.6_

  - [x] 7.4 Write property test for the Progress_Indicator
    - **Property 9: The Progress_Indicator counts only data-entry steps**
    - `tests/test_formatters.py::test_property_progress_indicator`
    - **Validates: Requirements 4.1, 4.2**

  - [x] 7.5 Write property test for card completeness
    - **Property 10: The card always shows what has been collected and what is being asked**
    - `tests/test_formatters.py::test_property_card_contains_collected`
    - **Validates: Requirements 3.3, 4.11**

  - [x] 7.6 Write property test for summary completeness
    - **Property 22: Summary_State lists every collected value**
    - `tests/test_formatters.py::test_property_summary_completeness`
    - **Validates: Requirements 4.6**

  - [x] 7.7 Write property test for confirmation completeness
    - **Property 17: A confirmation names the vehicle and lists every field of its record type**
    - `tests/test_formatters.py::test_property_confirmation_completeness`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

  - [x] 7.8 Write property test for queued/saved parity
    - **Property 24: A queued confirmation lists the same values as a saved one**
    - `tests/test_formatters.py::test_property_queued_matches_saved`
    - **Validates: Requirements 9.2, 9.3**

  - [x] 7.9 Write property test for HTML escaping
    - **Property 28: Every interpolated value is escaped exactly once**
    - `tests/test_formatters.py::test_property_html_escaping`
    - Generators must include `<`, `>`, `&`, `"`, emoji and empty strings, so a description such as
      `oil change <5000km` is covered
    - **Validates: Requirements 11.7, NF-6.3**

  - [x] 7.10 Write property test for decimal round-trip
    - **Property 30: Decimal separators round-trip in every locale**
    - `tests/test_formatters.py::test_property_decimal_roundtrip`
    - **Validates: Requirements 12.4, NF-3.3**

  - [x] 7.11 Write property test for the localized vehicle fallback
    - **Property 34: An unnameable vehicle falls back to a localized label**
    - `tests/test_formatters.py::test_property_vehicle_fallback_localized`
    - **Validates: Requirements 13.6**

- [x] 8. Checkpoint - Pure modules complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Card_Message lifecycle
  - [x] 9.1 Add the FakeBot fixture (`tests/conftest.py`)
    - Recording fake exposing `send_message`, `edit_message_text`, `edit_message_reply_markup`,
      `delete_message`, `answer_callback_query`, `set_my_commands`, with per-call payload capture and
      injectable failures, plus temporary-database and locale fixtures
    - _Requirements: NF-1.1, NF-1.2_

  - [x] 9.2 Implement the card service (`bot/services/card_service.py`)
    - `open`, `update`, `finalize`, `strip_markup`, `consume_prompt_reply`, all HTML parse mode
    - `update` swallows `BadRequest("message is not modified")` and returns the same id; on any other
      `TelegramError` it sends a new message with identical text and markup and returns its id, which
      the caller adopts as the new card
    - `finalize` guarantees the markup is either absent or the follow-up keyboard
    - `consume_prompt_reply` is the only `delete_message` caller in the codebase and swallows every
      `TelegramError` at DEBUG level
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.9, 7.3, NF-2.4, NF-4.2_

  - [x] 9.3 Write property test for the edit-failure fallback
    - **Property 12: A failed card edit preserves the content and adopts the new message**
    - `tests/test_card_service.py::test_property_edit_failure_fallback`
    - **Validates: Requirements 3.7**

  - [x] 9.4 Write property test for the deletion scope
    - **Property 13: The only deleted messages are typed replies to bot prompts**
    - `tests/test_card_service.py::test_property_deleted_set_equals_prompt_replies`
    - **Validates: Requirements 3.4, 3.5, NF-4.2**

  - [x] 9.5 Write unit tests for the card service error branches
    - `tests/test_card_service.py`: "message is not modified" is swallowed and the id is unchanged, a
      delete failure is logged at DEBUG and does not raise, `finalize` never leaves a step keyboard
    - _Requirements: 3.6, 3.9_

- [x] 10. Submission service
  - [x] 10.1 Implement the record submitter (`bot/services/record_submitter.py`)
    - `SubmitOutcome(status, consumption, vehicle_name)` and `submit(user_id, vehicle_id, kind, values)`
    - Build the validated model, build the payload, call the matching `add_*_record`
    - On a successful fuel save, one follow-up `get_gas_records` supplies the reported `fuelEconomy`
      and the previous record for `estimate`, and the same response is folded into the tracker; if that
      follow-up fails the outcome stays `saved` with no consumption
    - On `LubeLoggerUnreachableError`, enqueue the record through the existing `QueueService`, still
      observe the odometer, and return `queued` with no consumption
    - Single entry point for both the guided path and the inline-argument path
    - _Requirements: 5.5, 6.5, 6.6, 6.9, 9.1, 9.3, 12.2, 12.5_

  - [x] 10.2 Write property test for queue round-trip
    - **Property 23: Enqueuing loses nothing**
    - `tests/test_offline_flow.py::test_property_queue_roundtrip`
    - **Validates: Requirements 9.1**

- [x] 11. Unified conversation flow
  - [x] 11.1 Create the flow skeleton, state and guard (`bot/handlers/record_flow.py`)
    - States `COLLECT, SUMMARY, REGRESSION, ABANDON`; `FlowState` dataclass in
      `context.user_data["flow"]`; one `clear_flow(context)` used by every terminal branch
    - `guard(update, context, cb)` answering every callback query exactly once, rejecting
      non-whitelisted senders, and rejecting a mismatched Flow_Token with the localized
      `alert_expired` alert without touching any state
    - `get_record_conversation_handler(auth_filter)` with `allow_reentry=True` and the entry points
      for the three commands, the write Menu_Labels and the Log another callback
    - _Requirements: 4.12, 11.1, 11.2, 11.4, 11.8, 13.2_

  - [x] 11.2 Write property test for the callback guard
    - **Property 5: The callback guard answers once and rejects safely**
    - `tests/test_record_flow.py::test_property_callback_guard`
    - **Validates: Requirements 11.2, 11.4, 11.8**

  - [x] 11.3 Implement flow start with smart defaults
    - One live `get_vehicle_snapshots()` call, which doubles as connectivity probe and wake-up; fold
      the snapshots into the tracker and refresh the persisted Active_Vehicle_Name
    - Auto-select and persist the only available vehicle, announcing it once; reuse an already
      persisted active vehicle without prompting or re-announcing
    - On failure, continue with the persisted vehicle, name and local odometer reference
    - Read the reference locally, then open the Card_Message with the step keyboard, the collected
      values, the prompt, the Progress_Indicator and the reference line with its date and source
    - _Requirements: 3.1, 3.3, 5.1, 5.2, 5.3, 5.6, 5.7, 5.11, 5.12, 5.13, 9.6, NF-2.1, NF-2.2_

  - [x] 11.4 Write property test for the API call budget
    - **Property 14: A flow costs one API call at start and none per step**
    - `tests/test_record_flow.py::test_property_api_call_budget`
    - **Validates: Requirements 5.11, NF-2.1, NF-2.2, NF-2.3**

  - [x] 11.5 Write property test for one card per operation
    - **Property 11: One card message per operation, one edit per step**
    - `tests/test_record_flow.py::test_property_single_card_message`
    - **Validates: Requirements 3.1, 3.2, NF-2.4**

  - [x] 11.6 Implement value collection, choice buttons and suggestion reuse
    - `collect_value` validates the typed value, deletes it through `consume_prompt_reply`, advances
      the step index or returns to Summary_State when a single field was being edited, and on failure
      re-renders the same step with the field's localized error instead of ending the flow
    - `on_choice` handles closed-choice fields such as the full-tank flag; `on_keep_suggestion` accepts
      the offered value without retyping
    - Accept both comma and dot decimal separators; set the placeholder for each prompted field
    - _Requirements: 3.4, 3.8, 4.5, 4.9, 4.10, 4.11, 5.7, 12.4, 13.1, NF-2.3_

  - [x] 11.7 Write property test for invalid typed values
    - **Property 19: An invalid typed value never ends the flow**
    - `tests/test_record_flow.py::test_property_invalid_value_reprompts`
    - **Validates: Requirements 4.11, 13.1**

  - [x] 11.8 Implement the odometer regression gate
    - Enter `REGRESSION` only when the entered value is strictly lower than the reference, render the
      warning stating both values, offer confirm and re-enter alongside cancel
    - On confirmation set `regression_confirmed` and carry the entered value forward, with no further
      warning for the remainder of the flow; never reject the value outright
    - _Requirements: 5.8, 5.9, 5.10_

  - [x] 11.9 Write property test for the regression gate
    - **Property 21: An odometer regression warns and gates, but never rejects**
    - `tests/test_record_flow.py::test_property_odometer_regression_gate`
    - **Validates: Requirements 5.8, 5.9, 5.10**

  - [x] 11.10 Implement Summary_State, the Field_Picker and save
    - Render the summary listing every collected value with save, edit and cancel
    - Edit swaps the markup for the Field_Picker, one button per field labelled with its current value,
      without changing state; picking a field re-prompts that field alone and returns to the summary
    - Save calls `RecordSubmitter.submit` and finalizes the card into the saved confirmation with the
      Log another and Latest buttons, or into the queued confirmation with Log another only
    - On `LubeLoggerApiError`, render the localized API-error card and keep the values in the summary
    - _Requirements: 4.6, 4.7, 4.8, 4.9, 6.1, 6.2, 6.3, 6.10, 9.1, 9.2, 9.4_

  - [x] 11.11 Write property test for single-field editing
    - **Property 18: Editing one field from the Field_Picker preserves every other value**
    - `tests/test_record_flow.py::test_property_field_picker_preserves_values`
    - **Validates: Requirements 4.8, 4.9**

  - [x] 11.12 Implement cancellation and flow abandonment
    - The cancel button and `/cancel` share one implementation: discard the values, clear the flow
      state, edit the card to the cancellation notice with no inline keyboard
    - A Menu_Label arriving as a typed answer stores no value and moves to `ABANDON`, which asks for
      confirmation; confirming discards the values and starts the requested operation, declining
      returns to the state the flow came from
    - _Requirements: 3.9, 4.4, 4.12, 11.5, 11.6, 13.2_

  - [x] 11.13 Write property test for cancellation equivalence
    - **Property 20: Cancelling clears the flow, whichever way it is cancelled**
    - `tests/test_record_flow.py::test_property_cancel_equivalence`
    - **Validates: Requirements 4.4, 4.12, 13.2**

  - [x] 11.14 Write property test for Menu_Label navigation
    - **Property 27: A Menu_Label typed during a flow is navigation, not data**
    - `tests/test_record_flow.py::test_property_menu_label_is_navigation`
    - **Validates: Requirements 11.5, 11.6**

  - [x] 11.15 Implement the Log another shortcut
    - Start a fresh flow of the same kind on the same vehicle with a new Flow_Token, skipping vehicle
      selection and opening directly on the first data-entry prompt
    - Strip the inline keyboard from the previous confirmation, leaving its text intact
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 11.16 Write property test for Log another
    - **Property 26: Log another starts an equivalent fresh flow**
    - `tests/test_record_flow.py::test_property_log_another_fresh_flow`
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 11.17 Write property test for log privacy
    - **Property 35: Message content is never logged**
    - `tests/test_record_flow.py::test_property_no_message_content_logged`
    - **Validates: Requirements NF-4.1**

  - [x] 11.18 Write unit tests for the smart-default scenarios
    - `tests/test_record_flow.py`: single vehicle auto-selected, persisted and announced once; an
      already active vehicle triggers no notice; the reference line disappears when nothing is known
      locally and the instance is down
    - _Requirements: 5.1, 5.2, 5.6_

- [x] 12. Checkpoint - Guided flow working end to end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Offline path in the guided flow
  - [x] 13.1 Wire the queued outcome into the flow
    - Render the queued confirmation from the same values as a saved one, state that the record will
      sync automatically, omit the consumption figure, attach Log another only, and leave the retry
      job's existing user notification untouched
    - Degrade reference data to the locally persisted odometer and vehicle name so the flow completes
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 12.5_

  - [x] 13.2 Write property test for offline completion
    - **Property 25: A flow completes even when LubeLogger is unreachable throughout**
    - `tests/test_offline_flow.py::test_property_offline_flow_completes`
    - **Validates: Requirements 5.12, 9.6**

- [~] 14. Navigation menu, onboarding and command registration
  - [x] 14.1 Implement the menu handler (`bot/handlers/menu.py`)
    - `/start`: with no active vehicle send a welcome of at most three sentences plus the vehicle
      keyboard; selection persists id and name, edits the message into a confirmation and establishes
      the Menu_Keyboard; with an active vehicle send a short welcome-back naming it; when LubeLogger
      is unreachable explain the situation, suggest retrying later, and still establish the keyboard
    - Send the Menu_Keyboard only when it is first established or its content changes, never
      re-attaching it to later messages and never altering it during a flow
    - Route the reading Menu_Labels through `resolve_menu_label` to the Latest and Options screens
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 14.2 Write unit tests for onboarding and keyboard establishment
    - `tests/test_menu.py`: no vehicle, one vehicle, several vehicles, unreachable; the Menu_Keyboard
      is sent exactly once with `is_persistent` and `resize_keyboard`; no later message re-attaches it;
      the welcome text is at most three sentences in every locale
    - _Requirements: 1.1, 1.3, 1.4, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 14.3 Implement the command registry (`bot/services/command_registry.py`)
    - `COMMANDS` covering start, fuel, service, km, last, vehicle, status, queue, lang, cancel with
      their `cmd_` description keys; pure `commands_for(lang)`
    - `register_all(bot, config_store, allowed_user_ids)`: one `set_my_commands` per supported locale
      with `language_code`, one default call, then one per whitelisted user with `BotCommandScopeChat`
      and that user's stored language; each call individually wrapped so a `TelegramError` logs a
      warning and startup continues
    - `register_for_chat(bot, chat_id, lang)` called again after a language change
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 14.4 Write property test for the registered command list
    - **Property 8: The registered command list is complete in every locale**
    - `tests/test_command_registry.py::test_property_commands_complete`
    - **Validates: Requirements 2.1, 2.2**

  - [ ] 14.5 Write unit tests for command registration
    - `tests/test_command_registry.py`: per-locale defaults, per-chat scopes for two users with
      different languages, re-registration after `/lang`, and the failure path that logs at WARNING
      without interrupting startup
    - _Requirements: 2.3, 2.4, 2.5, 2.6_

- [x] 15. Options and Latest menus
  - [x] 15.1 Implement the Options_Menu handler (`bot/handlers/options.py`)
    - Send one message carrying the Options_Menu with vehicle, language, status and queue entries;
      every selection edits that same message in place; every reached screen carries a back button
      returning it to the Options_Menu
    - Vehicle selection and language selection stay off the Menu_Keyboard
    - _Requirements: 1.9, 1.10, 1.11, 1.12, 1.13_

  - [x] 15.2 Implement the Latest menu handler (`bot/handlers/latest.py`)
    - Send one message offering last fuel and last odometer; each selection edits the message in place
      and keeps a back button; an empty result and an unreachable instance both render as a notice with
      the back button preserved
    - Fold what is read into the odometer tracker
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 15.3 Write unit tests for the two menus
    - `tests/test_menus.py`: each Options and Latest entry edits the same message id, the back button
      restores the menu, an empty record and an unreachable instance keep the back button
    - _Requirements: 1.10, 1.11, 10.2, 10.4, 10.5_

- [x] 16. Backward compatibility and defect fixes
  - [x] 16.1 Route the inline-argument path through the submitter
    - Move the duplicated `_parse_vehicle_override` / `_extract_vehicle_override` helpers into one
      `parse_vehicle_override` in `bot/services/command_parser.py`
    - In `fuel.py`, `service.py`, `odometer.py`: with arguments parse, validate and submit through
      `RecordSubmitter`, bypassing card, summary and confirmation step, while still applying the
      odometer regression gate and rendering the rich confirmation; without arguments delegate to
      `record_flow.start_flow`, carrying a `--vehicle` override into the started flow
    - Remove the three per-module `ConversationHandler` factories
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 13.1_

  - [x] 16.2 Write property test for the vehicle override
    - **Property 31: The vehicle override is extracted without disturbing the other arguments**
    - `tests/test_compat.py::test_property_vehicle_override_roundtrip`
    - **Validates: Requirements 12.3**

  - [x] 16.3 Write property test for inline/guided agreement
    - **Property 32: Inline-argument mode and guided mode agree**
    - `tests/test_compat.py::test_property_inline_matches_guided`
    - **Validates: Requirements 12.1, 12.2**

  - [x] 16.4 Fix the vehicle and settings handlers
    - `vehicle.py`: build the keyboard from one `get_vehicle_snapshots()` call, store the id-to-name
      mapping in `user_data`, and resolve the selected name from it instead of issuing a second call;
      fall back to the localized label when the mapping is gone, never to a second fetch or to the
      untranslated `Vehicle #<id>`; persist id and name together
    - `settings.py`: read the prompt from `get_text("lang_prompt", lang)` instead of the hardcoded
      bilingual string, and call `command_registry.register_for_chat` after persisting the language
    - _Requirements: 2.5, 5.13, 8.6, 13.3, 13.4, 13.6_

  - [x] 16.5 Write unit test for the single vehicle fetch
    - `tests/test_vehicle_handler.py`: `/vehicle` plus its selection callback issue exactly one
      `get_vehicle_snapshots` call in total, and an unnameable vehicle renders the localized fallback
    - _Requirements: 13.3, 13.6_

  - [x] 16.6 Render the query commands through the formatters (`bot/handlers/query.py`)
    - `/last fuel` and `/last km` keep their behaviour and arguments but render through
      `formatters`, escape API values, and fold what they read into the odometer tracker
    - _Requirements: 5.4, 10.6, 11.7, NF-6.3_

- [x] 17. Application wiring
  - [x] 17.1 Wire everything into the entry point (`bot/main.py`)
    - Instantiate `CardService`, `OdometerTracker`, `RecordSubmitter` in `post_init` and publish them
      in `bot_data`; call `command_registry.register_all` there too
    - Replace the three per-flow conversation handlers with the unified one, register the menu,
      options and latest handlers, keep the existing vehicle, settings and query handlers and the
      retry job unchanged
    - Add a global `add_error_handler` logging the traceback and replying with a generic localized
      message
    - _Requirements: 1.12, 2.1, 2.3, 9.5, 11.7, 12.5_

- [ ] 18. Existing test updates
  - [ ] 18.1 Update the tests that assert intentionally changed behaviour
    - `tests/test_handlers_unit.py`: the three commands no longer own their own conversation states;
      assert delegation to the unified flow and the new `user_data["flow"]` shape
    - `tests/test_i18n.py`: replace the deprecated key assertions with the new convention keys
    - `tests/test_integration.py`, `tests/test_query_handler.py`, `tests/test_settings_handler.py`:
      update the message-format and prompt assertions this feature changes
    - Everything else must keep passing untouched
    - _Requirements: 13.4, 13.5, NF-1.6_

- [ ] 19. Integration tests
  - [ ] 19.1 Write the full guided fuel flow integration test
    - `tests/test_integration_flow.py`: four steps, summary, save against a mocked LubeLogger
      returning a positive `fuelEconomy`, confirmation showing that figure without the estimate label,
      then Log another producing a fresh card
    - _Requirements: 3.1, 3.2, 4.6, 4.7, 6.1, 6.5, 6.10, 7.1, 7.2, 7.3_

  - [ ] 19.2 Write the regression test for `fuelEconomy` returned as `"0"`
    - `tests/test_integration_flow.py`: with `fuelEconomy` returned as the string `"0"` the
      confirmation must show the bot's own estimate labelled as an estimate when the conditions of
      Requirement 6.7 hold, and no consumption line at all when they do not — never `0.0 L/100 km`
      (design finding F2: zero means "not available")
    - _Requirements: 6.5, 6.6, 6.7, 6.8, 6.9_

  - [ ] 19.3 Write the field-picker and regression integration test
    - `tests/test_integration_flow.py`: complete a guided flow, correct one field from the
      Field_Picker, enter an odometer below the reference, confirm the warning, and assert the saved
      payload carries the corrected value and the confirmed odometer
    - _Requirements: 4.8, 4.9, 5.8, 5.9_

  - [ ] 19.4 Write the offline save and flush integration test
    - `tests/test_offline_flow.py`: guided save while unreachable produces the queued confirmation,
      the queue flush then sends the record and the existing per-user notification fires
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 12.5_

  - [ ] 19.5 Write the added-locale test
    - `tests/test_locale_addition.py`: dropping a synthetic locale JSON file into `bot/locales/` makes
      every rendered surface, including the Menu_Keyboard, the command descriptions and the label
      allowlist, use it with no code change
    - _Requirements: NF-3.1, NF-3.4_

- [ ] 20. Documentation
  - [ ] 20.1 Update the README
    - Describe the Menu_Keyboard and the guided flow with its summary and edit step, while keeping the
      inline-argument syntax documented for power users
    - Document the new command list as registered with Telegram
    - State the known limitation that costs and volumes are rendered as euro and litres regardless of
      the LubeLogger instance configuration, and that a reported consumption figure is labelled
      `L/100 km`
    - Keep the "a new language is one JSON file" statement accurate
    - _Requirements: NF-3.4, NF-5.1, NF-5.2_

- [ ] 21. Final checkpoint - Full verification
  - Run `uv run pytest` and ensure the whole suite is green, including the 176 pre-existing tests
  - Run `uv run ruff check .` and `uv run ruff format --check .` and fix anything this feature
    introduced
  - Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP
- Each task references the granular requirement clauses it satisfies; every property test names the
  design property it encodes
- All 35 correctness properties of the design are covered: 1-2 (task 2), 3 and 15-16 (task 5),
  4 and 7 (task 6), 9-10, 17, 22, 24, 28, 30, 34 (task 7), 12-13 (task 9), 23 (task 10),
  5, 11, 14, 18-21, 26-27, 35 (task 11), 25 (task 13), 8 (task 14), 29 (task 3), 31-32 (task 16),
  33 (task 2), 6 (task 1)
- Property tests follow the project testing standard: `hypothesis` with `@settings(max_examples=100)`
  and the tag `# Feature: improve-ux, Property N: <title>` in the docstring
- Requirement 9.5 is already satisfied in the working tree: `QueueService.flush` returns
  `sent_items` / `failed_items` and `retry_queue_job` notifies users grouped per user through the
  `queue_synced_multi` / `queue_failed_multi` keys. No task re-implements it; task 13.1 only has to
  leave it untouched
- The six pre-existing `ANN401` findings in `bot/config.py` are unrelated to this feature and stay out
  of scope. Task 21 only fixes lint findings this feature introduces
- The Open Question of Requirement 6.5 is closed in the design by reading the LubeLogger source, so no
  task verifies fuel economy against a live instance; task 19.2 covers the `fuelEconomy = 0` case
  instead

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "2.1", "3.1"] },
    { "id": 1, "tasks": ["1.4", "2.2", "2.3", "3.2"] },
    { "id": 2, "tasks": ["1.5", "2.4", "2.5", "3.3", "3.4"] },
    { "id": 3, "tasks": ["2.6", "3.5", "5.1", "5.3"] },
    { "id": 4, "tasks": ["2.7", "5.2", "5.4", "6.1", "7.1"] },
    { "id": 5, "tasks": ["5.5", "6.2", "7.2"] },
    { "id": 6, "tasks": ["6.3", "7.3"] },
    { "id": 7, "tasks": ["6.4", "7.4"] },
    { "id": 8, "tasks": ["7.5", "9.1"] },
    { "id": 9, "tasks": ["7.6", "9.2"] },
    { "id": 10, "tasks": ["7.7", "9.3"] },
    { "id": 11, "tasks": ["7.8", "9.4"] },
    { "id": 12, "tasks": ["7.9", "9.5"] },
    { "id": 13, "tasks": ["7.10", "10.1"] },
    { "id": 14, "tasks": ["7.11", "10.2"] },
    { "id": 15, "tasks": ["11.1"] },
    { "id": 16, "tasks": ["11.2"] },
    { "id": 17, "tasks": ["11.3"] },
    { "id": 18, "tasks": ["11.4"] },
    { "id": 19, "tasks": ["11.5"] },
    { "id": 20, "tasks": ["11.6"] },
    { "id": 21, "tasks": ["11.7"] },
    { "id": 22, "tasks": ["11.8"] },
    { "id": 23, "tasks": ["11.9"] },
    { "id": 24, "tasks": ["11.10"] },
    { "id": 25, "tasks": ["11.11"] },
    { "id": 26, "tasks": ["11.12"] },
    { "id": 27, "tasks": ["11.13"] },
    { "id": 28, "tasks": ["11.14"] },
    { "id": 29, "tasks": ["11.15"] },
    { "id": 30, "tasks": ["11.16"] },
    { "id": 31, "tasks": ["11.17"] },
    { "id": 32, "tasks": ["11.18", "13.1"] },
    { "id": 33, "tasks": ["13.2", "14.1", "14.3"] },
    { "id": 34, "tasks": ["14.2", "14.4", "15.1", "15.2", "16.1"] },
    { "id": 35, "tasks": ["14.5", "15.3", "16.2", "16.4", "16.6"] },
    { "id": 36, "tasks": ["16.3", "16.5"] },
    { "id": 37, "tasks": ["17.1"] },
    { "id": 38, "tasks": ["18.1"] },
    { "id": 39, "tasks": ["19.1", "19.4", "19.5", "20.1"] },
    { "id": 40, "tasks": ["19.2"] },
    { "id": 41, "tasks": ["19.3"] }
  ]
}
```
