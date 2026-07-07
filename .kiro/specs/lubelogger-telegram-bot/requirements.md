# Requirements Document

## Introduction

Bot Telegram che funge da interfaccia di inserimento rapido per LubeLogger (tracker self-hosted per manutenzione veicoli). Permette di registrare rifornimenti, tagliandi e letture odometro direttamente da una chat Telegram, senza accedere all'interfaccia web. Il bot opera in modalità polling, persiste i dati localmente quando LubeLogger non è raggiungibile, e gira come container Docker affiancato all'istanza LubeLogger esistente.

### Fonti di riferimento

- LubeLogger API: endpoint REST con autenticazione `x-api-key`
- Telegram Bot API: modalità polling (long-polling)
- Postman Collection ufficiale: `hargata/lubelog_scripts/misc/LubeLogger.postman_collection.json`

## Glossary

- **Bot**: L'applicazione Telegram bot che riceve comandi dall'utente e interagisce con LubeLogger_API
- **LubeLogger_API**: L'interfaccia REST di LubeLogger, autenticata tramite header `x-api-key`, con payload JSON a campi stringa
- **Queue_Service**: Il servizio interno al Bot che persiste record non ancora inviati su database SQLite locale
- **Validator**: Il componente Pydantic che valida i dati inseriti dall'utente prima dell'invio o dell'accodamento
- **Command_Parser**: Il componente che interpreta i messaggi dell'utente e li trasforma in strutture dati tipizzate
- **User**: Un utente Telegram il cui user ID è presente nella whitelist configurata
- **Vehicle**: Un veicolo registrato nell'istanza LubeLogger, identificato da un ID numerico
- **Active_Vehicle**: Il veicolo selezionato dall'utente come default per le operazioni di inserimento
- **Gas_Record**: Un record rifornimento carburante con data, odometro, litri, costo e flag pieno/mancato
- **Service_Record**: Un record manutenzione con data, odometro, descrizione e costo
- **Odometer_Record**: Una lettura odometro con data e chilometraggio
- **Config_Store**: Il database SQLite che persiste configurazione utente e coda offline tra riavvii

## Requirements

### Requirement 1: Access Control

**User Story:** As a vehicle owner, I want only authorized Telegram users to interact with the Bot, so that my vehicle data remains private.

#### Acceptance Criteria

1. WHEN a message is received from a Telegram user whose ID is not in the configured whitelist, THE Bot SHALL ignore the message and not respond
2. WHEN a message is received from a Telegram user whose ID is in the configured whitelist, THE Bot SHALL process the message normally
3. THE Bot SHALL read the whitelist of authorized Telegram user IDs from the `ALLOWED_USER_IDS` environment variable at startup
4. IF the `ALLOWED_USER_IDS` environment variable is empty or missing, THEN THE Bot SHALL refuse to start and log an error message

### Requirement 2: LubeLogger Authentication

**User Story:** As a system administrator, I want the Bot to authenticate against LubeLogger using an API key, so that API calls are authorized.

#### Acceptance Criteria

1. THE Bot SHALL include the configured API key in the `x-api-key` header of every HTTP request to LubeLogger_API
2. THE Bot SHALL read the API key from the `LUBELOGGER_API_KEY` environment variable at startup
3. IF the `LUBELOGGER_API_KEY` environment variable is empty or missing, THEN THE Bot SHALL refuse to start and log an error message
4. THE Bot SHALL never include the API key value in log messages or user-facing error responses

### Requirement 3: Vehicle Selection

**User Story:** As a vehicle owner, I want to select which vehicle to use for data entry, so that records go to the correct vehicle in LubeLogger.

#### Acceptance Criteria

1. WHEN the User sends the `/vehicle` command, THE Bot SHALL query LubeLogger_API for the list of available vehicles and present them as an inline keyboard
2. WHEN the User selects a vehicle from the inline keyboard, THE Bot SHALL store the selection as the Active_Vehicle in Config_Store and confirm the choice
3. WHEN the User sends any data entry command without having selected an Active_Vehicle, THE Bot SHALL prompt the User to select a vehicle first
4. THE Bot SHALL persist the Active_Vehicle selection in Config_Store so that it survives Bot restarts
5. WHEN the User sends a data entry command with the `--vehicle <id>` option, THE Bot SHALL use the specified vehicle ID for that single operation instead of the Active_Vehicle

