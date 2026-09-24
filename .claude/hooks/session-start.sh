#!/bin/bash
# SessionStart hook: install backend + frontend dependencies so tests and linters
# work immediately in Claude Code on the web. Idempotent; web-only.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# Backend: Python deps (FastAPI, SQLModel, anthropic, openai, mcp, pytest, ruff) into backend/.venv
if command -v uv >/dev/null 2>&1; then
  (cd "$ROOT/backend" && uv sync --quiet)
else
  python3 -m pip install --quiet uv
  (cd "$ROOT/backend" && python3 -m uv sync --quiet)
fi

# Frontend: npm install (not ci) so the cached container state is reused between sessions
(cd "$ROOT/frontend" && npm install --no-audit --no-fund --loglevel=error)

# Tests must never reach for a local LLM or paid API.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export OLLAMA_AUTODETECT=false' >> "$CLAUDE_ENV_FILE"
fi
