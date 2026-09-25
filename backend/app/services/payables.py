"""Supplier khata (payables): what the shop owes its wholesalers.

* A received purchase order automatically becomes a purchase bill, due after the supplier's credit days.
* Purchase bills can also be entered by hand (with the supplier's own bill number).
* Payments are allocated to the oldest open bills first (FIFO), in cash / UPI / bank / cheque.
* A daily job raises a "payable_due" alert for bills due within two days.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.hooks.bus import bus
from app.models import (
    IST,
    Alert,
    AlertSeverity,
    PurchaseOrder,
    Supplier,
    SupplierBill,
    SupplierPayment,
    ist_today,
    utcnow,
)
from app.money import inr
from app.services import india

PAY_MODES = ("cash", "upi", "bank", "cheque")


class PayablesError(ValueError):
    pass


def _open(bill: SupplierBill) -> float:
    return round(bill.amount - bill.paid, 2)


def bill_brief(bill: SupplierBill, today: date | None = None) -> dict:
    today = today or ist_today()
    due = _open(bill)
    return {
        "id": bill.id,
        "supplier_id": bill.supplier_id,
        "po_id": bill.po_id,
        "bill_no": bill.bill_no,
        "bill_date": bill.bill_date.isoformat(),
        "due_date": bill.due_date.isoformat(),
        "amount": bill.amount,
        "paid": bill.paid,
        "balance": due,
        "overdue": due > 0 and bill.due_date < today,
        "days_left": (bill.due_date - today).days,
        "notes": bill.notes,
    }


def bill_from_po(session: Session, po: PurchaseOrder) -> SupplierBill | None:
    """Create the purchase bill for a received PO (called inside receive_po, before its commit)."""
    if session.exec(select(SupplierBill).where(SupplierBill.po_id == po.id)).first():
        return None
    supplier = session.get(Supplier, po.supplier_id)
    amount = india.po_tax(session, po)["grand_total"]
    if amount <= 0:
        return None
    received = (po.received_at or utcnow()).astimezone(IST).date()
    bill = SupplierBill(
        supplier_id=po.supplier_id,
        po_id=po.id,
        bill_no=po.number,
        bill_date=received,
        due_date=received + timedelta(days=supplier.credit_days if supplier else 15),
        amount=round(amount, 2),
        notes=f"Goods received on {po.number}",
    )
    session.add(bill)
    return bill


def add_bill(
    session: Session,
    supplier_id: int,
    amount: float,
    *,
    bill_no: str | None = None,
    bill_date: date | None = None,
    due_date: date | None = None,
    notes: str | None = None,
    actor: str = "user",
) -> SupplierBill:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise PayablesError(f"Supplier {supplier_id} not found")
    if amount <= 0:
        raise PayablesError("Bill amount must be positive")
    bill_date = bill_date or ist_today()
    bill = SupplierBill(
        supplier_id=supplier_id,
        bill_no=(bill_no or "").strip() or None,
        bill_date=bill_date,
        due_date=due_date or bill_date + timedelta(days=supplier.credit_days),
        amount=round(amount, 2),
        notes=notes,
    )
    session.add(bill)
    session.commit()
    session.refresh(bill)
    bus.emit("payable.bill_added", {"supplier": supplier.name, **bill_brief(bill)}, source=actor)
    return bill


def pay_supplier(
    session: Session,
    supplier_id: int,
    amount: float,
    *,
    mode: str = "cash",
    reference: str | None = None,
    actor: str = "user",
) -> dict:
    """Pay a supplier; the money clears the oldest open bills first."""
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise PayablesError(f"Supplier {supplier_id} not found")
    if mode not in PAY_MODES:
        raise PayablesError(f"Payment mode must be one of {', '.join(PAY_MODES)}")
    if amount <= 0:
        raise PayablesError("Payment amount must be positive")
    bills = session.exec(
        select(SupplierBill)
        .where(SupplierBill.supplier_id == supplier_id, SupplierBill.paid < SupplierBill.amount)
        .order_by(SupplierBill.due_date, SupplierBill.id)
    ).all()
    owed = round(sum(_open(b) for b in bills), 2)
    if owed <= 0:
        raise PayablesError(f"Nothing is due to {supplier.name}")
    amount = round(min(amount, owed), 2)
    left = amount
    cleared = []
    for bill in bills:
        if left <= 0:
            break
        part = round(min(left, _open(bill)), 2)
        bill.paid = round(bill.paid + part, 2)
        left = round(left - part, 2)
        cleared.append({"bill_no": bill.bill_no, "paid": part})
        session.add(bill)
    payment = SupplierPayment(supplier_id=supplier_id, amount=amount, mode=mode, reference=reference, created_by=actor)
    session.add(payment)
    session.commit()
    result = {
        "supplier_id": supplier_id,
        "supplier": supplier.name,
        "amount": amount,
        "mode": mode,
        "reference": reference,
        "bills": cleared,
        "balance": round(owed - amount, 2),
    }
    bus.emit("payable.paid", result, source=actor)
    return result


def supplier_dues(session: Session, supplier_id: int | None = None, include_clear: bool = False) -> list[dict]:
    """Per supplier: balance owed, overdue amount, next due date and open bills (biggest balance first)."""
    today = ist_today()
    suppliers = session.exec(select(Supplier).order_by(Supplier.name)).all()
    stmt = select(SupplierBill).order_by(SupplierBill.due_date, SupplierBill.id)
    if supplier_id:
        stmt = stmt.where(SupplierBill.supplier_id == supplier_id)
    bills: dict[int, list[SupplierBill]] = {}
    for bill in session.exec(stmt):
        bills.setdefault(bill.supplier_id, []).append(bill)
    last_pay = {
        p.supplier_id: p
        for p in session.exec(select(SupplierPayment).order_by(SupplierPayment.created_at, SupplierPayment.id)).all()
    }
    rows = []
    for sup in suppliers:
        if supplier_id and sup.id != supplier_id:
            continue
        mine = bills.get(sup.id, [])
        open_bills = [b for b in mine if _open(b) > 0]
        balance = round(sum(_open(b) for b in open_bills), 2)
        if balance <= 0 and not include_clear and not supplier_id:
            continue
        overdue = round(sum(_open(b) for b in open_bills if b.due_date < today), 2)
        pay = last_pay.get(sup.id)
        rows.append(
            {
                "supplier_id": sup.id,
                "name": sup.name,
                "phone": sup.phone,
                "upi_id": sup.upi_id,
                "credit_days": sup.credit_days,
                "balance": balance,
                "overdue": overdue,
                "next_due": open_bills[0].due_date.isoformat() if open_bills else None,
                "bills": [bill_brief(b, today) for b in (mine if supplier_id else open_bills)],
                "last_payment": {"amount": pay.amount, "mode": pay.mode, "date": pay.created_at.isoformat()} if pay else None,
                "upi_link": india.upi_link(sup.upi_id, sup.name, balance, "Payment") if sup.upi_id and balance > 0 else None,
            }
        )
    return sorted(rows, key=lambda r: (-r["overdue"], -r["balance"]))


def payables_summary(session: Session) -> dict:
    dues = supplier_dues(session)
    today = ist_today()
    week = today + timedelta(days=7)
    due_week = 0.0
    for row in dues:
        for b in row["bills"]:
            if date.fromisoformat(b["due_date"]) <= week:
                due_week += b["balance"]
    return {
        "total": round(sum(r["balance"] for r in dues), 2),
        "overdue": round(sum(r["overdue"] for r in dues), 2),
        "due_this_week": round(due_week, 2),
        "suppliers": len(dues),
    }


def supplier_payments_by_mode(session: Session, start: datetime, end: datetime) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in session.exec(select(SupplierPayment).where(SupplierPayment.created_at >= start, SupplierPayment.created_at < end)):
        out[p.mode] = round(out.get(p.mode, 0.0) + p.amount, 2)
    return out


def raise_due_alerts(session: Session, within_days: int = 2) -> list[dict]:
    """Daily: one alert per supplier with bills due within `within_days` (or overdue)."""
    today = ist_today()
    limit = today + timedelta(days=within_days)
    existing = {
        a.message
        for a in session.exec(select(Alert).where(Alert.kind == "payable_due", Alert.resolved == False))  # noqa: E712
    }
    raised = []
    for row in supplier_dues(session):
        due = round(sum(b["balance"] for b in row["bills"] if date.fromisoformat(b["due_date"]) <= limit), 2)
        if due <= 0:
            continue
        late = row["overdue"] > 0
        message = f"Pay {row['name']} {inr(due)} - " + ("overdue" if late else f"due by {row['next_due']}")
        if message in existing:
            continue
        session.add(
            Alert(kind="payable_due", severity=AlertSeverity.CRITICAL if late else AlertSeverity.WARNING, message=message)
        )
        raised.append({"supplier": row["name"], "amount": due, "overdue": late, "message": message})
    session.commit()
    for r in raised:
        bus.emit("payable.due", r, source="scheduler")
    return raised
