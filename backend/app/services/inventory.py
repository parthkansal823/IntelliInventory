"""Stock operations. Every mutation writes a StockMovement and emits `stock.changed`."""

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import MovementType, Product, StockLevel, StockMovement, Warehouse


class InventoryError(ValueError):
    pass


def find_product(session: Session, ref: str | int) -> Product:
    """Resolve a product by id, SKU (case-insensitive) or exact name."""
    product = None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        product = session.get(Product, int(ref))
    if product is None and isinstance(ref, str):
        key = ref.strip()
        product = session.exec(select(Product).where(func.upper(Product.sku) == key.upper())).first()
        if product is None:
            product = session.exec(select(Product).where(func.lower(Product.name) == key.lower())).first()
    if product is None:
        raise InventoryError(f"Product '{ref}' not found")
    return product


def find_warehouse(session: Session, ref: str | int | None) -> Warehouse:
    if ref in (None, ""):
        wh = session.exec(select(Warehouse).order_by(Warehouse.id)).first()
    elif isinstance(ref, int) or str(ref).isdigit():
        wh = session.get(Warehouse, int(ref))
    else:
        wh = session.exec(select(Warehouse).where(func.upper(Warehouse.code) == str(ref).upper())).first()
    if wh is None:
        raise InventoryError(f"Warehouse '{ref}' not found")
    return wh


def on_hand(session: Session, product_id: int) -> int:
    total = session.exec(select(func.sum(StockLevel.quantity)).where(StockLevel.product_id == product_id)).one()
    return int(total or 0)


def on_hand_map(session: Session) -> dict[int, int]:
    rows = session.exec(select(StockLevel.product_id, func.sum(StockLevel.quantity)).group_by(StockLevel.product_id))
    return {pid: int(q or 0) for pid, q in rows}


def stock_by_warehouse(session: Session, product_id: int) -> list[dict]:
    rows = session.exec(
        select(Warehouse, StockLevel)
        .join(StockLevel, StockLevel.warehouse_id == Warehouse.id)
        .where(StockLevel.product_id == product_id)
        .order_by(Warehouse.id)
    )
    return [{"warehouse_id": w.id, "code": w.code, "name": w.name, "quantity": sl.quantity} for w, sl in rows]


def apply_movement(
    session: Session,
    product: Product,
    warehouse: Warehouse,
    type: MovementType,
    quantity: int,
    *,
    actor: str = "user",
    reference: str | None = None,
    note: str | None = None,
    created_at: datetime | None = None,
    commit: bool = True,
) -> StockMovement:
    """Apply a signed quantity change to one product/warehouse bucket."""
    if quantity == 0:
        raise InventoryError("Quantity must be non-zero")
    level = session.get(StockLevel, (product.id, warehouse.id))
    if level is None:
        level = StockLevel(product_id=product.id, warehouse_id=warehouse.id, quantity=0)
    if level.quantity + quantity < 0:
        raise InventoryError(f"Insufficient stock for {product.sku} in {warehouse.code}: have {level.quantity}, need {-quantity}")
    level.quantity += quantity
    movement = StockMovement(
        product_id=product.id,
        warehouse_id=warehouse.id,
        type=type,
        quantity=quantity,
        actor=actor,
        reference=reference,
        note=note,
        **({"created_at": created_at} if created_at else {}),
    )
    session.add(level)
    session.add(movement)
    if commit:
        session.commit()
        session.refresh(movement)
        emit_stock_changed(session, product, warehouse, movement)
    return movement


def emit_stock_changed(session: Session, product: Product, warehouse: Warehouse, movement: StockMovement) -> None:
    bus.emit(
        "stock.changed",
        {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "warehouse": warehouse.code,
            "type": movement.type,
            "delta": movement.quantity,
            "on_hand": on_hand(session, product.id),
            "actor": movement.actor,
            "reference": movement.reference,
        },
        source=movement.actor,
    )


def adjust_stock(
    session: Session,
    product_ref: str | int,
    delta: int,
    *,
    warehouse_ref: str | int | None = None,
    reason: str | None = None,
    actor: str = "user",
    type: MovementType = MovementType.ADJUSTMENT,
) -> StockMovement:
    product = find_product(session, product_ref)
    warehouse = (
        find_warehouse(session, warehouse_ref) if warehouse_ref not in (None, "") else primary_warehouse(session, product.id)
    )
    return apply_movement(session, product, warehouse, type, delta, actor=actor, note=reason)


def primary_warehouse(session: Session, product_id: int) -> Warehouse:
    """The warehouse holding the most stock of a product (default for unqualified movements)."""
    level = session.exec(
        select(StockLevel).where(StockLevel.product_id == product_id).order_by(StockLevel.quantity.desc())
    ).first()
    return session.get(Warehouse, level.warehouse_id) if level else find_warehouse(session, None)


def transfer_stock(
    session: Session, product_ref: str | int, qty: int, from_ref: str | int, to_ref: str | int, *, actor: str = "user"
) -> tuple[StockMovement, StockMovement]:
    if qty <= 0:
        raise InventoryError("Transfer quantity must be positive")
    product = find_product(session, product_ref)
    src, dst = find_warehouse(session, from_ref), find_warehouse(session, to_ref)
    if src.id == dst.id:
        raise InventoryError("Source and destination warehouses must differ")
    ref = f"TRF-{product.sku}-{src.code}-{dst.code}"
    out = apply_movement(session, product, src, MovementType.TRANSFER_OUT, -qty, actor=actor, reference=ref, commit=False)
    inn = apply_movement(session, product, dst, MovementType.TRANSFER_IN, qty, actor=actor, reference=ref, commit=False)
    session.commit()
    for wh, mv in ((src, out), (dst, inn)):
        session.refresh(mv)
        emit_stock_changed(session, product, wh, mv)
    return out, inn
