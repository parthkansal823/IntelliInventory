"""Deterministic demo data: catalog, users, and 120 days of realistic history.

History is generated *backwards* from a chosen end state per product, so the
stock trajectory is always non-negative and every scenario the product is
meant to demonstrate (low stock, stockout, overstock, demand spike, shrinkage,
demand collapse) is guaranteed to be present on "today".
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, time, timedelta

from sqlmodel import Session, func, select

from app.config import get_settings
from app.models import (
    Category,
    MovementType,
    POStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    StockLevel,
    StockMovement,
    Supplier,
    User,
    Warehouse,
    utcnow,
)
from app.security import hash_password

DAYS = 120

CATEGORIES = [
    ("Electronics", "#6366f1"),
    ("Accessories", "#0ea5e9"),
    ("Office Supplies", "#f59e0b"),
    ("Home & Kitchen", "#10b981"),
    ("Health & Beauty", "#ec4899"),
    ("Sports & Outdoors", "#84cc16"),
    ("Groceries", "#f97316"),
    ("Toys & Games", "#a855f7"),
]

SUPPLIERS = [
    ("TechSource Global", "orders@techsource.example", "+1 415 555 0101", 10, 4.6),
    ("Pacific Components", "sales@pacific-comp.example", "+1 206 555 0144", 14, 4.1),
    ("OfficeHub Wholesale", "b2b@officehub.example", "+1 312 555 0190", 5, 4.4),
    ("HomeGoods Direct", "supply@homegoods.example", "+1 646 555 0123", 7, 3.9),
    ("FreshFarm Distributors", "orders@freshfarm.example", "+1 503 555 0177", 3, 4.8),
    ("PlayWorld Imports", "trade@playworld.example", "+1 213 555 0165", 21, 3.7),
]

WAREHOUSES = [
    ("MAIN", "Central DC", "Mumbai"),
    ("NORTH", "North Hub", "Delhi"),
    ("SOUTH", "South Hub", "Bengaluru"),
]

# sku, name, category, supplier, unit cost, unit price, base daily demand, MOQ, scenario, trend
PRODUCTS = [
    ("ELC-1001", "Wireless Earbuds Pro", 0, 0, 28.0, 59.0, 14, 10, "low", 0.2),
    ("ELC-1002", "Smart Watch S2", 0, 0, 65.0, 129.0, 6, 5, "shrinkage", 0.1),
    ("ELC-1003", "Bluetooth Speaker Mini", 0, 0, 18.0, 39.0, 9, 10, "spike", 0.0),
    ("ELC-1004", "4K Action Camera", 0, 0, 95.0, 189.0, 2, 2, "out", 0.1),
    ("ELC-1005", "Noise-Cancelling Headphones", 0, 0, 110.0, 229.0, 4, 2, "healthy", 0.5),
    ("ELC-1006", "Portable SSD 1TB", 0, 0, 55.0, 99.0, 5, 5, "healthy", 0.2),
    ("ACC-2001", "USB-C Fast Charger 65W", 1, 1, 9.0, 24.0, 22, 20, "critical", 0.3),
    ("ACC-2002", "Braided USB-C Cable 2m", 1, 1, 2.5, 9.0, 40, 50, "healthy", 0.1),
    ("ACC-2003", "Wireless Charging Pad", 1, 1, 7.0, 19.0, 11, 10, "healthy", 0.0),
    ("ACC-2004", 'Laptop Sleeve 14"', 1, 1, 8.0, 25.0, 7, 10, "healthy", -0.1),
    ("ACC-2005", "Power Bank 20000mAh", 1, 1, 16.0, 39.0, 12, 10, "healthy", 0.45),
    ("OFF-3001", "A4 Copy Paper (500 sheets)", 2, 2, 3.2, 6.5, 35, 50, "low", 0.0),
    ("OFF-3002", "Gel Pens (Pack of 10)", 2, 2, 2.1, 5.99, 18, 20, "healthy", -0.3),
    ("OFF-3003", "Ergonomic Office Chair", 2, 2, 120.0, 249.0, 1.2, 1, "healthy", 0.1),
    ("OFF-3004", "Standing Desk Converter", 2, 2, 90.0, 179.0, 0.8, 1, "overstock", 0.0),
    ("OFF-3005", "Sticky Notes Mega Pack", 2, 2, 1.8, 4.99, 20, 25, "healthy", 0.0),
    ("HOM-4001", "Stainless Steel Water Bottle", 3, 3, 6.0, 18.0, 16, 12, "healthy", 0.25),
    ("HOM-4002", "Ceramic Coffee Mug Set", 3, 3, 9.0, 24.0, 6, 6, "overstock", -0.1),
    ("HOM-4003", "Non-Stick Frying Pan 28cm", 3, 3, 14.0, 34.0, 5, 5, "healthy", 0.0),
    ("HOM-4004", "Air Fryer 5L", 3, 3, 48.0, 99.0, 3, 2, "low_on_order", 0.35),
    ("HOM-4005", "Bamboo Cutting Board", 3, 3, 5.0, 15.0, 7, 10, "healthy", 0.0),
    ("HLT-5001", "Hand Sanitizer 500ml", 4, 3, 1.5, 4.5, 25, 24, "spike", 0.0),
    ("HLT-5002", "Vitamin C Serum", 4, 3, 6.0, 22.0, 8, 12, "healthy", 0.3),
    ("HLT-5003", "Electric Toothbrush", 4, 3, 22.0, 49.0, 4, 4, "healthy", 0.1),
    ("SPT-6001", "Yoga Mat Premium", 5, 5, 9.0, 29.0, 8, 10, "low", 0.2),
    ("SPT-6002", "Adjustable Dumbbells 20kg", 5, 5, 55.0, 119.0, 2, 2, "healthy", 0.0),
    ("SPT-6003", "Running Socks (3-pack)", 5, 5, 3.0, 12.0, 15, 20, "healthy", 0.1),
    ("SPT-6004", "Insulated Sports Flask", 5, 5, 7.0, 21.0, 6, 10, "healthy", 0.0),
    ("GRC-7001", "Organic Green Tea (100 bags)", 6, 4, 3.5, 8.99, 20, 24, "healthy", 0.1),
    ("GRC-7002", "Arabica Coffee Beans 1kg", 6, 4, 11.0, 24.0, 12, 10, "critical", 0.2),
    ("GRC-7003", "Almonds 500g", 6, 4, 6.0, 13.0, 14, 12, "out", 0.0),
    ("GRC-7004", "Dark Chocolate 70% Bar", 6, 4, 1.1, 3.49, 30, 48, "shrinkage", 0.0),
    ("GRC-7005", "Protein Bars (Box of 12)", 6, 4, 12.0, 27.0, 9, 6, "healthy", 0.4),
    ("TOY-8001", "Building Blocks Set 500pc", 7, 5, 18.0, 45.0, 4, 4, "healthy", 0.0),
    ("TOY-8002", "RC Racing Car", 7, 5, 22.0, 55.0, 3, 4, "overstock", -0.2),
    ("TOY-8003", "Jigsaw Puzzle 1000pc", 7, 5, 7.0, 19.0, 5, 6, "drop", 0.0),
    ("TOY-8004", "Plush Teddy Bear", 7, 5, 6.0, 18.0, 6, 12, "healthy", 0.1),
]

WEEKLY = {
    "retail": [0.85, 0.88, 0.9, 0.95, 1.1, 1.35, 1.25],
    "office": [1.2, 1.15, 1.15, 1.1, 1.0, 0.45, 0.35],
    "grocery": [0.95, 0.95, 0.95, 1.0, 1.05, 1.2, 1.15],
}

USERS = [
    ("admin@intelliinventory.dev", "Aarav Admin", Role.ADMIN),
    ("manager@intelliinventory.dev", "Meera Manager", Role.MANAGER),
    ("staff@intelliinventory.dev", "Sam Staff", Role.STAFF),
    ("viewer@intelliinventory.dev", "Vik Viewer", Role.VIEWER),
]


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def seed_users(session: Session) -> None:
    if session.exec(select(func.count()).select_from(User)).one():
        return
    pw = hash_password(get_settings().demo_password)
    for email, name, role in USERS:
        session.add(User(email=email, name=name, role=role, password_hash=pw))
    session.commit()


def seed_demo(session: Session) -> bool:
    """Populate an empty database. Returns True when data was created."""
    seed_users(session)
    if session.exec(select(func.count()).select_from(Product)).one():
        return False

    rng = random.Random(42)
    today = utcnow().date()

    cats = [Category(name=n, color=c) for n, c in CATEGORIES]
    sups = [Supplier(name=n, email=e, phone=p, lead_time_days=lt, rating=r) for n, e, p, lt, r in SUPPLIERS]
    whs = [Warehouse(code=c, name=n, location=loc) for c, n, loc in WAREHOUSES]
    session.add_all(cats + sups + whs)
    session.commit()

    movements: list[StockMovement] = []
    levels: dict[tuple[int, int], int] = {}
    received_pos: list[tuple[PurchaseOrder, PurchaseOrderLine, StockMovement]] = []
    open_pos: list[tuple[Product, Supplier, int, POStatus]] = []

    def at(day_index: int, hour: int | None = None) -> datetime:
        d = today - timedelta(days=DAYS - 1 - day_index)
        return datetime.combine(d, time(hour if hour is not None else rng.randint(9, 20), rng.randint(0, 59)), tzinfo=UTC)

    for i, (sku, name, ci, si, cost, price, base, moq, scenario, trend) in enumerate(PRODUCTS):
        supplier = sups[si]
        lead = supplier.lead_time_days
        home = whs[0] if i % 5 < 3 else whs[1] if i % 5 == 3 else whs[2]
        product = Product(
            sku=sku,
            name=name,
            category_id=cats[ci].id,
            supplier_id=supplier.id,
            unit_cost=cost,
            unit_price=price,
            min_order_qty=moq,
            description=f"{name} — {CATEGORIES[ci][0].lower()} item supplied by {supplier.name}.",
            created_at=at(0, 8) - timedelta(days=1),
        )
        session.add(product)
        session.flush()

        profile = WEEKLY["office" if ci == 2 else "grocery" if ci == 6 else "retail"]
        sales = []
        for d in range(DAYS):
            day = today - timedelta(days=DAYS - 1 - d)
            lam = base * profile[day.weekday()] * (1 + trend * d / DAYS)
            if scenario == "spike" and d >= DAYS - 2:
                lam *= 6
            if scenario == "drop" and d >= DAYS - 7:
                lam *= 0.1
            sales.append(_poisson(rng, lam))
        if scenario == "out":
            for d in range(DAYS - 3, DAYS):
                sales[d] = 0  # nothing left to sell

        shrink = {DAYS - 3: round(base * 2.5) + 6} if scenario == "shrinkage" else {}

        cover = {
            "healthy": lead + rng.uniform(14, 35),
            "spike": lead + 25,
            "drop": lead + 30,
            "shrinkage": lead + 12,
            "low": lead * 0.7,
            "low_on_order": lead * 0.6,
            "critical": 0.5,
            "out": 0.0,
            "overstock": lead + 170,
        }[scenario]
        end_stock = max(0, math.ceil(base * (1 + trend) * cover)) if scenario != "out" else 0
        if scenario == "overstock":
            end_stock = max(end_stock, 150)

        cap = base * (lead + 40) + moq
        stock = end_stock
        receipts: dict[int, int] = {}
        for d in range(DAYS - 1, -1, -1):
            before = stock + sales[d] + shrink.get(d, 0)
            no_receipt_window = scenario == "overstock" and d > DAYS - 12
            if before > cap and not no_receipt_window and d > 2:
                floor_level = rng.uniform(base * 1.5, base * max(lead * 0.8, 2))
                qty = int((before - floor_level) // moq * moq)
                if qty > 0:
                    receipts[d] = qty
                    before -= qty
            stock = before
        opening = stock

        if opening:
            movements.append(
                StockMovement(
                    product_id=product.id,
                    warehouse_id=home.id,
                    type=MovementType.RECEIPT,
                    quantity=opening,
                    reference="OPENING",
                    note="Opening balance",
                    actor="system:seed",
                    created_at=at(0, 7) - timedelta(days=1),
                )
            )
        for d in range(DAYS):
            if d in receipts:
                ts = at(d, 8)
                jitter = rng.choice([-1, 0, 0, 0, 0, 0, 1] if supplier.rating >= 4.4 else [-1, 0, 0, 1, 2, 3])
                created = ts - timedelta(days=lead + jitter)
                po = PurchaseOrder(
                    number="",
                    supplier_id=supplier.id,
                    warehouse_id=home.id,
                    status=POStatus.RECEIVED,
                    created_by="user:manager@intelliinventory.dev",
                    created_at=created,
                    expected_at=created + timedelta(days=lead),
                    received_at=ts,
                )
                line = PurchaseOrderLine(product_id=product.id, quantity=receipts[d], unit_cost=cost)
                mv = StockMovement(
                    product_id=product.id,
                    warehouse_id=home.id,
                    type=MovementType.RECEIPT,
                    quantity=receipts[d],
                    actor="system:seed",
                    created_at=ts,
                )
                received_pos.append((po, line, mv))
                movements.append(mv)
            if sales[d]:
                movements.append(
                    StockMovement(
                        product_id=product.id,
                        warehouse_id=home.id,
                        type=MovementType.SALE,
                        quantity=-sales[d],
                        reference="POS",
                        actor="system:pos",
                        created_at=at(d),
                    )
                )
            if d in shrink:
                note = "Unexplained variance found during shelf check" if ci == 0 else "Expired stock written off"
                movements.append(
                    StockMovement(
                        product_id=product.id,
                        warehouse_id=home.id,
                        type=MovementType.ADJUSTMENT,
                        quantity=-shrink[d],
                        note=note,
                        actor="user:staff@intelliinventory.dev",
                        created_at=at(d),
                    )
                )
        levels[(product.id, home.id)] = end_stock

        # Some products also hold a small static buffer in another warehouse.
        if i % 3 == 0 and scenario not in ("out", "critical"):
            other = whs[(whs.index(home) + 1) % len(whs)]
            buffer_qty = max(2, round(base * 3))
            levels[(product.id, other.id)] = buffer_qty
            movements.append(
                StockMovement(
                    product_id=product.id,
                    warehouse_id=other.id,
                    type=MovementType.RECEIPT,
                    quantity=buffer_qty,
                    reference="OPENING",
                    note="Opening balance",
                    actor="system:seed",
                    created_at=at(0, 7) - timedelta(days=1),
                )
            )

        if scenario == "low_on_order":
            open_pos.append((product, supplier, max(moq, math.ceil(base * 30 / moq) * moq), POStatus.ORDERED))
        elif scenario == "healthy" and i % 4 == 1:
            open_pos.append(
                (product, supplier, max(moq, math.ceil(base * 20 / moq) * moq), [POStatus.APPROVED, POStatus.ORDERED][i % 2])
            )

    session.add_all(movements)
    for (pid, wid), qty in levels.items():
        session.add(StockLevel(product_id=pid, warehouse_id=wid, quantity=qty))

    received_pos.sort(key=lambda r: r[0].created_at)
    year = today.year
    n = 0
    for po, line, mv in received_pos:
        n += 1
        po.number = f"PO-{year}-{n:04d}"
        mv.reference = po.number
        po.lines.append(line)
        session.add(po)
    for product, supplier, qty, status in open_pos:
        n += 1
        created = utcnow() - timedelta(days=rng.randint(1, 4))
        po = PurchaseOrder(
            number=f"PO-{year}-{n:04d}",
            supplier_id=supplier.id,
            warehouse_id=whs[0].id,
            status=status,
            created_by="user:manager@intelliinventory.dev",
            created_at=created,
            expected_at=created + timedelta(days=supplier.lead_time_days),
            notes="Replenishment for upcoming demand",
        )
        po.lines.append(PurchaseOrderLine(product_id=product.id, quantity=qty, unit_cost=product.unit_cost))
        session.add(po)
    session.commit()
    return True
