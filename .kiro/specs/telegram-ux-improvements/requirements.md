# Requirements Document

## Introduction

This feature improves the Telegram bot UX for the LubeLogger bot by introducing persistent keyboards, smart defaults, improved conversation flows with progress indicators and confirmation steps, rich post-save feedback with computed metrics, command registration with BotFather, a better onboarding experience, and in-place message editing to keep the chat clean. The goal is to make the bot intuitive and visually guided so users never need to memorize commands.

## Glossary

- **Bot**: The LubeLogger Telegram bot application built with python-telegram-bot v20+.
- **Reply_Keyboard**: A persistent keyboard rendered below the message input area using Telegram's ReplyKeyboardMarkup.
- **Inline_Keyboard**: An inline keyboard attached to a specific message using InlineKeyboardMarkup.
- **Conversation_Flow**: A multi-step ConversationHandler interaction where the Bot collects input across multiple messages.
- **Smart_Default**: An automatically inferred value presented to the user based on their history or configuration (e.g., auto-selected vehicle, last odometer reading).
- **Progress_Indicator**: A textual label showing the current step number and total steps within a Conversation_Flow (e.g., "Step 2/4").
- **Summary_Message**: A formatted recap of all collected values shown to the user before final submission.
- **Consumption_Metric**: The fuel consumption computed as liters per 100 km based on the delta between the current and previous odometer reading.
- **BotFather_Commands**: The list of bot command descriptions registered via the Telegram `setMyCommands` API so that they appear as autocomplete suggestions when the user types "/".
- **In_Place_Edit**: Editing the Bot's previously sent message via `edit_message_text` or `edit_message_reply_markup` instead of sending a new message.

## Requirements

### Requirement 1: Persistent Reply Keyboard

**User Story:** As a user, I want an always-visible keyboard with main action buttons, so that I never need to remember slash commands.

#### Acceptance Criteria

1. WHEN the user sends /start or selects a vehicle for the first time, THE Bot SHALL display a Reply_Keyboard containing the buttons "⛽ Fuel", "🔧 Service", "📊 History".
2. WHILE the user is not inside a Conversation_Flow, THE Bot SHALL keep the Reply_Keyboard visible on every response message.
3. WHEN the user taps a Reply_Keyboard button, THE Bot SHALL trigger the corresponding command handler (fuel, service, or last).
4. WHILE the user is inside a Conversation_Flow, THE Bot SHALL replace the Reply_Keyboard with a single "❌ Cancel" button.
5. WHEN the Conversation_Flow ends (by completion or cancellation), THE Bot SHALL restore the main Reply_Keyboard.

### Requirement 2: Register Commands with BotFather

**User Story:** As a user, I want commands to appear as suggestions when I type "/", so that I can discover available actions without reading documentation.

#### Acceptance Criteria

1. WHEN the Bot application starts, THE Bot SHALL call the Telegram `setMyCommands` API to register the commands: fuel, service, km, vehicle, last, status, lang, start.
2. THE Bot SHALL include a short localized description for each registered command.
3. IF the `setMyCommands` call fails, THEN THE Bot SHALL log the error at WARNING level and continue startup without interruption.

### Requirement 3: Smart Defaults

**User Story:** As a user, I want the bot to auto-select my vehicle and show my last odometer reading, so that I can enter data faster with less typing.

#### Acceptance Criteria

1. WHEN the user starts a Conversation_Flow and has exactly one vehicle configured in LubeLogger, THE Bot SHALL auto-select that vehicle without prompting.
2. WHEN the user starts a Conversation_Flow and has exactly one vehicle configured, THE Bot SHALL inform the user which vehicle was auto-selected.
3. WHEN the Bot asks for an odometer reading, THE Bot SHALL display the last known odometer value as a reference (e.g., "Last reading: 45230 km").
4. IF the LubeLogger API is unreachable when fetching the last odometer reading, THEN THE Bot SHALL skip the reference display and prompt without it.

### Requirement 4: Improved Conversation Flow

**User Story:** As a user, I want to see where I am in the flow and have the option to cancel at any step, so that I feel in control of the interaction.

#### Acceptance Criteria