### Requirement 4: Fuel Record Entry

**User Story:** As a vehicle owner, I want to register fuel fill-ups from Telegram, so that I can track fuel consumption without opening the web UI.

#### Acceptance Criteria

1. WHEN the User sends the `/fuel` command without arguments, THE Bot SHALL start a conversational flow requesting: odometer, liters, cost, and full-tank flag
2. WHEN the User sends the `/fuel` command with positional arguments (odometer, liters, cost), THE Bot SHALL parse the arguments and create a Gas_Record with default values for omitted fields
3. THE Validator SHALL reject a Gas_Record where odometer is not a positive integer
4. THE Validator SHALL reject a Gas_Record where fuel consumed (liters) is not a positive number
5. THE Validator SHALL reject a Gas_Record where cost is a negative number
6. WHEN the User omits the date, THE Bot SHALL default to the current date in `YYYY-MM-DD` format
7. WHEN the User omits the full-tank flag, THE Bot SHALL default `isFillToFull` to `true`
8. WHEN the User omits the missed-fuel-up flag, THE Bot SHALL default `missedFuelUp` to `false`
9. WHEN a valid Gas_Record is confirmed, THE Bot SHALL send a POST request to `/api/vehicle/gasrecords/add?vehicleId={id}` with all fields as string values
10. WHEN LubeLogger_API responds with a success status, THE Bot SHALL send a confirmation message to the User with a summary of the recorded data

### Requirement 5: Service Record Entry

**User Story:** As a vehicle owner, I want to register maintenance and service records from Telegram, so that I can log repairs and scheduled maintenance quickly.

#### Acceptance Criteria

1. WHEN the User sends the `/service` command without arguments, THE Bot SHALL start a conversational flow requesting: odometer, description, and cost
2. WHEN the User sends the `/service` command with positional arguments (odometer, description, cost), THE Bot SHALL parse the arguments and create a Service_Record with default values for omitted fields
3. THE Validator SHALL reject a Service_Record where odometer is not a positive integer
4. THE Validator SHALL reject a Service_Record where description is empty
5. THE Validator SHALL reject a Service_Record where cost is a negative number
6. WHEN the User omits the date, THE Bot SHALL default to the current date in `YYYY-MM-DD` format
7. WHEN a valid Service_Record is confirmed, THE Bot SHALL send a POST request to `/api/vehicle/servicerecords/add?vehicleId={id}` with all fields as string values
8. WHEN LubeLogger_API responds with a success status, THE Bot SHALL send a confirmation message to the User with a summary of the recorded data

### Requirement 6: Odometer Record Entry

**User Story:** As a vehicle owner, I want to register odometer readings from Telegram, so that I can keep mileage up to date with minimal effort.

#### Acceptance Criteria

1. WHEN the User sends the `/km` command with an odometer value, THE Bot SHALL create an Odometer_Record with the current date and specified odometer
2. WHEN the User sends the `/km` command without arguments, THE Bot SHALL prompt the User to enter the current odometer reading
3. THE Validator SHALL reject an Odometer_Record where odometer is not a positive integer
4. WHEN the User omits the date, THE Bot SHALL default to the current date in `YYYY-MM-DD` format
5. WHEN a valid Odometer_Record is confirmed, THE Bot SHALL send a POST request to `/api/vehicle/odometerrecords/add?vehicleId={id}` with all fields as string values
6. WHEN LubeLogger_API responds with a success status, THE Bot SHALL send a confirmation message to the User with the recorded odometer value

### Requirement 7: Data Consultation

**User Story:** As a vehicle owner, I want to query my latest records from Telegram, so that I can check my last entry without opening the web UI.

#### Acceptance Criteria

1. WHEN the User sends the `/last fuel` command, THE Bot SHALL query the latest Gas_Record from LubeLogger_API and display date, odometer, liters, and cost
2. WHEN the User sends the `/last km` command, THE Bot SHALL query the latest Odometer_Record from LubeLogger_API and display date and odometer value
3. WHEN the User sends the `/status` command, THE Bot SHALL attempt to connect to LubeLogger_API and report whether the service is reachable, along with queue status
4. IF LubeLogger_API is unreachable during a consultation command, THEN THE Bot SHALL inform the User that LubeLogger is currently unavailable

### Requirement 8: Offline Queue and Resilience

