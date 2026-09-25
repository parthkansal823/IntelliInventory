"""Products, categories, suppliers, warehouses."""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import func, select

from app.hooks.bus import bus
from app.models import Category, MovementType, Product, StockMovement, Supplier, Warehouse, ist_today
from app.security import CurrentUser, DbSession, ManagerUser, actor
from app.services import analytics, india, inventory

router = APIRouter(prefix="/api", tags=["catalog"])


class ProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category_id: int | None = None
    supplier_id: int | None = None
    unit_cost: float = Field(ge=0, default=0)
    unit_price: float = Field(ge=0, default=0)
    reorder_point: int | None = Field(default=None, ge=0)
    safety_stock: int | None = Field(default=None, ge=0)
    min_order_qty: int = Field(default=1, ge=1)
    lead_time_days: int | None = Field(default=None, ge=1)
    hsn_code: str | None = Field(default=None, max_length=8)
    gst_rate: float | None = Field(default=None, ge=0, le=100)  # optional: AI fills it in later
    barcode: str | None = Field(default=None, max_length=32)
    unit: str = Field(default="pcs", max_length=12)
    expiry_date: date | None = None
    initial_qty: int = Field(default=0, ge=0)
    warehouse_id: int | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category_id: int | None = None
    supplier_id: int | None = None
    unit_cost: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    reorder_point: int | None = Field(default=None, ge=0)
    safety_stock: int | None = Field(default=None, ge=0)
    min_order_qty: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=1)
    hsn_code: str | None = Field(default=None, max_length=8)
    gst_rate: float | None = Field(default=None, ge=0, le=100)
    barcode: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=12)
    expiry_date: date | None = None
    is_active: bool | None = None
    clear_overrides: bool = False


def product_row(p: Product, m: analytics.ProductMetrics | None) -> dict:
    base = {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "category_id": p.category_id,
        "supplier_id": p.supplier_id,
        "unit_cost": p.unit_cost,
        "unit_price": p.unit_price,
        "min_order_qty": p.min_order_qty,
        "is_active": p.is_active,
        "manual_reorder_point": p.reorder_point,
        "manual_safety_stock": p.safety_stock,
        "lead_time_override": p.lead_time_days,
        "hsn_code": p.hsn_code,
        "gst_rate": p.gst_rate,
        "gst_source": p.gst_source,
        "price_incl_gst": round(p.unit_price * (1 + (p.gst_rate or 0) / 100), 2),
        "barcode": p.barcode,
        "unit": p.unit,
        "expiry_date": p.expiry_date.isoformat() if p.expiry_date else None,
        "days_to_expiry": (p.expiry_date - ist_today()).days if p.expiry_date else None,
    }
    if m:
        base.update({k: v for k, v in m.to_dict().items() if k not in ("product_id", "sku", "name", "unit_cost", "unit_price")})
    return base


@router.get("/products")
def list_products(session: DbSession, _: CurrentUser) -> list[dict]:
    metrics = {m.product_id: m for m in analytics.compute_metrics(session)}
    products = session.exec(select(Product).order_by(Product.sku)).all()
    return [product_row(p, metrics.get(p.id)) for p in products]


@router.get("/products/{product_id}")
def get_product(session: DbSession, product_id: int, _: CurrentUser) -> dict:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    m = analytics.metrics_for(session, product_id)
    moves = session.exec(
        select(StockMovement, Warehouse)
        .join(Warehouse)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc())
        .limit(40)
    ).all()
    return {
        **product_row(product, m),
        "warehouses": inventory.stock_by_warehouse(session, product_id),
        "movements": [
            {
                "id": mv.id,
                "created_at": mv.created_at.isoformat(),
                "type": mv.type,
                "quantity": mv.quantity,
                "warehouse": w.code,
                "reference": mv.reference,
                "note": mv.note,
                "actor": mv.actor,
            }
            for mv, w in moves
        ],
        "forecast": analytics.product_forecast(session, product_id, 30) if m else None,
    }


@router.post("/products", status_code=201)
def create_product(session: DbSession, body: ProductIn, user: ManagerUser) -> dict:
    sku = body.sku.strip().upper()
    if session.exec(select(Product).where(func.upper(Product.sku) == sku)).first():
        raise HTTPException(409, f"SKU {sku} already exists")
    data = body.model_dump(exclude={"initial_qty", "warehouse_id"})
    data["sku"] = sku
    data["barcode"] = (body.barcode or "").strip() or None
    if data["barcode"] and session.exec(select(Product).where(Product.barcode == data["barcode"])).first():
        raise HTTPException(409, f"Barcode {data['barcode']} is already used by another product")
    product = Product(**data)
    if product.gst_rate is not None:
        product.gst_source = "manual"
    session.add(product)
    session.commit()
    session.refresh(product)
    bus.emit("product.created", {"id": product.id, "sku": product.sku, "name": product.name}, source=actor(user))
    if body.initial_qty:
        wh = inventory.find_warehouse(session, body.warehouse_id)
        inventory.apply_movement(
            session,
            product,
            wh,
            MovementType.RECEIPT,
            body.initial_qty,
            actor=actor(user),
            reference="INITIAL",
            note="Initial stock",
        )
    return product_row(product, analytics.metrics_for(session, product.id))


