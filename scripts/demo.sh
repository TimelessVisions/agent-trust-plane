#!/usr/bin/env bash
# Start the gateway, run the evals against it, and start the dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m atp_gateway --port 8000 &
GW=$!
trap 'kill $GW' EXIT
sleep 3
uv run python -m atp_evals --gateway http://127.0.0.1:8000 || true
curl -s -X POST http://127.0.0.1:8000/evals/run > /dev/null
echo "gateway: http://127.0.0.1:8000/docs   dashboard: http://localhost:3000"
(cd apps/dashboard && npm run dev)
