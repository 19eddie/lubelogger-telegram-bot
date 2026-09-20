# QA Test Plan — LubeLogger Telegram Bot

<!--
AI/QA MAINTENANCE CONTRACT

1. Test case IDs are permanent. Do not renumber or reuse them.
2. Allowed status values: NOT_RUN, IN_PROGRESS, PASS, FAIL, BLOCKED, SKIPPED, RETEST.
3. Update only result fields after execution: status, actual_result, evidence, defect_id,
   executed_by, executed_at, environment, and notes.
4. Do not replace expected behavior or test steps to make a failed test pass.
5. For every rerun, append one row to the central Execution history table in Section 25.
6. Never store Telegram tokens, API keys, personal data, or unredacted production logs here.
7. Use ISO dates: YYYY-MM-DD. Use UTC when recording timestamps.
-->

## 0. Document control

- `document_id`: `QA-LUBELOGGER-BOT`
- `project`: `lubelogger-telegram-bot`
- `target_branch`: `v0.1`
- `scope`: current base bot, not `feat/ux-design`
- `document_status`: `IN_PROGRESS`
- `created_at`: `2026-08-29`
- `last_updated_at`: `2026-08-29`
- `owner`: `QA`
- `telegram_command_menu`: `CLEARED`
- `persistent_reply_keyboard_expected`: `ABSENT`
- `external_live_testing`: `REQUIRED`

## 1. Status model

| Status | Meaning |
|---|---|
| `NOT_RUN` | Test has not been executed. |
| `IN_PROGRESS` | Test execution is currently active. |
| `PASS` | Actual result matches expected result. |
| `FAIL` | Actual result differs from expected result. |
| `BLOCKED` | Cannot execute because a prerequisite is unavailable. |
| `SKIPPED` | Intentionally excluded, with explanation in `notes`. |
| `RETEST` | A previous failure was fixed and requires verification. |

Priority values:

- `P0`: release blocker, data loss, security bypass, bot unavailable;
- `P1`: critical user journey broken;
- `P2`: important functional defect with workaround;
- `P3`: minor UX, wording, or cosmetic defect.

## 2. Test environment contract

### 2.1 Required environment

Use a dedicated, disposable environment:

- Telegram test bot token;
- LubeLogger test instance;
- SQLite database dedicated to QA;
- Docker/Compose deployment matching the target deployment;
- one authorized Telegram user;
- one unauthorized Telegram user;
- at least two test vehicles;
- one vehicle with existing fuel/odometer records;
- one vehicle without records.

Never use production data or production credentials in this file.

### 2.2 Suggested QA configuration

```env
TELEGRAM_BOT_TOKEN=<redacted-test-token>
LUBELOGGER_URL=<redacted-test-url>
LUBELOGGER_API_KEY=<redacted-test-key>
ALLOWED_USER_IDS=<authorized-test-user-id>
DB_PATH=/data/qa-bot.db
QUEUE_RETRY_INTERVAL=5
HTTP_TIMEOUT=3
MAX_RETRY_ATTEMPTS=3
```

### 2.3 Startup commands

Run from repository root:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check bot
uv run python -m compileall -q bot
```

For container testing:

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs --tail=100 telegram-bot
```

For the full stack:

```bash
docker compose -f docker-compose.full.yml config --quiet
docker compose -f docker-compose.full.yml up -d
docker compose -f docker-compose.full.yml ps
```

### 2.4 Telegram UX baseline

The current branch does not register BotFather commands at startup. The Telegram command menu was cleared manually after testing `feat/ux-design`.

The current branch is expected to have:

- no `/command` suggestions registered by the bot;
- no persistent `ReplyKeyboardMarkup` from `feat/ux-design`;
- manual commands still functional when typed explicitly.

If commands or the persistent UX keyboard reappear after starting `v0.1`, record a regression against `UX-001` or `UX-002`.

## 3. Result update protocol

For each test case:

1. Set `status` to `IN_PROGRESS` before execution.
2. Execute steps exactly as written.
3. Record the exact user-visible result in `actual_result`.
4. Add screenshot/log/database/API evidence with secrets redacted.
5. Set `status` to `PASS`, `FAIL`, `BLOCKED`, or `SKIPPED`.
6. Add a defect ID when status is `FAIL`.
7. Append a row to the central Execution history table in Section 25.

Required result fields in every test case:

