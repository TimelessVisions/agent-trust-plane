# Run every check CI runs, locally (PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -p no:warnings
uv run python -m atp_evals
uv run atp doctor --port 1
uv run atp demo injection | Out-Null
uv run atp demo regression | Out-Null
uv run atp demo mcp | Out-Null
uv run atp test examples/regression-suite/accounts-payable.yaml --quiet
Push-Location apps/dashboard
npm run typecheck
npm run build
Pop-Location
