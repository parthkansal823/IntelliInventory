#!/usr/bin/env bash
# Container entrypoint for Hugging Face Spaces (also works in any Docker host that sets $PORT).
set -uo pipefail

# 1. Hermes AI via Ollama, inside this container: free and private. The app falls back to the
#    built-in offline planner automatically if the model is not available.
if [ "${AI_PROVIDER:-auto}" != "offline" ] && command -v ollama > /dev/null; then
  ollama serve > /tmp/ollama.log 2>&1 &
  for _ in $(seq 1 60); do curl -sf "${OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" > /dev/null && break; sleep 1; done
  ollama list | grep -q "${HERMES_MODEL%%:*}" || ollama pull "${HERMES_MODEL}" || echo "Hermes model unavailable - using the offline planner"
  # Load the model into memory now so the first chat is quick.
  curl -s "${OLLAMA_URL:-http://127.0.0.1:11434}/api/generate" \
    -d "{\"model\": \"${HERMES_MODEL}\", \"prompt\": \"namaste\", \"stream\": false, \"options\": {\"num_predict\": 1}}" > /dev/null 2>&1 &
fi

# 2. Database schema (fresh SQLite for the demo, or your Neon Postgres for the real shop).
cd /app/backend
alembic upgrade head || echo "alembic: schema already present - continuing"

# 3. The app (API + web UI) on the port the platform gives us.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers --forwarded-allow-ips='*'
