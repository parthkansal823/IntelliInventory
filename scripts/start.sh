#!/usr/bin/env bash
# IntelliInventory - one-command start for macOS / Linux:  ./scripts/start.sh
# First run installs everything (a few minutes). Then open http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv > /dev/null || { echo "Install uv first:  curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
command -v npm > /dev/null || { echo "Install Node.js (LTS) first: https://nodejs.org"; exit 1; }
if [ ! -f frontend/dist/index.html ]; then
  echo "Building the web app (first run only)..."
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi
( sleep 6; (command -v open > /dev/null && open http://localhost:8000) || (command -v xdg-open > /dev/null && xdg-open http://localhost:8000) || true ) &
echo "Starting IntelliInventory on http://localhost:8000  (Ctrl+C to stop)"
cd backend && exec uv run uvicorn app.main:app --port 8000
