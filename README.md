# LubeLogger Telegram Bot

A Telegram bot that lets you log fuel fill-ups, service records, and odometer readings to [LubeLogger](https://github.com/hargata/lubelogger) — right from your phone. No web UI needed.

**Why this exists:** Logging a refuel shouldn't mean opening a browser, navigating to your LubeLogger instance, and filling out a form. With this bot, you send a Telegram message and you're done. It also works great when your LubeLogger runs on a home server with no public access — the bot sits next to it on the same network, and Telegram bridges the gap from anywhere. If LubeLogger is temporarily down, records queue locally and sync later.

## Quick Start

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and grab your token.

2. **(Recommended)** Enable authentication in LubeLogger ([guide](https://docs.lubelogger.com/Installation/Authentication/)) and create an API key with Editor scope ([API docs](https://docs.lubelogger.com/Advanced/API/)). If auth is disabled, skip this step.

3. **Get your Telegram user ID** — send `/start` to [@userinfobot](https://t.me/userinfobot).

4. **Create a `.env` file** (see `.env.example`):
   ```env
   TELEGRAM_BOT_TOKEN=your-token
   LUBELOGGER_URL=http://lubelogger:8080
   LUBELOGGER_API_KEY=your-api-key  # omit if auth is disabled
   ALLOWED_USER_IDS=123456789
   ```

5. **Start everything:**
   ```bash
   docker compose up -d
   ```

The bot connects to LubeLogger on the internal Docker network — no extra ports exposed.

## Commands Reference

| Command | Description |
|---------|-------------|
| `/start` | Welcome message, prompts vehicle selection |
| `/vehicle` | Select active vehicle via inline keyboard |
| `/fuel <odo> <liters> <cost>` | Log a fuel fill-up |
| `/service <odo> "<desc>" <cost>` | Log a maintenance record |
| `/km <odo>` | Log an odometer reading |
| `/last fuel` | Show latest fuel record |
| `/last km` | Show latest odometer record |
| `/status` | Check LubeLogger connectivity and queue status |
| `/queue` | Show pending queued records |
| `/lang` | Change bot language (English / Italian) |
| `/cancel` | Cancel active conversation |

### Usage examples

```
/fuel 45000 42.5 78.90       # Log 42.5L at €78.90, odometer 45000
/fuel 45000 42,5 78,90       # Comma decimals work too
/service 45100 "Oil change" 89.00
/km 45200
/last fuel
/status
```

All data-entry commands also work without arguments — the bot will guide you through a step-by-step conversation.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `LUBELOGGER_URL` | Yes | — | LubeLogger base URL (e.g. `http://lubelogger:8080`) |
| `LUBELOGGER_API_KEY` | No | — | API key from LubeLogger settings. Required only if authentication is enabled ([docs](https://docs.lubelogger.com/Advanced/API/)) |
| `ALLOWED_USER_IDS` | Yes | — | Comma-separated Telegram user IDs |
| `DB_PATH` | No | `/data/bot.db` | SQLite database file path |
| `QUEUE_RETRY_INTERVAL` | No | `300` | Seconds between queue retry attempts |
| `HTTP_TIMEOUT` | No | `10` | HTTP request timeout in seconds |
| `MAX_RETRY_ATTEMPTS` | No | `3` | Max retries before marking a record as failed |

## Docker Compose

The provided `docker-compose.yml` runs the bot alongside LubeLogger:

```yaml
services:
  lubelogger:
    image: ghcr.io/hargata/lubelogger:latest
    ports:
      - "8080:8080"
    volumes:
      - lubelogger_config:/App/config
      - lubelogger_data:/App/data
      - lubelogger_documents:/App/wwwroot/documents
      - lubelogger_images:/App/wwwroot/images
      - lubelogger_temp:/App/wwwroot/temp

  telegram-bot:
    build: .
    restart: unless-stopped
    depends_on:
      - lubelogger
    volumes:
      - bot_data:/data
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - LUBELOGGER_URL=http://lubelogger:8080
      - LUBELOGGER_API_KEY=${LUBELOGGER_API_KEY}
      - ALLOWED_USER_IDS=${ALLOWED_USER_IDS}

volumes:
  lubelogger_config:
  lubelogger_data:
  lubelogger_documents:
  lubelogger_images:
  lubelogger_temp:
  bot_data:
```

The bot uses Telegram polling mode — no inbound ports required.

## Architecture

```
bot/
├── main.py              # Entry point: config → DB init → handlers → polling
├── config.py            # pydantic-settings config from env vars
├── exceptions.py        # Custom exception hierarchy
├── i18n.py              # Locale loader (JSON files, English fallback)
├── handlers/            # Telegram command & conversation handlers
│   ├── fuel.py
│   ├── service.py
│   ├── odometer.py
│   ├── vehicle.py
│   ├── query.py
│   └── settings.py
├── services/            # Business logic
│   ├── lubelogger_client.py   # httpx async client (x-api-key auth)
│   ├── queue_service.py       # Offline queue with SQLite persistence
│   ├── config_store.py        # Per-user preferences (vehicle, language)
│   └── command_parser.py      # Argument parsing & decimal normalization
├── models/              # Pydantic models for validation & serialization
│   ├── inputs.py
│   ├── validators.py
│   ├── payloads.py
│   └── responses.py
├── middleware/          # Auth filter (whitelist enforcement)
└── locales/             # Translation JSON files (en.json, it.json)
```

**Data flow:** Command → Parser → Pydantic Validator → LubeLogger Client → API  
**On failure:** Record queues to SQLite → Job retries every 5 min → Syncs when back online

## Contributing

```bash
# Clone and install
git clone https://github.com/19eddie/lubelogger-telegram-bot.git
cd lubelogger-telegram-bot
uv sync

# Run tests
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format .
```

### Adding a language

Create a new JSON file in `bot/locales/` (e.g. `de.json`) with the same keys as `en.json`. No code changes needed.

### Tech stack

- Python 3.11+ with async/await
- `python-telegram-bot` v20+ (polling mode)
- `httpx` for async HTTP
- `pydantic` v2 for validation
- `aiosqlite` for persistence
- `hypothesis` for property-based testing

## License

MIT
