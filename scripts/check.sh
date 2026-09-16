#!/usr/bin/env bash
# Run every check CI runs, locally.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -p no:warnings
uv run python -m atp_evals
(cd apps/dashboard && npm run typecheck && npm run build)
