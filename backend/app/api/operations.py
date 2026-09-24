"""Stock operations, purchasing, cycle counts, import/export."""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import func, select

from app.models import CycleCount, MovementType, POStatus, Product, PurchaseOrder, StockMovement, Warehouse, utcnow
from app.security import CurrentUser, DbSession, ManagerUser, StaffUser, actor
from app.services import analytics, counts, importer, inventory, purchasing
from app.services.india import transfer_eway

router = APIRouter(prefix="/api", tags=["operations"])


# --- stock ---------------------------------------------------------------------------


class AdjustIn(BaseModel):
    product_id: int
    quantity: int = Field(description="Signed delta")
    warehouse_id: int | None = None
    reason: str | None = None
    type: Literal["adjustment", "receipt", "sale", "return"] = "adjustment"


class TransferIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    from_warehouse_id: int
    to_warehouse_id: int


class ScanIn(BaseModel):
    code: str = Field(description="Scanned barcode / QR payload / SKU")
    action: Literal["lookup", "receive", "sell", "adjust", "return"] = "lookup"
    quantity: int = 1
    warehouse_id: int | None = None


@router.post("/inventory/adjust")
def adjust(session: DbSession, body: AdjustIn, user: StaffUser) -> dict:
    kind = MovementType(body.type)
    qty = (
        -abs(body.quantity)
        if kind == MovementType.SALE
        else abs(body.quantity)
        if kind in (MovementType.RECEIPT, MovementType.RETURN)
        else body.quantity
    )
    mv = inventory.adjust_stock(
        session, body.product_id, qty, warehouse_ref=body.warehouse_id, reason=body.reason, actor=actor(user), type=kind
    )
    return {"movement_id": mv.id, "on_hand": inventory.on_hand(session, body.product_id)}


@router.post("/inventory/transfer")
def transfer(session: DbSession, body: TransferIn, user: StaffUser) -> dict:
    out, inn = inventory.transfer_stock(
        session, body.product_id, body.quantity, body.from_warehouse_id, body.to_warehouse_id, actor=actor(user)
    )
    product = session.get(Product, body.product_id)
    eway = transfer_eway(
        session, product, body.quantity, session.get(Warehouse, out.warehouse_id), session.get(Warehouse, inn.warehouse_id)
    )
    return {"warehouses": inventory.stock_by_warehouse(session, body.product_id), "eway": eway}


@router.post("/inventory/scan")
def scan(session: DbSession, body: ScanIn, user: StaffUser) -> dict:
    """Barcode/QR scan endpoint for the mobile scan mode. Accepts SKU or `ii:<sku>` QR payloads."""
    code = body.code.strip().removeprefix("ii:").removeprefix("II:")
    product = inventory.find_product(session, code)
    result: dict = {"product": {"id": product.id, "sku": product.sku, "name": product.name}}
    if body.action != "lookup":
        if body.quantity <= 0 and body.action != "adjust":
            raise HTTPException(400, "Quantity must be positive")
        qty = {"receive": body.quantity, "return": body.quantity, "sell": -body.quantity, "adjust": body.quantity}[body.action]
        kind = {
            "receive": MovementType.RECEIPT,
            "return": MovementType.RETURN,
            "sell": MovementType.SALE,
            "adjust": MovementType.ADJUSTMENT,
        }[body.action]
        inventory.adjust_stock(
            session, product.id, qty, warehouse_ref=body.warehouse_id, reason=f"Scan: {body.action}", actor=actor(user), type=kind
        )
    m = analytics.metrics_for(session, product.id)
    result.update(
        {
            "on_hand": m.on_hand,
            "status": m.status,
            "reorder_point": m.reorder_point,
            "warehouses": inventory.stock_by_warehouse(session, product.id),
        }
    )
    return result


