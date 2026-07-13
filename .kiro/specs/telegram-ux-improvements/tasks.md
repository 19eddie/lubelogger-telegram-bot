# Implementation Plan: Telegram UX Improvements

## Overview

This plan refactors the LubeLogger Telegram bot to provide a polished, guided UX with persistent keyboards, in-place message editing, progress indicators, summary/confirmation steps, consumption metrics, command registration, and improved onboarding. Implementation follows a bottom-up approach: infrastructure modules first, then handler refactoring, then wiring and integration.

## Tasks

- [x] 1. Create infrastructure modules (keyboards, conversation helpers, metrics, commands)
  - [x] 1.1 Create `bot/services/keyboard.py` with keyboard builder functions
    - Implement `main_menu_keyboard(lang)` returning a ReplyKeyboardMarkup with "⛽ Fuel", "🔧 Service", "📊 History" buttons
    - Implement `cancel_keyboard(lang)` returning a single "❌ Cancel" button ReplyKeyboardMarkup
    - Implement `summary_inline_keyboard(lang)` returning InlineKeyboardMarkup with "✅ Save", "✏️ Edit", "❌ Cancel"
    - Implement `confirmation_inline_keyboard(record_type, lang)` returning InlineKeyboardMarkup with "🔁 Log another", "📊 History"
    - All functions use `get_text()` for localized labels
    - _Requirements: 1.1, 1.4, 4.4, 5.4, 6.1_

  - [x] 1.2 Create `bot/services/conversation.py` with shared conversation utilities
    - Implement `format_progress(current_step, total_steps)` returning "📍 Step {current}/{total}"
    - Implement `format_summary(fields, lang)` rendering an ordered dict of label/value pairs as a multi-line summary
    - Implement `send_or_edit(update, context, text, *, reply_markup, message_key)` that edits the previous bot message or falls back to sending a new one on BadRequest/TimedOut
    - Store/retrieve message IDs via `context.user_data[message_key]`
    - _Requirements: 4.1, 4.4, 8.1, 8.2, 8.3_

  - [x] 1.3 Create `bot/services/metrics.py` with consumption computation
    - Implement `compute_consumption(liters, current_odometer, previous_odometer)` returning L/100km or None
    - Raise ValueError if liters <= 0; return None if delta <= 0
    - _Requirements: 5.2, 5.3_

  - [x] 1.4 Create `bot/commands.py` with BotFather command registration
    - Define COMMANDS list: fuel, service, km, vehicle, last, status, lang, start
    - Implement `build_commands(lang)` returning list of BotCommand with localized descriptions from i18n
    - Implement `register_commands(app)` calling `app.bot.set_my_commands()`; log WARNING on failure without crashing
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Add i18n keys for all new UX strings
  - [x] 2.1 Update `bot/locales/en.json` with all new English keys
    - Add ~25 keys as defined in the design: keyboard_fuel, keyboard_service, keyboard_history, keyboard_cancel, progress_step, summary_title, summary_save, summary_edit, summary_cancel, confirm_fuel, confirm_fuel_consumption, confirm_service, confirm_odometer, btn_log_another, btn_history, auto_vehicle_selected, last_odometer_hint, start_welcome_new, start_welcome_back, start_api_unreachable, cmd_fuel, cmd_service, cmd_km, cmd_vehicle, cmd_last, cmd_status, cmd_lang, cmd_start, conversation_cancelled_notice, edit_fallback_notice
    - _Requirements: 2.2, 4.1, 4.4, 5.1, 5.5, 7.1, 7.4, 7.5_

  - [x] 2.2 Update `bot/locales/it.json` with corresponding Italian translations
    - Mirror all keys added to en.json with proper Italian text
    - _Requirements: 2.2_

