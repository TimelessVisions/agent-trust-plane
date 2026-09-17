#!/usr/bin/env bash
# Run every check CI runs, locally.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -p no:warnings
uv run python -m atp_evals
uv run atp doctor --port 1
uv run atp demo injection >/dev/null
uv run atp demo regression >/dev/null
uv run atp demo mcp >/dev/null
uv run atp test examples/regression-suite/accounts-payable.yaml --quiet
(cd apps/dashboard && npm run typecheck && npm run build)