**User Story:** As a vehicle owner, I want my data entries to be saved locally when LubeLogger is unreachable, so that no data is lost due to network issues.

#### Acceptance Criteria

1. IF LubeLogger_API is unreachable when a record is submitted, THEN THE Queue_Service SHALL persist the record in the local SQLite database with status `pending`
2. WHEN a record is queued locally, THE Bot SHALL inform the User that the record was saved locally and will be synced when LubeLogger becomes available
3. WHILE the Queue_Service contains pending records, THE Bot SHALL attempt to send them to LubeLogger_API every 5 minutes
4. WHEN a queued record is successfully sent to LubeLogger_API, THE Queue_Service SHALL update its status to `sent` and notify the User
5. THE Queue_Service SHALL process pending records in FIFO order (oldest first)
6. WHEN the User sends the `/queue` command, THE Bot SHALL display the number of pending records and their types
7. THE Queue_Service SHALL persist all pending records in SQLite so that they survive Bot restarts
8. IF a queued record fails to send after 3 consecutive attempts, THEN THE Queue_Service SHALL mark it as `failed` and notify the User

### Requirement 9: Command Parsing

**User Story:** As a vehicle owner, I want to enter data using short commands with inline arguments, so that I can register records quickly without multi-step conversations.

#### Acceptance Criteria

1. WHEN the User sends `/fuel <odometer> <liters> <cost>`, THE Command_Parser SHALL parse the three positional numeric arguments into a Gas_Record
2. WHEN the User sends `/service <odometer> "<description>" <cost>`, THE Command_Parser SHALL parse the odometer, quoted description, and cost into a Service_Record
3. WHEN the User sends `/km <odometer>`, THE Command_Parser SHALL parse the single numeric argument into an Odometer_Record
4. IF the Command_Parser receives arguments that do not match the expected format, THEN THE Bot SHALL respond with a usage hint showing the correct syntax
5. THE Command_Parser SHALL accept both dot and comma as decimal separators for numeric values (e.g., `45.2` and `45,2`)
6. FOR ALL valid record data, parsing a command string then formatting it back to a command string then parsing again SHALL produce an equivalent record (round-trip property)

### Requirement 10: Input Validation

**User Story:** As a vehicle owner, I want the Bot to validate my input before sending to LubeLogger, so that I get immediate feedback on errors.

#### Acceptance Criteria

1. THE Validator SHALL reject any record where the odometer value is less than or equal to zero
2. THE Validator SHALL reject any Gas_Record where liters is less than or equal to zero
3. THE Validator SHALL reject any record where cost is less than zero
4. THE Validator SHALL reject any Service_Record where description is an empty string or contains only whitespace
5. THE Validator SHALL accept any record where all numeric fields are within valid ranges and required string fields are non-empty
6. WHEN the Validator rejects a record, THE Bot SHALL respond with a specific error message indicating which field failed validation and why
7. FOR ALL valid inputs, THE Validator SHALL produce a validated record (no false rejections); FOR ALL invalid inputs, THE Validator SHALL produce a validation error (no false acceptances)

### Requirement 11: Configuration Persistence

**User Story:** As a vehicle owner, I want my Bot settings to persist between restarts, so that I do not have to reconfigure after updates or crashes.

#### Acceptance Criteria

1. THE Config_Store SHALL persist user preferences (Active_Vehicle, language) in the local SQLite database
2. WHEN the Bot starts, THE Config_Store SHALL load previously saved user preferences from the database
3. WHEN the User changes the Active_Vehicle, THE Config_Store SHALL immediately write the new value to the database
4. THE Config_Store SHALL support multiple users, each with independent preferences keyed by Telegram user ID

### Requirement 12: Startup and Health

**User Story:** As a system administrator, I want the Bot to validate its configuration at startup, so that misconfigurations are caught immediately.

#### Acceptance Criteria

1. WHEN the Bot starts, THE Bot SHALL validate that all required environment variables are set: `TELEGRAM_BOT_TOKEN`, `LUBELOGGER_URL`, `LUBELOGGER_API_KEY`, `ALLOWED_USER_IDS`
2. IF any required environment variable is missing, THEN THE Bot SHALL exit with a non-zero status code and log which variable is missing
3. WHEN the Bot starts successfully, THE Bot SHALL log the configured LubeLogger URL (without the API key) and the number of allowed user IDs
4. WHEN the User sends the `/start` command, THE Bot SHALL respond with a welcome message and prompt for vehicle selection if no Active_Vehicle is configured

