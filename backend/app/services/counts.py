"""Cycle counts: snapshot expected stock, capture counted quantities, post variances."""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import CountStatus, CycleCount, CycleCountLine, MovementType, Product, StockLevel, Warehouse, utcnow
from app.services.analytics import compute_metrics
from app.services.inventory import InventoryError, apply_movement, emit_stock_changed, find_warehouse


def create_count(session: Session, warehouse_ref: str | int | None, scope: str = "all", *, actor: str = "user") -> CycleCount:
    warehouse = find_warehouse(session, warehouse_ref)
    scope = scope.upper() if scope.upper() in ("A", "B", "C") else "all"
    levels = session.exec(select(StockLevel).where(StockLevel.warehouse_id == warehouse.id)).all()
    if scope != "all":
        classes = {m.product_id: m.abc_class for m in compute_metrics(session)}
        levels = [lv for lv in levels if classes.get(lv.product_id) == scope]
    if not levels:
        raise InventoryError(f"No stocked products in {warehouse.code} for scope {scope}")
    number = f"CC-{utcnow():%y%m%d}-{session.exec(select(func.count()).select_from(CycleCount)).one() + 1:03d}"
    count = CycleCount(number=number, warehouse_id=warehouse.id, scope=scope, created_by=actor)
    for lv in levels:
        count.lines.append(CycleCountLine(product_id=lv.product_id, expected=lv.quantity))
    session.add(count)
    session.commit()
    session.refresh(count)
    bus.emit("count.created", {"number": count.number, "warehouse": warehouse.code, "lines": len(count.lines)}, source=actor)
    return count


def record_counts(session: Session, count: CycleCount, counts: dict[int, int | None]) -> CycleCount:
    if count.status != CountStatus.OPEN:
        raise InventoryError(f"{count.number} is {count.status}")
    lines = {ln.id: ln for ln in count.lines}
    for line_id, counted in counts.items():
        line = lines.get(int(line_id))
        if line is None:
            raise InventoryError(f"Line {line_id} is not part of {count.number}")
        if counted is not None and counted < 0:
            raise InventoryError("Counted quantity cannot be negative")
        line.counted = counted
        session.add(line)
    session.commit()
    return count


def post_count(session: Session, count: CycleCount, *, actor: str = "user") -> CycleCount:
    if count.status != CountStatus.OPEN:
        raise InventoryError(f"{count.number} is {count.status}")
    warehouse = session.get(Warehouse, count.warehouse_id)
    posted = []
    for line in count.lines:
        if line.counted is None or line.counted == line.expected:
            continue
        product = session.get(Product, line.product_id)
        mv = apply_movement(
            session,
            product,
            warehouse,
            MovementType.ADJUSTMENT,
            line.counted - line.expected,
            actor=actor,
            reference=count.number,
            note=f"Cycle count variance ({line.expected} → {line.counted})",
            commit=False,
        )
        posted.append((product, mv))
    count.status = CountStatus.POSTED
    count.posted_at = utcnow()
    session.add(count)
    session.commit()
    for product, mv in posted:
        session.refresh(mv)
        emit_stock_changed(session, product, warehouse, mv)
    bus.emit("count.posted", count_summary(session, count), source=actor)
    return count


def count_summary(session: Session, count: CycleCount) -> dict:
    warehouse = session.get(Warehouse, count.warehouse_id)
    lines = []
    for ln in count.lines:
        product = session.get(Product, ln.product_id)
        variance = None if ln.counted is None else ln.counted - ln.expected
        lines.append(
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "sku": product.sku,
                "name": product.name,
                "expected": ln.expected,
                "counted": ln.counted,
                "variance": variance,
                "variance_value": round(variance * product.unit_cost, 2) if variance is not None else None,
            }
        )
    counted = [ln for ln in lines if ln["counted"] is not None]
    return {
        "id": count.id,
        "number": count.number,
        "status": count.status,
        "scope": count.scope,
        "warehouse": {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name},
        "created_by": count.created_by,
        "created_at": count.created_at.isoformat(),
        "posted_at": count.posted_at.isoformat() if count.posted_at else None,
        "lines": sorted(lines, key=lambda ln: ln["sku"]),
        "progress": {"counted": len(counted), "total": len(lines)},
        "net_variance_units": sum(ln["variance"] for ln in counted),
        "net_variance_value": round(sum(ln["variance_value"] for ln in counted), 2),
        "accuracy_pct": round(sum(1 for ln in counted if ln["variance"] == 0) / len(counted) * 100, 1) if counted else None,
    }
