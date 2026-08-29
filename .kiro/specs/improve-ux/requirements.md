# Requirements Document

## Introduction

This feature reworks the interaction model of the LubeLogger Telegram bot so that a user never needs to remember a command or retype a value the bot already knows. It introduces a persistent navigation keyboard, a single self-updating message per data-entry operation, smart defaults sourced from the vehicle's own history, a confirmation step with an edit-any-field option, and richer post-save feedback.

The interaction model rests on a strict separation of concerns that the Telegram Bot API imposes rather than merely suggests: `editMessageText` and `editMessageReplyMarkup` accept only an `InlineKeyboardMarkup`, and a `ReplyKeyboardMarkup` can only be changed by sending a new message. Therefore the reply keyboard is used exclusively as a static navigation menu and is never swapped mid-flow, while every step of a Conversation_Flow is rendered as an inline keyboard on one Card_Message that is edited in place. Typed answers to bot prompts are deleted so the card stays the last message in the chat.

Existing behaviour that must survive unchanged: inline-argument commands (`/fuel 45000 42,5 78,90`), the `--vehicle <id>` override, the offline SQLite queue, and the auth whitelist.

## Glossary

- **Bot**: The LubeLogger Telegram bot application built with python-telegram-bot v20+.
- **Menu_Keyboard**: The persistent `ReplyKeyboardMarkup` acting as the bot's main navigation, sent with `is_persistent=True` and `resize_keyboard=True`. It is never replaced or removed during normal operation.
- **Inline_Keyboard**: An `InlineKeyboardMarkup` attached to a specific message, used for all in-flow actions.
- **Card_Message**: The single Bot message representing an in-progress operation. It shows the values collected so far, the current prompt, and the available actions, and is updated via `editMessageText` at every step instead of being re-sent.
- **Conversation_Flow**: A multi-step interaction, driven by a `ConversationHandler`, during which the Bot collects the fields of one record.
- **Flow_Token**: A short opaque identifier generated when a Conversation_Flow starts, embedded in the `callback_data` of that flow's Inline_Keyboard buttons and used to reject taps coming from a superseded Card_Message.
- **Progress_Indicator**: A label showing the current data-entry step and the total number of data-entry steps of the flow (e.g. "Step 2/4").
- **Summary_State**: The state of the Card_Message after all fields are collected, listing every value with the Save, Edit and Cancel actions.
- **Field_Picker**: The Inline_Keyboard shown after tapping Edit in Summary_State, containing one button per collected field labelled with its current value, allowing a single field to be corrected without restarting the flow.
- **Smart_Default**: A value the Bot infers and offers without being asked, such as the only available vehicle or the vehicle's last known odometer.
- **Last_Known_Odometer**: The highest odometer value known for a vehicle, computed as the maximum across its latest gas record, latest service record, latest odometer record, and any value the Bot itself has recorded locally, together with the date and source of that value.
- **Options_Menu**: An Inline_Keyboard reachable from the Menu_Keyboard, grouping the settings and diagnostics actions that are too rare to deserve a permanent button: vehicle selection, language, connectivity status and queue status.
- **Active_Vehicle_Name**: The display name of the user's active vehicle, persisted next to its identifier so that messages can name the vehicle even when LubeLogger cannot be reached. It is refreshed whenever the vehicle list is fetched.
- **Consumption_Metric**: Fuel consumption expressed as litres per 100 km for a fuel record.
- **BotFather_Commands**: The command list registered through the Telegram `setMyCommands` API so it appears as autocomplete when the user types "/".
- **Menu_Label**: The text of a Menu_Keyboard button. Because tapping such a button sends a plain text message rather than a command, Menu_Labels are matched against a closed allowlist built from every supported locale.

## Requirements

### Requirement 1: Persistent Navigation Menu

**User Story:** As a user, I want an always-visible set of main actions, so that I never need to remember slash commands.

#### Acceptance Criteria