1. WHEN the Bot sends a prompt during a Conversation_Flow, THE Bot SHALL include a Progress_Indicator showing the current step and total steps (e.g., "Step 2/4").
2. WHILE the user is inside a Conversation_Flow, THE Bot SHALL display a "❌ Cancel" button accessible at every step.
3. WHEN the user taps "❌ Cancel" at any step, THE Bot SHALL abort the Conversation_Flow, discard collected data, and restore the main Reply_Keyboard.
4. WHEN all inputs have been collected in a Conversation_Flow, THE Bot SHALL display a Summary_Message listing all entered values with "✅ Save", "✏️ Edit", and "❌ Cancel" Inline_Keyboard buttons.
5. WHEN the user taps "✅ Save" on the Summary_Message, THE Bot SHALL submit the record to LubeLogger.
6. WHEN the user taps "✏️ Edit" on the Summary_Message, THE Bot SHALL restart the Conversation_Flow from step 1 with previously entered values as defaults.
7. WHEN the user taps "❌ Cancel" on the Summary_Message, THE Bot SHALL discard all collected data, remove the Summary_Message Inline_Keyboard, and restore the main Reply_Keyboard.

### Requirement 5: Rich Confirmation After Saving

**User Story:** As a user, I want a detailed confirmation after saving a record, so that I can verify what was logged and quickly take follow-up actions.

#### Acceptance Criteria

1. WHEN a fuel record is saved successfully, THE Bot SHALL display a formatted confirmation including: vehicle name, odometer, liters, cost, full-tank status, and date.
2. WHEN a fuel record is saved and a previous fuel record exists for the same vehicle, THE Bot SHALL compute and display the Consumption_Metric (L/100km) based on the odometer delta and liters filled.
3. IF no previous fuel record exists for the vehicle, THEN THE Bot SHALL omit the Consumption_Metric from the confirmation.
4. WHEN a record is saved successfully, THE Bot SHALL attach an Inline_Keyboard with "🔁 Log another" and "📊 History" buttons to the confirmation message.
5. WHEN a service or odometer record is saved successfully, THE Bot SHALL display a formatted confirmation including: vehicle name, odometer, and record-specific details (description and cost for service).

### Requirement 6: Repeat/Shortcut Button

**User Story:** As a user, I want a quick way to log another record of the same type after saving, so that I can batch-enter multiple records efficiently.

#### Acceptance Criteria

1. WHEN the user taps "🔁 Log another" on a confirmation message, THE Bot SHALL start a new Conversation_Flow of the same record type with the vehicle pre-selected.
2. WHEN the "🔁 Log another" flow starts, THE Bot SHALL skip the vehicle selection step and display the first data-entry prompt directly.

### Requirement 7: Better /start Onboarding

**User Story:** As a user, I want a concise welcome message with clear next steps, so that I understand how to use the bot immediately.

#### Acceptance Criteria

1. WHEN a new user sends /start with no active vehicle set, THE Bot SHALL display a brief welcome message (maximum 3 sentences) explaining the bot purpose.
2. WHEN a new user sends /start with no active vehicle set, THE Bot SHALL display an Inline_Keyboard with available vehicles for immediate selection.
3. WHEN the user selects a vehicle from the onboarding Inline_Keyboard, THE Bot SHALL set that vehicle as active and display the main Reply_Keyboard.
4. WHEN a returning user sends /start with an active vehicle already set, THE Bot SHALL display a brief welcome-back message and the main Reply_Keyboard.
5. IF the LubeLogger API is unreachable during onboarding, THEN THE Bot SHALL inform the user and suggest retrying with /start later.

### Requirement 8: Edit Messages In Place

**User Story:** As a user, I want the bot to update its previous messages instead of sending new ones, so that the chat stays clean during multi-step flows.

#### Acceptance Criteria

1. WHILE the user is inside a Conversation_Flow, THE Bot SHALL edit its previous prompt message to show the new prompt instead of sending a separate message.
2. WHEN the Bot edits a message in place, THE Bot SHALL preserve the Progress_Indicator in the updated content.
3. IF editing a message fails (e.g., message is too old or was deleted), THEN THE Bot SHALL fall back to sending a new message.
4. WHEN the Summary_Message is confirmed or cancelled, THE Bot SHALL edit it to show the final outcome (confirmation text or cancellation notice) and remove the Inline_Keyboard.
