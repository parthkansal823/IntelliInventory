"""Billing for Indian shops: GST tax invoices / bills of supply, payments (cash, UPI, card, bank, credit) and the
customer khata (udhaar ledger).

* Numbering  - one series per financial year (April-March): INV/26-27/00001 (<= 16 characters, GST rule 46).
* GST        - CGST + SGST when the place of supply is the seller's state, IGST for other states, zero-rated
               export invoices (under LUT) for customers outside India, and a bill of supply when GST is off.
* Prices     - entered GST-exclusive (B2B) or GST-inclusive (retail MRP style); discounts per line; round-off to
               the nearest rupee; amount in words in the Indian system (lakh / crore).
* Stock      - every invoice line posts a `sale` movement; cancelling posts the stock back as a `return`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import (
    IST,
    Customer,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    MovementType,
    Payment,
    Warehouse,
    utcnow,
)
from app.services import india
from app.services.inventory import (
    InventoryError,
    apply_movement,
    emit_stock_changed,
    find_product,
    find_warehouse,
    primary_warehouse,
)
from app.services.settings import get_setting, set_setting

PAYMENT_MODES = ("cash", "upi", "card", "bank", "credit")
EXPORT_NOTE = "Supply meant for export under LUT without payment of IGST."
BILL_OF_SUPPLY_NOTE = "Bill of supply - seller not registered under GST / GST not charged."

PROFILE_KEY = "business.profile"
PROFILE_DEFAULTS = {
    "name": "Kansal General Store",
    "address": "",
    "gstin": "",
    "state": "",
    "phone": "",
    "email": "",
    "upi_id": "",
    "invoice_prefix": "INV",
    "terms": "Goods once sold will not be taken back or exchanged.",
}


class BillingError(ValueError):
    pass


# --- Business profile ---------------------------------------------------------------------------


def business_profile() -> dict:
    return {**PROFILE_DEFAULTS, **(get_setting(PROFILE_KEY) or {})}


def update_business_profile(changes: dict) -> dict:
    profile = business_profile()
    clean = {k: (v.strip() if isinstance(v, str) else v) for k, v in changes.items() if k in PROFILE_DEFAULTS and v is not None}
    try:
        if clean.get("phone"):
            clean["phone"] = india.normalize_phone(clean["phone"])
        if clean.get("upi_id"):
            clean["upi_id"] = india.normalize_upi(clean["upi_id"])
        if clean.get("state"):
            clean["state"] = india.normalize_state(clean["state"])
    except ValueError as exc:
        raise BillingError(str(exc)) from exc
    if clean.get("gstin"):
        ok, info = india.validate_gstin(clean["gstin"])
        if not ok:
            raise BillingError(f"Invalid GSTIN: {info}")
        clean["gstin"] = clean["gstin"].upper()
        clean["state"] = info
    if "invoice_prefix" in clean:
        prefix = "".join(ch for ch in clean["invoice_prefix"].upper() if ch.isalnum())
        if not 1 <= len(prefix) <= 4:
            raise BillingError("Invoice prefix must be 1-4 letters/digits (invoice numbers are limited to 16 characters)")
        clean["invoice_prefix"] = prefix
    profile.update(clean)
    set_setting(PROFILE_KEY, profile)
    return profile


# --- Helpers ----------------------------------------------------------------------------------


def financial_year(day: date) -> str:
    """Indian financial year label: 24 Sep 2026 -> "26-27", 10 Feb 2027 -> "26-27"."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def next_invoice_number(session: Session, prefix: str, on: datetime | None = None) -> str:
    fy = financial_year((on or utcnow()).astimezone(IST).date())
    series = f"{prefix}/{fy}/"
    numbers = session.exec(select(Invoice.number).where(Invoice.number.startswith(series))).all()
    last = max((int(n.rsplit("/", 1)[1]) for n in numbers if n.rsplit("/", 1)[1].isdigit()), default=0)
    return f"{series}{last + 1:05d}"