1. WHEN the user sends /start, THE Bot SHALL send the Menu_Keyboard with `is_persistent=True` and `resize_keyboard=True`.
2. THE Menu_Keyboard SHALL contain five buttons laid out in two rows that separate writing actions from reading ones: "⛽ Fuel", "🔧 Service" and "🚧 Odometer" on the first row, "📊 Latest" and "⚙️ Options" on the second.
3. THE Bot SHALL send the Menu_Keyboard only when it is first established for a chat or when its content changes, and SHALL NOT re-attach it to every outgoing message.
4. THE Bot SHALL NOT replace, remove, or otherwise alter the Menu_Keyboard while a Conversation_Flow is active.
5. WHEN the user taps a Menu_Keyboard button, THE Bot SHALL start the corresponding operation: fuel entry, service entry, odometer entry, the Latest menu of Requirement 10, or the Options_Menu.
6. THE Bot SHALL recognise Menu_Labels through an allowlist covering all supported locales, so that a keyboard rendered in one language keeps working after the user changes language with /lang.
7. THE Menu_Keyboard SHALL be localized, and each button label SHALL contain a text word in addition to its emoji.
8. THE writing buttons and the reading buttons SHALL be labelled so that their purpose cannot be confused: "🚧 Odometer" records a new reading, while "📊 Latest" only displays existing records.
9. WHEN the user taps "⚙️ Options", THE Bot SHALL send a message carrying the Options_Menu, with entries for vehicle selection, language, connectivity status and queue status.
10. WHEN the user selects an entry of the Options_Menu, THE Bot SHALL edit that same message in place to render the selected action.
11. THE Options_Menu and every screen reached from it SHALL carry a "↩ Back" button returning the message to the Options_Menu.
12. THE /vehicle, /lang, /status and /queue commands SHALL keep working as direct entry points to the same behaviour.
13. THE Bot SHALL NOT place vehicle selection or language selection directly on the Menu_Keyboard, because they are configuration actions rather than daily ones.

### Requirement 2: Command Registration

**User Story:** As a user, I want commands to appear as suggestions when I type "/", so that I can discover available actions without reading documentation.

#### Acceptance Criteria

1. WHEN the Bot application starts, THE Bot SHALL register via `setMyCommands` the commands: start, fuel, service, km, last, vehicle, status, queue, lang, cancel.
2. THE Bot SHALL provide a localized one-line description for every registered command in every supported locale.
3. WHEN registering commands, THE Bot SHALL use `BotCommandScopeChat` for each whitelisted user, using the language stored for that user in ConfigStore, so the descriptions match the language the user actually chose.
4. THE Bot SHALL additionally register a default command list with `language_code` per supported locale, so that users see localized descriptions before any per-chat registration exists.
5. WHEN the user changes language with /lang, THE Bot SHALL re-register the commands for that chat in the newly selected language.
6. IF a `setMyCommands` call fails, THEN THE Bot SHALL log the failure at WARNING level and continue startup without interruption.

### Requirement 3: Single Card Message Per Operation

**User Story:** As a user, I want the bot to keep its interaction in one message, so that the chat does not fill up with prompts every time I log a refuel.

#### Acceptance Criteria

1. WHEN a Conversation_Flow starts, THE Bot SHALL send exactly one Card_Message and SHALL store its identifier for the duration of the flow.
2. WHEN the Bot advances to the next step of a Conversation_Flow, THE Bot SHALL update the Card_Message via `editMessageText` instead of sending a new message.
3. THE Card_Message SHALL show, at every step, the values collected so far, the current prompt, and the Progress_Indicator.
4. WHEN the Bot has consumed a typed answer to a prompt it issued inside an active Conversation_Flow, THE Bot SHALL delete that user message so the Card_Message remains the last message in the chat.
5. THE Bot SHALL NOT delete any message other than a typed answer to its own prompt inside an active Conversation_Flow.
6. IF deleting a user message fails for any reason, THEN THE Bot SHALL log at DEBUG level and continue the flow without informing the user.
7. IF editing the Card_Message fails, THEN THE Bot SHALL send a new message with the same content and adopt it as the new Card_Message.
8. WHEN a Conversation_Flow prompts for a typed value, THE Bot SHALL set `input_field_placeholder` on the Menu_Keyboard to a hint describing the expected value.
9. WHEN a Conversation_Flow terminates, by save, queue, or cancellation, THE Bot SHALL edit the Card_Message to its final state and remove its Inline_Keyboard except for the follow-up actions defined in Requirements 6 and 9.

### Requirement 4: Guided Flow With Confirmation

**User Story:** As a user, I want to see where I am, fix a single wrong value, and back out at any point, so that I stay in control and never save a typo.

#### Acceptance Criteria

