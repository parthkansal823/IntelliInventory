"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import func, select

from app.agents.providers import describe_providers, resolve_provider_name
from app.api import agents, auth, automation, catalog, insights, operations
from app.config import get_settings
from app.db import init_db, session_scope
from app.hooks import builtin as builtin_hooks
from app.hooks.bus import bus, toggles
from app.mcp_server import mcp
from app.models import Alert
from app.plugins import load_plugins
from app.seed import seed_demo, seed_users
from app.services.inventory import InventoryError
from app.services.scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("intelliinventory")
VERSION = "1.0.0"


def _bootstrap() -> None:
    settings = get_settings()
    init_db()
    with session_scope() as s:
        seeded = seed_demo(s) if settings.seed_demo_data else (seed_users(s) or False)
        if seeded or not s.exec(select(func.count()).select_from(Alert)).one():
            builtin_hooks.evaluate_alerts(s, emit=False)  # initial alerts without waking the autopilot
    toggles.load()
    load_plugins(settings.plugins_dir)


def create_app(*, start_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    mcp_app = mcp.streamable_http_app(streamable_http_path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(_bootstrap)
        bus.bind_loop(asyncio.get_running_loop())
        scheduler = asyncio.create_task(scheduler_loop()) if start_scheduler else None
        log.info("IntelliInventory ready — AI provider: %s", resolve_provider_name())
        async with mcp.session_manager.run():
            yield
        if scheduler:
            scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler
        await bus.drain()
        bus.bind_loop(None)

    app = FastAPI(
        title="IntelliInventory API",
        version=VERSION,
        description="AI-native inventory management: forecasting, multi-agent copilot (Hermes / Claude / offline), hooks, MCP.",
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(InventoryError)
    async def inventory_error(_: Request, exc: InventoryError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    for module in (auth, catalog, operations, insights, agents, automation):
        app.include_router(module.router)
    app.include_router(auth.users_router)

    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "version": VERSION}

    @app.get("/api/system/info", tags=["system"])
    def info() -> dict:
        return {
            "version": VERSION,
            "active_provider": resolve_provider_name(),
            "providers": describe_providers(),
            "mcp": {
                "http_url": "http://localhost:8000/mcp/",
                "stdio_command": "uv run --directory backend python -m app.mcp_server",
                "auth_header": "Authorization: Bearer <INTEGRATION_TOKEN>",
            },
            "database": settings.database_url.split(":")[0],
        }

    # MCP over streamable HTTP, protected by the integration token.
    async def mcp_guard(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            token = headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(token, settings.integration_token):
                response = JSONResponse({"detail": "Missing or invalid integration token"}, status_code=401)
                await response(scope, receive, send)
                return
        await mcp_app(scope, receive, send)

    app.mount("/mcp", mcp_guard)
    _mount_spa(app, settings.frontend_dist)
    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the built React app (single-container deployment)."""
    if not (dist / "index.html").exists():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "mcp")):
            raise HTTPException(404, "Not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