- `status`
- `actual_result`
- `evidence`
- `defect_id`
- `executed_by`
- `executed_at`
- `environment`
- `notes`

## 4. Execution summary

Update this table after each QA run. Do not infer counts from prose.

| Metric | Value |
|---|---:|
| Total test cases | `TBD` |
| `PASS` | `TBD` |
| `FAIL` | `TBD` |
| `BLOCKED` | `TBD` |
| `NOT_RUN` | `TBD` |
| Open P0 defects | `TBD` |
| Open P1 defects | `TBD` |
| Release decision | `PENDING` |

## 5. Baseline results already available

These results were produced during repository validation. They are a baseline, not a substitute for live Telegram/LubeLogger QA.

### AUTO-001 — Existing automated test suite

- `type`: `AUTOMATED`
- `priority`: `P1`
- `status`: `PASS`
- `command`: `uv run pytest`
- `expected_result`: all automated tests pass
- `actual_result`: `177 passed`
- `evidence`: terminal run, 2026-08-29
- `defect_id`: `-`
- `executed_by`: `Kiro`
- `executed_at`: `2026-08-29`
- `environment`: local `.venv`, Python 3.14 runtime
- `notes`: includes regression coverage proving gas payload omits EV-only `startingSoc`/`endingSoc`; does not prove live Telegram or live LubeLogger compatibility

### AUTO-002 — Ruff lint

- `type`: `AUTOMATED`
- `priority`: `P2`
- `status`: `PASS`
- `command`: `uv run ruff check .`
- `expected_result`: no lint errors
- `actual_result`: `All checks passed`
- `evidence`: terminal run, 2026-08-29
- `defect_id`: `-`
- `executed_by`: `Kiro`
- `executed_at`: `2026-08-29`
- `environment`: local `.venv`
- `notes`: `-`

### AUTO-003 — Source formatting

- `type`: `AUTOMATED`
- `priority`: `P3`
- `status`: `PASS`
- `command`: `uv run ruff format --check bot`
- `expected_result`: source files already formatted
- `actual_result`: `26 files already formatted`
- `evidence`: terminal run, 2026-08-29
- `defect_id`: `-`
- `executed_by`: `Kiro`
- `executed_at`: `2026-08-29`
- `environment`: local `.venv`
- `notes`: scope intentionally limited to `bot`; existing test formatting is outside this baseline

### AUTO-004 — Python compilation

- `type`: `AUTOMATED`
- `priority`: `P1`
- `status`: `PASS`
- `command`: `uv run python -m compileall -q bot`
- `expected_result`: no syntax or compilation errors
- `actual_result`: `PASS`
- `evidence`: terminal run, 2026-08-29
- `defect_id`: `-`
- `executed_by`: `Kiro`
- `executed_at`: `2026-08-29`
- `environment`: local `.venv`
- `notes`: `-`

### AUTO-005 — Mocked command smoke test

- `type`: `INTEGRATION_MOCKED`
- `priority`: `P1`
- `status`: `PASS`
- `command`: temporary in-memory smoke runner
- `expected_result`: all command handlers, guided flows, callbacks, API errors, offline queue, auth and cancel paths complete without unexpected exceptions
- `actual_result`: `all-command-smoke: PASS`
- `evidence`: terminal run, 2026-08-29
- `defect_id`: `-`
- `executed_by`: `Kiro`
- `executed_at`: `2026-08-29`
- `environment`: local `.venv`, mocked Telegram/LubeLogger
- `notes`: does not replace live manual QA

## 6. Setup and startup test cases

### SETUP-001 — Correct branch and clean test target

- `type`: `SETUP`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: repository available
- `steps`:
  1. Run `git branch --show-current`.
  2. Confirm target is `v0.1`.
  3. Confirm QA uses a dedicated database and test credentials.
- `expected_result`: correct branch and isolated environment confirmed
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SETUP-002 — Configuration validation