1. WHEN the Bot prompts for a value inside a Conversation_Flow, THE Bot SHALL include a Progress_Indicator counting only data-entry steps and excluding the Summary_State.
2. IF a Conversation_Flow has a single data-entry step, THEN THE Bot SHALL omit the Progress_Indicator.
3. WHILE a Conversation_Flow is active, THE Card_Message SHALL carry a "✕ Cancel" Inline_Keyboard button at every step.
4. WHEN the user taps "✕ Cancel", THE Bot SHALL discard all collected values, clear the flow state from `user_data`, and edit the Card_Message to a cancellation notice with no Inline_Keyboard.
5. WHEN a step offers a closed set of choices, such as the full-tank flag, THE Bot SHALL present them as Inline_Keyboard buttons rather than asking for typed text.
6. WHEN all fields have been collected, THE Bot SHALL edit the Card_Message into Summary_State, listing every collected value with "✅ Save", "✏️ Edit" and "✕ Cancel" buttons.
7. WHEN the user taps "✅ Save", THE Bot SHALL submit the record as specified in Requirement 6 or queue it as specified in Requirement 9.
8. WHEN the user taps "✏️ Edit", THE Bot SHALL replace the Summary_State buttons with the Field_Picker, showing one button per field labelled with the field name and its current value.
9. WHEN the user selects a field from the Field_Picker, THE Bot SHALL re-prompt for that field alone, keeping every other collected value, and SHALL return to Summary_State once the new value is accepted.
10. WHEN the user is re-prompted for a single field, THE Bot SHALL offer the current value as a tappable button so it can be kept without retyping.
11. IF a typed value fails validation at any step, THEN THE Bot SHALL keep the flow at that step, re-render the Card_Message with a localized error, and SHALL NOT terminate the flow.
12. THE /cancel command SHALL remain a valid fallback in every Conversation_Flow and SHALL behave identically to the "✕ Cancel" button.

### Requirement 5: Smart Defaults and Odometer Sanity Check

**User Story:** As a user, I want the bot to know my vehicle and my last mileage, so that I type as little as possible and cannot silently record a wrong reading.

#### Acceptance Criteria

1. WHEN a Conversation_Flow starts, the user has no active vehicle, and exactly one vehicle is available, THE Bot SHALL select that vehicle, persist it as the active vehicle in ConfigStore, and inform the user of the selection once.
2. WHEN a Conversation_Flow starts and an active vehicle is already persisted, THE Bot SHALL use it without prompting and SHALL NOT repeat the auto-selection notice.
3. WHEN the Bot prompts for an odometer value, THE Bot SHALL display the Last_Known_Odometer with its date and source as a reference (e.g. "Last: 45,230 km — fuel record of 12/07").
4. THE Last_Known_Odometer SHALL be computed as the maximum across the vehicle's latest gas record, latest service record, latest odometer record, and any odometer value the Bot has itself submitted or queued for that vehicle.
5. THE Bot SHALL persist the Last_Known_Odometer per vehicle locally, and SHALL update it after every successful submission and after every enqueued record.
6. IF LubeLogger is unreachable when refreshing the Last_Known_Odometer, THEN THE Bot SHALL use the locally persisted value, and SHALL omit the reference entirely when no local value exists.
7. WHEN the Bot prompts for an odometer value and a Last_Known_Odometer exists, THE Bot SHALL offer that value as a tappable Inline_Keyboard button so a reading equal to the last one requires no typing.
8. IF the odometer value entered by the user is lower than the Last_Known_Odometer, THEN THE Bot SHALL warn the user, state both values, and require an explicit confirmation before accepting it.
9. WHEN the user confirms a lower odometer value, THE Bot SHALL accept it and continue the flow without further warnings for that flow.
10. THE Bot SHALL NOT reject an odometer value solely because it is lower than the Last_Known_Odometer.
11. WHEN a Conversation_Flow starts, THE Bot SHALL fetch the vehicle list from LubeLogger with a single live call, which doubles as a connectivity probe and as a wake-up for instances that idle down.
12. IF that call fails, THEN THE Bot SHALL continue the flow using the persisted active vehicle and its Active_Vehicle_Name, without blocking data entry.
13. WHEN the vehicle list is fetched successfully, THE Bot SHALL refresh the persisted Active_Vehicle_Name of the active vehicle.

### Requirement 6: Rich Confirmation After Saving

**User Story:** As a user, I want a detailed confirmation after saving, so that I can verify what was logged and immediately do the next thing.

#### Acceptance Criteria

