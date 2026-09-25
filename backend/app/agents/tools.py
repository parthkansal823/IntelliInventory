"""Inventory tools exposed to agents and MCP clients.

Each tool is a typed function; its signature becomes the JSON schema and its
docstring the description the model sees. Tools return JSON-friendly dicts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlmodel import select

from app.db import session_scope
from app.models import Alert, MovementType, POStatus, Product, PurchaseOrder, StockMovement, Warehouse, utcnow
from app.services import analytics, counts, india, inventory, purchasing, simulator, suppliers
from app.services.inventory import InventoryError

from .toolkit import get_actor, tools

Sku = Annotated[str, Field(description="Product SKU, e.g. ELC-1001 (a product name also works)")]


def _metrics_row(m: analytics.ProductMetrics) -> dict:
    return {
        "sku": m.sku,
        "name": m.name,
        "category": m.category,
        "supplier": m.supplier,
        "on_hand": m.on_hand,
        "on_order": m.on_order,
        "status": m.status,
        "avg_daily_demand": m.avg_daily_demand,
        "days_of_cover": m.days_of_cover,
        "reorder_point": m.reorder_point,
        "safety_stock": m.safety_stock,
        "suggested_order_qty": m.suggested_order_qty,
        "abc_class": m.abc_class,
        "unit_cost": m.unit_cost,
        "unit_price": m.unit_price,
    }


def _resolve(session, ref: str) -> Product:
    try:
        return inventory.find_product(session, ref)
    except InventoryError:
        names = {p.id: f"{p.sku} {p.name}" for p in session.exec(select(Product))}
        match = process.extractOne(ref, names, scorer=fuzz.WRatio, score_cutoff=70)
        if match:
            return session.get(Product, match[2])
        raise


# --- read tools ------------------------------------------------------------------------


@tools.tool(tags=("read", "overview"))
def get_inventory_summary() -> dict:
    """Live inventory KPIs: SKU count, units, stock value, low/out-of-stock counts, open POs and alerts,
    30-day revenue trend, stock-health breakdown and top-selling products."""
    with session_scope() as s:
        d = analytics.dashboard(s)
    trend = d["sales_trend"]
    return {
        "kpis": d["kpis"],
        "status_breakdown": d["status_breakdown"],
        "top_movers": d["top_movers"],
        "last_7_days_revenue": round(sum(t["revenue"] for t in trend[-7:]), 2),
        "previous_7_days_revenue": round(sum(t["revenue"] for t in trend[-14:-7]), 2),
    }


@tools.tool(tags=("read", "search"))
def search_products(
    query: Annotated[str, Field(description="Free-text search over SKU, name, category and supplier")] = "",
    status: Annotated[
        Literal["out", "critical", "low", "healthy", "overstock"] | None, Field(description="Filter by stock status")
    ] = None,
    category: Annotated[str | None, Field(description="Filter by category name")] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> dict:
    """Fuzzy-search the product catalog and return live stock metrics for each match."""
    with session_scope() as s:
        metrics = analytics.compute_metrics(s)
    if status:
        metrics = [m for m in metrics if m.status == status]
    if category:
        metrics = [m for m in metrics if (m.category or "").lower() == category.lower()]
    if query.strip():
        corpus = {i: f"{m.sku} {m.name} {m.category} {m.supplier}" for i, m in enumerate(metrics)}
        hits = process.extract(query, corpus, scorer=fuzz.WRatio, limit=limit, score_cutoff=55)
        metrics = [metrics[key] for _, _, key in hits]
    return {"count": len(metrics[:limit]), "products": [_metrics_row(m) for m in metrics[:limit]]}


@tools.tool(tags=("read", "product"))
def get_product_details(sku: Sku) -> dict:
    """Full detail for one product: stock per warehouse, replenishment policy (safety stock, reorder point, EOQ),
    days of cover, 14-day forecast and the 10 most recent stock movements."""
    with session_scope() as s:
        product = _resolve(s, sku)
        m = analytics.metrics_for(s, product.id)
        fc = analytics.product_forecast(s, product.id, 14)
        moves = s.exec(
            select(StockMovement)
            .where(StockMovement.product_id == product.id)
            .order_by(StockMovement.created_at.desc())
            .limit(10)
        ).all()
        return {
            **_metrics_row(m),
            "eoq": m.eoq,
            "lead_time_days": m.lead_time_days,
            "stockout_date": m.stockout_date,
            "stock_value": m.stock_value,
            "warehouses": inventory.stock_by_warehouse(s, product.id),
            "forecast_14d": {
                "total": fc["total_forecast"],
                "avg_daily": fc["avg_daily_forecast"],
                "method": fc["method"],
                "mape": fc["mape"],
            },
            "recent_movements": [
                {
                    "date": mv.created_at.date().isoformat(),
                    "type": mv.type,
                    "quantity": mv.quantity,
                    "reference": mv.reference,
                    "actor": mv.actor,
                }
                for mv in moves
            ],
        }


@tools.tool(tags=("read", "replenishment"))
def get_low_stock_items(limit: Annotated[int, Field(ge=1, le=50)] = 15) -> dict:
    """Products that are out of stock, critical (below safety stock) or low (below reorder point)."""
    order = {"out": 0, "critical": 1, "low": 2}
    with session_scope() as s:
        items = [m for m in analytics.compute_metrics(s) if m.status in order]
    items.sort(key=lambda m: (order[m.status], m.days_of_cover or 0))
    return {"count": len(items), "items": [_metrics_row(m) for m in items[:limit]]}


@tools.tool(tags=("read", "replenishment", "procurement"))
def get_reorder_recommendations(
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
    supplier: Annotated[str | None, Field(description="Only recommendations for this supplier (name)")] = None,
) -> dict:
    """What to reorder now: items whose inventory position is at/below the reorder point, with EOQ-based
    suggested quantities (rounded to the supplier MOQ), estimated cost and the reason."""
    with session_scope() as s:
        recs = analytics.reorder_recommendations(s, 100)
    if supplier:
        recs = [r for r in recs if supplier.lower() in (r["supplier"] or "").lower()]
    keys = (
        "sku",
        "name",
        "supplier",
        "supplier_id",
        "status",
        "on_hand",
        "on_order",
        "reorder_point",
        "days_of_cover",
        "suggested_order_qty",
        "unit_cost",
        "estimated_cost",
        "reason",
    )
    rows = [{k: r[k] for k in keys} for r in recs[:limit]]
    return {"count": len(recs), "total_estimated_cost": round(sum(r["estimated_cost"] for r in recs), 2), "items": rows}


@tools.tool(tags=("read", "forecast"))
def forecast_demand(sku: Sku, horizon_days: Annotated[int, Field(ge=7, le=90)] = 30) -> dict:
    """Demand forecast for a product (Holt-Winters with weekly seasonality) with an 80% confidence band,
    backtest error (MAPE), trend, and a comparison with the last 30 days of actual sales."""
    with session_scope() as s:
        product = _resolve(s, sku)
        fc = analytics.product_forecast(s, product.id, horizon_days)
        m = analytics.metrics_for(s, product.id)
    last30 = sum(h["actual"] for h in fc["history"][-30:])
    weekly = [round(sum(p["forecast"] for p in fc["forecast"][i : i + 7]), 1) for i in range(0, horizon_days, 7)]
    return {
        "sku": product.sku,
        "name": product.name,
        "method": fc["method"],
        "mape_pct": fc["mape"],
        "horizon_days": horizon_days,
        "forecast_total": fc["total_forecast"],
        "avg_daily": fc["avg_daily_forecast"],
        "trend_per_day": fc["trend_per_day"],
        "last_30_days_actual": last30,
        "weekly_totals": weekly,
        "next_7_days": fc["forecast"][:7],
        "on_hand": m.on_hand,
        "days_of_cover": m.days_of_cover,
        "projected_stockout_date": m.stockout_date,
    }


@tools.tool(tags=("read", "forecast", "simulation"))
def simulate_policy(
    sku: Sku,
    demand_multiplier: Annotated[float, Field(ge=0.1, le=5, description="1.2 = +20% demand")] = 1.0,
    lead_time_days: Annotated[int | None, Field(ge=1, le=120, description="Override supplier lead time")] = None,
    service_level: Annotated[float, Field(ge=0.5, le=0.999, description="Target cycle service level")] = 0.95,
    order_qty: Annotated[int | None, Field(ge=1, description="Override order quantity (default EOQ)")] = None,
    horizon_days: Annotated[int, Field(ge=7, le=180)] = 60,
) -> dict:
    """What-if Monte-Carlo simulation (300 runs) of the replenishment policy under changed demand, lead time,
    service level or order quantity. Returns fill rate, stockout probability, average inventory and costs."""
    with session_scope() as s:
        product = _resolve(s, sku)
        result = simulator.simulate(
            s,
            product.id,
            horizon=horizon_days,
            demand_multiplier=demand_multiplier,
            lead_time_days=lead_time_days,
            service_level=service_level,
            order_qty=order_qty,
        )
    result.pop("projection")
    return result


@tools.tool(tags=("read", "audit"))
def detect_anomalies(window_days: Annotated[int, Field(ge=3, le=30)] = 7) -> dict:
    """Detect unusual activity in the recent window: demand spikes (z-score), demand collapses and
    large stock write-offs (possible shrinkage/theft/damage)."""
    with session_scope() as s:
        found = analytics.detect_anomalies(s, window_days)
    return {"count": len(found), "anomalies": found}


@tools.tool(tags=("read", "audit"))
def get_stock_movements(
    sku: Annotated[str | None, Field(description="Limit to one product")] = None,
    movement_type: Annotated[
        Literal["receipt", "sale", "adjustment", "transfer_in", "transfer_out", "return"] | None, Field()
    ] = None,
    days: Annotated[int, Field(ge=1, le=120)] = 14,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    """Stock movement ledger (receipts, sales, adjustments, transfers) with actor and reference."""
    with session_scope() as s:
        stmt = (
            select(StockMovement, Product, Warehouse)
            .join(Product, Product.id == StockMovement.product_id)
            .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
            .where(StockMovement.created_at >= utcnow() - timedelta(days=days))
        )
        if sku:
            stmt = stmt.where(StockMovement.product_id == _resolve(s, sku).id)
        if movement_type:
            stmt = stmt.where(StockMovement.type == MovementType(movement_type))
        rows = s.exec(stmt.order_by(StockMovement.created_at.desc()).limit(limit)).all()
        return {
            "count": len(rows),
            "movements": [
                {
                    "timestamp": mv.created_at.isoformat(timespec="minutes"),
                    "sku": p.sku,
                    "name": p.name,
                    "warehouse": w.code,
                    "type": mv.type,
                    "quantity": mv.quantity,
                    "reference": mv.reference,
                    "note": mv.note,
                    "actor": mv.actor,
                }
                for mv, p, w in rows
            ],
        }


@tools.tool(tags=("read", "procurement"))
def list_purchase_orders(
    status: Annotated[
        Literal["draft", "approved", "ordered", "received", "cancelled", "open"] | None,
        Field(description="'open' = draft, approved or ordered"),
    ] = "open",
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> dict:
    """Purchase orders with supplier, lines, totals and expected delivery."""
    with session_scope() as s:
        stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
        if status == "open":
            stmt = stmt.where(PurchaseOrder.status.in_(purchasing.OPEN_STATUSES))
        elif status:
            stmt = stmt.where(PurchaseOrder.status == POStatus(status))
        orders = [purchasing.po_summary(s, po) for po in s.exec(stmt.limit(limit))]
    return {"count": len(orders), "purchase_orders": orders}


@tools.tool(tags=("read", "procurement"))
def list_suppliers() -> dict:
    """Supplier scorecards: on-time delivery rate, actual vs promised lead time, spend, grade."""
    with session_scope() as s:
        return {"suppliers": suppliers.supplier_scorecards(s)}


@tools.tool(tags=("read", "analytics"))
def abc_analysis() -> dict:
    """ABC (Pareto) classification by consumption value: A = top 80%, B = next 15%, C = last 5%."""
    with session_scope() as s:
        result = analytics.abc_summary(s)
    result["products"] = result["products"][:15]
    return result


@tools.tool(tags=("read", "analytics"))
def margin_report(days: Annotated[int, Field(ge=7, le=120)] = 30) -> dict:
    """Revenue, cost of goods sold, gross profit and margin % per category for the recent period."""
    with session_scope() as s:
        return {"days": days, "categories": suppliers.margin_by_category(s, days)}


@tools.tool(tags=("read", "analytics"))
def get_health_score() -> dict:
    """Overall inventory health score (0-100, graded A-E) with an explainable breakdown: availability,
    service risk, capital efficiency, replenishment coverage and stock accuracy."""
    with session_scope() as s:
        return analytics.health_score(s)


@tools.tool(tags=("read", "analytics", "pricing"))
def get_markdown_suggestions(
    clear_days: Annotated[int, Field(ge=14, le=180, description="Days to clear the excess")] = 60,
) -> dict:
    """Smart markdown advisor: overstocked / slow-moving items, the capital tied up, and the discount that
    clears the excess in time without pricing below cost + 5% (assumes price elasticity of -2)."""
    with session_scope() as s:
        items = analytics.markdown_suggestions(s, clear_days)
    return {"count": len(items), "capital_tied": round(sum(i["capital_tied"] for i in items), 2), "items": items[:10]}


@tools.tool(tags=("read", "india", "forecast", "procurement"))
def plan_festival_stock(
    festival: Annotated[
        str | None, Field(description="Festival name, e.g. Diwali, Dhanteras, Holi, Eid (default: next major one)")
    ] = None,
) -> dict:
    """Indian festival demand planner: upcoming festival (Navratri, Dhanteras, Diwali, Chhath, Christmas, Sankranti,
    Eid, Holi, Rakhi, Ganesh Chaturthi, Onam...), expected demand uplift per category, and what to order by when."""
    with session_scope() as s:
        plan = india.festival_plan(s, festival)
    plan["items"] = [i for i in plan["items"] if i["suggested_order_qty"]][:12] or plan["items"][:8]
    plan["upcoming"] = [
        {"name": f["name"], "date": f["date"], "days_away": f["days_away"]} for f in india.festival_calendar()[:6]
    ]
    return plan


@tools.tool(tags=("read", "india", "tax"))
def gst_summary(days: Annotated[int, Field(ge=7, le=120, description="Period in days")] = 30) -> dict:
    """GST estimate (GSTR-3B style): output tax on sales vs input tax credit on received purchases, per slab
    (GST 2.0: 0/5/18/40%), and the net GST payable."""
    with session_scope() as s:
        return india.gst_report(s, days)


@tools.tool(tags=("read", "india", "tax"))
def suggest_gst(
    product_name: Annotated[str, Field(description="Product name, e.g. 'Stainless steel lunch box'")],
    category: Annotated[str | None, Field(description="Optional category")] = None,
) -> dict:
    """Suggest the HSN code and current GST slab for a product name (rule-based, uses the slabs configured in Settings)."""
    from app.services.gst_ai import suggest_by_rules

    return {"product": product_name, **suggest_by_rules(product_name, category)}


@tools.tool(tags=("read", "audit"))
def list_alerts(limit: Annotated[int, Field(ge=1, le=50)] = 20) -> dict:
    """Open alerts (stockouts, low stock, overstock, anomalies), most severe first."""
    with session_scope() as s:
        rows = s.exec(
            select(Alert, Product)
            .outerjoin(Product)
            .where(Alert.resolved == False)  # noqa: E712
            .order_by(Alert.created_at.desc())
        ).all()
    order = {"critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: order.get(r[0].severity, 3))
    return {
        "count": len(rows),
        "alerts": [
            {
                "id": a.id,
                "kind": a.kind,
                "severity": a.severity,
                "sku": p.sku if p else None,
                "message": a.message,
                "since": a.created_at.isoformat(timespec="minutes"),
            }
            for a, p in rows[:limit]
        ],
    }


# --- write tools -------------------------------------------------------------------------


class OrderItem(BaseModel):
    sku: str = Field(description="Product SKU")
    quantity: int = Field(gt=0, description="Units to order")


@tools.tool(mutates=True, tags=("write", "procurement"))
def create_purchase_order(
    items: Annotated[list[OrderItem], Field(min_length=1, description="Lines to order (same supplier)")],
    supplier: Annotated[str | None, Field(description="Supplier name; defaults to the first item's supplier")] = None,
    warehouse: Annotated[str | None, Field(description="Destination warehouse code, e.g. MAIN")] = None,
    notes: Annotated[str | None, Field(description="Reason / context for the buyer")] = None,
) -> dict:
    """Create a DRAFT purchase order (safe: a manager must approve it before it is sent to the supplier).
    All items should come from the same supplier."""
    with session_scope() as s:
        lines = [
            (
                _resolve(s, item["sku"] if isinstance(item, dict) else item.sku),
                item["quantity"] if isinstance(item, dict) else item.quantity,
            )
            for item in items
        ]
        supplier_id = None
        if supplier:
            match = next((c for c in suppliers.supplier_scorecards(s) if supplier.lower() in c["name"].lower()), None)
            if match is None:
                raise InventoryError(f"Supplier '{supplier}' not found")
            supplier_id = match["id"]
        mixed = {p.supplier_id for p, _ in lines}
        if len(mixed) > 1 and supplier_id is None:
            raise InventoryError("Items belong to different suppliers; create one purchase order per supplier")
        po = purchasing.create_po(s, lines, supplier_id=supplier_id, warehouse_ref=warehouse, created_by=get_actor(), notes=notes)
        return {"created": True, "purchase_order": purchasing.po_summary(s, po)}


@tools.tool(requires_approval=True, tags=("write", "procurement"))
def update_purchase_order_status(
    po_number: Annotated[str, Field(description="e.g. PO-2026-0042")],
    status: Literal["approved", "ordered", "received", "cancelled"],
) -> dict:
    """Advance or cancel a purchase order (draft→approved→ordered→received). Receiving posts stock.
    Requires human approval."""
    with session_scope() as s:
        po = purchasing.find_po(s, po_number)
        purchasing.set_status(s, po, POStatus(status), actor=get_actor())
        s.refresh(po)
        return {"updated": True, "purchase_order": purchasing.po_summary(s, po)}


@tools.tool(requires_approval=True, tags=("write", "audit"))
def adjust_stock(
    sku: Sku,
    quantity_delta: Annotated[int, Field(description="Positive to add stock, negative to remove (write-off)")],
    reason: Annotated[str, Field(description="Why the adjustment is needed")],
    warehouse: Annotated[str | None, Field(description="Warehouse code (default MAIN)")] = None,
) -> dict:
    """Adjust on-hand stock (damage, loss, found stock, corrections). Requires human approval."""
    with session_scope() as s:
        product = _resolve(s, sku)
        mv = inventory.adjust_stock(s, product.id, quantity_delta, warehouse_ref=warehouse, reason=reason, actor=get_actor())
        return {"adjusted": True, "sku": product.sku, "delta": mv.quantity, "on_hand": inventory.on_hand(s, product.id)}


@tools.tool(requires_approval=True, tags=("write", "audit"))
def transfer_stock(
    sku: Sku,
    quantity: Annotated[int, Field(gt=0)],
    from_warehouse: Annotated[str, Field(description="Source warehouse code")],
    to_warehouse: Annotated[str, Field(description="Destination warehouse code")],
) -> dict:
    """Move stock between warehouses. Requires human approval."""
    with session_scope() as s:
        product = _resolve(s, sku)
        out, inn = inventory.transfer_stock(s, product.id, quantity, from_warehouse, to_warehouse, actor=get_actor())
        eway = india.transfer_eway(s, product, quantity, s.get(Warehouse, out.warehouse_id), s.get(Warehouse, inn.warehouse_id))
        return {
            "eway": eway,
            "transferred": True,
            "sku": product.sku,
            "quantity": quantity,
            "warehouses": inventory.stock_by_warehouse(s, product.id),
        }


@tools.tool(requires_approval=True, tags=("write", "replenishment"))
def update_reorder_settings(
    sku: Sku,
    reorder_point: Annotated[int | None, Field(ge=0, description="Manual reorder point; omit to keep")] = None,
    safety_stock: Annotated[int | None, Field(ge=0)] = None,
    min_order_qty: Annotated[int | None, Field(ge=1)] = None,
) -> dict:
    """Override a product's replenishment parameters. Requires human approval."""
    with session_scope() as s:
        product = _resolve(s, sku)
        if reorder_point is not None:
            product.reorder_point = reorder_point
        if safety_stock is not None:
            product.safety_stock = safety_stock
        if min_order_qty is not None:
            product.min_order_qty = min_order_qty
        s.add(product)
        s.commit()
        m = analytics.metrics_for(s, product.id)
        return {"updated": True, **_metrics_row(m)}


