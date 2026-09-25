"""Supplier khata (payables): purchase bills and payments to suppliers."""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.security import CurrentUser, DbSession, ManagerUser, actor
from app.services import payables

router = APIRouter(tags=["payables"])


@router.get("/api/payables")
def dues(session: DbSession, _: CurrentUser, all: bool = False) -> dict:
    return {"summary": payables.payables_summary(session), "suppliers": payables.supplier_dues(session, include_clear=all)}


@router.get("/api/payables/{supplier_id}")
def supplier(session: DbSession, supplier_id: int, _: CurrentUser) -> dict:
    rows = payables.supplier_dues(session, supplier_id)
    if not rows:
        raise HTTPException(404, "Supplier not found")
    return rows[0]


class BillIn(BaseModel):
    supplier_id: int
    amount: float = Field(gt=0)
    bill_no: str | None = Field(default=None, max_length=40)
    bill_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=200)


@router.post("/api/supplier-bills", status_code=201)
def add_bill(session: DbSession, body: BillIn, user: ManagerUser) -> dict:
    try:
        bill = payables.add_bill(
            session,
            body.supplier_id,
            body.amount,
            bill_no=body.bill_no,
            bill_date=body.bill_date,
            due_date=body.due_date,
            notes=body.notes,
            actor=actor(user),
        )
    except payables.PayablesError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 400, str(exc)) from exc
    return payables.bill_brief(bill)


class PayIn(BaseModel):
    supplier_id: int
    amount: float = Field(gt=0)
    mode: str = "cash"
    reference: str | None = Field(default=None, max_length=60)


@router.post("/api/supplier-payments", status_code=201)
def pay(session: DbSession, body: PayIn, user: ManagerUser) -> dict:
    try:
        return payables.pay_supplier(
            session, body.supplier_id, body.amount, mode=body.mode, reference=body.reference, actor=actor(user)
        )
    except payables.PayablesError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 400, str(exc)) from exc