1. WHEN a fuel record is saved successfully, THE Bot SHALL edit the Card_Message into a confirmation showing vehicle name, date, odometer, litres, cost, and full-tank status.
2. WHEN a service record is saved successfully, THE Bot SHALL show vehicle name, date, odometer, description, and cost.
3. WHEN an odometer record is saved successfully, THE Bot SHALL show vehicle name, date, and odometer.
4. THE Bot SHALL resolve the vehicle name from the persisted Active_Vehicle_Name, so that confirmations show a real name rather than a numeric identifier even when LubeLogger is unreachable.
5. IF the LubeLogger API exposes a computed fuel economy value for a gas record, THEN THE Bot SHALL display that value rather than computing its own, so the number always matches the LubeLogger web UI.
6. IF the LubeLogger API does not expose a computed fuel economy value, THEN THE Bot SHALL compute the Consumption_Metric itself and SHALL label it as an estimate.
7. WHEN computing the Consumption_Metric itself, THE Bot SHALL do so only if a previous gas record exists for the vehicle AND both the current and the previous record have full-tank set AND neither has the missed-fuel-up flag set.
8. IF the odometer delta between the current and the previous gas record is zero or negative, THEN THE Bot SHALL omit the Consumption_Metric.
9. IF the conditions for a meaningful Consumption_Metric are not met, THEN THE Bot SHALL omit it silently rather than displaying a placeholder or a warning.
10. WHEN a record is saved successfully, THE Bot SHALL attach an Inline_Keyboard with "🔁 Log another" and "📊 Latest" buttons to the confirmation.

### Requirement 7: Log Another Shortcut

**User Story:** As a user, I want to log a second record right after the first, so that I can enter a backlog of receipts without navigating back.

#### Acceptance Criteria

1. WHEN the user taps "🔁 Log another" on a confirmation, THE Bot SHALL start a new Conversation_Flow of the same record type on the same vehicle.
2. WHEN a "🔁 Log another" flow starts, THE Bot SHALL skip vehicle selection and present the first data-entry prompt directly.
3. WHEN a "🔁 Log another" flow starts, THE Bot SHALL send a new Card_Message and SHALL remove the Inline_Keyboard from the previous confirmation, leaving its text intact as a record of what was saved.

### Requirement 8: Onboarding

**User Story:** As a new user, I want to understand the bot and be operational in one interaction, so that I do not have to read documentation.

#### Acceptance Criteria

1. WHEN a user with no active vehicle sends /start, THE Bot SHALL send a welcome message of at most three sentences describing what the bot does.
2. WHEN a user with no active vehicle sends /start, THE Bot SHALL attach an Inline_Keyboard listing the available vehicles for immediate selection.
3. WHEN the user selects a vehicle during onboarding, THE Bot SHALL persist it as active, edit the message into a confirmation, and establish the Menu_Keyboard.
4. WHEN a user with an active vehicle sends /start, THE Bot SHALL send a short welcome-back message naming the active vehicle and establish the Menu_Keyboard.
5. IF LubeLogger is unreachable during onboarding, THEN THE Bot SHALL explain the situation, suggest retrying with /start later, and still establish the Menu_Keyboard so the user is not left without navigation.
6. WHEN onboarding completes with a vehicle selection, THE Bot SHALL persist the Active_Vehicle_Name together with the vehicle identifier.

### Requirement 9: Offline Path in the New Flows

**User Story:** As a user, I want the guided flow to behave predictably when my LubeLogger is down, so that I never lose an entry I have already typed.

#### Acceptance Criteria

1. WHEN the user taps "✅ Save" and LubeLogger is unreachable, THE Bot SHALL enqueue the record in the existing offline queue and SHALL NOT lose any collected value.
2. WHEN a record is enqueued from Summary_State, THE Bot SHALL edit the Card_Message into a queued-state confirmation that lists the same values as a saved confirmation and states that the record will sync automatically.
3. WHEN a record is enqueued, THE Bot SHALL omit the Consumption_Metric from the queued confirmation.
4. WHEN a record is enqueued, THE Bot SHALL attach only the "🔁 Log another" button to the queued confirmation.
5. WHEN a queued record is later synced or permanently failed by the retry job, THE Bot SHALL notify the submitting user as already implemented, and SHALL NOT attempt to edit the original Card_Message.
6. IF LubeLogger is unreachable when a Conversation_Flow needs reference data, such as the Last_Known_Odometer or the vehicle name, THEN THE Bot SHALL degrade to the locally persisted Last_Known_Odometer and Active_Vehicle_Name, and SHALL allow the flow to complete.