- `type`: `CONFIGURATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: `.env` configured with test values
- `steps`:
  1. Start the bot with valid configuration.
  2. Remove `TELEGRAM_BOT_TOKEN` and restart.
  3. Restore it and set an empty `ALLOWED_USER_IDS`.
  4. Restore valid configuration.
- `expected_result`: valid config starts; invalid/missing config stops cleanly with a logged configuration error; no secret is printed
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: never store `.env` contents here

### SETUP-003 — Container startup

- `type`: `DEPLOYMENT`
- `priority`: `P0`
- `status`: `PASS`
- `preconditions`: Docker installed; test `.env` available
- `steps`:
  1. Run `docker compose config --quiet`.
  2. Run `docker compose up -d`.
  3. Run `docker compose ps` and inspect logs.
  4. Send `/start` from Telegram.
- `expected_result`: configuration valid, container running, polling active, `/start` handled
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: repeat with `docker-compose.full.yml` when full-stack deployment is in scope

## 7. Authentication test cases

### AUTH-001 — Authorized user

- `type`: `SECURITY`
- `priority`: `P0`
- `status`: `PASS`
- `preconditions`: user ID is in `ALLOWED_USER_IDS`
- `steps`:
  1. Send `/start`.
  2. Send `/vehicle`, `/fuel`, `/service`, `/km`, `/last fuel`, `/last km`, `/status`, `/queue`, `/lang`.
  3. Press vehicle and language callback buttons.
- `expected_result`: all authorized operations execute normally
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `/cancel` is tested in conversation cases

### AUTH-002 — Unauthorized user

- `type`: `SECURITY`
- `priority`: `P0`
- `status`: `PASS`
- `preconditions`: second Telegram user not in `ALLOWED_USER_IDS`
- `steps`:
  1. Send every documented command.
  2. Attempt callback actions from a copied/old inline keyboard.
- `expected_result`: no application response, no database change, no queue item, no language/vehicle change
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: do not treat Telegram's silent filtering as a defect

### AUTH-003 — Authorization after restart

- `type`: `SECURITY`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: bot has been restarted
- `steps`:
  1. Repeat `AUTH-001` with authorized user.
  2. Repeat `AUTH-002` with unauthorized user.
- `expected_result`: authorization behavior unchanged after restart
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 8. `/start` test cases

### START-001 — Start without active vehicle

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: authorized user has no active vehicle
- `steps`:
  1. Send `/start`.
- `expected_result`: localized welcome message instructs user to select a vehicle with `/vehicle`; no UX keyboard from `feat/ux-design`
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### START-002 — Start with active vehicle

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle already stored
- `steps`:
  1. Send `/start`.
- `expected_result`: welcome message shown; active vehicle remains unchanged; no persistent reply keyboard
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `leggo lo stesso messaggio del test START-001`

### START-003 — Start in selected language

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: user language set to Italian or English
- `steps`:
  1. Set language through `/lang`.
  2. Restart the bot.
  3. Send `/start`.
- `expected_result`: welcome message uses persisted language
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: execute once per supported language

## 9. `/vehicle` test cases

### VEHICLE-001 — Vehicle list

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: LubeLogger has at least two test vehicles
- `steps`:
  1. Send `/vehicle`.
- `expected_result`: one inline button per API vehicle; labels are readable; callback selection data is valid
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### VEHICLE-002 — Select and persist vehicle

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: `/vehicle` keyboard displayed
- `steps`:
  1. Select vehicle A.
  2. Send `/start`.
  3. Send `/fuel` without arguments.
- `expected_result`: vehicle A is persisted; `/start` does not ask for selection; `/fuel` uses A
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: verify database state only through redacted evidence

### VEHICLE-003 — Change active vehicle

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: vehicle A currently active; vehicle B available
- `steps`:
  1. Select vehicle B.
  2. Create one fuel, service, or odometer record.
  3. Check LubeLogger.
- `expected_result`: new record belongs to B, not A
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### VEHICLE-004 — Empty, unreachable, and API error responses

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: ability to stop LubeLogger or use controlled test responses
- `steps`:
  1. Test `/vehicle` with an empty vehicle list.
  2. Test with LubeLogger unreachable.
  3. Test with `4xx/5xx` response.
- `expected_result`: user-friendly response for each case; no crash; no invalid vehicle persisted
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 10. `/fuel` test cases

### FUEL-001 — Valid inline command with dot decimals

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/fuel 45000 42.5 78.90`.
  2. Inspect confirmation.
  3. Inspect LubeLogger record.
- `expected_result`: confirmation contains liters, cost, odometer; API record has correct vehicle and fields
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-002 — Valid inline command with comma decimals

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: same as `FUEL-001`
- `steps`:
  1. Send `/fuel 45000 42,5 78,90`.
