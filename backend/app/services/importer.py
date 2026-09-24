"""CSV import (with dry-run preview) and CSV export."""

from __future__ import annotations

import csv
import io

from sqlalchemy import func
from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import Category, MovementType, Product, StockMovement, Supplier, Warehouse
from app.services.analytics import compute_metrics
from app.services.inventory import apply_movement, find_warehouse

IMPORT_COLUMNS = [
    "sku",
    "name",
    "category",
    "supplier",
    "unit_cost",
    "unit_price",
    "min_order_qty",
    "reorder_point",
    "safety_stock",
    "initial_qty",
    "warehouse",
]


def import_products(session: Session, text: str, *, commit: bool, actor: str = "user") -> dict:
    reader = csv.DictReader(io.StringIO(text.strip()))
    missing = {"sku", "name"} - set(reader.fieldnames or [])
    if missing:
        return {"ok": False, "error": f"Missing required columns: {', '.join(sorted(missing))}", "rows": []}

    cats = {c.name.lower(): c for c in session.exec(select(Category))}
    sups = {s.name.lower(): s for s in session.exec(select(Supplier))}
    rows, created, updated = [], 0, 0
    for n, raw in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in raw.items() if k}
        errors: list[str] = []
        sku = row.get("sku", "").upper()
        if not sku:
            errors.append("sku is required")
        if not row.get("name"):
            errors.append("name is required")

        def num(key: str, cast=float, default=None, row=row, errors=errors):
            value = row.get(key, "")
            if value == "":
                return default
            try:
                return cast(value)
            except ValueError:
                errors.append(f"{key} must be a number")
                return default

        cost, price = num("unit_cost", float, 0.0), num("unit_price", float, 0.0)
        moq, rop, ss, qty = (
            num("min_order_qty", int, 1),
            num("reorder_point", int),
            num("safety_stock", int),
            num("initial_qty", int, 0),
        )
        category = cats.get(row.get("category", "").lower()) if row.get("category") else None
        supplier = sups.get(row.get("supplier", "").lower()) if row.get("supplier") else None
        if row.get("supplier") and supplier is None:
            errors.append(f"unknown supplier '{row['supplier']}'")
        existing = session.exec(select(Product).where(func.upper(Product.sku) == sku)).first() if sku else None
        action = "error" if errors else "update" if existing else "create"
        rows.append({"line": n, "sku": sku, "name": row.get("name"), "action": action, "errors": errors})
        if not commit or errors:
            continue

        if category is None and row.get("category"):
            category = Category(name=row["category"])
            session.add(category)
            session.flush()
            cats[category.name.lower()] = category
        product = existing or Product(sku=sku, name=row["name"])
        product.name = row["name"]
        product.unit_cost, product.unit_price, product.min_order_qty = cost, price, moq or 1
        product.reorder_point, product.safety_stock = rop, ss
        product.category_id = category.id if category else product.category_id
        product.supplier_id = supplier.id if supplier else product.supplier_id
        session.add(product)
        session.flush()
        if not existing and qty:
            warehouse = find_warehouse(session, row.get("warehouse") or None)
            apply_movement(
                session,
                product,
                warehouse,
                MovementType.RECEIPT,
                qty,
                actor=actor,
                reference="IMPORT",
                note="Initial quantity from CSV import",
                commit=False,
            )
        created += 0 if existing else 1
        updated += 1 if existing else 0

    if commit:
        session.commit()
        bus.emit("catalog.imported", {"created": created, "updated": updated}, source=actor)
    return {
        "ok": all(r["action"] != "error" for r in rows),
        "committed": commit,
        "summary": {
            "create": sum(r["action"] == "create" for r in rows),
            "update": sum(r["action"] == "update" for r in rows),
            "error": sum(r["action"] == "error" for r in rows),
        },
        "rows": rows,
    }


def export_inventory_csv(session: Session) -> str:
    out = io.StringIO()
    fields = [
        "sku",
        "name",
        "category",
        "supplier",
        "on_hand",
        "on_order",
        "unit_cost",
        "unit_price",
        "stock_value",
        "avg_daily_demand",
        "safety_stock",
        "reorder_point",
        "eoq",
        "days_of_cover",
        "status",
        "abc_class",
        "suggested_order_qty",
    ]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for m in sorted(compute_metrics(session), key=lambda m: m.sku):
        writer.writerow(m.to_dict())
    return out.getvalue()


def export_movements_csv(session: Session, days: int = 30) -> str:
    from datetime import timedelta

    from app.models import utcnow

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["timestamp", "sku", "product", "warehouse", "type", "quantity", "reference", "note", "actor"])
    rows = session.exec(
        select(StockMovement, Product, Warehouse)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
        .where(StockMovement.created_at >= utcnow() - timedelta(days=days))
        .order_by(StockMovement.created_at.desc())
    )
    for mv, p, w in rows:
        writer.writerow(
            [mv.created_at.isoformat(), p.sku, p.name, w.code, mv.type, mv.quantity, mv.reference or "", mv.note or "", mv.actor]
        )
    return out.getvalue()