- [x] 3. Checkpoint - Verify infrastructure compiles
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Refactor `/start` onboarding and wire main keyboard
  - [x] 4.1 Refactor `bot/handlers/settings.py` for improved onboarding
    - New user (no active vehicle): show welcome message (max 3 sentences) + inline keyboard listing available vehicles from LubeLogger API
    - Returning user (active vehicle): show welcome-back message + main Reply_Keyboard
    - On vehicle selection callback: set vehicle as active, display main Reply_Keyboard
    - Handle LubeLogger unreachable: show error message suggesting /start later
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 1.1_

  - [x] 4.2 Update `bot/main.py` to call `register_commands` in `post_init`
    - Import and call `register_commands(application)` at the end of `post_init`
    - Add handler for main keyboard button presses (text matching "⛽ Fuel", "🔧 Service", "📊 History") to dispatch to corresponding command handlers
    - _Requirements: 2.1, 1.3_

- [x] 5. Refactor fuel conversation handler with full UX improvements
  - [x] 5.1 Refactor `bot/handlers/fuel.py` with progress indicators, in-place editing, vehicle auto-select, and summary step
    - Add VEHICLE_SELECT and SUMMARY states to conversation
    - Auto-select vehicle when user has exactly one; show selection inline keyboard for multiple
    - Each step prompt uses `send_or_edit()` with `format_progress(step, total)`
    - Replace Reply_Keyboard with cancel_keyboard during flow
    - After collecting all fields, display summary via `format_summary()` with summary inline keyboard
    - Handle "✅ Save" callback: submit to LubeLogger, show rich confirmation with consumption metric
    - Handle "✏️ Edit" callback: restart flow at step 1 with previously entered values as defaults
    - Handle "❌ Cancel" callback: discard data, restore main keyboard
    - Show last odometer as reference hint when prompting for odometer
    - Attach confirmation_inline_keyboard ("🔁 Log another", "📊 History") after successful save
    - "🔁 Log another" starts a new fuel flow with vehicle pre-selected
    - Restore main Reply_Keyboard after completion or cancellation
    - _Requirements: 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Write property test for progress indicator formatting
    - **Property 1: Progress indicator formatting**
    - **Validates: Requirements 4.1**
    - Use Hypothesis: `current_step = st.integers(min_value=1, max_value=total_steps)`, `total_steps = st.integers(min_value=1, max_value=20)`
    - Assert output matches "📍 Step {current}/{total}" format

  - [x] 5.3 Write property test for consumption metric formula
    - **Property 2: Consumption metric formula correctness**
    - **Validates: Requirements 5.2**
    - Use Hypothesis: `liters = st.floats(min_value=0.1, max_value=200.0)`, odometer pairs where current > previous > 0
    - Assert `result == liters / (current - previous) * 100` and result > 0

  - [x] 5.4 Write property test for summary message completeness
    - **Property 3: Summary message completeness**
    - **Validates: Requirements 4.4**
    - Use Hypothesis: `fields = st.dictionaries(st.text(min_size=1, max_size=30), st.text(min_size=1, max_size=50), min_size=1, max_size=10)`
    - Assert every value string appears in the formatted output

- [x] 6. Refactor service conversation handler with UX improvements
  - [x] 6.1 Refactor `bot/handlers/service.py` with progress indicators, in-place editing, vehicle auto-select, and summary/confirmation
    - Same pattern as fuel: add VEHICLE_SELECT, SUMMARY states
    - Auto-select single vehicle; progress indicators; send_or_edit; cancel_keyboard during flow
    - Summary with save/edit/cancel; rich confirmation with vehicle name, odometer, description, cost, date
    - Attach confirmation_inline_keyboard; "🔁 Log another" support; restore main keyboard on end
    - _Requirements: 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.4, 5.5, 6.1, 6.2, 8.1, 8.2, 8.3, 8.4_

- [x] 7. Refactor odometer conversation handler with UX improvements
  - [x] 7.1 Refactor `bot/handlers/odometer.py` with progress indicators, in-place editing, vehicle auto-select, and summary/confirmation
    - Same pattern: VEHICLE_SELECT, SUMMARY states; auto-select; progress; send_or_edit; cancel_keyboard
    - Summary with save/edit/cancel; rich confirmation with vehicle name, odometer, date
    - Attach confirmation_inline_keyboard; "🔁 Log another" support; restore main keyboard on end
    - _Requirements: 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.4, 5.5, 6.1, 6.2, 8.1, 8.2, 8.3, 8.4_

