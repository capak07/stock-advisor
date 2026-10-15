#!/usr/bin/env bash
# Runs a pipeline command inside a Linux container.
# Why: Windows Application Control blocks psycopg's bundled libpq DLLs on the dev machine.
# Usage (from anywhere): pipeline/scripts/in-docker.sh uv run pytest -q
# Needs the advisor-pg Postgres container (see README) for integration tests.
set -euo pipefail
cd "$(dirname "$0")/.."
repo="$(cd .. && (pwd -W 2>/dev/null || pwd))"
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$repo:/repo" -w /repo/pipeline \
  -v advisor-venv:/opt/venv -v advisor-uv-cache:/root/.cache/uv \
  -e UV_PROJECT_ENVIRONMENT=/opt/venv -e UV_LINK_MODE=copy \
  -e TEST_DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:54329/advisor_test \
  -e DATABASE_URL -e ADMIN_DATABASE_URL -e ADVISOR_CACHE_DIR -e SEC_USER_AGENT \
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  sh -c 'uv sync --locked -q && exec "$@"' sh "$@"