---

## Non-Functional Requirements

### Requirement NF-1: Performance and Resources

**User Story:** As a system administrator, I want the Bot to run efficiently on low-power hardware, so that it can be deployed alongside LubeLogger on a Raspberry Pi.

#### Acceptance Criteria

1. WHILE the Bot is idle (no incoming messages), THE Bot SHALL consume less than 64 MB of RSS memory
2. WHEN the User sends a command, THE Bot SHALL respond within 3 seconds under normal network conditions
3. THE Bot SHALL use async I/O for all network operations to avoid blocking the event loop

### Requirement NF-2: Deployment

**User Story:** As a system administrator, I want to deploy the Bot as a Docker container alongside LubeLogger, so that the setup is simple and reproducible.

#### Acceptance Criteria

1. THE Bot SHALL be distributable as a Docker container image
2. THE Bot SHALL accept all configuration through environment variables (no configuration files required)
3. THE Bot SHALL use a single SQLite file for local persistence, mountable as a Docker volume
4. THE Bot SHALL operate in Telegram polling mode (no inbound network ports required)

### Requirement NF-3: Security

**User Story:** As a system administrator, I want the Bot to follow security best practices, so that credentials and data are protected.

#### Acceptance Criteria

1. THE Bot SHALL never log or display the LubeLogger API key in any output
2. THE Bot SHALL never log or display the Telegram bot token in any output
3. WHEN a message is received from an unauthorized user, THE Bot SHALL not reveal its existence or functionality
4. THE Bot SHALL not expose any network ports (polling mode only)

### Requirement NF-4: Maintainability

**User Story:** As a developer, I want the codebase to follow Python best practices with full type safety, so that the project is easy to understand and contribute to.

#### Acceptance Criteria

1. THE Bot codebase SHALL use Python 3.11+ with full type annotations on all functions
2. THE Bot codebase SHALL pass `ruff` linting with zero errors
3. THE Bot codebase SHALL include automated tests using pytest and hypothesis
4. THE Bot SHALL include a README.md structured as follows:
   - A concise intro highlighting the problem solved and key strengths (offline resilience, quick entry, Docker-ready)
   - A Quick Start section (5 steps or fewer to get the bot running)
   - A Commands Reference section with usage examples for each command
   - A Configuration section documenting all environment variables
   - A Docker Compose section showing how to add the bot alongside LubeLogger
   - An Architecture section with a brief overview for contributors
   - A Contributing section with development setup instructions
5. THE README SHALL be written in English with a clear, engaging tone suitable for open-source discovery (e.g., GitHub trending, Show and Tell)

### Requirement NF-5: Internationalization

**User Story:** As a vehicle owner, I want Bot messages in my language, so that the interface feels natural to use.

#### Acceptance Criteria

1. THE Bot SHALL use English as the default language for all user-facing messages
2. THE Bot SHALL include Italian as an available translation
3. THE Bot SHALL store all user-facing strings in a dedicated module or dictionary, separate from business logic
4. THE Bot architecture SHALL allow adding new language translations without modifying business logic code
5. THE Bot SHALL allow each User to select their preferred language via a `/lang` command, persisted in Config_Store

---

## Technical Constraints

- **Telegram Bot API**: polling mode (long-polling), no webhook
- **LubeLogger API**: autenticazione via `x-api-key`, payload JSON con tutti i campi come stringhe, endpoint verificati dal codice sorgente C# e dalla Postman Collection ufficiale
- **Database locale**: SQLite tramite aiosqlite (nessun processo DB separato)
- **Linguaggio**: Python 3.11+ con async/await per tutto l'I/O
- **Librerie core**: `python-telegram-bot` v20+, `httpx`, `pydantic` v2, `aiosqlite`
- **Package manager**: `uv`
- **Linting/formatting**: `ruff`
- **Testing**: `pytest` + `hypothesis`

---

## Out of Scope (v1)

- Repair records e upgrade records (aggiungibili in v2)
- Upload allegati/foto ricevute
- Notifiche push da LubeLogger verso il bot
- Gestione multi-utente con permessi differenziati (admin/viewer)
- Modalità webhook Telegram
- Integrazione con extra fields custom di LubeLogger
- Comandi per cancellare o modificare record esistenti
