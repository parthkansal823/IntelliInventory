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

# Demo shop: Kansal General Store, Kharar (Punjab) - a typical Indian general / kirana store.
# (The app itself works for any shop anywhere in India; this is only the sample data.)
CATEGORIES = [
    ("Atta, Rice & Dal", "#f59e0b"),
    ("Oil & Ghee", "#eab308"),
    ("Masale & Dry Fruits", "#b45309"),
    ("Snacks & Biscuits", "#f97316"),
    ("Beverages", "#0ea5e9"),
    ("Personal Care", "#ec4899"),
    ("Home Care", "#10b981"),
    ("Dairy & Bakery", "#6366f1"),
    ("Puja Samagri", "#dc2626"),
]

# name, email, phone, lead time, rating, state, PAN (GSTIN is derived with a valid checksum)
SUPPLIERS = [
    ("Aggarwal Traders", "orders@aggarwaltraders.example.in", "+91 98140 10101", 2, 4.6, "Punjab", "AAFFA4821K"),
    ("Mohali Oil & Ghee Depot", "sales@mohalioil.example.in", "+91 98150 20144", 3, 4.4, "Punjab", "AAKFM6310M"),
    ("Chandigarh Snacks Agency", "b2b@chdsnacks.example.in", "+91 98720 30190", 3, 4.2, "Chandigarh", "AABCC7742P"),
    ("Ludhiana FMCG Distributors", "supply@ldhfmcg.example.in", "+91 98880 40123", 5, 4.5, "Punjab", "AADCL2291Q"),
    ("Tricity Dairy Supplies", "orders@tricitydairy.example.in", "+91 98760 50177", 1, 4.8, "Punjab", "AAFFT5503R"),
    ("Delhi Dry Fruits & Masala Co.", "trade@delhidryfruits.example.in", "+91 99100 60165", 7, 3.9, "Delhi", "AAGCD8816L"),
    ("Amritsar Puja Bhandar", "sales@amritsarpuja.example.in", "+91 98150 70188", 6, 4.1, "Punjab", "AAHFA3345N"),
]

WAREHOUSES = [
    ("MAIN", "Shop (counter)", "Main Bazaar, Kharar", "Punjab"),
    ("GODOWN", "Godown", "Near Grain Market, Kharar", "Punjab"),
]

