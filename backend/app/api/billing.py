"""Billing endpoints: invoices, payments, customers (khata) and the business profile printed on bills."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from app.models import Customer
from app.security import CurrentUser, DbSession, ManagerUser, StaffUser, actor
from app.services import billing

router = APIRouter(tags=["billing"])


class ProfileIn(BaseModel):
    name: str | None = None
    address: str | None = None
    gstin: str | None = None
    state: str | None = None
    phone: str | None = None
    email: str | None = None
    upi_id: str | None = None
    invoice_prefix: str | None = None
    terms: str | None = None


@router.get("/api/billing/profile")
def get_profile(_: CurrentUser) -> dict:
    return billing.business_profile()


@router.patch("/api/billing/profile")
def update_profile(body: ProfileIn, _: ManagerUser) -> dict:
    return billing.update_business_profile(body.model_dump(exclude_unset=True))


@router.get("/api/billing/summary")
def summary(session: DbSession, _: CurrentUser, days: int = 30) -> dict:
    return billing.billing_summary(session, max(1, min(days, 365)))


@router.get("/api/billing/dues")
def dues(session: DbSession, _: CurrentUser) -> list[dict]:
    return billing.customer_dues(session)


class CustomerIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None
    state: str | None = None
    address: str | None = None


@router.get("/api/customers")
def customers(session: DbSession, _: CurrentUser, q: str | None = None) -> list[dict]:
    return billing.list_customers(session, q)


@router.post("/api/customers", status_code=201)
def create_customer(session: DbSession, body: CustomerIn, _: StaffUser) -> Customer:
    fields = billing.customer_fields(body.model_dump())
    if fields["phone"] and session.exec(select(Customer).where(Customer.phone == fields["phone"])).first():
        raise HTTPException(409, f"A customer with phone {fields['phone']} already exists")
    customer = Customer(**fields)
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@router.patch("/api/customers/{customer_id}")
def update_customer(session: DbSession, customer_id: int, body: CustomerIn, _: StaffUser) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    for key, value in billing.customer_fields(body.model_dump()).items():
        setattr(customer, key, value)
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


class ItemIn(BaseModel):
    product_id: int | None = None
    sku: str | None = None
    quantity: int = Field(gt=0)
    unit_price: float | None = Field(default=None, ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)


class InvoiceIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1)
    customer_id: int | None = None
    customer: CustomerIn | None = None
    warehouse: str | int | None = None
    payment_mode: str = "cash"
    amount_paid: float | None = Field(default=None, ge=0)
    prices_include_gst: bool = False
    notes: str | None = None


@router.get("/api/invoices")
def invoices(
    session: DbSession,
    _: CurrentUser,
    status: str | None = None,
    q: str | None = None,
    customer_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    return billing.list_invoices(session, status, q, customer_id, max(1, min(limit, 500)))


@router.get("/api/invoices/{invoice_id}")
def invoice(session: DbSession, invoice_id: int, _: CurrentUser) -> dict:
    return billing.invoice_detail(session, billing.find_invoice(session, invoice_id))


@router.post("/api/invoices", status_code=201)
def create_invoice(session: DbSession, body: InvoiceIn, user: StaffUser) -> dict:
    inv = billing.create_invoice(
        session,
        [i.model_dump() for i in body.items],
        customer_id=body.customer_id,
        customer=body.customer.model_dump() if body.customer else None,
        warehouse_ref=body.warehouse,
        payment_mode=body.payment_mode,
        amount_paid=body.amount_paid,
        prices_include_gst=body.prices_include_gst,
        notes=body.notes,
        actor=actor(user),
    )
    return billing.invoice_detail(session, inv)


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    mode: str = "cash"
    reference: str | None = None


@router.post("/api/invoices/{invoice_id}/payments")
def pay(session: DbSession, invoice_id: int, body: PaymentIn, user: StaffUser) -> dict:
    inv = billing.find_invoice(session, invoice_id)
    billing.record_payment(session, inv, body.amount, body.mode, body.reference, actor=actor(user))
    return billing.invoice_detail(session, inv)


class CancelIn(BaseModel):
    reason: str | None = None


@router.post("/api/invoices/{invoice_id}/cancel")
def cancel(session: DbSession, invoice_id: int, body: CancelIn, user: ManagerUser) -> dict:
    inv = billing.find_invoice(session, invoice_id)
    billing.cancel_invoice(session, inv, body.reason, actor=actor(user))
    return billing.invoice_detail(session, inv)