_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def _words(n: int) -> str:
    if n == 0:
        return "Zero"
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, n = divmod(n, 100)
    parts = []
    if crore:
        parts.append(f"{_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two(thousand)} Thousand")
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if n:
        parts.append(_two(n))
    return " ".join(parts)


def amount_in_words(amount: float) -> str:
    """1,23,456.50 -> "Rupees One Lakh Twenty-Three Thousand Four Hundred Fifty-Six and Fifty Paise Only"."""
    rupees, paise = divmod(round(abs(amount) * 100), 100)
    text = f"Rupees {_words(rupees)}"
    if paise:
        text += f" and {_two(paise)} Paise"
    return text + " Only"


def _status(total: float, paid: float) -> InvoiceStatus:
    if paid >= total - 0.005:
        return InvoiceStatus.PAID
    return InvoiceStatus.PARTIAL if paid > 0 else InvoiceStatus.UNPAID


def _resolve_customer(session: Session, customer_id: int | None, data: dict | None) -> Customer | None:
    if customer_id:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise BillingError(f"Customer {customer_id} not found")
        return customer
    data = {k: v for k, v in (data or {}).items() if v not in (None, "")}
    if not data.get("name") and not data.get("phone"):
        return None
    fields = customer_fields(data)
    customer = None
    if fields.get("phone"):
        customer = session.exec(select(Customer).where(Customer.phone == fields["phone"])).first()
    if customer is None:
        customer = Customer(**{"name": fields.get("name") or fields["phone"], **fields})
    else:
        for key, value in fields.items():
            if value and (key != "name" or not customer.name):
                setattr(customer, key, value)
    session.add(customer)
    session.flush()
    return customer


def customer_fields(data: dict) -> dict:
    """Validate customer input (phone +91 or international, GSTIN, state / Outside India)."""
    out = {k: (data.get(k) or None) for k in ("name", "email", "address")}
    try:
        out["phone"] = india.normalize_phone(data.get("phone"))
        out["state"] = india.normalize_state(data.get("state"))
    except ValueError as exc:
        raise BillingError(str(exc)) from exc
    out["gstin"] = None
    if data.get("gstin"):
        ok, info = india.validate_gstin(data["gstin"])
        if not ok:
            raise BillingError(f"Invalid GSTIN: {info}")
        out["gstin"] = data["gstin"].strip().upper()
        out["state"] = info
    return out


# --- Invoices -------------------------------------------------------------------------------