### Requirement 10: Latest Records Menu

**User Story:** As a user, I want to check the last thing I logged without typing a command with an argument, so that consulting data is as easy as entering it.

#### Acceptance Criteria

1. WHEN the user taps "📊 Latest" from the Menu_Keyboard or from a confirmation, THE Bot SHALL send a message with an Inline_Keyboard offering "⛽ Last fuel" and "🚧 Last odometer".
2. WHEN the user selects an option from the Latest menu, THE Bot SHALL edit that same message in place to show the requested record.
3. WHEN showing a record from the Latest menu, THE Bot SHALL include a "↩ Back" button returning the message to the Latest menu.
4. IF no record of the requested type exists, THEN THE Bot SHALL edit the message to state that, keeping the "↩ Back" button.
5. IF LubeLogger is unreachable, THEN THE Bot SHALL edit the message to the unreachable notice, keeping the "↩ Back" button.
6. THE existing `/last fuel` and `/last km` commands SHALL keep working unchanged.

### Requirement 11: Interaction Robustness

**User Story:** As a user, I want stale buttons and unusual input to fail safely, so that the bot never saves something I did not intend.

#### Acceptance Criteria

1. WHEN a Conversation_Flow starts, THE Bot SHALL generate a Flow_Token and embed it in the `callback_data` of every Inline_Keyboard button belonging to that flow.
2. WHEN the Bot receives a callback query whose Flow_Token does not match the user's current flow, THE Bot SHALL answer the callback with a localized "this action has expired" alert and SHALL NOT modify any state.
3. THE `callback_data` of every button SHALL stay within Telegram's 64-byte limit and SHALL carry only an action identifier and a Flow_Token, never field values.
4. THE Bot SHALL answer every callback query it receives, so that the client never shows a hanging progress indicator.
5. WHEN a Menu_Label arrives as a typed answer while a Conversation_Flow is awaiting a value, THE Bot SHALL treat it as a navigation intent rather than as data, and SHALL ask the user to confirm abandoning the flow in progress.
6. WHEN the user confirms abandoning a flow in progress, THE Bot SHALL discard the collected values and start the requested operation.
7. THE Bot SHALL send all user-facing messages with HTML parse mode and SHALL escape every value originating from user input or from the LubeLogger API before interpolating it, so that a description such as "oil change <5000km" cannot break message delivery.
8. WHEN a callback query arrives from a user who is not in the whitelist, THE Bot SHALL answer it and ignore it, consistently with the existing auth behaviour.

### Requirement 12: Backward Compatibility

**User Story:** As an existing user, I want my current way of using the bot to keep working, so that an interface improvement does not become a regression.

#### Acceptance Criteria

1. WHEN a data-entry command is invoked with inline arguments, THE Bot SHALL parse, validate and submit immediately, bypassing the Card_Message, Summary_State and confirmation step.
2. WHEN a data-entry command is invoked with inline arguments, THE Bot SHALL still apply the odometer sanity check of Requirement 5.8 and the rich confirmation of Requirement 6.
3. THE `--vehicle <id>` override SHALL keep working in inline-argument mode and SHALL apply to the started Conversation_Flow when no arguments follow it.
4. THE comma and dot decimal separators SHALL keep being accepted in every typed input, in both inline-argument and Conversation_Flow modes.
5. THE existing auth whitelist, offline queue, and queue notification behaviour SHALL remain functionally unchanged.

### Requirement 13: Existing Defects To Fix

**User Story:** As a user, I want the inconsistencies in the current flows fixed as part of this rework, so that the bot behaves the same way everywhere.

#### Acceptance Criteria

1. WHEN an invalid odometer value is entered during the /km flow, THE Bot SHALL re-prompt for the value instead of terminating the conversation, matching the behaviour of the fuel and service flows.
2. WHEN a service flow is cancelled, THE Bot SHALL clear its collected values from `user_data`, so that no residual data can leak into a subsequent flow started via re-entry.
3. THE Bot SHALL resolve vehicle names without issuing a second `get_vehicles` call after a vehicle selection, reusing the list already fetched when the selection keyboard was built.
4. THE language selection prompt SHALL be read from the locale files rather than hardcoded as a bilingual string in the handler.
5. THE i18n keys for equivalent prompts across flows SHALL follow one naming convention, replacing the current mix of `prompt_odometer` and `fuel_ask_odometer`.
6. WHEN a vehicle cannot be resolved to a name, THE Bot SHALL fall back to a localized label rather than the untranslated string "Vehicle #<id>".

