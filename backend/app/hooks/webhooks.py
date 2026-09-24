"""Outbound webhooks: HMAC-SHA256 signed, retried with backoff, every delivery logged."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import time

import httpx
from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.hooks.bus import Event
from app.models import Webhook, WebhookDelivery, utcnow
from app.money import inr

SIGNATURE_HEADER = "X-IntelliInventory-Signature"
RETRY_DELAYS = (0.5, 1.5, 4.0)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, body), signature)


def _matches(webhook: Webhook, event_type: str) -> bool:
    return any(fnmatch.fnmatchcase(event_type, pattern) for pattern in (webhook.events or ["*"]))


def _text_summary(event: Event) -> str:
    p = event.payload
    if event.type.startswith("stock.") and "sku" in p:
        return f"[{event.type}] {p.get('name')} ({p.get('sku')}): on hand {p.get('on_hand')}"
    if event.type.startswith("po.") and "number" in p:
        return (
            f"[{event.type}] {p['number']} ({p.get('status')}) — {p.get('supplier', {}).get('name', '')} {inr(p.get('total', 0))}"
        )
    if event.type == "report.created":
        return f"*{p.get('title')}*\n{p.get('content', '')[:2500]}"
    return f"[{event.type}] {json.dumps(p, default=str)[:300]}"


def build_body(webhook: Webhook, event: Event) -> bytes:
    payload = event.to_dict()
    # Chat-app friendly: Slack and Discord incoming webhooks render `text` / `content`.
    if "hooks.slack.com" in webhook.url:
        payload = {"text": _text_summary(event)}
    elif "discord.com/api/webhooks" in webhook.url:
        payload = {"content": _text_summary(event)[:1900]}
    return json.dumps(payload, default=str).encode()


async def deliver(webhook: Webhook, event: Event, client: httpx.AsyncClient | None = None) -> WebhookDelivery:
    body = build_body(webhook, event)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "IntelliInventory-Webhooks/1.0",
        "X-IntelliInventory-Event": event.type,
        "X-IntelliInventory-Delivery": event.id,
    }
    if webhook.secret:
        headers[SIGNATURE_HEADER] = sign(webhook.secret, body)

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=get_settings().webhook_timeout_seconds)
    started = time.perf_counter()
    status_code, error, attempts = None, None, 0
    try:
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
            attempts = attempt + 1
            try:
                resp = await client.post(webhook.url, content=body, headers=headers)
                status_code, error = resp.status_code, None
                if resp.status_code < 500 and resp.status_code != 429:
                    break
                error = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        if own_client:
            await client.aclose()

    success = status_code is not None and 200 <= status_code < 300
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event_type=event.type,
        status_code=status_code,
        success=success,
        attempts=attempts,
        error=None if success else (error or f"HTTP {status_code}"),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    await asyncio.to_thread(_record, webhook.id, delivery)
    return delivery


def _record(webhook_id: int, delivery: WebhookDelivery) -> None:
    with session_scope() as s:
        s.add(delivery)
        hook = s.get(Webhook, webhook_id)
        if hook:
            hook.last_status = delivery.status_code
            hook.last_error = delivery.error
            hook.last_delivery_at = utcnow()
            s.add(hook)
        s.commit()


def _active_hooks(event_type: str) -> list[Webhook]:
    with session_scope() as s:
        return [w for w in s.exec(select(Webhook).where(Webhook.active)) if _matches(w, event_type)]


async def dispatch(event: Event) -> None:
    if event.type.startswith("webhook."):
        return  # never fan out our own delivery notifications
    hooks = await asyncio.to_thread(_active_hooks, event.type)
    if hooks:
        await asyncio.gather(*(deliver(h, event) for h in hooks), return_exceptions=True)