def create_invoice(
    session: Session,
    items: list[dict],
    *,
    customer_id: int | None = None,
    customer: dict | None = None,
    warehouse_ref: str | int | None = None,
    payment_mode: str = "cash",
    amount_paid: float | None = None,
    payments: list[dict] | None = None,
    prices_include_gst: bool = False,
    notes: str | None = None,
    actor: str = "user",
    created_at: datetime | None = None,
    emit: bool = True,
) -> Invoice:
    """Bill items (each {product_id | sku, quantity, unit_price?, discount_pct?}); posts stock and payment.

    `payments` splits the money received across modes, e.g. [{"mode": "cash", "amount": 500}, {"mode": "upi", ...}];
    whatever is not paid goes on the customer's khata.
    """
    if not items:
        raise BillingError("Add at least one item to the bill")
    split = [p for p in (payments or []) if float(p.get("amount") or 0) > 0]
    for p in split:
        if p.get("mode") not in PAYMENT_MODES or p.get("mode") == "credit":
            raise BillingError("Split payments must be cash, upi, card or bank")
    if split:
        modes = {p["mode"] for p in split}
        payment_mode = modes.pop() if len(modes) == 1 else "split"
        amount_paid = sum(float(p["amount"]) for p in split)
    elif payment_mode not in PAYMENT_MODES:
        raise BillingError(f"Payment mode must be one of {', '.join(PAYMENT_MODES)}")
    profile = business_profile()
    buyer = _resolve_customer(session, customer_id, customer)
    if payment_mode == "credit" and buyer is None:
        raise BillingError("Udhaar (credit) needs the customer's name and phone number for the khata")
    fixed_wh = find_warehouse(session, warehouse_ref) if warehouse_ref not in (None, "") else None

    seller_state = profile["state"] or (fixed_wh.state if fixed_wh else None) or _first_warehouse_state(session)
    place = (buyer.state if buyer else None) or seller_state
    gst_on = india.gst_enabled()
    export = place == india.OUTSIDE_INDIA
    interstate = export or india.is_interstate(seller_state, place)
    kind = "bill_of_supply" if not gst_on else "export_invoice" if export else "tax_invoice"
    when = created_at or utcnow()
    number = next_invoice_number(session, profile["invoice_prefix"], when)

    invoice = Invoice(
        number=number,
        kind=kind,
        customer_id=buyer.id if buyer else None,
        customer_name=buyer.name if buyer else "Walk-in customer",
        customer_phone=buyer.phone if buyer else None,
        customer_gstin=buyer.gstin if buyer else None,
        customer_address=buyer.address if buyer else None,
        place_of_supply=place,
        warehouse_id=fixed_wh.id if fixed_wh else None,
        payment_mode=payment_mode,
        prices_include_gst=prices_include_gst,
        notes=notes,
        created_by=actor,
        created_at=when,
    )
    moved = []
    subtotal = discount = taxable_sum = tax_sum = 0.0
    for raw in items:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            raise BillingError("Quantities must be positive")
        product = find_product(session, raw.get("product_id") or raw.get("sku") or "")
        rate = float(product.gst_rate or 0) if gst_on else 0.0
        # MRP-style (GST-inclusive) shelf prices are whole rupees; GST-exclusive B2B prices keep paise
        default_price = round(product.unit_price * (1 + rate / 100)) if prices_include_gst else product.unit_price
        price = float(raw["unit_price"]) if raw.get("unit_price") is not None else round(default_price, 2)
        disc_pct = min(max(float(raw.get("discount_pct") or 0), 0.0), 100.0)
        gross = price * qty
        net = gross * (1 - disc_pct / 100)
        taxable = net / (1 + rate / 100) if prices_include_gst else net
        tax = 0.0 if export else taxable * rate / 100
        taxable, tax = round(taxable, 2), round(tax, 2)
        warehouse = fixed_wh or primary_warehouse(session, product.id)
        invoice.lines.append(
            InvoiceLine(
                product_id=product.id,
                warehouse_id=warehouse.id,
                sku=product.sku,
                name=product.name,
                hsn_code=product.hsn_code,
                quantity=qty,
                unit_price=price,
                discount_pct=disc_pct,
                gst_rate=rate,
                taxable=taxable,
                tax=tax,
                total=round(taxable + tax, 2),
            )
        )
        subtotal += gross
        discount += gross - net
        taxable_sum += taxable
        tax_sum += tax
        moved.append((product, warehouse, qty))

    exact = taxable_sum + tax_sum
    total = float(round(exact))
    invoice.subtotal, invoice.discount = round(subtotal, 2), round(discount, 2)
    invoice.taxable, invoice.tax = round(taxable_sum, 2), round(tax_sum, 2)
    if interstate:
        invoice.igst = invoice.tax
    else:
        invoice.cgst = round(invoice.tax / 2, 2)
        invoice.sgst = round(invoice.tax - invoice.cgst, 2)
    invoice.round_off = round(total - exact, 2)
    invoice.total = total
    paid = (0.0 if payment_mode == "credit" else total) if amount_paid is None else min(max(float(amount_paid), 0.0), total)
    if paid < total - 0.005 and buyer is None:
        raise BillingError("Money is still due on this bill - add the customer's name and phone so it goes on their khata")
    invoice.amount_paid = round(paid, 2)
    invoice.status = _status(total, paid)
    if kind == "export_invoice":
        invoice.notes = "\n".join(filter(None, [notes, EXPORT_NOTE]))

    movements = []
    try:
        for product, warehouse, qty in moved:
            mv = apply_movement(
                session,
                product,
                warehouse,
                MovementType.SALE,
                -qty,
                actor=actor,
                reference=number,
                note=f"Invoice {number} - {invoice.customer_name}",
                created_at=when,
                commit=False,
            )
            movements.append((product, warehouse, mv))
    except InventoryError:
        session.rollback()
        raise
    session.add(invoice)
    session.flush()
    received = split or ([{"mode": "cash" if payment_mode == "credit" else payment_mode, "amount": paid}] if paid > 0 else [])
    remaining = invoice.amount_paid
    for p in received:  # change returned in cash is not recorded - payments never exceed the bill
        amount = round(min(float(p["amount"]), remaining), 2)
        if amount <= 0:
            continue
        remaining = round(remaining - amount, 2)
        session.add(
            Payment(
                invoice_id=invoice.id,
                amount=amount,
                mode=p["mode"],
                reference=p.get("reference"),
                created_by=actor,
                created_at=when,
            )
        )
    session.commit()
    session.refresh(invoice)
    if emit:
        for product, warehouse, mv in movements:
            session.refresh(mv)
            emit_stock_changed(session, product, warehouse, mv)
        bus.emit("invoice.created", invoice_brief(invoice), source=actor)
    return invoice


