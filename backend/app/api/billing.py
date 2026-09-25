"""Billing endpoints: invoices, payments, customers (khata) and the business profile printed on bills."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from app.models import Customer, Role, utcnow
from app.security import ROLE_RANK, CurrentUser, DbSession, ManagerUser, StaffUser, actor
from app.services import billing, offers, voice

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


@router.get("/api/billing/day-close")
def day_close(session: DbSession, _: CurrentUser, day: date | None = None) -> dict:
    """Aaj ka hisaab (day-end closing) - for today unless `day` (YYYY-MM-DD) is given."""
    return billing.day_close(session, day)


@router.get("/api/billing/dues")
def dues(session: DbSession, _: CurrentUser) -> list[dict]:
    return billing.customer_dues(session)


@router.get("/api/billing/offers")
def get_offers(_: CurrentUser) -> dict:
    """Offers & loyalty settings (switched off unless the shop turns them on)."""
    return offers.offers_config()


class OffersIn(BaseModel):
    enabled: bool | None = None
    loyalty: dict | None = None
    offers: list[dict] | None = None


@router.put("/api/billing/offers")
def put_offers(body: OffersIn, _: ManagerUser) -> dict:
    try:
        return offers.update_offers_config(body.model_dump(exclude_unset=True))
    except offers.OfferError as exc:
        raise HTTPException(400, str(exc)) from exc


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/api/billing/parse")
def parse_order(session: DbSession, body: ParseIn, _: CurrentUser) -> dict:
    """Voice / quick-type billing: "do kilo aata aur ek maggi" -> matched products with quantities."""
    return voice.parse_order(session, body.text)


@router.get("/api/credit-notes")
def credit_notes(session: DbSession, _: CurrentUser, limit: int = 100) -> list[dict]:
    return billing.list_credit_notes(session, max(1, min(limit, 500)))


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


@router.get("/api/customers/{customer_id}")
def customer_history(session: DbSession, customer_id: int, _: CurrentUser) -> dict:
    """Bills, favourite items, total spent, loyalty points and udhaar balance of one customer."""
    return billing.customer_history(session, billing.find_customer(session, customer_id))


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


class PaymentPart(BaseModel):
    mode: str
    amount: float = Field(ge=0)
    reference: str | None = None


class InvoiceIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1)
    customer_id: int | None = None
    customer: CustomerIn | None = None
    warehouse: str | int | None = None
    payment_mode: str = "cash"
    amount_paid: float | None = Field(default=None, ge=0)
    payments: list[PaymentPart] | None = None  # split payment, e.g. part cash + part UPI
    prices_include_gst: bool = False
    notes: str | None = None
    redeem_points: int = Field(default=0, ge=0)
    apply_offers: bool = False  # the app applies offers itself and sends the discounts
    client_ref: str | None = Field(default=None, max_length=64)  # offline bills: sync key (sent again = same bill)
    created_at: datetime | None = None  # offline bills: when the bill was really made


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


@router.get("/api/invoices/export.csv", response_class=PlainTextResponse)
def export_sales_register(session: DbSession, _: ManagerUser, days: int = 31) -> PlainTextResponse:
    """Sales register CSV (GSTR-1 friendly) for your CA or Tally."""
    return PlainTextResponse(
        billing.sales_register_csv(session, max(1, min(days, 366))),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sales-register-{days}d.csv"'},
    )


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
        payments=[p.model_dump() for p in body.payments] if body.payments else None,
        prices_include_gst=body.prices_include_gst,
        notes=body.notes,
        actor=actor(user),
        redeem_points=body.redeem_points,
        apply_offers=body.apply_offers,
        client_ref=body.client_ref,
        created_at=_offline_time(body.created_at) if body.client_ref else None,
    )
    return billing.invoice_detail(session, inv)


def _offline_time(when: datetime | None) -> datetime | None:
    """Accept the original time of an offline bill if it is plausible (up to 7 days old, not in the future)."""
    if when is None:
        return None
    if when.tzinfo is None:
        raise HTTPException(422, "created_at needs a timezone")
    now = utcnow()
    return when if now - timedelta(days=7) <= when <= now + timedelta(minutes=5) else None


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


class ReturnLine(BaseModel):
    line_id: int
    quantity: int = Field(gt=0)


class ReturnIn(BaseModel):
    items: list[ReturnLine] = Field(min_length=1)
    refund_mode: str = "cash"
    reason: str | None = Field(default=None, max_length=200)


BIG_REFUND = 2000  # refunds above this need a manager


@router.post("/api/invoices/{invoice_id}/return")
def return_items(session: DbSession, invoice_id: int, body: ReturnIn, user: StaffUser) -> dict:
    """Sales return / wapsi: take back some items, issue a credit note, put the stock back."""
    inv = billing.find_invoice(session, invoice_id)
    items = [i.model_dump() for i in body.items]
    if ROLE_RANK[user.role] < ROLE_RANK[Role.MANAGER]:
        by_id = {ln.id: ln for ln in inv.lines}
        value = sum(
            by_id[i["line_id"]].total * i["quantity"] / by_id[i["line_id"]].quantity for i in items if i["line_id"] in by_id
        )
        if value - billing.balance_of(inv) > BIG_REFUND:
            raise HTTPException(403, f"Refunds above Rs {BIG_REFUND} need a manager")
    note = billing.return_items(session, inv, items, refund_mode=body.refund_mode, reason=body.reason, actor=actor(user))
    session.refresh(inv)
    return {"credit_note": billing.credit_note_brief(note), "invoice": billing.invoice_detail(session, inv)}
