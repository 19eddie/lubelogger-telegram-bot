# ==========================================
# Stage 1: Build Python application
# ==========================================
FROM python:3.15-slim-trixie AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY bot/ ./bot/

RUN uv sync --frozen --no-dev


# ==========================================
# Stage 2: Production runtime
# ==========================================
FROM python:3.15-slim-trixie AS runtime

# Update Debian packages
RUN rm -rf /usr/local/lib/python3.15/site-packages/pip \
    /usr/local/lib/python3.15/site-packages/pip-*.dist-info \
    /usr/local/bin/pip*
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and data directory
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 \
       --gid 10001 \
       --no-create-home \
       --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown 10001:10001 /data

WORKDIR /app

# Copy only application and virtual environment
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 bot/ ./bot/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/custom"

USER 10001:10001

CMD ["python", "-m", "bot.main"]
