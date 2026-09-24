"""Supplier scorecards and margin analytics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    Category,
    MovementType,
    POStatus,
    Product,
    PurchaseOrder,
    StockMovement,
    Supplier,
    day_start,
    utcnow,
)


def supplier_scorecards(session: Session, days: int = 120) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    suppliers = session.exec(select(Supplier).order_by(Supplier.name)).all()
    pos = session.exec(select(PurchaseOrder).where(PurchaseOrder.created_at >= since)).all()
    by_supplier: dict[int, list[PurchaseOrder]] = defaultdict(list)
    for po in pos:
        by_supplier[po.supplier_id].append(po)

    cards = []
    for sup in suppliers:
        orders = by_supplier.get(sup.id, [])
        received = [po for po in orders if po.status == POStatus.RECEIVED and po.received_at]
        on_time = [po for po in received if po.expected_at and po.received_at.date() <= po.expected_at.date()]
        lead_times = [(po.received_at - po.created_at).days for po in received]
        spend = sum(line.quantity * line.unit_cost for po in received for line in po.lines)
        on_time_rate = len(on_time) / len(received) * 100 if received else None
        avg_lead = statistics.fmean(lead_times) if lead_times else None
        # Composite score: 60% on-time, 25% lead-time accuracy, 15% catalog rating.
        lead_accuracy = max(0.0, 100 - abs((avg_lead or sup.lead_time_days) - sup.lead_time_days) / sup.lead_time_days * 100)
        score = 0.6 * (on_time_rate if on_time_rate is not None else 80) + 0.25 * lead_accuracy + 0.15 * sup.rating * 20
        cards.append(
            {
                "id": sup.id,
                "name": sup.name,
                "email": sup.email,
                "phone": sup.phone,
                "rating": sup.rating,
                "promised_lead_time": sup.lead_time_days,
                "actual_lead_time": round(avg_lead, 1) if avg_lead is not None else None,
                "on_time_rate": round(on_time_rate, 1) if on_time_rate is not None else None,
                "orders_received": len(received),
                "open_orders": sum(1 for po in orders if po.status in (POStatus.DRAFT, POStatus.APPROVED, POStatus.ORDERED)),
                "spend": round(spend, 2),
                "score": round(score, 1),
                "grade": "A" if score >= 85 else "B" if score >= 70 else "C",
                "products": session.exec(select(func.count()).select_from(Product).where(Product.supplier_id == sup.id)).one(),
            }
        )
    return sorted(cards, key=lambda c: -c["score"])


def margin_by_category(session: Session, days: int = 30) -> list[dict]:
    since = day_start(utcnow().date() - timedelta(days=days - 1))
    rows = session.exec(
        select(
            Category.name,
            Category.color,
            func.sum(-StockMovement.quantity * Product.unit_price),
            func.sum(-StockMovement.quantity * Product.unit_cost),
            func.sum(-StockMovement.quantity),
        )
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Category, Category.id == Product.category_id)
        .where(StockMovement.type == MovementType.SALE, StockMovement.created_at >= since)
        .group_by(Category.name, Category.color)
    ).all()
    out = []
    for name, color, revenue, cogs, units in rows:
        revenue, cogs = float(revenue or 0), float(cogs or 0)
        out.append(
            {
                "category": name,
                "color": color,
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "gross_profit": round(revenue - cogs, 2),
                "margin_pct": round((revenue - cogs) / revenue * 100, 1) if revenue else 0,
                "units": int(units or 0),
            }
        )
    return sorted(out, key=lambda r: -r["revenue"])
