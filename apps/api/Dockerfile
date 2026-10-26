# syntax=docker/dockerfile:1
# FastAPI service image (also runs migrations and maintenance jobs).
# Build from the repo root:  docker build -f apps/api/Dockerfile -t moneymoney-api .
#
#   default command                         -> HTTP server on $PORT (Cloud Run sets it)
#   python -m finance_core.manage migrate   -> deploy-time migration (Cloud Run Job)
#   python -m finance_core.manage prune-checkpoints -> daily retention job

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.22

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- build: resolve the locked environment into /app/.venv ---------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Third-party dependencies first: this layer only rebuilds when the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package finance-api --no-install-workspace

# Then the workspace packages themselves (installed from /app, so alembic.ini and the
# migrations directory resolve from finance_core's location).
COPY backend backend
COPY apps/api apps/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package finance-api

# --- runtime: no uv, no build tooling, non-root ---------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home app
WORKDIR /app
# Root-owned code: the service user can run it but not modify it.
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    HOST=0.0.0.0 \
    PORT=8000
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\", timeout=2)"]
CMD ["python", "-m", "finance_api.serve"]
