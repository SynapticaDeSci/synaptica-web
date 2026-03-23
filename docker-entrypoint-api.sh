#!/bin/bash
set -euo pipefail

# Run DB migrations
uv run alembic upgrade head || echo "DB migration skipped (may already be up to date)"

# Start HOL sidecar in background
echo "Starting HOL sidecar..."
node frontend/scripts/hol-sidecar.mjs &
HOL_PID=$!

# Give sidecar a moment to start
sleep 2

echo "Starting API server..."
exec uv run python -m uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8080}"