# Illustrative HSN codes and GST 2.0 slabs (w.e.f. 22 Sep 2025: 0/5/18/40%) - confirm with your CA.
# sku, name, category, supplier, cost ₹, selling price ₹ (before GST), daily demand, MOQ, scenario, trend, HSN, GST %,
# unit, shelf life in days (None = does not expire)
PRODUCTS = [
    ("ATA-101", "Chakki Fresh Atta 10kg", 0, 0, 380, 420, 12, 10, "healthy", 0.1, "1101", 5, "pack", 90),
    ("ATA-102", "Basmati Rice 5kg", 0, 0, 480, 560, 6, 5, "healthy", 0.2, "1006", 5, "pack", 365),
    ("ATA-103", "Toor Dal 1kg", 0, 0, 140, 160, 15, 20, "low", 0.1, "0713", 5, "pack", 180),
    ("ATA-104", "Kala Chana 1kg", 0, 0, 85, 98, 8, 10, "healthy", 0.0, "0713", 5, "pack", 180),
    ("ATA-105", "Sugar 1kg", 0, 0, 42, 46, 25, 50, "critical", 0.1, "1701", 5, "pack", 365),
    ("ATA-106", "Iodised Salt 1kg", 0, 0, 22, 27, 10, 25, "healthy", 0.0, "2501", 0, "pack", 730),
    ("OIL-201", "Kachi Ghani Mustard Oil 1L", 1, 1, 150, 170, 14, 12, "healthy", 0.1, "1514", 5, "bottle", 270),
    ("OIL-202", "Desi Ghee 1L", 1, 1, 560, 620, 5, 6, "shrinkage", 0.0, "0405", 5, "tin", 270),
    ("OIL-203", "Refined Soyabean Oil 1L", 1, 1, 125, 140, 10, 12, "healthy", 0.0, "1507", 5, "pouch", 270),
    ("MSL-301", "Haldi Powder 200g", 2, 5, 45, 55, 6, 10, "healthy", 0.0, "0910", 5, "pack", 365),
    ("MSL-302", "Garam Masala 100g", 2, 5, 45, 75, 4, 10, "overstock", -0.1, "0910", 5, "pack", 365),
    ("MSL-303", "Almonds (Badam) 500g", 2, 5, 420, 490, 4, 5, "out", 0.0, "0802", 5, "pack", 180),
    ("MSL-304", "Kaju 250g", 2, 5, 250, 295, 3, 5, "healthy", 0.3, "0801", 5, "pack", 180),
    ("SNK-401", "Glucose Biscuits Family Pack", 3, 2, 38, 45, 30, 48, "spike", 0.0, "1905", 5, "pack", 180),
    ("SNK-402", "Aloo Bhujia 400g", 3, 2, 80, 95, 12, 24, "healthy", 0.1, "2106", 5, "pack", 120),
    ("SNK-403", "Suji Rusk 300g", 3, 2, 35, 42, 10, 24, "low", 0.0, "1905", 5, "pack", 120),
    ("SNK-404", "Chocolate Bar 50g", 3, 2, 38, 45, 20, 48, "healthy", 0.2, "1806", 5, "pcs", 270),
    ("SNK-405", "Instant Noodles (Pack of 4)", 3, 2, 48, 56, 15, 24, "healthy", 0.1, "1902", 5, "pack", 240),
    ("BEV-501", "Assam Tea 500g", 4, 2, 210, 245, 8, 10, "critical", 0.1, "0902", 5, "pack", 365),
    ("BEV-502", "Cold Drink 2L", 4, 2, 55, 68, 10, 12, "healthy", 0.3, "2202", 40, "bottle", 180),
    ("BEV-503", "Instant Coffee 50g", 4, 2, 130, 155, 4, 10, "healthy", 0.0, "2101", 5, "jar", 365),
    ("BEV-504", "Mango Juice 1L", 4, 2, 85, 100, 6, 12, "drop", 0.0, "2009", 5, "pack", 180),
    ("PRC-601", "Bathing Soap (Pack of 4)", 5, 3, 120, 140, 9, 12, "healthy", 0.1, "3401", 5, "pack", 730),
    ("PRC-602", "Toothpaste 150g", 5, 3, 85, 100, 8, 12, "healthy", 0.0, "3306", 5, "pcs", 540),
    ("PRC-603", "Shampoo 340ml", 5, 3, 190, 230, 4, 6, "low_on_order", 0.2, "3305", 5, "bottle", 730),
    ("PRC-604", "Coconut Hair Oil 500ml", 5, 3, 150, 180, 5, 6, "healthy", 0.1, "3305", 5, "bottle", 540),
    ("HMC-701", "Detergent Powder 1kg", 6, 3, 95, 115, 10, 12, "healthy", 0.1, "3402", 18, "pack", 730),
    ("HMC-702", "Dishwash Bar (Pack of 3)", 6, 3, 40, 50, 8, 24, "healthy", 0.0, "3402", 18, "pack", 730),
    ("HMC-703", "Floor Cleaner 1L", 6, 3, 120, 185, 3, 6, "overstock", 0.0, "3402", 18, "bottle", 730),
    ("HMC-704", "Toilet Cleaner 500ml", 6, 3, 80, 95, 3, 12, "healthy", 0.0, "3808", 18, "bottle", 730),
    ("DRY-801", "Brown Bread 400g", 7, 4, 35, 40, 20, 20, "healthy", 0.0, "1905", 0, "pack", 3),
    ("DRY-802", "Paneer 200g", 7, 4, 80, 90, 8, 10, "low", 0.2, "0406", 0, "pack", 4),
    ("DRY-803", "Butter 100g", 7, 4, 52, 58, 6, 10, "healthy", 0.0, "0405", 5, "pack", 60),
    ("DRY-804", "Dahi (Curd) 400g", 7, 4, 35, 40, 12, 12, "healthy", 0.1, "0403", 0, "cup", 6),
    ("PUJ-901", "Agarbatti (Pack of 100)", 8, 6, 45, 60, 8, 24, "healthy", 0.0, "3307", 5, "pack", None),
    ("PUJ-902", "Clay Diya (Pack of 12)", 8, 6, 30, 40, 2, 24, "healthy", 0.0, "6912", 5, "pack", None),
    ("PUJ-903", "Camphor (Kapoor) 50g", 8, 6, 40, 50, 3, 12, "healthy", 0.0, "2914", 5, "pack", None),
    ("PUJ-904", "Cotton Wicks (Batti)", 8, 6, 15, 20, 3, 24, "healthy", 0.0, "5601", 5, "pack", None),
]

# Products whose shelf stock expires soon in the demo (days from today) - shows the expiry alert.
EXPIRING_SOON = {"DRY-801": 2, "DRY-802": 3, "DRY-804": 5, "SNK-403": 12}


def ean13(index: int) -> str:
    """Valid EAN-13 barcode with the India GS1 prefix 890 (demo values)."""
    body = f"890{7000000 + index * 137:09d}"[:12]
    check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    return body + str(check)


WEEKLY = {
    "retail": [0.85, 0.88, 0.9, 0.95, 1.1, 1.35, 1.25],
    "office": [1.2, 1.15, 1.15, 1.1, 1.0, 0.45, 0.35],
    "grocery": [0.95, 0.95, 0.95, 1.0, 1.05, 1.2, 1.15],
}