@router.get("/inventory/movements")
def movements(
    session: DbSession,
    _: CurrentUser,
    product_id: int | None = None,
    type: str | None = None,
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    stmt = (
        select(StockMovement, Product, Warehouse)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
        .where(StockMovement.created_at >= utcnow() - timedelta(days=days))
    )
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if type:
        stmt = stmt.where(StockMovement.type == MovementType(type))
    rows = session.exec(stmt.order_by(StockMovement.created_at.desc()).offset(offset).limit(min(limit, 1000))).all()
    return {
        "items": [
            {
                "id": mv.id,
                "created_at": mv.created_at.isoformat(),
                "product_id": p.id,
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
        ]
    }


@router.get("/inventory/export.csv", response_class=PlainTextResponse)
def export_inventory(session: DbSession, _: CurrentUser) -> PlainTextResponse:
    return PlainTextResponse(
        importer.export_inventory_csv(session),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


@router.get("/inventory/movements.csv", response_class=PlainTextResponse)
def export_movements(session: DbSession, _: CurrentUser, days: int = 30) -> PlainTextResponse:
    return PlainTextResponse(
        importer.export_movements_csv(session, days),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=movements.csv"},
    )


class ImportIn(BaseModel):
    csv: str
    commit: bool = False


@router.post("/inventory/import")
def import_csv(session: DbSession, body: ImportIn, user: ManagerUser) -> dict:
    return importer.import_products(session, body.csv, commit=body.commit, actor=actor(user))


@router.get("/inventory/import-template.csv", response_class=PlainTextResponse)
def import_template(_: CurrentUser) -> PlainTextResponse:
    sample = (
        ",".join(importer.IMPORT_COLUMNS) + "\nNEW-0001,Sample Product,Accessories,Pacific Components,4.5,12.99,10,,,100,MAIN\n"
    )
    return PlainTextResponse(
        sample, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=import-template.csv"}
    )


# --- purchasing ------------------------------------------------------------------------


class POLineIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class POIn(BaseModel):
    lines: list[POLineIn] = Field(min_length=1)
    supplier_id: int | None = None
    warehouse_id: int | None = None
    notes: str | None = None


class POStatusIn(BaseModel):
    status: POStatus


class FromRecsIn(BaseModel):
    product_ids: list[int] | None = None


@router.get("/purchase-orders")
def list_pos(session: DbSession, _: CurrentUser, status: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if status == "open":
        stmt = stmt.where(PurchaseOrder.status.in_(purchasing.OPEN_STATUSES))
    elif status:
        stmt = stmt.where(PurchaseOrder.status == POStatus(status))
    return [purchasing.po_summary(session, po) for po in session.exec(stmt.limit(limit))]


@router.get("/purchase-orders/stats")
def po_stats(session: DbSession, _: CurrentUser) -> dict:
    rows = session.exec(select(PurchaseOrder.status, func.count()).group_by(PurchaseOrder.status)).all()
    return {status: n for status, n in rows}


@router.get("/purchase-orders/{po_id}")
def get_po(session: DbSession, po_id: int, _: CurrentUser) -> dict:
    return purchasing.po_summary(session, purchasing.find_po(session, po_id))


@router.post("/purchase-orders", status_code=201)
def create_po(session: DbSession, body: POIn, user: StaffUser) -> dict:
    lines = [(inventory.find_product(session, ln.product_id), ln.quantity) for ln in body.lines]
    po = purchasing.create_po(
        session, lines, supplier_id=body.supplier_id, warehouse_ref=body.warehouse_id, created_by=actor(user), notes=body.notes
    )
    return purchasing.po_summary(session, po)


@router.post("/purchase-orders/from-recommendations", status_code=201)
def create_from_recs(session: DbSession, body: FromRecsIn, user: StaffUser) -> list[dict]:
    """One draft PO per supplier from current reorder recommendations."""
    recs = analytics.reorder_recommendations(session, 200)
    if body.product_ids:
        recs = [r for r in recs if r["product_id"] in body.product_ids]
    by_supplier: dict[int, list] = {}
    for r in recs:
        if r["supplier_id"]:
            by_supplier.setdefault(r["supplier_id"], []).append(r)
    created = []
    for supplier_id, items in by_supplier.items():
        lines = [(session.get(Product, r["product_id"]), r["suggested_order_qty"]) for r in items]
        po = purchasing.create_po(
            session, lines, supplier_id=supplier_id, created_by=actor(user), notes="Generated from reorder recommendations"
        )
        created.append(purchasing.po_summary(session, po))
    if not created:
        raise HTTPException(400, "Nothing to reorder")
    return created


@router.post("/purchase-orders/{po_id}/status")
def set_po_status(session: DbSession, po_id: int, body: POStatusIn, user: ManagerUser) -> dict:
    po = purchasing.set_status(session, purchasing.find_po(session, po_id), body.status, actor=actor(user))
    session.refresh(po)
    return purchasing.po_summary(session, po)


# --- cycle counts ------------------------------------------------------------------------


class CountIn(BaseModel):
    warehouse_id: int
    scope: Literal["all", "A", "B", "C"] = "all"


class CountEntriesIn(BaseModel):
    counts: dict[int, int | None]


@router.get("/counts")
def list_counts(session: DbSession, _: CurrentUser) -> list[dict]:
    rows = session.exec(select(CycleCount).order_by(CycleCount.created_at.desc()).limit(50)).all()
    out = []
    for c in rows:
        summary = counts.count_summary(session, c)
        summary.pop("lines")
        out.append(summary)
    return out


@router.post("/counts", status_code=201)
def create_count(session: DbSession, body: CountIn, user: StaffUser) -> dict:
    return counts.count_summary(session, counts.create_count(session, body.warehouse_id, body.scope, actor=actor(user)))


@router.get("/counts/{count_id}")
def get_count(session: DbSession, count_id: int, _: CurrentUser) -> dict:
    count = session.get(CycleCount, count_id)
    if count is None:
        raise HTTPException(404, "Count not found")
    return counts.count_summary(session, count)


@router.put("/counts/{count_id}")
def record(session: DbSession, count_id: int, body: CountEntriesIn, _: StaffUser) -> dict:
    count = session.get(CycleCount, count_id)
    if count is None:
        raise HTTPException(404, "Count not found")
    return counts.count_summary(session, counts.record_counts(session, count, body.counts))


@router.post("/counts/{count_id}/post")
def post(session: DbSession, count_id: int, user: ManagerUser) -> dict:
    count = session.get(CycleCount, count_id)
    if count is None:
        raise HTTPException(404, "Count not found")
    return counts.count_summary(session, counts.post_count(session, count, actor=actor(user)))
