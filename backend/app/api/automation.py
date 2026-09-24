"""Hooks, webhooks, scheduled jobs, plugins, live events and integrations."""

import asyncio
import hmac
import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlmodel import select
from sse_starlette.sse import EventSourceResponse

from app.agents.hooks import agent_hooks
from app.config import get_settings
from app.hooks import webhooks
from app.hooks.builtin import autopilot_enabled
from app.hooks.bus import Event, bus, toggles
from app.models import EventLog, Webhook, WebhookDelivery
from app.plugins import LOADED as LOADED_PLUGINS
from app.security import AdminUser, CurrentUser, DbSession, ManagerUser
from app.services.scheduler import JOBS, run_job
from app.services.settings import set_setting

router = APIRouter(prefix="/api", tags=["automation"])


# --- hooks ------------------------------------------------------------------------------


@router.get("/hooks")
def list_hooks(_: CurrentUser) -> dict:
    return {
        "agent": [h.to_dict() for h in agent_hooks.hooks],
        "event": [
            {
                "name": h.name,
                "pattern": h.pattern,
                "description": h.description,
                "priority": h.priority,
                "builtin": h.builtin,
                "async": h.is_async,
                "enabled": toggles.is_enabled(h.name),
                "kind": "event",
            }
            for h in bus.hooks
        ],
        "plugins": LOADED_PLUGINS,
    }


class ToggleIn(BaseModel):
    enabled: bool


@router.patch("/hooks/{name}")
def toggle_hook(name: str, body: ToggleIn, user: ManagerUser) -> dict:
    known = {h.name for h in agent_hooks.hooks} | {h.name for h in bus.hooks}
    if name not in known:
        raise HTTPException(404, f"Unknown hook {name}")
    toggles.set_enabled(name, body.enabled)
    bus.emit("hook.toggled", {"hook": name, "enabled": body.enabled}, source=f"user:{user.email}")
    return {"name": name, "enabled": body.enabled}


# --- settings -----------------------------------------------------------------------------


class AutomationSettingsIn(BaseModel):
    autopilot_enabled: bool | None = None


@router.get("/automation/settings")
def automation_settings(_: CurrentUser) -> dict:
    return {"autopilot_enabled": autopilot_enabled(), "autopilot_cooldown_hours": get_settings().autopilot_cooldown_hours}


@router.patch("/automation/settings")
def update_automation_settings(body: AutomationSettingsIn, user: ManagerUser) -> dict:
    if body.autopilot_enabled is not None:
        set_setting("autopilot.enabled", body.autopilot_enabled)
        bus.emit("autopilot.toggled", {"enabled": body.autopilot_enabled}, source=f"user:{user.email}")
    return automation_settings(user)


# --- scheduled jobs --------------------------------------------------------------------------


@router.get("/jobs")
def list_jobs(_: CurrentUser) -> list[dict]:
    return [job.to_dict() for job in JOBS.values()]


@router.post("/jobs/{name}/run")
async def trigger_job(name: str, _: ManagerUser) -> dict:
    if name not in JOBS:
        raise HTTPException(404, "Unknown job")
    return {"job": name, "result": await run_job(name)}


# --- webhooks -----------------------------------------------------------------------------------


class WebhookIn(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default_factory=lambda: ["*"])
    secret: str | None = None
    active: bool = True


def webhook_out(w: Webhook) -> dict:
    return {
        "id": w.id,
        "url": w.url,
        "events": w.events,
        "active": w.active,
        "has_secret": bool(w.secret),
        "last_status": w.last_status,
        "last_error": w.last_error,
        "last_delivery_at": w.last_delivery_at.isoformat() if w.last_delivery_at else None,
        "created_at": w.created_at.isoformat(),
    }


@router.get("/webhooks")
def list_webhooks(session: DbSession, _: CurrentUser) -> list[dict]:
    return [webhook_out(w) for w in session.exec(select(Webhook).order_by(Webhook.id))]


@router.post("/webhooks", status_code=201)
def create_webhook(session: DbSession, body: WebhookIn, _: AdminUser) -> dict:
    hook = Webhook(
        url=str(body.url), events=body.events or ["*"], secret=body.secret or secrets.token_hex(16), active=body.active
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)
    return {**webhook_out(hook), "secret": hook.secret}  # secret shown once


@router.patch("/webhooks/{webhook_id}")
def update_webhook(session: DbSession, webhook_id: int, body: WebhookIn, _: AdminUser) -> dict:
    hook = session.get(Webhook, webhook_id)
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    hook.url, hook.events, hook.active = str(body.url), body.events or ["*"], body.active
    if body.secret:
        hook.secret = body.secret
    session.add(hook)
    session.commit()
    return webhook_out(hook)


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(session: DbSession, webhook_id: int, _: AdminUser) -> dict:
    hook = session.get(Webhook, webhook_id)
    if hook:
        for d in session.exec(select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook_id)):
            session.delete(d)
        session.delete(hook)
        session.commit()
    return {"deleted": True}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(session: DbSession, webhook_id: int, _: ManagerUser) -> dict:
    hook = session.get(Webhook, webhook_id)
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    delivery = await webhooks.deliver(
        hook, Event(type="webhook.test", payload={"message": "Hello from IntelliInventory 👋"}, source="test")
    )
    return {
        "success": delivery.success,
        "status_code": delivery.status_code,
        "error": delivery.error,
        "duration_ms": delivery.duration_ms,
    }


@router.get("/webhooks/{webhook_id}/deliveries")
def deliveries(session: DbSession, webhook_id: int, _: CurrentUser, limit: int = 50) -> list[WebhookDelivery]:
    return list(
        session.exec(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
    )


# --- events -------------------------------------------------------------------------------------


@router.get("/events")
def list_events(session: DbSession, _: CurrentUser, type: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(EventLog).order_by(EventLog.id.desc())
    if type:
        stmt = stmt.where(EventLog.type.startswith(type))
    return [
        {"id": e.id, "type": e.type, "source": e.source, "payload": e.payload, "ts": e.created_at.isoformat()}
        for e in session.exec(stmt.limit(min(limit, 500)))
    ]


@router.get("/events/stream")
async def stream_events(_: CurrentUser) -> EventSourceResponse:
    """Live domain events (Server-Sent Events). Browsers pass `?access_token=`."""

    async def gen():
        yield {"event": "ready", "data": json.dumps({"ok": True})}
        async for event in bus.subscribe():
            yield {"data": json.dumps(event.to_dict(), default=str)}

    return EventSourceResponse(gen(), ping=20)


# --- integrations (Hermes Agent plugin & gateway hooks) ----------------------------------------------


class IngestIn(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    source: str = "hermes-agent"


@router.post("/integrations/events", status_code=202)
async def ingest(body: IngestIn, authorization: Annotated[str | None, Header()] = None) -> dict:
    """Accept events from external agents (e.g. the Hermes Agent plugin). Auth: `Bearer INTEGRATION_TOKEN`."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, get_settings().integration_token):
        raise HTTPException(401, "Invalid integration token")
    event_type = body.type if "." in body.type else f"hermes.{body.type}"
    await asyncio.to_thread(bus.emit, f"external.{event_type}", body.payload, body.source[:60])
    return {"accepted": True}