- `expected_result`: same semantic values and one record created
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-003 — Invalid syntax

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: active vehicle
- `steps`:
  1. Send `/fuel` with zero, one, two, and four arguments.
  2. Send `/fuel 45000 abc 20`.
- `expected_result`: usage/validation message; no API record; no pending queue item
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-004 — Invalid numeric boundaries

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle
- `steps`:
  1. Test zero and negative odometer.
  2. Test zero and negative liters.
  3. Test negative cost.
  4. Test fractional odometer.
  5. Test `inf` and `nan` values.
- `expected_result`: invalid value rejected; no truncation; no crash; no record created
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-005 — Guided flow success

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/fuel`.
  2. Tap the inline `Today` button for today's date, or reply with a valid past date.
  3. Reply with odometer.
  4. Reply with liters.
  5. Reply with cost.
  6. Reply with `yes` or `no` for full tank.
  7. Reply with `yes` or `no` for missed previous fuel-up.
- `expected_result`: date prompt shows the inline `Today` button; prompts appear in order; one record is created with selected date and `missedFuelUp` value; final confirmation is shown
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: execute once with full tank/missed false and once with non-full/missed true

### FUEL-006 — Guided validation and retry

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active guided `/fuel` flow
- `steps`:
  1. Enter invalid date, then a valid past date.
  2. Enter invalid odometer, liters, and cost one at a time.
  3. Enter valid value after each error.
  4. Enter an ambiguous missed answer, then a valid answer.
- `expected_result`: error is shown; same step remains active; valid retry advances flow; selected date and missed value are retained
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-007 — Full-tank and missed choice validation

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: guided flow at full-tank or missed-fuel step
- `steps`:
  1. Test `yes`, `y`, `1`, `true` for full tank.
  2. Test `no`, `n`, `0`, `false` for full tank.
  3. Test Italian `si` and `sì`.
  4. Test an ambiguous value such as `maybe` at both boolean steps.
- `expected_result`: supported values advance; ambiguous value keeps the same step and asks again; missed answer maps to `missedFuelUp`
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-008 — Guided cancel and state cleanup

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active guided `/fuel` flow
- `steps`:
  1. Send `/cancel` at date, odometer, liters, cost, full-tank, and missed-fuel steps in separate runs.
  2. Start a new `/fuel` flow.
- `expected_result`: flow ends; no record is created; previous date, values, and flags are not reused
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### FUEL-009 — Vehicle override

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: active vehicle A; vehicle B exists
- `steps`:
  1. Send `/fuel --vehicle <B_ID> 45000 40 80`.
  2. Inspect LubeLogger.
- `expected_result`: record belongs to B; active vehicle preference is not unexpectedly changed
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: feature exists in code even if not emphasized in README

### FUEL-010 — API error and offline behavior

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `PASS`
- `preconditions`: active vehicle; controlled LubeLogger availability
- `steps`:
  1. Test successful API response.
  2. Test `4xx/5xx` response.
  3. Stop LubeLogger and send a valid fuel record.
  4. Inspect `/queue` and `/status`.
- `expected_result`: success saves remotely; API error gives safe error; unreachable saves locally and reports queued state
- `actual_result`: `PASS`: guided `/fuel` reached LubeLogger but returned `500`; redacted response body was `{"success":false,"message":"The input string '' was not in a correct format."}`. `20/80` workaround rejected: these are EV SoC defaults, not user fuel data. Gas payload now omits SoC; live retest is blocked pending runtime version/capability verification.
- `evidence`: redacted client log at `2026-08-29 09:16 UTC`; official LubeLogger API sample separates Gas/Diesel from EV payloads; official source history shows an intermediate runtime parsed missing SoC unconditionally, while later source defaults missing values; automated payload omission test; commit not created
- `defect_id`: `DEF-FUEL-001`
- `executed_by`: `User` (live run), `Kiro` (diagnosis/fix)
- `executed_at`: `2026-08-29`
- `environment`: full-stack LubeLogger runtime; exact `latest` image version not recorded
- `notes`: body indicates server-side parsing of an empty numeric field. Client endpoint/auth/core fields matched API contract. Do not retry write until duplicate check; first identify runtime version/capability via read-only `/api/version` and `/api`, then upgrade/fix server and rerun with current payload.

### FUEL-011 — Retroactive date and missed flag via inline command

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/fuel 45000 42.5 78.90 --date 2024-01-15 --missed`.
  2. Inspect the LubeLogger record and `/last fuel`.
