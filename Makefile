.PHONY: install dev api web test lint format build docker mcp migrate reset-db

install:            ## install backend + frontend dependencies
	cd backend && uv sync
	cd frontend && npm install

api:                ## run the API with auto-reload on :8000
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:                ## run the Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

dev:                ## run API + web together
	$(MAKE) -j2 api web

test:               ## run all tests
	cd backend && uv run pytest -q
	cd frontend && npm test

lint:               ## lint + typecheck everything
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint && npm run typecheck

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .

build:              ## production build of the SPA (served by FastAPI from frontend/dist)
	cd frontend && npm run build

docker:             ## build and run the single-container app on :8000
	docker compose up --build

mcp:                ## run the MCP server over stdio (for Hermes Agent / Claude Code)
	cd backend && uv run python -m app.mcp_server

migrate:            ## apply Alembic migrations (Postgres / production)
	cd backend && uv run alembic upgrade head

reset-db:           ## delete the local SQLite DB (re-seeded on next start)
	rm -f backend/data/intelliinventory.db*
