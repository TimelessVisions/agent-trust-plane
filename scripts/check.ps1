# Run every check CI runs, locally (PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -p no:warnings
uv run python -m atp_evals
Push-Location apps/dashboard
npm run typecheck
npm run build
Pop-Location
