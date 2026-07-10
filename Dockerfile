FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files for dependency resolution
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY bot/ ./bot/

# Install the project itself
RUN uv sync --frozen --no-dev

# Create data directory for SQLite
RUN mkdir -p /data

# Run as non-root user for security
RUN useradd --no-create-home --shell /bin/false botuser && chown -R botuser:botuser /data
USER botuser

CMD ["uv", "run", "python", "-m", "bot.main"]
