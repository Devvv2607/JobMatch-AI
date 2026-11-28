# syntax=docker/dockerfile:1

# --- model: export + quantise the embedding and reranking models (build time only) --
# Sentence Transformers and PyTorch live only in this stage. The runtime images copy
# the int8 ONNX files and tokenizers, nothing else. Each export ends with a parity check
# against the fp32 model and fails the build if the int8 runtime diverges.
FROM python:3.12-slim AS model

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/hf

WORKDIR /build
COPY model/requirements.txt ./model/requirements.txt
# No pip cache mount: this stage rebuilds rarely, and the cache costs ~1 GB of disk.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple -r model/requirements.txt
COPY model/export_embedding_model.py model/export_reranker_model.py ./model/
COPY app/ml ./app/ml
RUN python model/export_embedding_model.py /opt/models/bge-small-en-v1.5
RUN python model/export_reranker_model.py /opt/models/ms-marco-MiniLM-L6-v2

# --- prod: runtime dependencies, application code and the model --------------------
FROM python:3.12-slim AS prod

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/bm25 /tmp/prometheus && chown app:app /data/bm25 /tmp/prometheus
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=jobmatch-uv,target=/root/.cache/uv uv sync --frozen --no-dev

COPY --from=model /opt/models /opt/models

# pg_dump for the worker's daily backup, at the server's major version (16): pg_restore
# 16 in the db container must be able to read the archives. From the PostgreSQL
# project's apt repository (Debian's own client is a newer major version).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump \
    && ln -s /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
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
RUN --mount=type=cache,id=jobmatch-uv,target=/root/.cache/uv uv sync --frozen
COPY tests ./tests
COPY scripts ./scripts
# /app is read-only for the app user; test and lint tooling write their state to /tmp.
ENV COVERAGE_FILE=/tmp/.coverage \
    RUFF_CACHE_DIR=/tmp/.ruff_cache \
    MYPY_CACHE_DIR=/tmp/.mypy_cache
USER app