def _first_warehouse_state(session: Session) -> str | None:
    return session.exec(select(Warehouse.state).where(Warehouse.state.is_not(None)).order_by(Warehouse.id)).first()


def record_payment(
    session: Session, invoice: Invoice, amount: float, mode: str = "cash", reference: str | None = None, actor: str = "user"
) -> Invoice:
    if invoice.status == InvoiceStatus.CANCELLED:
        raise BillingError(f"{invoice.number} is cancelled")
    balance = round(invoice.total - invoice.amount_paid, 2)
    if balance <= 0:
        raise BillingError(f"{invoice.number} is already fully paid")
    if amount <= 0:
        raise BillingError("Payment amount must be positive")
    if mode not in PAYMENT_MODES or mode == "credit":
        raise BillingError("Payment mode must be cash, upi, card or bank")
    amount = round(min(amount, balance), 2)
    session.add(Payment(invoice_id=invoice.id, amount=amount, mode=mode, reference=reference, created_by=actor))
    invoice.amount_paid = round(invoice.amount_paid + amount, 2)
    invoice.status = _status(invoice.total, invoice.amount_paid)
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    bus.emit("invoice.paid", {**invoice_brief(invoice), "payment": amount, "mode": mode}, source=actor)
    return invoice


def cancel_invoice(session: Session, invoice: Invoice, reason: str | None = None, actor: str = "user") -> Invoice:
    if invoice.status == InvoiceStatus.CANCELLED:
        raise BillingError(f"{invoice.number} is already cancelled")
    movements = []
    for line in invoice.lines:
        product = find_product(session, line.product_id)
        warehouse = session.get(Warehouse, line.warehouse_id)
        mv = apply_movement(
            session,
            product,
            warehouse,
            MovementType.RETURN,
            line.quantity,
            actor=actor,
            reference=invoice.number,
            note=f"Invoice {invoice.number} cancelled" + (f": {reason}" if reason else ""),
            commit=False,
        )
        movements.append((product, warehouse, mv))
    invoice.status = InvoiceStatus.CANCELLED
    invoice.cancelled_at = utcnow()
    if reason:
        invoice.notes = "\n".join(filter(None, [invoice.notes, f"Cancelled: {reason}"]))
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    for product, warehouse, mv in movements:
        session.refresh(mv)
        emit_stock_changed(session, product, warehouse, mv)
    bus.emit("invoice.cancelled", invoice_brief(invoice), source=actor)
    return invoice


def find_invoice(session: Session, ref: str | int) -> Invoice:
    invoice = None
    if isinstance(ref, int) or str(ref).isdigit():
        invoice = session.get(Invoice, int(ref))
    if invoice is None:
        key = str(ref).strip().upper()
        invoice = session.exec(select(Invoice).where(func.upper(Invoice.number) == key)).first()
    if invoice is None:
        raise BillingError(f"Invoice '{ref}' not found")
    return invoice