- `expected_result`: one record is created with date `2024-01-15`, `missedFuelUp=true`, and visible missed indicator
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: repeat without options to verify legacy syntax still uses today and `missedFuelUp=false`

### FUEL-012 — Fuel date boundary validation

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle
- `steps`:
  1. Test malformed dates such as `15-01-2024` and `2024-1-15`.
  2. Test a future date.
  3. Test the inline `Today` button, a past date, and guided aliases `today` and `oggi`.
- `expected_result`: malformed/future dates are rejected; the `Today` button and aliases resolve to today; past dates are accepted
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 10A. `/help` test cases

### HELP-001 — Display available commands

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: authorized Telegram user; bot running
- `steps`:
  1. Send `/help`.
  2. Repeat after selecting Italian with `/lang`.
- `expected_result`: localized help message generated from the central command catalog lists every available command, including `/help` and `/cancel`; no API or database operation is required
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: command menu suggestions remain a separate feature; `/help` must work when typed explicitly


## 11. `/service` test cases

### SERVICE-001 — Valid quoted inline command

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/service 45100 "Oil change" 89.00`.
  2. Inspect confirmation and LubeLogger.
- `expected_result`: full description, cost, odometer, date, and vehicle are correct
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-002 — Unquoted single-word description

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: active vehicle
- `steps`:
  1. Send `/service 45100 Brakes 120`.
- `expected_result`: one-word description accepted and stored
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-003 — Description normalization

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: active vehicle
- `steps`:
  1. Test a description with multiple internal spaces.
  2. Test leading/trailing spaces.
  3. Test empty and whitespace-only description.
- `expected_result`: valid text is preserved/trimmed; empty text rejected
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-004 — Numeric validation

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle
- `steps`:
  1. Test zero/negative odometer.
  2. Test fractional odometer.
  3. Test negative, `inf`, and `nan` cost.
- `expected_result`: invalid values rejected without truncation or crash
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-005 — Guided flow success

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/service`.
  2. Enter odometer.
  3. Enter description.
  4. Enter cost.
- `expected_result`: prompts occur in order; one remote record created; confirmation shown
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-006 — Guided retry and cancel

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: guided `/service` flow
- `steps`:
  1. Enter invalid odometer and cost.
  2. Recover with valid values.
  3. Repeat with `/cancel` in every step.
  4. Start a new `/service`.
- `expected_result`: invalid steps repeat; cancel clears state; new flow is clean
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SERVICE-007 — Offline and API errors

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle; controlled LubeLogger availability
- `steps`:
  1. Test API success.
  2. Test `4xx/5xx`.
  3. Test connection refusal/timeout.
- `expected_result`: success saves; API error is reported safely; unreachable queues payload
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 12. `/km` test cases