# The demo has exactly two people: Parth (owner / admin) and Ananya (manager).
USERS = [
    ("parth@intelliinventory.dev", "Parth", Role.ADMIN),
    ("ananya@intelliinventory.dev", "Ananya", Role.MANAGER),
]
DEMO_ACCOUNTS = [
    {"email": "parth@intelliinventory.dev", "name": "Parth", "role": "Admin", "note": "owner - everything: billing, GST, users"},
    {
        "email": "ananya@intelliinventory.dev",
        "name": "Ananya",
        "role": "Manager",
        "note": "billing, approves POs & agent actions",
    },
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

    for i, (sku, name, ci, si, cost, price, base, moq, scenario, trend, hsn, gst, unit, shelf) in enumerate(PRODUCTS):
        supplier = sups[si]
        lead = supplier.lead_time_days
        home = whs[0] if i % 4 else whs[1]  # most stock on the shop shelves, bulk in the godown
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
            barcode=ean13(i),
            unit=unit,
            expiry_date=(today + timedelta(days=EXPIRING_SOON.get(sku, round(shelf * 0.6)))) if shelf else None,
            min_order_qty=moq,
            description=f"{name} — {CATEGORIES[ci][0].lower()} item supplied by {supplier.name}.",
            created_at=at(0, 8) - timedelta(days=1),
        )
        session.add(product)
        session.flush()

        profile = WEEKLY["retail" if ci in (5, 6) else "grocery"]
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
                    created_by="user:ananya@intelliinventory.dev",
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
                        actor="user:parth@intelliinventory.dev",
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
            created_by="user:ananya@intelliinventory.dev",
            created_at=created,
            expected_at=created + timedelta(days=supplier.lead_time_days),
            notes="Replenishment for upcoming demand",
        )
        po.lines.append(PurchaseOrderLine(product_id=product.id, quantity=qty, unit_cost=product.unit_cost))
        session.add(po)
    session.commit()
    seed_billing(session, rng)
    return True


# days ago, customer (None = walk-in), items (sku, qty), payment mode, amount paid (None = full / credit = 0)
DEMO_BILLS = [
    (6, None, [("ATA-101", 1), ("OIL-201", 2), ("ATA-106", 1)], "cash", None),
    (6, "parth", [("SNK-404", 4), ("BEV-502", 1)], "upi", None),
    (5, "parth", [("ATA-101", 2), ("ATA-103", 3), ("OIL-203", 2)], "credit", None),
    (5, None, [("PRC-602", 2), ("PRC-601", 1)], "cash", None),
    (4, "ananya", [("OIL-202", 1), ("MSL-304", 2)], "card", None),
    (3, None, [("SNK-402", 2), ("BEV-503", 1)], "upi", None),
    (3, "parth", [("HMC-701", 2), ("HMC-702", 3)], "upi", 100.0),  # part-paid, rest on khata
    (2, None, [("DRY-803", 2), ("DRY-801", 1)], "upi", None),
    (2, None, [("PUJ-901", 2), ("PUJ-903", 1)], "cash", None),
    (1, "ananya", [("ATA-102", 1), ("MSL-301", 2)], "upi", None),
    (1, "parth", [("SNK-405", 3)], "credit", None),
    (0, None, [("SNK-404", 2), ("BEV-502", 1)], "upi", None),
    (0, None, [("ATA-104", 1), ("PUJ-904", 2)], "cash", None),
]


def seed_billing(session: Session, rng: random.Random) -> None:
    """A week of bills: counter sales, UPI/card and udhaar on the khata."""
    from app.models import Customer
    from app.services import billing
    from app.services.settings import set_setting

    set_setting(billing.PROFILE_KEY, billing.demo_profile())
    customers = {
        "parth": Customer(name="Parth", phone="+91 98140 45678", state="Punjab", address="Ward 7, Kharar"),
        "ananya": Customer(name="Ananya", phone="+91 98760 12345", state="Punjab", address="Sector 115, Mohali"),
    }
    session.add_all(customers.values())
    session.commit()
    now = utcnow()
    per_day: dict[int, int] = {}
    for days_ago, who, items, mode, paid in DEMO_BILLS:
        day = now.astimezone(IST).date() - timedelta(days=days_ago)
        slot = per_day[days_ago] = per_day.get(days_ago, -1) + 1  # keeps invoice numbers in time order
        shop_time = time(10 + 5 * slot + rng.randint(0, 4), rng.randint(0, 59))
        when = min(datetime.combine(day, shop_time, tzinfo=IST).astimezone(UTC), now)
        billing.create_invoice(
            session,
            [{"sku": sku, "quantity": qty} for sku, qty in items],
            customer_id=customers[who].id if who else None,
            payment_mode=mode,
            amount_paid=paid,
            prices_include_gst=True,  # general store: counter prices include GST (MRP style)
            actor="user:ananya@intelliinventory.dev",
            created_at=when,
            emit=False,
        )
