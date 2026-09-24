"""Inventory intelligence: demand forecasting, reorder policy, ABC, anomalies.

Pure-Python and deterministic so it works offline and is cheap to call from
agents. Methods:

* Demand forecast   - additive Holt-Winters (level + trend + weekly season),
                      falling back to Holt's linear smoothing on short history.
* Safety stock      - z * sigma_daily * sqrt(lead time), 95% service level.
* Reorder point     - mean daily demand * lead time + safety stock.
* Order quantity    - Economic Order Quantity, rounded up to the supplier MOQ.
* ABC analysis      - Pareto split on trailing consumption value (80/15/5).
* Anomalies         - z-score demand spikes, demand collapse, shrinkage.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    Alert,
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
from app.money import inr
from app.services.india import festival_multiplier
from app.services.inventory import on_hand_map
from app.services.purchasing import on_order_map

SERVICE_LEVEL_Z = 1.65  # ~95% cycle service level
ORDERING_COST = 4000.0  # ₹ per purchase order
HOLDING_RATE = 0.25  # annual holding cost as a fraction of unit cost
HISTORY_DAYS = 90


# --- Demand history ------------------------------------------------------------


def daily_sales(session: Session, days: int = HISTORY_DAYS, product_ids: list[int] | None = None) -> dict[int, list[float]]:
    """Units sold per product per day, oldest first, zero-filled, ending today."""
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    day_col = func.date(StockMovement.created_at)
    stmt = (
        select(StockMovement.product_id, day_col, func.sum(-StockMovement.quantity))
        .where(StockMovement.type == MovementType.SALE)
        .where(StockMovement.created_at >= day_start(start))
        .group_by(StockMovement.product_id, day_col)
    )
    if product_ids:
        stmt = stmt.where(StockMovement.product_id.in_(product_ids))
    series: dict[int, list[float]] = defaultdict(lambda: [0.0] * days)
    for pid, day, qty in session.exec(stmt):
        d = day if isinstance(day, date) else date.fromisoformat(str(day))
        idx = (d - start).days
        if 0 <= idx < days:
            series[pid][idx] = float(qty or 0)
    return series


# --- Forecasting ---------------------------------------------------------------


@dataclass
class Forecast:
    method: str
    forecast: list[float]
    lower: list[float]
    upper: list[float]
    mape: float | None
    fitted_level: float
    trend_per_day: float


def forecast_series(series: list[float], horizon: int = 30, season: int = 7) -> Forecast:
    """Additive Holt-Winters with a weekly season; Holt linear on short series."""
    n = len(series)
    if n == 0 or not any(series):
        zeros = [0.0] * horizon
        return Forecast("none", zeros, zeros, zeros, None, 0.0, 0.0)

    alpha, beta, gamma = 0.3, 0.05, 0.2
    use_season = n >= season * 3
    if use_season:
        first = series[:season]
        second = series[season : 2 * season]
        level = statistics.fmean(first)
        trend = (statistics.fmean(second) - level) / season
        seasonal = [x - level for x in first]
    else:
        level, trend, seasonal = series[0], 0.0, [0.0] * season

    errors: list[float] = []
    ape: list[float] = []
    for t, actual in enumerate(series):
        s = seasonal[t % season] if use_season else 0.0
        predicted = level + trend + s
        if t >= season:
            errors.append(actual - predicted)
            if actual > 0:
                ape.append(abs(actual - predicted) / actual)
        prev_level = level
        level = alpha * (actual - s) + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        if use_season:
            seasonal[t % season] = gamma * (actual - level) + (1 - gamma) * s

    sigma = statistics.pstdev(errors) if len(errors) > 1 else statistics.pstdev(series)
    forecast, lower, upper = [], [], []
    for h in range(1, horizon + 1):
        s = seasonal[(n + h - 1) % season] if use_season else 0.0
        point = max(0.0, level + h * trend + s)
        band = 1.28 * sigma * math.sqrt(1 + h / season)  # ~80% interval widening with horizon
        forecast.append(round(point, 2))
        lower.append(round(max(0.0, point - band), 2))
        upper.append(round(point + band, 2))
    return Forecast(
        method="holt-winters" if use_season else "holt",
        forecast=forecast,
        lower=lower,
        upper=upper,
        mape=round(statistics.fmean(ape) * 100, 1) if ape else None,
        fitted_level=round(level, 2),
        trend_per_day=round(trend, 3),
    )


# --- Per-product policy metrics ------------------------------------------------


@dataclass
class ProductMetrics:
    product_id: int
    sku: str
    name: str
    category: str | None
    supplier: str | None
    supplier_id: int | None
    unit_cost: float
    unit_price: float
    on_hand: int
    on_order: int
    avg_daily_demand: float
    demand_std: float
    lead_time_days: int
    safety_stock: int
    reorder_point: int
    eoq: int
    days_of_cover: float | None
    stockout_date: str | None
    status: str  # out | critical | low | healthy | overstock
    suggested_order_qty: int
    stock_value: float
    abc_class: str = "C"

    def to_dict(self) -> dict:
        return asdict(self)


def _status(on_hand: int, safety: int, rop: int, avg: float, days_cover: float | None) -> str:
    if on_hand <= 0:
        return "out"
    if on_hand <= safety:
        return "critical"
    if on_hand <= rop:
        return "low"
    if days_cover is not None and days_cover > 120 and on_hand > max(rop, 1) * 3:
        return "overstock"
    return "healthy"


def compute_metrics(session: Session, product_ids: list[int] | None = None) -> list[ProductMetrics]:
    stmt = select(Product, Category, Supplier).outerjoin(Category).outerjoin(Supplier).where(Product.is_active)
    if product_ids:
        stmt = stmt.where(Product.id.in_(product_ids))
    rows = session.exec(stmt).all()
    stock = on_hand_map(session)
    on_order = on_order_map(session)
    sales = daily_sales(session, HISTORY_DAYS, product_ids)
    recent_window = 28
    today = utcnow().date()

    metrics: list[ProductMetrics] = []
    for product, category, supplier in rows:
        series = sales.get(product.id, [0.0] * HISTORY_DAYS)
        recent = series[-recent_window:]
        avg = statistics.fmean(recent)
        std = statistics.pstdev(recent) if len(recent) > 1 else 0.0
        lead = product.lead_time_days or (supplier.lead_time_days if supplier else 7)
        safety = product.safety_stock if product.safety_stock is not None else math.ceil(SERVICE_LEVEL_Z * std * math.sqrt(lead))
        rop = product.reorder_point if product.reorder_point is not None else math.ceil(avg * lead + safety)
        annual = avg * 365
        holding = max(product.unit_cost * HOLDING_RATE, 0.01)
        eoq = math.ceil(math.sqrt(2 * annual * ORDERING_COST / holding)) if annual > 0 else 0
        qty = stock.get(product.id, 0)
        incoming = on_order.get(product.id, 0)
        cover = round(qty / avg, 1) if avg > 0 else None
        stockout = (today + timedelta(days=int(cover))).isoformat() if cover is not None else None

        suggested = 0
        position = qty + incoming
        if position <= rop and (avg > 0 or qty <= 0):
            need = max(eoq, rop - position + math.ceil(avg * lead), product.min_order_qty, 1)
            moq = max(product.min_order_qty, 1)
            suggested = int(math.ceil(need / moq) * moq)

        metrics.append(
            ProductMetrics(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                category=category.name if category else None,
                supplier=supplier.name if supplier else None,
                supplier_id=supplier.id if supplier else None,
                unit_cost=product.unit_cost,
                unit_price=product.unit_price,
                on_hand=qty,
                on_order=incoming,
                avg_daily_demand=round(avg, 2),
                demand_std=round(std, 2),
                lead_time_days=lead,
                safety_stock=int(safety),
                reorder_point=int(rop),
                eoq=eoq,
                days_of_cover=cover,
                stockout_date=stockout,
                status=_status(qty, int(safety), int(rop), avg, cover),
                suggested_order_qty=suggested,
                stock_value=round(qty * product.unit_cost, 2),
            )
        )

    _assign_abc(metrics)
    return metrics


def _assign_abc(metrics: list[ProductMetrics]) -> None:
    consumption = sorted(metrics, key=lambda m: m.avg_daily_demand * m.unit_cost, reverse=True)
    total = sum(m.avg_daily_demand * m.unit_cost for m in consumption) or 1.0
    running = 0.0
    for m in consumption:
        running += m.avg_daily_demand * m.unit_cost
        share = running / total
        m.abc_class = "A" if share <= 0.80 else "B" if share <= 0.95 else "C"


def metrics_for(session: Session, product_id: int) -> ProductMetrics | None:
    # ABC needs the full population, so compute all and pick one.
    return next((m for m in compute_metrics(session) if m.product_id == product_id), None)


# --- Reports -------------------------------------------------------------------


def reorder_recommendations(session: Session, limit: int = 50) -> list[dict]:
    urgency = {"out": 0, "critical": 1, "low": 2, "healthy": 3, "overstock": 4}
    recs = [m for m in compute_metrics(session) if m.suggested_order_qty > 0]
    recs.sort(key=lambda m: (urgency[m.status], m.days_of_cover if m.days_of_cover is not None else -1))
    out = []
    for m in recs[:limit]:
        d = m.to_dict()
        d["estimated_cost"] = round(m.suggested_order_qty * m.unit_cost, 2)
        d["reason"] = _reorder_reason(m)
        out.append(d)
    return out


def _reorder_reason(m: ProductMetrics) -> str:
    if m.status == "out":
        return "Out of stock"
    if m.days_of_cover is not None and m.days_of_cover < m.lead_time_days:
        return f"Stock runs out in ~{m.days_of_cover:g} days, lead time is {m.lead_time_days} days"
    return f"Inventory position ({m.on_hand + m.on_order}) is at or below reorder point ({m.reorder_point})"


def product_forecast(session: Session, product_id: int, horizon: int = 30) -> dict:
    series = daily_sales(session, HISTORY_DAYS, [product_id]).get(product_id, [0.0] * HISTORY_DAYS)
    fc = forecast_series(series, horizon)
    today = utcnow().date()
    history = [{"date": (today - timedelta(days=HISTORY_DAYS - 1 - i)).isoformat(), "actual": v} for i, v in enumerate(series)]
    product = session.get(Product, product_id)
    category = session.get(Category, product.category_id) if product and product.category_id else None
    projection, festivals = [], {}
    for i, (f, lo, hi) in enumerate(zip(fc.forecast, fc.lower, fc.upper, strict=True)):
        day = today + timedelta(days=i + 1)
        # Festival-aware: lift the statistical forecast inside Indian festival buying windows.
        mult, festival = festival_multiplier(category.name if category else None, day)
        point = {
            "date": day.isoformat(),
            "forecast": round(f * mult, 2),
            "lower": round(lo * mult, 2),
            "upper": round(hi * mult, 2),
        }
        if festival:
            point["festival"] = festival
            festivals[festival] = max(festivals.get(festival, 1.0), mult)
        projection.append(point)
    fc.forecast = [p["forecast"] for p in projection]
    return {
        "method": fc.method,
        "mape": fc.mape,
        "trend_per_day": fc.trend_per_day,
        "total_forecast": round(sum(fc.forecast), 1),
        "avg_daily_forecast": round(sum(fc.forecast) / horizon, 2) if horizon else 0,
        "history": history,
        "forecast": projection,
        "festivals": [{"name": k, "uplift": v} for k, v in festivals.items()],
    }


def abc_summary(session: Session) -> dict:
    metrics = compute_metrics(session)
    groups: dict[str, dict] = {c: {"class": c, "count": 0, "consumption_value": 0.0, "stock_value": 0.0} for c in "ABC"}
    for m in metrics:
        g = groups[m.abc_class]
        g["count"] += 1
        g["consumption_value"] += m.avg_daily_demand * m.unit_cost * 30
        g["stock_value"] += m.stock_value
    for g in groups.values():
        g["consumption_value"] = round(g["consumption_value"], 2)
        g["stock_value"] = round(g["stock_value"], 2)
    return {
        "classes": list(groups.values()),
        "products": [
            {
                "sku": m.sku,
                "name": m.name,
                "class": m.abc_class,
                "monthly_consumption_value": round(m.avg_daily_demand * m.unit_cost * 30, 2),
            }
            for m in sorted(metrics, key=lambda m: m.avg_daily_demand * m.unit_cost, reverse=True)
        ],
    }


def detect_anomalies(session: Session, window_days: int = 7) -> list[dict]:
    """Flag unusual demand spikes/drops and suspicious negative adjustments."""
    products = {p.id: p for p in session.exec(select(Product).where(Product.is_active))}
    sales = daily_sales(session, 60)
    today = utcnow().date()
    findings: list[dict] = []
    for pid, series in sales.items():
        product = products.get(pid)
        if product is None:
            continue
        baseline, recent = series[:-window_days], series[-window_days:]
        mean = statistics.fmean(baseline)
        std = statistics.pstdev(baseline) or 1.0
        peak_offset = max(range(len(recent)), key=lambda i: recent[i])
        value = recent[peak_offset]
        z = (value - mean) / std
        if z >= 3.5 and value >= mean + 5:
            day = today - timedelta(days=window_days - 1 - peak_offset)
            spike_days = sum(1 for v in recent if (v - mean) / std >= 3.5)
            findings.append(
                {
                    "kind": "demand_spike",
                    "severity": "warning" if z < 6 else "critical",
                    "sku": product.sku,
                    "name": product.name,
                    "date": day.isoformat(),
                    "value": value,
                    "baseline": round(mean, 2),
                    "z_score": round(z, 1),
                    "message": f"{product.name} sold {value:g} units on {day:%b %d} ({z:.1f}σ above its {mean:.1f}/day baseline)"
                    + (f"; {spike_days} spike days this week" if spike_days > 1 else ""),
                }
            )
        recent_mean = statistics.fmean(recent)
        if mean >= 2 and recent_mean < mean * 0.3:
            findings.append(
                {
                    "kind": "demand_drop",
                    "severity": "warning",
                    "sku": product.sku,
                    "name": product.name,
                    "date": today.isoformat(),
                    "value": round(recent_mean, 2),
                    "baseline": round(mean, 2),
                    "z_score": None,
                    "message": f"{product.name} demand fell to {recent_mean:.1f}/day from a {mean:.1f}/day baseline",
                }
            )

    since = day_start(today - timedelta(days=window_days * 2))
    adjustments = session.exec(
        select(StockMovement)
        .where(StockMovement.type == MovementType.ADJUSTMENT)
        .where(StockMovement.created_at >= since)
        .where(StockMovement.quantity < 0)
    )
    for mv in adjustments:
        product = products.get(mv.product_id)
        if product is None:
            continue
        avg = statistics.fmean(sales.get(mv.product_id, [0.0])[-28:]) if mv.product_id in sales else 0
        if -mv.quantity >= max(5, 2 * avg):
            findings.append(
                {
                    "kind": "shrinkage",
                    "severity": "critical" if -mv.quantity * product.unit_cost > 500 else "warning",
                    "sku": product.sku,
                    "name": product.name,
                    "date": mv.created_at.date().isoformat(),
                    "value": mv.quantity,
                    "baseline": round(avg, 2),
                    "z_score": None,
                    "message": f"Write-off of {-mv.quantity} × {product.name} ({inr(-mv.quantity * product.unit_cost)})"
                    + (f": {mv.note}" if mv.note else ""),
                }
            )
    order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: f["date"], reverse=True)
    findings.sort(key=lambda f: order.get(f["severity"], 3))
    return findings


def dashboard(session: Session) -> dict:
    metrics = compute_metrics(session)
    today = utcnow().date()
    start = day_start(today - timedelta(days=29))
    day_col = func.date(StockMovement.created_at)
    trend_rows = session.exec(
        select(day_col, func.sum(-StockMovement.quantity), func.sum(-StockMovement.quantity * Product.unit_price))
        .join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.type == MovementType.SALE, StockMovement.created_at >= start)
        .group_by(day_col)
    ).all()
    by_day = {str(d): (float(u or 0), float(r or 0)) for d, u, r in trend_rows}
    trend = []
    for i in range(30):
        d = (today - timedelta(days=29 - i)).isoformat()
        units, revenue = by_day.get(d, (0.0, 0.0))
        trend.append({"date": d, "units": units, "revenue": round(revenue, 2)})

    categories: dict[str, float] = defaultdict(float)
    status_counts: dict[str, int] = defaultdict(int)
    for m in metrics:
        categories[m.category or "Uncategorized"] += m.stock_value
        status_counts[m.status] += 1

    open_pos = session.exec(
        select(func.count())
        .select_from(PurchaseOrder)
        .where(PurchaseOrder.status.in_((POStatus.DRAFT, POStatus.APPROVED, POStatus.ORDERED)))
    ).one()
    open_alerts = session.exec(select(func.count()).select_from(Alert).where(Alert.resolved == False)).one()  # noqa: E712
    revenue_30 = sum(t["revenue"] for t in trend)
    prev_start = start - timedelta(days=30)
    prev_revenue = (
        session.exec(
            select(func.sum(-StockMovement.quantity * Product.unit_price))
            .select_from(StockMovement)
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.type == MovementType.SALE)
            .where(StockMovement.created_at >= prev_start, StockMovement.created_at < start)
        ).one()
        or 0.0
    )

    movers = sorted(metrics, key=lambda m: m.avg_daily_demand * m.unit_price, reverse=True)[:5]
    return {
        "kpis": {
            "total_skus": len(metrics),
            "total_units": sum(m.on_hand for m in metrics),
            "inventory_value": round(sum(m.stock_value for m in metrics), 2),
            "low_stock": status_counts["low"] + status_counts["critical"],
            "out_of_stock": status_counts["out"],
            "overstock": status_counts["overstock"],
            "open_purchase_orders": open_pos,
            "open_alerts": open_alerts,
            "revenue_30d": round(revenue_30, 2),
            "revenue_change_pct": round((revenue_30 - prev_revenue) / prev_revenue * 100, 1) if prev_revenue else None,
            "reorder_needed": sum(1 for m in metrics if m.suggested_order_qty > 0),
        },
        "sales_trend": trend,
        "category_value": [{"category": k, "value": round(v, 2)} for k, v in sorted(categories.items(), key=lambda kv: -kv[1])],
        "status_breakdown": [
            {"status": s, "count": status_counts.get(s, 0)} for s in ("healthy", "low", "critical", "out", "overstock")
        ],
        "top_movers": [
            {
                "sku": m.sku,
                "name": m.name,
                "avg_daily_demand": m.avg_daily_demand,
                "daily_revenue": round(m.avg_daily_demand * m.unit_price, 2),
                "status": m.status,
            }
            for m in movers
        ],
    }


# --- Unique insights ---------------------------------------------------------------------

PRICE_ELASTICITY = -2.0  # assumed: a 10% price cut lifts unit demand ~20%


def health_score(session: Session) -> dict:
    """One 0-100 'inventory health' score with an explainable breakdown."""
    metrics = compute_metrics(session)
    n = len(metrics) or 1
    total_value = sum(m.stock_value for m in metrics) or 1.0
    out = sum(1 for m in metrics if m.status == "out")
    at_risk = sum(1 for m in metrics if m.status in ("critical", "low"))
    overstock_value = sum(m.stock_value for m in metrics if m.status == "overstock")
    needs = [m for m in metrics if m.status in ("out", "critical", "low")]
    covered = sum(1 for m in needs if m.on_order > 0)
    since = day_start(utcnow().date() - timedelta(days=30))
    shrink_value = sum(
        -mv.quantity * p.unit_cost
        for mv, p in session.exec(
            select(StockMovement, Product)
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.type == MovementType.ADJUSTMENT, StockMovement.quantity < 0, StockMovement.created_at >= since)
        )
    )
    components = [
        {
            "key": "availability",
            "label": "Availability",
            "weight": 35,
            "score": 1 - out / n,
            "detail": f"{n - out} of {n} SKUs in stock",
        },
        {
            "key": "service_risk",
            "label": "Service risk",
            "weight": 25,
            "score": 1 - at_risk / n,
            "detail": f"{at_risk} SKUs below reorder point",
        },
        {
            "key": "capital",
            "label": "Capital efficiency",
            "weight": 20,
            "score": 1 - min(1.0, overstock_value / total_value * 2),
            "detail": f"{inr(overstock_value)} tied up in overstock",
        },
        {
            "key": "replenishment",
            "label": "Replenishment coverage",
            "weight": 10,
            "score": covered / len(needs) if needs else 1.0,
            "detail": f"{covered} of {len(needs)} at-risk SKUs already on order",
        },
        {
            "key": "accuracy",
            "label": "Stock accuracy",
            "weight": 10,
            "score": 1 - min(1.0, shrink_value / total_value * 20),
            "detail": f"{inr(shrink_value)} written off in 30 days",
        },
    ]
    for c in components:
        c["score"] = round(max(0.0, min(1.0, c["score"])) * 100, 1)
    score = round(sum(c["score"] * c["weight"] for c in components) / 100, 1)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
    weakest = min(components, key=lambda c: c["score"])
    return {
        "score": score,
        "grade": grade,
        "components": components,
        "focus": f"Biggest lever: {weakest['label'].lower()} — {weakest['detail']}.",
    }


def markdown_suggestions(session: Session, clear_days: int = 60) -> list[dict]:
    """Smart markdown advisor: discounts that clear excess stock without selling below cost."""
    out = []
    for m in compute_metrics(session):
        target = m.reorder_point + max(m.eoq, math.ceil(m.avg_daily_demand * 30))
        excess = m.on_hand - target
        cover = m.days_of_cover if m.days_of_cover is not None else (999 if m.on_hand else 0)
        if excess <= 0 or cover < 75 or m.unit_price <= 0:
            continue
        base = max(m.avg_daily_demand, 0.05)
        needed = excess / clear_days + base  # daily sales needed to clear in time
        uplift = needed / base - 1
        discount = min(0.5, uplift / -PRICE_ELASTICITY)
        floor = max(0.0, 1 - (m.unit_cost * 1.05) / m.unit_price)  # never below cost + 5%
        applied = round(min(discount, floor), 3)
        new_daily = base * (1 + -PRICE_ELASTICITY * applied)
        new_price = round(m.unit_price * (1 - applied), 2)
        out.append(
            {
                "product_id": m.product_id,
                "sku": m.sku,
                "name": m.name,
                "category": m.category,
                "on_hand": m.on_hand,
                "days_of_cover": cover,
                "excess_units": int(excess),
                "capital_tied": round(excess * m.unit_cost, 2),
                "suggested_discount_pct": round(applied * 100, 1),
                "new_price": new_price,
                "current_price": m.unit_price,
                "projected_days_to_clear": round(excess / max(new_daily, 0.01)) if applied else None,
                "margin_after_pct": round((new_price - m.unit_cost) / new_price * 100, 1) if new_price else 0,
                "capped_by_cost": discount > floor,
                "action": "Bundle or transfer instead — discount floor reached"
                if discount > floor and applied < 0.05
                else f"Run a {applied:.0%} markdown for ~{clear_days} days",
            }
        )
    return sorted(out, key=lambda r: -r["capital_tied"])