# --- Views ----------------------------------------------------------------------------------


def invoice_brief(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "number": inv.number,
        "kind": inv.kind,
        "status": inv.status,
        "customer_id": inv.customer_id,
        "customer_name": inv.customer_name,
        "customer_phone": inv.customer_phone,
        "payment_mode": inv.payment_mode,
        "items": len(inv.lines),
        "taxable": inv.taxable,
        "tax": inv.tax,
        "total": inv.total,
        "amount_paid": inv.amount_paid,
        "balance": round(inv.total - inv.amount_paid, 2) if inv.status != InvoiceStatus.CANCELLED else 0.0,
        "created_at": inv.created_at.isoformat(),
    }


def invoice_detail(session: Session, inv: Invoice) -> dict:
    profile = business_profile()
    interstate = inv.igst > 0 or inv.kind == "export_invoice" or india.is_interstate(profile["state"], inv.place_of_supply)
    hsn: dict[tuple, dict] = {}
    for line in inv.lines:
        row = hsn.setdefault(
            (line.hsn_code, line.gst_rate),
            {"hsn_code": line.hsn_code, "gst_rate": line.gst_rate, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0},
        )
        row["taxable"] += line.taxable
        if interstate:
            row["igst"] += line.tax
        else:
            row["cgst"] += line.tax / 2
            row["sgst"] += line.tax / 2
    payments = session.exec(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.created_at)).all()
    balance = inv.total - inv.amount_paid
    notes = [n for n in (inv.notes or "").split("\n") if n]
    if inv.kind == "bill_of_supply":
        notes.append(BILL_OF_SUPPLY_NOTE)
    return {
        **invoice_brief(inv),
        "title": {"tax_invoice": "Tax Invoice", "bill_of_supply": "Bill of Supply", "export_invoice": "Export Invoice"}[inv.kind],
        "seller": profile,
        "customer_gstin": inv.customer_gstin,
        "customer_address": inv.customer_address,
        "place_of_supply": inv.place_of_supply,
        "interstate": interstate,
        "prices_include_gst": inv.prices_include_gst,
        "subtotal": inv.subtotal,
        "discount": inv.discount,
        "cgst": inv.cgst,
        "sgst": inv.sgst,
        "igst": inv.igst,
        "round_off": inv.round_off,
        "amount_in_words": amount_in_words(inv.total),
        "notes": notes,
        "created_by": inv.created_by,
        "cancelled_at": inv.cancelled_at.isoformat() if inv.cancelled_at else None,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "sku": line.sku,
                "name": line.name,
                "hsn_code": line.hsn_code,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount_pct": line.discount_pct,
                "gst_rate": line.gst_rate,
                "taxable": line.taxable,
                "tax": line.tax,
                "total": line.total,
            }
            for line in inv.lines
        ],
        "hsn_summary": [{k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()} for r in hsn.values()],
        "payments": [
            {"amount": p.amount, "mode": p.mode, "reference": p.reference, "created_at": p.created_at.isoformat()}
            for p in payments
        ],
        "upi_link": india.upi_link(profile["upi_id"], profile["name"], balance, f"Invoice {inv.number}")
        if profile["upi_id"] and balance > 0.5 and inv.status != InvoiceStatus.CANCELLED
        else None,
    }


def list_invoices(
    session: Session,
    status: str | None = None,
    q: str | None = None,
    customer_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    stmt = select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(limit)
    if status == "due":
        stmt = stmt.where(Invoice.status.in_([InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL]))
    elif status and status != "all":
        stmt = stmt.where(Invoice.status == status)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Invoice.number.ilike(like), Invoice.customer_name.ilike(like), Invoice.customer_phone.ilike(like)))
    return [invoice_brief(inv) for inv in session.exec(stmt)]


def _ist_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=IST)


