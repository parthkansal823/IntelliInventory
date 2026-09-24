#!/bin/bash
# PostToolUse hook: format/fix the file Claude just edited. Never blocks the edit.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
FILE=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("file_path",""))' 2>/dev/null || true)
[ -z "$FILE" ] || [ ! -f "$FILE" ] && exit 0

case "$FILE" in
  "$ROOT"/backend/*.py)
    (cd "$ROOT/backend" && uv run --quiet ruff format "$FILE" >/dev/null 2>&1 && uv run --quiet ruff check --fix --quiet "$FILE" >/dev/null 2>&1) || true
    ;;
  "$ROOT"/frontend/src/*.ts|"$ROOT"/frontend/src/*.tsx)
    (cd "$ROOT/frontend" && npx --no-install oxlint --fix "$FILE" >/dev/null 2>&1) || true
    ;;
esac
exit 0
