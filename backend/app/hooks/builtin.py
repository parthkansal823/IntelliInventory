"""Built-in event hooks. Imported once at startup to register them on the bus."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlmodel import Session, select

from app.config import get_settings
from app.db import session_scope
from app.hooks import webhooks
from app.hooks.bus import Event, bus
from app.models import Alert, AlertSeverity, EventLog, POStatus, PurchaseOrder, PurchaseOrderLine, utcnow
from app.services.analytics import compute_metrics
from app.services.settings import get_setting, set_setting

log = logging.getLogger("intelliinventory.hooks")

STOCK_ALERT_KINDS = ("low_stock", "stockout", "overstock")
_STATUS_TO_ALERT = {
    "out": ("stockout", AlertSeverity.CRITICAL, "stock.out"),
    "critical": ("low_stock", AlertSeverity.CRITICAL, "stock.low"),
    "low": ("low_stock", AlertSeverity.WARNING, "stock.low"),
    "overstock": ("overstock", AlertSeverity.INFO, "stock.overstock"),
}


# --- audit trail -----------------------------------------------------------------


@bus.on("*", name="audit_log", description="Persist every domain event to the audit trail", priority=10)
def audit_log(event: Event) -> None:
    with session_scope() as s:
        s.add(EventLog(type=event.type, source=event.source, payload=event.payload))
        s.commit()


# --- alert engine --------------------------------------------------------------------


def evaluate_alerts(session: Session, product_ids: list[int] | None = None, *, emit: bool = True) -> list[tuple[str, dict]]:
    """Open, escalate or resolve stock alerts to match current product status."""
    events: list[tuple[str, dict]] = []
    metrics = compute_metrics(session, product_ids)
    open_alerts: dict[int, list[Alert]] = {}
    stmt = select(Alert).where(Alert.resolved == False, Alert.kind.in_(STOCK_ALERT_KINDS))  # noqa: E712
    if product_ids:
        stmt = stmt.where(Alert.product_id.in_(product_ids))
    for alert in session.exec(stmt):
        open_alerts.setdefault(alert.product_id, []).append(alert)

    for m in metrics:
        existing = open_alerts.get(m.product_id, [])
        target = _STATUS_TO_ALERT.get(m.status)
        payload = {
            "product_id": m.product_id,
            "sku": m.sku,
            "name": m.name,
            "status": m.status,
            "on_hand": m.on_hand,
            "on_order": m.on_order,
            "reorder_point": m.reorder_point,
            "days_of_cover": m.days_of_cover,
            "suggested_order_qty": m.suggested_order_qty,
            "supplier": m.supplier,
        }
        keep = None
        for alert in existing:
            if target and alert.kind == target[0]:
                keep = alert
                if alert.severity != target[1]:
                    alert.severity = target[1]
                    session.add(alert)
            else:
                alert.resolved, alert.resolved_at = True, utcnow()
                session.add(alert)
                if alert.kind in ("low_stock", "stockout") and not target:
                    events.append(("stock.replenished", payload))
        if target and keep is None:
            kind, severity, event_type = target
            session.add(Alert(kind=kind, severity=severity, product_id=m.product_id, message=_alert_message(m)))
            events.append((event_type, payload))
    session.commit()
    if emit:
        for event_type, payload in events:
            bus.emit(event_type, payload, source="alert-engine")
    return events


def _alert_message(m) -> str:
    if m.status == "out":
        return f"{m.name} ({m.sku}) is out of stock"
    if m.status == "overstock":
        return f"{m.name} ({m.sku}) is overstocked: {m.days_of_cover:g} days of cover"
    cover = f", ~{m.days_of_cover:g} days of cover" if m.days_of_cover is not None else ""
    return f"{m.name} ({m.sku}) is below its reorder point: {m.on_hand} on hand vs ROP {m.reorder_point}{cover}"


@bus.on("stock.changed", name="stock_alerts", description="Raise, escalate and resolve stock alerts", priority=20)
def stock_alerts(event: Event) -> None:
    with session_scope() as s:
        evaluate_alerts(s, [event.payload["product_id"]])


# --- webhooks ------------------------------------------------------------------------


@bus.on("*", name="webhook_dispatch", description="Deliver events to webhooks (HMAC-signed, retried)", priority=90)
async def webhook_dispatch(event: Event) -> None:
    await webhooks.dispatch(event)


# --- autopilot -----------------------------------------------------------------------


def autopilot_enabled() -> bool:
    value = get_setting("autopilot.enabled")
    return get_settings().autopilot_enabled if value is None else bool(value)


def _has_open_po(product_id: int) -> bool:
    with session_scope() as s:
        return (
            s.exec(
                select(PurchaseOrderLine.id)
                .join(PurchaseOrder)
                .where(PurchaseOrderLine.product_id == product_id)
                .where(PurchaseOrder.status.in_((POStatus.DRAFT, POStatus.APPROVED, POStatus.ORDERED)))
            ).first()
            is not None
        )


def _claim_cooldown(product_id: int) -> bool:
    key = f"autopilot.last.{product_id}"
    last = get_setting(key)
    now = utcnow()
    if last:
        from datetime import datetime

        if now - datetime.fromisoformat(last) < timedelta(hours=get_settings().autopilot_cooldown_hours):
            return False
    set_setting(key, now.isoformat())
    return True


@bus.on(
    "stock.low|stock.out",
    name="autopilot_replenish",
    description="Procurement agent drafts a purchase order when stock runs low",
    priority=95,
)
async def autopilot_replenish(event: Event) -> None:
    p = event.payload
    if not autopilot_enabled() or not p.get("suggested_order_qty"):
        return
    if await asyncio.to_thread(_has_open_po, p["product_id"]):
        return
    if not await asyncio.to_thread(_claim_cooldown, p["product_id"]):
        return
    from app.agents.runtime import run_autonomous

    task = (
        f"Stock alert: {p['name']} ({p['sku']}) is {p['status']} — {p['on_hand']} on hand, "
        f"{p['on_order']} on order, reorder point {p['reorder_point']}, suggested order {p['suggested_order_qty']}. "
        f"Review reorder recommendations for its supplier ({p.get('supplier')}) and draft ONE purchase order "
        f"covering {p['sku']} plus any other items from the same supplier that need reordering. "
        "Leave it as a draft for a manager to approve, then summarise what you drafted in two sentences."
    )
    bus.emit("autopilot.triggered", {"sku": p["sku"], "name": p["name"], "status": p["status"]}, source="autopilot")
    try:
        await run_autonomous("procurement", task, trigger="autopilot", title=f"Autopilot · {p['sku']}")
    except Exception:  # noqa: BLE001
        log.exception("autopilot run failed for %s", p["sku"])


# --- GST auto-fill ---------------------------------------------------------------------------


@bus.on(
    "product.created|catalog.imported",
    name="gst_autofill",
    description="AI fills missing HSN code + GST rate from the product name (marked for review)",
    priority=96,
)
async def gst_autofill(event: Event) -> None:
    from app.services.gst_ai import autofill_missing
    from app.services.india import gst_enabled

    if not await asyncio.to_thread(gst_enabled):
        return
    ids = [event.payload["id"]] if event.type == "product.created" and event.payload.get("id") else None
    await autofill_missing(ids)


def register() -> None:
    """Importing this module registers the hooks; kept for explicitness."""
