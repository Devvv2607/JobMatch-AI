# syntax=docker/dockerfile:1

# --- prod: runtime dependencies and application code only -------------------------
FROM python:3.12-slim AS prod

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

USER app
EXPOSE 8000
# --no-proxy-headers: client IP is decided only by TRUSTED_PROXY_COUNT in app code.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--timeout-graceful-shutdown", "20"]

# --- dev: adds test and lint tooling; what `docker compose up` builds --------------
FROM prod AS dev

USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY tests ./tests
COPY scripts ./scripts
# /app is read-only for the app user; test and lint tooling write their state to /tmp.
ENV COVERAGE_FILE=/tmp/.coverage \
    RUFF_CACHE_DIR=/tmp/.ruff_cache \
    MYPY_CACHE_DIR=/tmp/.mypy_cache
USER app
