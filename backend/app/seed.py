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
    IST,
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
from app.services.india import make_gstin

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

# name, email, phone, lead time, rating, state, PAN (GSTIN is derived with a valid checksum)
SUPPLIERS = [
    ("TechSource India Pvt Ltd", "orders@techsource.example.in", "+91 98450 10101", 10, 4.6, "Karnataka", "AAACT4821K"),
    ("Pacific Components LLP", "sales@pacificcomp.example.in", "+91 94440 20144", 14, 4.1, "Tamil Nadu", "AAKFP6310M"),
    ("OfficeHub Wholesale", "b2b@officehub.example.in", "+91 98110 30190", 5, 4.4, "Delhi", "AABCO7742P"),
    ("HomeGoods Direct", "supply@homegoods.example.in", "+91 98250 40123", 7, 3.9, "Gujarat", "AADCH2291Q"),
    ("FreshFarm Distributors", "orders@freshfarm.example.in", "+91 98200 50177", 3, 4.8, "Maharashtra", "AAFFF5503R"),
    ("PlayWorld Imports", "trade@playworld.example.in", "+91 99200 60165", 21, 3.7, "Maharashtra", "AAGCP8816L"),
]

WAREHOUSES = [
    ("MAIN", "Central DC", "Bhiwandi, Mumbai", "Maharashtra"),
    ("NORTH", "North Hub", "Okhla, Delhi", "Delhi"),
    ("SOUTH", "South Hub", "Hosur Road, Bengaluru", "Karnataka"),
]

# Indian-market demo catalogue, priced in rupees (cost, selling price), with illustrative HSN codes and
# GST 2.0 slabs (w.e.f. 22 Sep 2025: 0/5/18/40%) - confirm rates for your own products with your CA.
# sku, name, category, supplier, unit cost ₹, selling price ₹, base daily demand, MOQ, scenario, trend, HSN, GST %
PRODUCTS = [
    ("ELC-1001", "Wireless Earbuds (TWS, 40h)", 0, 0, 900, 1499, 14, 10, "low", 0.2, "8518", 18),
    ("ELC-1002", "Smart Watch with Bluetooth Calling", 0, 0, 1400, 2499, 6, 5, "shrinkage", 0.1, "8517", 18),
    ("ELC-1003", "Bluetooth Speaker 10W", 0, 0, 700, 1299, 9, 10, "spike", 0.0, "8518", 18),
    ("ELC-1004", 'LED Smart TV 32"', 0, 0, 9500, 13999, 2, 2, "out", 0.1, "8528", 18),
    ("ELC-1005", "Ceiling Fan 1200mm (BLDC)", 0, 0, 2300, 3499, 4, 2, "healthy", 0.5, "8414", 18),
    ("ELC-1006", "Portable SSD 1TB", 0, 0, 4400, 6999, 5, 5, "healthy", 0.2, "8471", 18),
    ("ACC-2001", "Fast Charger 33W Type-C", 1, 1, 350, 699, 22, 20, "critical", 0.3, "8504", 18),
    ("ACC-2002", "Braided USB-C Cable 2m", 1, 1, 120, 299, 40, 50, "healthy", 0.1, "8544", 18),
    ("ACC-2003", "Mobile Back Cover (Silicone)", 1, 1, 60, 199, 11, 10, "healthy", 0.0, "3926", 18),
    ("ACC-2004", 'Laptop Sleeve 14"', 1, 1, 350, 799, 7, 10, "healthy", -0.1, "4202", 18),
    ("ACC-2005", "Power Bank 20000mAh", 1, 1, 900, 1499, 12, 10, "healthy", 0.45, "8507", 18),
    ("OFF-3001", "A4 Copy Paper 75 GSM (500 sheets)", 2, 2, 260, 399, 35, 50, "low", 0.0, "4802", 18),
    ("OFF-3002", "Ball Pens (Pack of 10)", 2, 2, 45, 100, 18, 20, "healthy", -0.3, "9608", 18),
    ("OFF-3003", "Ergonomic Mesh Office Chair", 2, 2, 4200, 6999, 1.2, 1, "healthy", 0.1, "9401", 18),
    ("OFF-3004", "Steel Almirah 2-Door", 2, 2, 7500, 11999, 0.8, 1, "overstock", 0.0, "9403", 18),
    ("OFF-3005", "Long Notebooks (Pack of 6)", 2, 2, 150, 240, 20, 25, "healthy", 0.0, "4820", 0),
    ("HOM-4001", "Steel Water Bottle 1L", 3, 3, 220, 449, 16, 12, "healthy", 0.25, "7323", 5),
    ("HOM-4002", "Pressure Cooker 5L", 3, 3, 1100, 1799, 6, 6, "overstock", -0.1, "7615", 5),
    ("HOM-4003", "Non-Stick Tawa 28cm", 3, 3, 450, 799, 5, 5, "healthy", 0.0, "7615", 5),
    ("HOM-4004", "Air Fryer 4.2L", 3, 3, 3600, 5999, 3, 2, "low_on_order", 0.35, "8516", 18),
    ("HOM-4005", "Steel Lunch Box (3 Tier)", 3, 3, 250, 499, 7, 10, "healthy", 0.0, "7323", 5),
    ("HLT-5001", "Hand Sanitizer 500ml", 4, 3, 95, 199, 25, 24, "spike", 0.0, "3808", 18),
    ("HLT-5002", "Coconut Hair Oil 500ml", 4, 3, 120, 210, 8, 12, "healthy", 0.3, "3305", 5),
    ("HLT-5003", "Electric Toothbrush", 4, 3, 1200, 1999, 4, 4, "healthy", 0.1, "8509", 18),
    ("SPT-6001", "Yoga Mat 6mm", 5, 5, 350, 699, 8, 10, "low", 0.2, "9506", 5),
    ("SPT-6002", "Cricket Bat (Kashmir Willow)", 5, 5, 1100, 1899, 2, 2, "healthy", 0.0, "9506", 5),
    ("SPT-6003", "Cotton Sports Socks (3 pairs)", 5, 5, 120, 299, 15, 20, "healthy", 0.1, "6115", 5),
    ("SPT-6004", "Badminton Racquet", 5, 5, 450, 899, 6, 10, "healthy", 0.0, "9506", 5),
    ("GRC-7001", "Assam Tea 1kg", 6, 4, 380, 560, 20, 24, "healthy", 0.1, "0902", 5),
    ("GRC-7002", "Filter Coffee Powder 1kg", 6, 4, 520, 799, 12, 10, "critical", 0.2, "0901", 5),
    ("GRC-7003", "Almonds (Badam) 500g", 6, 4, 420, 649, 14, 12, "out", 0.0, "0802", 5),
    ("GRC-7004", "Soan Papdi 500g", 6, 4, 90, 160, 30, 48, "shrinkage", 0.0, "2106", 5),
    ("GRC-7005", "Basmati Rice 5kg", 6, 4, 480, 699, 9, 6, "healthy", 0.4, "1006", 5),
    ("TOY-8001", "Building Blocks Set 500pc", 7, 5, 700, 1299, 4, 4, "healthy", 0.0, "9503", 5),
    ("TOY-8002", "RC Racing Car", 7, 5, 800, 1499, 3, 4, "overstock", -0.2, "9503", 5),
    ("TOY-8003", "Ludo & Snakes-Ladders Board Game", 7, 5, 150, 299, 5, 6, "drop", 0.0, "9504", 5),
    ("TOY-8004", "Plush Teddy Bear", 7, 5, 250, 549, 6, 12, "healthy", 0.1, "9503", 5),
]