- [x] 8. Checkpoint - Verify all handlers refactored correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Wire keyboard dispatch and ensure persistent keyboard across non-conversation messages
  - [x] 9.1 Ensure main Reply_Keyboard is attached to all non-conversation bot responses
    - Update query handlers (last, status, queue) to attach main_menu_keyboard to reply messages
    - Ensure vehicle selection and language change responses include main keyboard
    - _Requirements: 1.2, 1.5_

- [x] 10. Write property and unit tests
  - [x] 10.1 Write property test for confirmation message completeness
    - **Property 4: Confirmation message completeness**
    - **Validates: Requirements 5.1, 5.5**
    - Use Hypothesis: random vehicle names, odometer > 0, liters > 0, cost ≥ 0, boolean full_tank, date strings
    - Assert all field values appear in the formatted confirmation string

  - [x] 10.2 Write property test for command descriptions completeness
    - **Property 5: Command descriptions completeness**
    - **Validates: Requirements 2.2**
    - Use Hypothesis: `lang = st.sampled_from(["en", "it"])`
    - Assert `len(build_commands(lang)) == 8` and all descriptions are non-empty

  - [x] 10.3 Write unit tests for keyboard builders (`tests/test_keyboard.py`)
    - Test `main_menu_keyboard` returns correct buttons for "en" and "it"
    - Test `cancel_keyboard` returns single cancel button
    - Test `summary_inline_keyboard` returns 3 inline buttons
    - Test `confirmation_inline_keyboard` returns 2 inline buttons
    - _Requirements: 1.1, 1.4, 4.4, 5.4_

  - [x] 10.4 Write unit tests for conversation helpers (`tests/test_conversation.py`)
    - Test `format_progress` with valid and edge-case inputs
    - Test `format_summary` with various field dictionaries
    - Test `send_or_edit` falls back to send when BadRequest is raised
    - Test `send_or_edit` stores message ID in user_data
    - _Requirements: 4.1, 8.1, 8.3_

  - [x] 10.5 Write unit tests for metrics (`tests/test_metrics.py`)
    - Test `compute_consumption` with normal values
    - Test returns None when delta <= 0
    - Test raises ValueError when liters <= 0
    - _Requirements: 5.2, 5.3_

  - [x] 10.6 Write unit tests for commands (`tests/test_commands.py`)
    - Test `build_commands("en")` returns 8 BotCommand objects
    - Test `register_commands` logs WARNING on failure
    - Test `register_commands` succeeds with mock bot
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 10.7 Write unit tests for onboarding (`tests/test_onboarding.py`)
    - Test /start with no vehicle shows welcome + vehicle list
    - Test /start with active vehicle shows welcome-back + main keyboard
    - Test /start when API unreachable shows error message
    - Test vehicle selection from onboarding sets vehicle + shows main keyboard
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 10.8 Write unit tests for confirmation flows (`tests/test_confirmation.py`)
    - Test fuel confirmation includes all field values
    - Test fuel confirmation includes consumption metric when previous record exists
    - Test fuel confirmation omits consumption when no previous record
    - Test service confirmation includes vehicle, odometer, description, cost
    - Test odometer confirmation includes vehicle, odometer
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 10.9 Write integration tests for full conversation flows (`tests/test_flow_integration.py`)
    - Test complete fuel conversation flow with mocked LubeLogger client
    - Test "Log another" starts new flow with pre-selected vehicle
    - Test cancel at various steps restores main keyboard
    - Test edit from summary restarts flow with preserved values
    - Test in-place editing works across sequential steps
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.1, 6.2, 8.1_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python, so all implementations use Python 3.11+ with async/await
- Tests use pytest + hypothesis (property-based) + pytest-asyncio (async support)
- All new modules follow the existing project patterns (type annotations, docstrings, from __future__ import annotations)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "1.4", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["4.1", "4.2"] },
    { "id": 3, "tasks": ["5.1", "6.1", "7.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "9.1"] },
    { "id": 5, "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "10.7", "10.8"] },
    { "id": 6, "tasks": ["10.9"] }
  ]
}
```
