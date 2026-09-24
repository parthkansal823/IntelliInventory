"""Purchase-order lifecycle: draft -> approved -> ordered -> received (or cancelled)."""

from datetime import timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import (
    MovementType,
    POStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    Warehouse,
    utcnow,
)
from app.services.inventory import InventoryError, apply_movement, emit_stock_changed, find_warehouse

TRANSITIONS: dict[POStatus, set[POStatus]] = {
    POStatus.DRAFT: {POStatus.APPROVED, POStatus.CANCELLED},
    POStatus.APPROVED: {POStatus.ORDERED, POStatus.CANCELLED},
    POStatus.ORDERED: {POStatus.RECEIVED, POStatus.CANCELLED},
    POStatus.RECEIVED: set(),
    POStatus.CANCELLED: set(),
}
OPEN_STATUSES = (POStatus.DRAFT, POStatus.APPROVED, POStatus.ORDERED)


def next_po_number(session: Session) -> str:
    year = utcnow().year
    count = session.exec(select(func.count()).select_from(PurchaseOrder)).one()
    return f"PO-{year}-{count + 1:04d}"


def find_po(session: Session, ref: str | int) -> PurchaseOrder:
    po = None
    if isinstance(ref, int) or str(ref).isdigit():
        po = session.get(PurchaseOrder, int(ref))
    if po is None:
        po = session.exec(select(PurchaseOrder).where(func.upper(PurchaseOrder.number) == str(ref).upper())).first()
    if po is None:
        raise InventoryError(f"Purchase order '{ref}' not found")
    return po


def create_po(
    session: Session,
    lines: list[tuple[Product, int]],
    *,
    supplier_id: int | None = None,
    warehouse_ref: str | int | None = None,
    created_by: str = "user",
    notes: str | None = None,
) -> PurchaseOrder:
    if not lines:
        raise InventoryError("A purchase order needs at least one line")
    supplier_id = supplier_id or lines[0][0].supplier_id
    supplier = session.get(Supplier, supplier_id) if supplier_id else None
    if supplier is None:
        raise InventoryError("Supplier not found")
    warehouse = find_warehouse(session, warehouse_ref)
    po = PurchaseOrder(
        number=next_po_number(session),
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        created_by=created_by,
        notes=notes,
        expected_at=utcnow() + timedelta(days=supplier.lead_time_days),
    )
    for product, qty in lines:
        if qty <= 0:
            raise InventoryError(f"Quantity for {product.sku} must be positive")
        qty = max(qty, product.min_order_qty)
        po.lines.append(PurchaseOrderLine(product_id=product.id, quantity=qty, unit_cost=product.unit_cost))
    session.add(po)
    session.commit()
    session.refresh(po)
    bus.emit("po.created", po_summary(session, po), source=created_by)
    return po


def set_status(session: Session, po: PurchaseOrder, status: POStatus, *, actor: str = "user") -> PurchaseOrder:
    if status == POStatus.RECEIVED:
        return receive_po(session, po, actor=actor)
    if status not in TRANSITIONS[po.status]:
        raise InventoryError(f"Cannot move {po.number} from {po.status} to {status}")
    previous = po.status
    po.status = status
    session.add(po)
    session.commit()
    bus.emit("po.status_changed", {**po_summary(session, po), "from": previous, "to": status}, source=actor)
    return po


def receive_po(session: Session, po: PurchaseOrder, *, actor: str = "user") -> PurchaseOrder:
    if POStatus.RECEIVED not in TRANSITIONS[po.status]:
        raise InventoryError(f"{po.number} must be ordered before it can be received (status: {po.status})")
    warehouse = session.get(Warehouse, po.warehouse_id)
    movements = []
    for line in po.lines:
        product = session.get(Product, line.product_id)
        mv = apply_movement(
            session,
            product,
            warehouse,
            MovementType.RECEIPT,
            line.quantity,
            actor=actor,
            reference=po.number,
            commit=False,
        )
        movements.append((product, mv))
    po.status = POStatus.RECEIVED
    po.received_at = utcnow()
    session.add(po)
    session.commit()
    for product, mv in movements:
        session.refresh(mv)
        emit_stock_changed(session, product, warehouse, mv)
    bus.emit("po.received", po_summary(session, po), source=actor)
    return po


def on_order_map(session: Session, statuses=(POStatus.APPROVED, POStatus.ORDERED)) -> dict[int, int]:
    rows = session.exec(
        select(PurchaseOrderLine.product_id, func.sum(PurchaseOrderLine.quantity))
        .join(PurchaseOrder)
        .where(PurchaseOrder.status.in_(statuses))
        .group_by(PurchaseOrderLine.product_id)
    )
    return {pid: int(q or 0) for pid, q in rows}


def po_summary(session: Session, po: PurchaseOrder) -> dict:
    supplier = session.get(Supplier, po.supplier_id)
    warehouse = session.get(Warehouse, po.warehouse_id)
    lines = []
    for line in po.lines:
        product = session.get(Product, line.product_id)
        lines.append(
            {
                "id": line.id,
                "product_id": line.product_id,
                "sku": product.sku if product else None,
                "name": product.name if product else None,
                "quantity": line.quantity,
                "unit_cost": line.unit_cost,
                "total": round(line.quantity * line.unit_cost, 2),
            }
        )
    from app.services.india import po_tax, upi_link  # local import avoids a cycle

    tax = po_tax(session, po)
    for item in lines:
        item.update(tax["lines"].get(item["id"], {}))
    return {
        "id": po.id,
        "number": po.number,
        "status": po.status,
        "supplier": {
            "id": supplier.id,
            "name": supplier.name,
            "phone": supplier.phone,
            "gstin": supplier.gstin,
            "state": supplier.state,
            "upi_id": supplier.upi_id,
        }
        if supplier
        else None,
        "warehouse": {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name} if warehouse else None,
        "created_by": po.created_by,
        "notes": po.notes,
        "created_at": po.created_at.isoformat(),
        "expected_at": po.expected_at.isoformat() if po.expected_at else None,
        "received_at": po.received_at.isoformat() if po.received_at else None,
        "lines": lines,
        "total": round(sum(item["total"] for item in lines), 2),
        "units": sum(item["quantity"] for item in lines),
        "tax": {k: v for k, v in tax.items() if k != "lines"},
        "grand_total": tax["grand_total"],
        "upi_link": upi_link(supplier.upi_id, supplier.name, tax["grand_total"], f"PO {po.number}")
        if supplier and supplier.upi_id
        else None,
    }