@tools.tool(mutates=True, tags=("write", "audit"))
def start_cycle_count(
    warehouse: Annotated[str, Field(description="Warehouse code, e.g. MAIN")] = "MAIN",
    scope: Annotated[Literal["all", "A", "B", "C"], Field(description="Count everything or one ABC class")] = "A",
) -> dict:
    """Open a cycle-count sheet (snapshot of expected quantities) for staff to fill in."""
    with session_scope() as s:
        count = counts.create_count(s, warehouse, scope, actor=get_actor())
        summary = counts.count_summary(s, count)
    summary["lines"] = summary["lines"][:10]
    return summary


@tools.tool(tags=("read", "india", "billing"))
def billing_summary(days: Annotated[int, Field(ge=1, le=120, description="Period in days")] = 7) -> dict:
    """Sales from bills/invoices: today's sales, the period total, average bill, money collected per payment mode
    (cash/UPI/card/bank) and the total udhaar (credit) still to collect."""
    from app.services import billing

    with session_scope() as s:
        data = billing.billing_summary(s, days)
        data["daily"] = data["daily"][-7:]
        return data


@tools.tool(tags=("read", "india", "billing"))
def customer_dues(limit: Annotated[int, Field(ge=1, le=50, description="Max customers")] = 10) -> list[dict]:
    """The khata: customers with unpaid / part-paid bills (udhaar), biggest balance first, with phone numbers and
    how many days the oldest bill has been outstanding."""
    from app.services import billing

    with session_scope() as s:
        return billing.customer_dues(s, limit)


@tools.tool(tags=("read", "india", "billing"))
def get_invoice(number: Annotated[str, Field(description="Invoice number, e.g. INV/26-27/00007")]) -> dict:
    """One invoice with its lines, GST breakup (CGST/SGST or IGST), payments and balance due."""
    from app.services import billing

    with session_scope() as s:
        d = billing.invoice_detail(s, billing.find_invoice(s, number))
        d.pop("seller", None)
        return d