## Non-Functional Requirements

### NF-1: Testability

1. Keyboard construction SHALL live in a dedicated module of pure functions that return Telegram markup objects from plain arguments, callable in tests without a Bot instance or network access.
2. Message rendering SHALL live in a dedicated module of pure functions that return the final message text from plain arguments, so that card layouts, confirmations and summaries are assertable as strings.
3. A test SHALL assert that every locale file exposes exactly the same set of keys, so that a message added in one language cannot silently fall back to English in another.
4. A test SHALL assert that every `callback_data` value produced by the keyboard module stays within 64 bytes.
5. The Consumption_Metric computation SHALL be a pure function covered by property-based tests, including the cases that must yield no value.
6. The existing test suite SHALL keep passing without modification, except where a test asserts a message format this feature intentionally changes.

### NF-2: Network Usage

1. THE Bot SHALL NOT introduce a persistent cache of the vehicle list. The list is fetched live, because the call is cheap and doubles as a wake-up for instances that idle down.
2. Starting a Conversation_Flow SHALL issue at most one LubeLogger API call.
3. Advancing from one step of a Conversation_Flow to the next SHALL issue no LubeLogger API call.
4. Card_Message updates SHALL be a single Telegram API call per step.
5. The only vehicle information persisted locally SHALL be the active vehicle identifier, its Active_Vehicle_Name, and the Last_Known_Odometer of Requirement 5.5, so that no vehicle-list cache invalidation problem is introduced.

### NF-3: Internationalization

1. Every new user-facing string SHALL exist in all supported locale files, including button labels, placeholders and callback alerts.
2. Menu_Labels SHALL be resolvable across locales, so that a keyboard rendered before a language change keeps functioning after it.
3. Numbers and dates SHALL be rendered in a format consistent with the selected locale.
4. Adding a locale SHALL still require only a new JSON file, with no code change, as documented in the README.

### NF-4: Privacy and Safety

1. The Bot SHALL NOT log message content, only structural information such as flow type, step and user identifier.
2. Message deletion SHALL be limited to the case defined in Requirement 3.4, and SHALL never be attempted on a message the Bot did not prompt for.
3. The API key SHALL continue to be absent from every log line and every user-facing message.

### NF-5: Documentation

1. The README command reference SHALL be updated to describe the Menu_Keyboard and the guided flow, while keeping the inline-argument syntax documented for power users.
2. The README SHALL state the known limitation that costs and volumes are rendered with euro and litre units regardless of the LubeLogger instance configuration.

### NF-6: External API Assumptions

1. THE Bot SHALL NOT assume that numeric and date values returned by LubeLogger are formatted in invariant culture, because an instance can be configured either way through its `LUBELOGGER_INVARIANT_API` setting. Parsing SHALL tolerate both.
2. THE Bot SHALL NOT assume that the LubeLogger instance is configured in litres and kilometres, since LubeLogger supports MPG, UK MPG, L/100km and km/L. Any consumption figure the Bot renders itself SHALL state the unit it is using.
3. Values read from LubeLogger SHALL be treated as untrusted input and escaped before being interpolated into a message, as required by Requirement 11.7.

## Out of Scope

The following are deliberately excluded from this iteration.

- **Bare numeric input as an implicit fuel entry** (sending "45000 42,5 78,90" with no command). It is the fastest possible entry path and worth a follow-up, but it interacts with Menu_Label matching and needs its own disambiguation rules.
- **Multi-record history listings.** The Latest menu shows one record per type, reusing the existing endpoints.
- **Unit and currency configuration.** Recorded as a known limitation in NF-5.2 instead.
- **Editing or deleting records already stored in LubeLogger.**
- **Photo or receipt attachments.**

## Open Questions

1. Requirement 6.5 depends on whether the LubeLogger API returns a computed fuel economy value for gas records. The published LubeLogger documentation does not describe the response schema of `/api/vehicle/gasrecords`, so this SHALL be resolved during design by querying a live instance. The outcome determines whether the Bot displays LubeLogger's own figure or falls back to the estimate of Requirement 6.6.