def day_close(session: Session, day: date | None = None) -> dict:
    """ "Aaj ka hisaab": one day's bills, money received by mode, udhaar given / collected and top items."""
    day = day or utcnow().astimezone(IST).date()
    start, end = _ist_midnight(day), _ist_midnight(day + timedelta(days=1))
    bills = session.exec(
        select(Invoice).where(Invoice.created_at >= start, Invoice.created_at < end, Invoice.status != InvoiceStatus.CANCELLED)
    ).all()
    cancelled = session.exec(
        select(func.count()).select_from(Invoice).where(Invoice.cancelled_at >= start, Invoice.cancelled_at < end)
    ).one()
    payments = session.exec(
        select(Payment, Invoice)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Payment.created_at >= start, Payment.created_at < end, Invoice.status != InvoiceStatus.CANCELLED)
    ).all()
    by_mode: dict[str, float] = {}
    collected_old = 0.0
    for pay, inv in payments:
        by_mode[pay.mode] = round(by_mode.get(pay.mode, 0.0) + pay.amount, 2)
        if inv.created_at < start:
            collected_old += pay.amount
    items: dict[str, dict] = {}
    for inv in bills:
        for line in inv.lines:
            row = items.setdefault(line.sku, {"sku": line.sku, "name": line.name, "quantity": 0, "amount": 0.0})
            row["quantity"] += line.quantity
            row["amount"] = round(row["amount"] + line.total, 2)
    sales = round(sum(i.total for i in bills), 2)
    return {
        "date": day.isoformat(),
        "bills": len(bills),
        "cancelled": cancelled,
        "sales": sales,
        "tax": round(sum(i.tax for i in bills), 2),
        "discount": round(sum(i.discount for i in bills), 2),
        "received": by_mode,
        "received_total": round(sum(by_mode.values()), 2),
        "cash_in_drawer": by_mode.get("cash", 0.0),
        "udhaar_given": round(sum(i.total - i.amount_paid for i in bills), 2),
        "udhaar_collected": round(collected_old, 2),
        "top_items": sorted(items.values(), key=lambda r: -r["amount"])[:10],
    }


def billing_summary(session: Session, days: int = 30) -> dict:
    """Sales from bills: today, the period, payment-mode split, daily series and money still to collect."""
    today = utcnow().astimezone(IST).date()
    start = today - timedelta(days=days - 1)
    invoices = session.exec(
        select(Invoice).where(Invoice.created_at >= _ist_midnight(start), Invoice.status != InvoiceStatus.CANCELLED)
    ).all()
    daily = {(start + timedelta(days=i)).isoformat(): 0.0 for i in range(days)}
    today_total = today_count = 0
    for inv in invoices:
        day = inv.created_at.astimezone(IST).date().isoformat()
        if day in daily:
            daily[day] += inv.total
        if day == today.isoformat():
            today_total += inv.total
            today_count += 1
    payments = session.exec(
        select(Payment.mode, func.sum(Payment.amount))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Payment.created_at >= _ist_midnight(start), Invoice.status != InvoiceStatus.CANCELLED)
        .group_by(Payment.mode)
    ).all()
    dues = customer_dues(session)
    total = sum(inv.total for inv in invoices)
    return {
        "days": days,
        "today": {"bills": today_count, "sales": round(today_total, 2)},
        "period": {
            "bills": len(invoices),
            "sales": round(total, 2),
            "tax": round(sum(inv.tax for inv in invoices), 2),
            "avg_bill": round(total / len(invoices), 2) if invoices else 0.0,
        },
        "collected_by_mode": {mode: round(float(amount or 0), 2) for mode, amount in payments},
        "outstanding": round(sum(d["balance"] for d in dues), 2),
        "customers_with_dues": len(dues),
        "daily": [{"date": d, "sales": round(v, 2)} for d, v in daily.items()],
        "financial_year": financial_year(today),
    }


