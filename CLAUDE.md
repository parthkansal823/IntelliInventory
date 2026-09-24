# IntelliInventory — guide for AI coding agents

## Layout
- `backend/` — FastAPI + SQLModel (Python 3.11, **uv**). Entry: `app/main.py` (`create_app`).
- `frontend/` — React 19 + Vite 8 + TypeScript 6 + Tailwind v4. Entry: `src/main.tsx`, routes in `src/App.tsx`.
- `integrations/hermes/` — Hermes Agent pack (plugin, gateway hook, skill, installer).

## Commands
- Backend: `cd backend && uv run pytest -q` · `uv run ruff check . && uv run ruff format --check .` · run: `uv run uvicorn app.main:app --reload`
- Frontend: `cd frontend && npm test` · `npm run lint` · `npm run typecheck` · dev: `npm run dev` (proxies `/api` → :8000)
- `make test`, `make lint`, `make dev` wrap all of the above.

## Conventions
- **One tool registry** (`app/agents/toolkit.py` + `app/agents/tools.py`): add agent/MCP tools as typed functions with
  `Annotated[..., Field(description=...)]` params and a docstring. Mark write tools `mutates=True`; anything that changes stock or
  order status must be `requires_approval=True`. Then add the tool name to an agent in `app/agents/registry.py`.
- Services commit first, **then** emit domain events via `app.hooks.bus.bus.emit(...)` (SQLite: never emit inside an open write transaction).
- Datetimes are timezone-aware UTC (`app.models.utcnow`, `day_start`) — SQLModel rejects naive datetimes.
- Agent lifecycle hooks (`app/agents/hooks.py`) follow the Hermes Agent contract: `pre_tool_call` returns
  `{"action": "block" | "modify" | "require_approval", ...}`. Hooks must never raise into the caller.
- The offline provider (`app/agents/providers/offline.py`) must keep working with no network: tests run with `AI_PROVIDER=offline`.
- Frontend data access goes through hooks in `src/hooks/queries.ts`; mutations use `useAction` (toast + invalidate).
- Charts: use the validated palette roles `--chart-1..3`, status colours only with icon + label, one y-axis.
- Keep the app free to run: no paid service may be required for any default code path.
