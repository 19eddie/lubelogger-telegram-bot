# LubeLogger Telegram Bot

A Telegram bot that lets you log fuel fill-ups, service records, and odometer readings to [LubeLogger](https://github.com/hargata/lubelog) — right from your phone. No web UI needed.

**Why this exists:** Logging a refuel shouldn't mean opening a browser, navigating to your LubeLogger instance, and filling out a form. With this bot, you send a Telegram message and you're done. It also works great when your LubeLogger runs on a home server with no public access — the bot sits next to it on the same network, and Telegram bridges the gap from anywhere. If LubeLogger is temporarily down, records queue locally and sync later.

## Quick Start

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and grab your token.

2. **(Recommended)** Enable authentication in LubeLogger ([guide](https://docs.lubelogger.com/Installation/Authentication/)) and create an API key with Editor scope ([API docs](https://docs.lubelogger.com/Advanced/API/)). If auth is disabled, skip this step.

3. **Get your Telegram user ID** — send `/start` to [@userinfobot](https://t.me/userinfobot).

4. **Create a `.env` file** (see `.env.example`):
   ```env
   TELEGRAM_BOT_TOKEN=your-token
   LUBELOGGER_URL=http://192.168.1.100:8080  # your LubeLogger address
   LUBELOGGER_API_KEY=your-api-key  # omit if auth is disabled
   ALLOWED_USER_IDS=123456789
   ```

5. **Start the bot:**
   ```bash
   docker compose up -d
   ```

If LubeLogger runs in the same Docker Compose stack, use the service name as URL (e.g., `http://app:8080`). See [Docker Compose](#docker-compose) for details.

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

### Bot only (recommended)

If you already have LubeLogger running, use the main `docker-compose.yml`:

```bash
docker compose up -d
```

Set `LUBELOGGER_URL` in your `.env` to point to your LubeLogger instance (e.g., `http://192.168.1.100:8080` or `http://lubelogger:8080` if on the same Docker network).

### Full stack (bot + LubeLogger)

To spin up both LubeLogger and the bot together:

```bash
docker compose -f docker-compose.full.yml up -d
```

The bot connects to LubeLogger via Docker internal DNS (`http://app:8080`) — no extra ports exposed for the bot.

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

### Commit & merge policy

- Use **Conventional Commits** (`feat:`, `fix:`, `chore:`, etc.) for all commits merged in `main`.
- Pull requests are expected to pass these required checks:
  - `CI / Lint (Python 3.12)`
  - `CI / Tests (Python 3.11)`
  - `CI / Tests (Python 3.12)`
  - `Conventional Commits / Validate commit messages`
- Configure branch protection on `main` to require all checks above before merge.

### CI/CD and releases

- `CI` workflow runs on pull requests and pushes to `main`:
  - Ruff lint checks
  - Test suite on Python 3.11 and 3.12
- `Release` workflow runs on pushes to `main`:
  - Re-runs lint and tests
  - Executes **semantic-release** (Node) to:
    - compute semantic version from commit history
    - create/update `CHANGELOG.md`
    - update `pyproject.toml` version
    - create Git tag and GitHub Release
- `Publish Docker image` workflow runs when a release tag (`v*`) is pushed:
  - Builds and publishes multi-arch image (`linux/amd64`, `linux/arm64`) to GHCR
  - Produces SBOM and provenance attestations

### Manual repository configuration required

Before relying on the release automation, configure the repository explicitly:

1. **Branch protection for `main`**
   - Require status checks:
     - `CI / Lint (Python 3.12)`
     - `CI / Tests (Python 3.11)`
     - `CI / Tests (Python 3.12)`
     - `Conventional Commits / Validate commit messages`
2. **Allow release pushes to `main`**
   - The release workflow uses `@semantic-release/git` to commit `CHANGELOG.md` and `pyproject.toml` back to `main`.
   - If branch protection blocks direct pushes from GitHub Actions, grant bypass permission to Actions (or disable the git commit plugin).
3. **Workflow permissions**
   - Keep workflow permissions enabled for `GITHUB_TOKEN`.
   - `release.yml` needs `contents: write`.
   - `publish-image.yml` needs `packages: write` to publish to GHCR.
4. **Secrets and environment variables**
   - No extra custom repository secrets are required for release/publish.
   - Workflows use the default `secrets.GITHUB_TOKEN`.

### GHCR image tags

Images are published to:

`ghcr.io/19eddie/lubelogger-telegram-bot`

With these tags:

- `latest`
- `vX.Y.Z` (full release tag)
- `X.Y.Z`
- `X.Y`
- `X`
- `sha-<commit>`

### First rollout checklist

1. Enable branch protection for `main` and mark required checks.
2. Merge one PR with valid Conventional Commits.
3. Verify semantic-release generates the first tag and GitHub release.
4. Verify GHCR image availability and expected tags.
5. Pull and run the released image as smoke test.

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