### KM-001 — Valid inline command

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/km 45200`.
  2. Inspect confirmation and LubeLogger.
- `expected_result`: one odometer record with correct vehicle and value
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### KM-002 — Guided flow success

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle; LubeLogger available
- `steps`:
  1. Send `/km`.
  2. Enter a valid odometer.
- `expected_result`: prompt shown; record saved; conversation ends
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### KM-003 — Invalid value and retry

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active guided `/km` flow
- `steps`:
  1. Enter `abc`, `0`, `-1`, fractional value, `inf`, and `nan` in separate runs.
  2. Enter a valid integer after each error.
- `expected_result`: invalid input rejected; flow remains usable; valid retry saves once
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### KM-004 — Vehicle override

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: vehicle B exists
- `steps`:
  1. Send `/km --vehicle <B_ID> 45200`.
  2. Inspect LubeLogger.
- `expected_result`: record belongs to B
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### KM-005 — No vehicle, offline, and API error

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: test configurations for each condition
- `steps`:
  1. Run `/km` without active vehicle.
  2. Run valid `/km` with LubeLogger unreachable.
  3. Run valid `/km` with `4xx/5xx` response.
- `expected_result`: no-vehicle message; offline queue; safe API error response
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### KM-006 — Cancel and state cleanup

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active guided `/km` flow
- `steps`:
  1. Send `/cancel`.
  2. Start a new `/km`.
- `expected_result`: cancellation ends flow and no old override/value survives
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 13. Query commands

### QUERY-001 — `/last fuel` with record

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle with fuel records
- `steps`:
  1. Send `/last fuel`.
- `expected_result`: latest date, liters, cost, and odometer shown
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUERY-002 — `/last km` with record

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: active vehicle with odometer records
- `steps`:
  1. Send `/last km`.
- `expected_result`: latest date and odometer shown
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUERY-003 — Empty and invalid `/last`

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle without the relevant records
- `steps`:
  1. Send `/last fuel` with no fuel records.
  2. Send `/last km` with no odometer records.
  3. Send `/last`.
  4. Send `/last unknown`.
- `expected_result`: empty-state or usage message; no crash
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUERY-004 — `/last` without active vehicle

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: no active vehicle
- `steps`:
  1. Send `/last fuel`.
  2. Send `/last km`.
- `expected_result`: user is instructed to select a vehicle; no API call that can produce an invalid query
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUERY-005 — `/last` backend errors

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle; controlled backend failure
- `steps`:
  1. Test `/last fuel` while offline.
  2. Test `/last km` while offline.
  3. Repeat with `4xx/5xx` response.
- `expected_result`: safe localized error message; bot remains responsive
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 14. `/status` and `/queue`

### STATUS-001 — `/status` online and empty queue

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: LubeLogger online; no pending records
- `steps`:
  1. Send `/status`.
- `expected_result`: reachable status and empty queue message
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### STATUS-002 — `/status` offline with pending queue

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: one or more pending records; LubeLogger offline
- `steps`:
  1. Send `/status`.
- `expected_result`: offline status plus correct pending count
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUEUE-001 — Empty `/queue`

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: no pending records
- `steps`:
  1. Send `/queue`.
- `expected_result`: empty queue message
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUEUE-002 — Queue count by type

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: pending gas, service, and odometer records
- `steps`:
  1. Send `/queue`.
  2. Compare total and per-type values with database state.
- `expected_result`: total and type counts match database state
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: confirm whether aggregate counts across users meet product requirements

## 15. `/lang`

### LANG-001 — Language selection

- `type`: `MANUAL`
- `priority`: `P2`
- `status`: `PASS`
- `preconditions`: authorized user
- `steps`:
  1. Send `/lang`.
  2. Select English.
  3. Send `/start`, `/status`, and `/fuel`.
  4. Select Italian.
  5. Repeat the commands.
- `expected_result`: language callback persists; subsequent messages use selected language
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: verify all user-facing paths used in the test have translations

### LANG-002 — Language persistence after restart

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `PASS`
- `preconditions`: language selected
- `steps`:
  1. Restart the bot.
  2. Send `/start` and `/status`.
- `expected_result`: selected language remains active
- `actual_result`: `PASS`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### LANG-003 — Unauthorized language callback

- `type`: `SECURITY`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: callback message exists; user is not authorized
- `steps`:
  1. Attempt to trigger a language callback as unauthorized user.
- `expected_result`: language is unchanged; no unauthorized response or side effect
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

## 16. `/cancel` and conversation lifecycle

### CANCEL-001 — Cancel each guided flow

- `type`: `MANUAL`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active `/fuel`, `/service`, or `/km` conversation
- `steps`:
  1. Run each conversation.
  2. Send `/cancel` at every available step in separate runs.
- `expected_result`: localized cancellation message; conversation ends; no remote or queued record
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### CANCEL-002 — Cancel outside conversation

- `type`: `MANUAL`
- `priority`: `P3`
- `status`: `NOT_RUN`
- `preconditions`: no active conversation
- `steps`:
  1. Send `/cancel`.
- `expected_result`: no crash. Confirm whether silent behavior is the intended product behavior.
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: open a product decision if a response is required

## 17. Offline queue and retry

### QUEUE-003 — Enqueue all record types while offline

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: LubeLogger stopped; active vehicle
- `steps`:
  1. Create a valid `/fuel` record.
  2. Create a valid `/service` record.
  3. Create a valid `/km` record.
  4. Check `/queue`.
- `expected_result`: all three records are pending with correct type, vehicle, user, and payload
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: inspect payload only in a redacted test database export

### QUEUE-004 — Queue survives bot restart

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: pending records exist
- `steps`:
  1. Stop the bot.
  2. Start the bot.
  3. Run `/queue`.
- `expected_result`: pending records remain available; no data loss
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUEUE-005 — Flush after backend recovery

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: pending records; `QUEUE_RETRY_INTERVAL` reduced for QA
- `steps`:
  1. Restore LubeLogger.
  2. Wait for the retry interval.
  3. Inspect LubeLogger.
  4. Run `/queue` and `/status`.
- `expected_result`: records sent once; pending count reaches zero; user receives sync notification
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: if manual waiting is impractical, invoke the retry job in a controlled test harness

### QUEUE-006 — FIFO ordering

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: backend offline; ability to inspect creation order
- `steps`:
  1. Create at least three records in known order.
  2. Restore backend.
  3. Inspect arrival order or backend timestamps.
- `expected_result`: oldest pending item is sent first; ordering preserved
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### QUEUE-007 — Retry exhaustion

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: pending item; controlled permanent API error; `MAX_RETRY_ATTEMPTS=3`
- `steps`:
  1. Create a pending record.
  2. Keep backend returning `4xx`.
  3. Wait for three retry attempts.
  4. Inspect `/queue`, logs, and user notification.
- `expected_result`: item becomes `failed`; retry job continues; user receives failure notification
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: never use a production record for this test

### QUEUE-008 — Corrupt payload does not stop queue job

- `type`: `INTEGRATION_DATABASE`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: disposable QA database
- `steps`:
  1. Insert a queue item with invalid JSON or unsupported record type.
  2. Run a queue flush.
  3. Inspect remaining queue items.
- `expected_result`: corrupt item marked failed; valid items remain processable; job does not crash
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: database manipulation allowed only in disposable QA environment

## 18. Persistence and multiuser behavior

### DATA-001 — Vehicle and language persistence

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: active vehicle and selected language
- `steps`:
  1. Restart the bot/container.
  2. Run `/start`, `/fuel`, `/service`, and `/km`.
- `expected_result`: preferences persist and are applied after restart
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### DATA-002 — Two-user isolation

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: two authorized users; separate active vehicles/languages
- `steps`:
  1. Set different active vehicles.
  2. Set different languages.
  3. Start guided conversations concurrently.
  4. Create offline records from both users.
- `expected_result`: no vehicle, language, temporary state, queue payload, or response crosses user boundaries
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: redact both user IDs in evidence

### DATA-003 — No duplicate after restart

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: a valid record submitted near a bot restart
- `steps`:
  1. Submit one valid record.
  2. Restart bot/container.
  3. Inspect LubeLogger and queue.
- `expected_result`: record exists exactly once; no unintended pending duplicate
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: record API id/timestamp in redacted evidence

## 19. API contract and error handling

### API-001 — API key authentication

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: LubeLogger authentication enabled
- `steps`:
  1. Run with valid API key.
  2. Run with invalid API key.
- `expected_result`: valid key permits operations; invalid key returns safe error and no data corruption
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: never record key value

### API-002 — HTTP failures

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: controlled backend or proxy capable of returning failures
- `steps`:
  1. Test `401`, `404`, and `500` responses.
  2. Test timeout.
  3. Test connection refusal.
  4. Exercise write and read commands.
- `expected_result`: each path produces safe user feedback; bot stays available for next command
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: distinguish API error from offline queue behavior

### API-003 — Response and payload fields

- `type`: `MANUAL_INTEGRATION`
- `priority`: `P1`
- `status`: `NOT_RUN`
- `preconditions`: LubeLogger available
- `steps`:
  1. Create each record type.
  2. Inspect resulting LubeLogger record.
  3. Use `/last` to read it back.
- `expected_result`: date, odometer, fuel/liters, cost, description, boolean fields, and vehicle match input
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: record only non-sensitive test values

## 20. Security and logging

### SEC-001 — Secret non-disclosure

- `type`: `SECURITY`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: test API key configured
- `steps`:
  1. Trigger API error, timeout, and connection error.
  2. Inspect Telegram messages.
  3. Inspect application logs.
- `expected_result`: Telegram token, API key, and secrets absent from messages/logs
- `actual_result`: `NOT_EXECUTED`
- `evidence`: redacted log excerpts only
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: immediately redact any accidental secret before storing evidence

### SEC-002 — Unauthorized callback protection

- `type`: `SECURITY`
- `priority`: `P0`
- `status`: `NOT_RUN`
- `preconditions`: valid callback message generated for authorized user
- `steps`:
  1. Attempt vehicle callback as unauthorized user.
  2. Attempt language callback as unauthorized user.
- `expected_result`: no persistence or API side effect
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: `-`

### SEC-003 — Input abuse and oversized values

- `type`: `SECURITY`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: authorized test user
- `steps`:
  1. Send very long service description.
  2. Send unusual Unicode and control characters.
  3. Send scientific notation, `inf`, `nan`, and very large values.
- `expected_result`: no crash, no log injection, validation behaves consistently, no secret exposure
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: do not use payloads intended to attack production

## 21. UX regression cases for current branch

### UX-001 — Slash command menu remains cleared

- `type`: `MANUAL_REGRESSION`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: cleanup script already executed; bot running from `v0.1`
- `steps`:
  1. Restart the current branch bot.
  2. Open Telegram command menu.
  3. Type `/` in the chat.
- `expected_result`: `v0.1` does not re-register the `feat/ux-design` command list; menu remains empty unless commands are manually configured
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: commands remain callable manually; this test concerns visibility only

### UX-002 — Persistent UX keyboard remains removed

- `type`: `MANUAL_REGRESSION`
- `priority`: `P2`
- `status`: `NOT_RUN`
- `preconditions`: cleanup script already executed; bot running from `v0.1`
- `steps`:
  1. Send `/start`.
  2. Send `/fuel`, `/service`, and `/km`.
  3. Restart the bot and send `/start` again.
- `expected_result`: no `Fuel/Service/Odometer/Latest/Options` persistent reply keyboard appears
- `actual_result`: `NOT_EXECUTED`
- `evidence`: `-`
- `defect_id`: `-`
- `executed_by`: `-`
- `executed_at`: `-`
- `environment`: `-`
- `notes`: if keyboard reappears, check that no process from `feat/ux-design` is running

## 22. Defect log

Use one row per defect. Link defects from test cases through `defect_id`.

| Defect ID | Title | Severity | First seen | Affected tests | Status | Owner | Fix version | Notes |
|---|---|---|---|---|---|---|---|---|
| `DEF-FUEL-001` | LubeLogger runtime returns 500 when gas payload omits numeric SoC fields | `P0` | `2026-08-29` | `FUEL-010` | `BLOCKED` | `Bot/LubeLogger runtime` | `v0.1-unreleased` | Redacted body reports empty-string format parse. Current official API treats SoC as EV-specific; client no longer invents `startingSoc`/`endingSoc`. Verify runtime version and upgrade/fix server before retest. |

## 23. Release gate

Set `release_decision` in Section 4 to `APPROVED` only when all conditions are true:

- all `P0` and `P1` cases are `PASS`;
- no open P0/P1 defect exists;
- every command has at least one positive and one negative result;
- guided flows complete and cancel cleanly;
- no valid record is lost or duplicated;
- offline queue survives restart and synchronizes after recovery;
- unauthorized users and callbacks have no side effects;
- language and vehicle preferences persist;
- no secret appears in Telegram or logs;
- Docker deployment and restart behavior pass;
- automated baseline remains green.

If a test cannot be executed, use `BLOCKED` and document the missing prerequisite. Do not mark it `PASS`.

## 24. Final QA run record

Complete this section after a full campaign.

- `run_id`: `-`
- `executed_by`: `-`
- `started_at`: `-`
- `finished_at`: `-`
- `branch`: `-`
- `commit`: `-`
- `environment`: `-`
- `total_cases`: `-`
- `passed`: `-`
- `failed`: `-`
- `blocked`: `-`
- `skipped`: `-`
- `open_p0`: `-`
- `open_p1`: `-`
- `release_decision`: `PENDING`
- `summary`: `NOT_EXECUTED`

## 25. Central execution history

Append one row for every execution or rerun. Keep old rows; do not overwrite history.

| Run ID | Test ID | Date UTC | Executor | Branch/commit | Environment | Status | Actual result | Evidence | Defect ID | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `RUN-2026-08-29-01` | `FUEL-010` | `2026-08-29` | `User + Kiro` | `v0.1 / uncommitted` | full-stack LubeLogger runtime | `FAIL` | Guided `/fuel` request returned HTTP 500; response body reported empty-string format parse. | Redacted log at `09:16 UTC`; payload contained no credentials. | `DEF-FUEL-001` | Provisional client workaround with hardcoded EV SoC was rejected and reverted; verify `/api/version`/`/api` on runtime before rerun. |
