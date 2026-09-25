"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import func, select
from starlette.background import BackgroundTask

from app.agents.providers import describe_providers, resolve_provider_name
from app.api import agents, auth, automation, billing, catalog, india, insights, operations, payables
from app.config import get_settings
from app.db import get_engine, init_db, session_scope
from app.hooks import builtin as builtin_hooks
from app.hooks.bus import bus, toggles
from app.mcp_server import mcp
from app.models import Alert, ist_today
from app.plugins import load_plugins
from app.security import AdminUser
from app.seed import DEMO_ACCOUNTS, ensure_production_setup, seed_demo
from app.services.billing import BillingError, business_profile
from app.services.inventory import InventoryError
from app.services.scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("intelliinventory")
VERSION = "1.0.0"


def _bootstrap() -> None:
    settings = get_settings()
    init_db()
    with session_scope() as s:
        if settings.should_seed_demo:
            seeded = seed_demo(s)
        else:
            ensure_production_setup(s)
            seeded = False
        if seeded or not s.exec(select(func.count()).select_from(Alert)).one():
            builtin_hooks.evaluate_alerts(s, emit=False)  # initial alerts without waking the autopilot
    toggles.load()
    load_plugins(settings.plugins_dir)


def create_app(*, start_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    # Behind a public URL the Host header is not localhost, so skip DNS-rebinding host pinning
    # (the endpoint is still protected by the integration bearer token).
    mcp_app = mcp.streamable_http_app(streamable_http_path="/", host="0.0.0.0" if settings.public_url else "127.0.0.1")

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
        description="AI-native inventory management: forecasting, free multi-agent copilot (Hermes / offline), hooks, MCP.",
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(InventoryError)
    async def inventory_error(_: Request, exc: InventoryError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(BillingError)
    async def billing_error(_: Request, exc: BillingError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404 if "not found" in str(exc) else 400)

    for module in (auth, catalog, operations, insights, india, billing, payables, agents, automation):
        app.include_router(module.router)
    app.include_router(auth.users_router)

    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "version": VERSION}

    @app.get("/api/system/public", tags=["system"])
    def public_config() -> dict:
        """Unauthenticated: what the login page needs to know."""
        return {
            "app_name": settings.app_name,
            "version": VERSION,
            "demo_mode": settings.demo_mode,
            "demo_accounts": DEMO_ACCOUNTS if settings.demo_mode and settings.should_seed_demo else [],
            "currency": "INR",
            "shop_name": business_profile()["name"],
        }

    @app.get("/api/system/info", tags=["system"])
    def info() -> dict:
        return {
            "version": VERSION,
            "active_provider": resolve_provider_name(),
            "providers": describe_providers(),
            "mcp": {
                "http_url": f"{(settings.public_url or 'http://localhost:8000').rstrip('/')}/mcp/",
                "stdio_command": "uv run --directory backend python -m app.mcp_server",
                "auth_header": "Authorization: Bearer <INTEGRATION_TOKEN>",
            },
            "database": settings.database_url.split(":")[0],
            "demo_mode": settings.demo_mode,
            "public_url": settings.public_url,
        }

    @app.get("/api/system/backup", tags=["system"])
    def backup(_: AdminUser) -> FileResponse:
        """Download a full copy of the database (SQLite). Keep it safe - it has all bills and customers."""
        if not settings.database_url.startswith("sqlite"):
            raise HTTPException(400, "Backups from the app work with SQLite. For PostgreSQL use pg_dump.")
        folder = Path(tempfile.mkdtemp(prefix="ii-backup-"))
        target = folder / f"intelliinventory-{ist_today().isoformat()}.db"
        with get_engine().connect() as conn:
            conn.exec_driver_sql("VACUUM INTO ?", (str(target),))
        return FileResponse(
            target,
            media_type="application/vnd.sqlite3",
            filename=target.name,
            background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True),
        )

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