@router.patch("/products/{product_id}")
def update_product(session: DbSession, product_id: int, body: ProductPatch, user: ManagerUser) -> dict:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    changes = body.model_dump(exclude_unset=True, exclude={"clear_overrides"})
    if changes.get("barcode"):
        changes["barcode"] = changes["barcode"].strip()
        clash = session.exec(select(Product).where(Product.barcode == changes["barcode"], Product.id != product_id)).first()
        if clash:
            raise HTTPException(409, f"Barcode {changes['barcode']} is already used by {clash.name}")
    for key, value in changes.items():
        setattr(product, key, value)
    if "gst_rate" in changes or "hsn_code" in changes:
        product.gst_source = "manual" if product.gst_rate is not None else None  # a human confirmed/edited it
    if body.clear_overrides:
        product.reorder_point = product.safety_stock = product.lead_time_days = None
    session.add(product)
    session.commit()
    bus.emit("product.updated", {"id": product.id, "sku": product.sku, "changes": list(changes)}, source=actor(user))
    return product_row(product, analytics.metrics_for(session, product.id))


@router.delete("/products/{product_id}")
def archive_product(session: DbSession, product_id: int, user: ManagerUser) -> dict:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    product.is_active = False
    session.add(product)
    session.commit()
    bus.emit("product.archived", {"id": product.id, "sku": product.sku}, source=actor(user))
    return {"archived": True}


# --- reference data ------------------------------------------------------------------


class CategoryIn(BaseModel):
    name: str
    color: str = "#6366f1"


class SupplierIn(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    lead_time_days: int = Field(default=7, ge=1)
    rating: float = Field(default=4.0, ge=0, le=5)
    gstin: str | None = None
    state: str | None = None
    upi_id: str | None = None

    def validated(self) -> dict:
        data = self.model_dump()
        try:
            data["phone"] = india.normalize_phone(self.phone)
            data["state"] = india.normalize_state(self.state)
            data["upi_id"] = india.normalize_upi(self.upi_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if self.gstin and self.gstin.strip():
            ok, info = india.validate_gstin(self.gstin)
            if not ok:
                raise HTTPException(422, f"Invalid GSTIN: {info}")
            data["gstin"] = self.gstin.strip().upper()
            data["state"] = info  # the GSTIN's state code decides CGST+SGST vs IGST
        else:
            data["gstin"] = None
        return data


class WarehouseIn(BaseModel):
    code: str
    name: str
    location: str | None = None
    state: str | None = None


@router.get("/categories")
def list_categories(session: DbSession, _: CurrentUser) -> list[Category]:
    return list(session.exec(select(Category).order_by(Category.name)))


@router.post("/categories", status_code=201)
def create_category(session: DbSession, body: CategoryIn, _: ManagerUser) -> Category:
    cat = Category(**body.model_dump())
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return cat


@router.get("/suppliers")
def list_suppliers(session: DbSession, _: CurrentUser) -> list[Supplier]:
    return list(session.exec(select(Supplier).order_by(Supplier.name)))


@router.post("/suppliers", status_code=201)
def create_supplier(session: DbSession, body: SupplierIn, _: ManagerUser) -> Supplier:
    sup = Supplier(**body.validated())
    session.add(sup)
    session.commit()
    session.refresh(sup)
    return sup


@router.patch("/suppliers/{supplier_id}")
def update_supplier(session: DbSession, supplier_id: int, body: SupplierIn, _: ManagerUser) -> Supplier:
    sup = session.get(Supplier, supplier_id)
    if sup is None:
        raise HTTPException(404, "Supplier not found")
    for k, v in body.validated().items():
        setattr(sup, k, v)
    session.add(sup)
    session.commit()
    return sup


@router.get("/warehouses")
def list_warehouses(session: DbSession, _: CurrentUser) -> list[dict]:
    rows = []
    for w in session.exec(select(Warehouse).order_by(Warehouse.id)):
        from app.models import StockLevel

        units = session.exec(select(func.sum(StockLevel.quantity)).where(StockLevel.warehouse_id == w.id)).one() or 0
        value = (
            session.exec(
                select(func.sum(StockLevel.quantity * Product.unit_cost))
                .join(Product, Product.id == StockLevel.product_id)
                .where(StockLevel.warehouse_id == w.id)
            ).one()
            or 0
        )
        rows.append(
            {
                "id": w.id,
                "code": w.code,
                "name": w.name,
                "location": w.location,
                "state": w.state,
                "units": int(units),
                "value": round(float(value), 2),
            }
        )
    return rows


@router.post("/warehouses", status_code=201)
def create_warehouse(session: DbSession, body: WarehouseIn, _: ManagerUser) -> Warehouse:
    try:
        state = india.normalize_state(body.state)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    wh = Warehouse(code=body.code.upper(), name=body.name, location=body.location, state=state)
    session.add(wh)
    session.commit()
    session.refresh(wh)
    return wh