def customer_dues(session: Session, limit: int | None = None) -> list[dict]:
    """The khata: customers who still owe money, biggest balance first."""
    open_invoices = session.exec(
        select(Invoice)
        .where(Invoice.status.in_([InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL]), Invoice.customer_id.is_not(None))
        .order_by(Invoice.created_at)
    ).all()
    today = utcnow().astimezone(IST).date()
    rows: dict[int, dict] = {}
    for inv in open_invoices:
        row = rows.setdefault(
            inv.customer_id,
            {
                "customer_id": inv.customer_id,
                "name": inv.customer_name,
                "phone": inv.customer_phone,
                "balance": 0.0,
                "invoices": [],
                "oldest": inv.created_at.astimezone(IST).date().isoformat(),
                "days_outstanding": (today - inv.created_at.astimezone(IST).date()).days,
            },
        )
        balance = round(inv.total - inv.amount_paid, 2)
        row["balance"] = round(row["balance"] + balance, 2)
        row["invoices"].append({"id": inv.id, "number": inv.number, "balance": balance, "date": inv.created_at.isoformat()})
    result = sorted(rows.values(), key=lambda r: -r["balance"])
    return result[:limit] if limit else result


def list_customers(session: Session, q: str | None = None, limit: int = 50) -> list[dict]:
    stmt = select(Customer).order_by(Customer.name).limit(limit)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.gstin.ilike(like)))
    dues = {d["customer_id"]: d["balance"] for d in customer_dues(session)}
    return [{**c.model_dump(mode="json"), "balance": dues.get(c.id, 0.0)} for c in session.exec(stmt)]


def demo_profile() -> dict:
    """Business profile used by the public demo."""
    return {
        "name": "Kansal General Store",
        "address": "Main Bazaar, Kharar, Distt. SAS Nagar (Mohali), Punjab 140301",
        "gstin": india.make_gstin("Punjab", "AAKFK4821R"),
        "state": "Punjab",
        "phone": "+91 98140 11223",
        "email": "kansalgeneralstore@example.in",
        "upi_id": "kansalstore@okaxis",
        "invoice_prefix": "KGS",
        "terms": "Goods once sold will not be taken back. Subject to Kharar jurisdiction. Dhanyavaad, phir padhariye!",
    }


def sales_register_csv(session: Session, days: int = 31) -> str:
    """GSTR-1 friendly sales register: one row per invoice and GST rate (hand it to your CA / import in Tally)."""
    import csv
    import io

    since = _ist_midnight(utcnow().astimezone(IST).date() - timedelta(days=days - 1))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "Invoice No",
            "Invoice Date",
            "Type",
            "Customer",
            "Customer GSTIN",
            "Place of Supply",
            "GST Rate %",
            "Taxable Value",
            "CGST",
            "SGST",
            "IGST",
            "Invoice Total",
            "Status",
        ]
    )
    invoices = session.exec(select(Invoice).where(Invoice.created_at >= since).order_by(Invoice.created_at)).all()
    for inv in invoices:
        by_rate: dict[float, list[float]] = {}
        for line in inv.lines:
            row = by_rate.setdefault(line.gst_rate, [0.0, 0.0])
            row[0] += line.taxable
            row[1] += line.tax
        for rate, (taxable, tax) in sorted(by_rate.items()):
            igst = tax if inv.igst > 0 else 0.0
            cgst = 0.0 if igst else tax / 2
            writer.writerow(
                [
                    inv.number,
                    inv.created_at.astimezone(IST).strftime("%d-%m-%Y"),
                    {"tax_invoice": "B2B" if inv.customer_gstin else "B2C", "export_invoice": "EXPORT"}.get(inv.kind, "BOS"),
                    inv.customer_name,
                    inv.customer_gstin or "",
                    inv.place_of_supply or "",
                    f"{rate:g}",
                    f"{taxable:.2f}",
                    f"{cgst:.2f}",
                    f"{tax - igst - cgst:.2f}",
                    f"{igst:.2f}",
                    f"{inv.total:.2f}",
                    inv.status,
                ]
            )
    return out.getvalue()