WEEKLY = {
    "retail": [0.85, 0.88, 0.9, 0.95, 1.1, 1.35, 1.25],
    "office": [1.2, 1.15, 1.15, 1.1, 1.0, 0.45, 0.35],
    "grocery": [0.95, 0.95, 0.95, 1.0, 1.05, 1.2, 1.15],
}

USERS = [
    ("admin@intelliinventory.dev", "Aarav Admin", Role.ADMIN),
    ("manager@intelliinventory.dev", "Meera Manager", Role.MANAGER),
    ("staff@intelliinventory.dev", "Sameer Staff", Role.STAFF),
    ("viewer@intelliinventory.dev", "Vikram Viewer", Role.VIEWER),
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


def ensure_production_setup(session: Session) -> None:
    """Actual (non-demo) deployments: one admin account and a default warehouse, nothing else."""
    import logging
    import secrets

    settings = get_settings()
    if not session.exec(select(func.count()).select_from(User)).one():
        password = settings.admin_password or secrets.token_urlsafe(12)
        session.add(
            User(
                email=settings.admin_email.lower(),
                name=settings.admin_name,
                role=Role.ADMIN,
                password_hash=hash_password(password),
            )
        )
        if not settings.admin_password:
            logging.getLogger("intelliinventory").warning(
                "Created admin %s with generated password: %s  (set ADMIN_PASSWORD to choose one)", settings.admin_email, password
            )
    if not session.exec(select(func.count()).select_from(Warehouse)).one():
        session.add(Warehouse(code="MAIN", name="Main warehouse"))
    session.commit()


def seed_demo(session: Session) -> bool:
    """Populate an empty database. Returns True when data was created."""
    seed_users(session)
    if session.exec(select(func.count()).select_from(Product)).one():
        return False

    rng = random.Random(42)
    now = utcnow()
    today = now.date()

    cats = [Category(name=n, color=c) for n, c in CATEGORIES]
    sups = [
        Supplier(
            name=n,
            email=e,
            phone=p,
            lead_time_days=lt,
            rating=r,
            state=st,
            gstin=make_gstin(st, pan),
            upi_id=f"{n.split()[0].lower()}@okicici",
        )
        for n, e, p, lt, r, st, pan in SUPPLIERS
    ]
    whs = [Warehouse(code=c, name=n, location=loc, state=st) for c, n, loc, st in WAREHOUSES]
    session.add_all(cats + sups + whs)
    session.commit()

    movements: list[StockMovement] = []
    levels: dict[tuple[int, int], int] = {}
    received_pos: list[tuple[PurchaseOrder, PurchaseOrderLine, StockMovement]] = []
    open_pos: list[tuple[Product, Supplier, int, POStatus]] = []

    def at(day_index: int, hour: int | None = None) -> datetime:
        d = today - timedelta(days=DAYS - 1 - day_index)
        # shop hours in India (9 am - 9 pm IST) - stored as UTC like every other timestamp
        shop_time = time(hour if hour is not None else rng.randint(9, 20), rng.randint(0, 59))
        return min(datetime.combine(d, shop_time, tzinfo=IST).astimezone(UTC), now)

    for i, (sku, name, ci, si, cost, price, base, moq, scenario, trend, hsn, gst) in enumerate(PRODUCTS):
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
            hsn_code=hsn,
            gst_rate=gst,
            gst_source="manual",
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
