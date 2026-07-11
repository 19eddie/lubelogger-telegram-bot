FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

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

# Activate venv via PATH — no uv needed at runtime
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "bot.main"]
