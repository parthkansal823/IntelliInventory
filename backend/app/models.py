"""SQLModel tables."""

from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

# India-only app: one fixed timezone (no DST in India). A fixed offset needs no tz database (works on Windows too).
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def utcnow() -> datetime:
    return datetime.now(UTC)


def ist_today() -> date:
    """Today's date in India."""
    return datetime.now(IST).date()


def day_start(d) -> datetime:
    """Midnight UTC for a date."""
    return datetime.combine(d, datetime.min.time(), tzinfo=UTC)


class MovementType(StrEnum):
    RECEIPT = "receipt"
    SALE = "sale"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RETURN = "return"


class POStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ORDERED = "ordered"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


# --- Catalog -----------------------------------------------------------------


class Category(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    color: str = "#6366f1"


class Supplier(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: str | None = None
    phone: str | None = None
    lead_time_days: int = 7
    rating: float = 4.0
    gstin: str | None = None  # 15-char GST identification number
    state: str | None = None  # Indian state, decides CGST+SGST vs IGST
    upi_id: str | None = None  # e.g. freshfarm@okhdfcbank - POs show a UPI "scan to pay" QR
    credit_days: int = 15  # days the supplier gives before a purchase bill is due (supplier udhaar)


class Warehouse(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    location: str | None = None
    state: str | None = None


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    sku: str = Field(index=True, unique=True)
    name: str = Field(index=True)
    description: str | None = None
    category_id: int | None = Field(default=None, foreign_key="category.id")
    supplier_id: int | None = Field(default=None, foreign_key="supplier.id")
    unit_cost: float = 0.0
    unit_price: float = 0.0
    # Manual overrides; when null the analytics engine computes them from demand.
    reorder_point: int | None = None
    safety_stock: int | None = None
    min_order_qty: int = 1
    lead_time_days: int | None = None
    hsn_code: str | None = None  # HSN code for GST (optional; AI can fill it later)
    gst_rate: float | None = None  # GST 2.0 slab in %: 0, 3 (gold/silver), 5, 18, 40; None = not set yet
    gst_source: str | None = None  # "manual" | "ai" (AI-suggested, pending review)
    barcode: str | None = Field(default=None, index=True)  # EAN-13 / UPC printed on the pack (scanner fills it)
    unit: str = "pcs"  # pcs | kg | g | L | ml | pack | box | dozen - shown on bills
    expiry_date: date | None = None  # nearest expiry of the stock on the shelf (FMCG / dairy / bakery)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    stock_levels: list["StockLevel"] = Relationship(back_populates="product")


class StockLevel(SQLModel, table=True):
    product_id: int = Field(foreign_key="product.id", primary_key=True)
    warehouse_id: int = Field(foreign_key="warehouse.id", primary_key=True)
    quantity: int = 0

    product: Product = Relationship(back_populates="stock_levels")


class StockMovement(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    warehouse_id: int = Field(foreign_key="warehouse.id")
    type: MovementType = Field(index=True)
    quantity: int  # signed: positive adds stock, negative removes it
    reference: str | None = None
    note: str | None = None
    actor: str = "system"
    created_at: datetime = Field(default_factory=utcnow, index=True)


# --- Purchasing --------------------------------------------------------------


class PurchaseOrder(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)
    supplier_id: int = Field(foreign_key="supplier.id")
    warehouse_id: int = Field(foreign_key="warehouse.id")
    status: POStatus = Field(default=POStatus.DRAFT, index=True)
    created_by: str = "user"
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    expected_at: datetime | None = None
    received_at: datetime | None = None

    lines: list["PurchaseOrderLine"] = Relationship(
        back_populates="order", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class PurchaseOrderLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="purchaseorder.id", index=True)
    product_id: int = Field(foreign_key="product.id")
    quantity: int
    unit_cost: float

    order: PurchaseOrder = Relationship(back_populates="lines")


# --- Billing (sales invoices, customer khata) ----------------------------------------------


class InvoiceStatus(StrEnum):
    PAID = "paid"
    PARTIAL = "partial"
    UNPAID = "unpaid"  # credit sale (udhaar) - shows up in the customer's khata
    CANCELLED = "cancelled"


class Customer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    phone: str | None = Field(default=None, index=True)  # +91 ... or any international number
    email: str | None = None
    gstin: str | None = None  # B2B buyers - printed on the tax invoice
    state: str | None = None  # Indian state or "Outside India" - decides the place of supply
    address: str | None = None
    points: int = 0  # loyalty points balance (only used when loyalty is switched on)
    created_at: datetime = Field(default_factory=utcnow)


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)  # INV/26-27/00001 - per financial year, max 16 chars (GST rule 46)
    kind: str = "tax_invoice"  # tax_invoice | bill_of_supply (GST off) | export_invoice
    customer_id: int | None = Field(default=None, foreign_key="customer.id", index=True)
    customer_name: str = "Walk-in customer"
    customer_phone: str | None = None
    customer_gstin: str | None = None
    customer_address: str | None = None
    place_of_supply: str | None = None
    warehouse_id: int | None = Field(default=None, foreign_key="warehouse.id")
    status: InvoiceStatus = Field(default=InvoiceStatus.PAID, index=True)
    payment_mode: str = "cash"  # cash | upi | card | bank | credit
    prices_include_gst: bool = False
    subtotal: float = 0.0  # sum of qty x price as entered
    discount: float = 0.0
    taxable: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    tax: float = 0.0
    round_off: float = 0.0
    total: float = 0.0
    amount_paid: float = 0.0
    amount_returned: float = 0.0  # value of credit notes (sales returns) against this bill
    amount_refunded: float = 0.0  # money handed back for those returns (the rest reduced the balance)
    points_earned: int = 0
    client_ref: str | None = Field(default=None, index=True, unique=True)  # offline bills: idempotency key
    notes: str | None = None
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow, index=True)
    cancelled_at: datetime | None = None

    lines: list["InvoiceLine"] = Relationship(back_populates="invoice", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class InvoiceLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    product_id: int = Field(foreign_key="product.id")
    warehouse_id: int = Field(foreign_key="warehouse.id")
    sku: str
    name: str
    hsn_code: str | None = None
    quantity: int
    unit_price: float  # as entered (GST-inclusive when the invoice says so)
    discount_pct: float = 0.0
    gst_rate: float = 0.0
    taxable: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    returned_qty: int = 0

    invoice: Invoice = Relationship(back_populates="lines")


class Payment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    amount: float
    mode: str = "cash"
    reference: str | None = None  # UPI UTR / cheque no.
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow)


class CreditNote(SQLModel, table=True):
    """Sales return against a bill (GST credit note). Stock goes back, the refund is cash/UPI or adjusts udhaar."""

    id: int | None = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)  # CN/26-27/00001
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    customer_id: int | None = Field(default=None, foreign_key="customer.id")
    customer_name: str = "Walk-in customer"
    taxable: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    refund_mode: str = "cash"  # cash | upi | adjust (reduces the udhaar balance)
    refunded: float = 0.0  # money handed back (cash/UPI); the rest adjusted the balance
    reason: str | None = None
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow, index=True)

    lines: list["CreditNoteLine"] = Relationship(back_populates="note", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class CreditNoteLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    note_id: int = Field(foreign_key="creditnote.id", index=True)
    invoice_line_id: int = Field(foreign_key="invoiceline.id")
    product_id: int = Field(foreign_key="product.id")
    warehouse_id: int = Field(foreign_key="warehouse.id")
    name: str
    quantity: int
    taxable: float = 0.0
    tax: float = 0.0
    total: float = 0.0

    note: CreditNote = Relationship(back_populates="lines")


# --- Supplier khata (payables) ---------------------------------------------------------------


class SupplierBill(SQLModel, table=True):
    """A purchase bill we owe the supplier (auto-created when a PO is received, or entered by hand)."""

    id: int | None = Field(default=None, primary_key=True)
    supplier_id: int = Field(foreign_key="supplier.id", index=True)
    po_id: int | None = Field(default=None, foreign_key="purchaseorder.id")
    bill_no: str | None = None  # the supplier's own invoice number
    bill_date: date
    due_date: date = Field(index=True)
    amount: float
    paid: float = 0.0
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SupplierPayment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    supplier_id: int = Field(foreign_key="supplier.id", index=True)
    amount: float
    mode: str = "cash"  # cash | upi | bank | cheque
    reference: str | None = None
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow, index=True)


# --- Automation / observability ---------------------------------------------


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # low_stock | stockout | anomaly | overstock
    severity: AlertSeverity = AlertSeverity.WARNING
    product_id: int | None = Field(default=None, foreign_key="product.id")
    message: str
    resolved: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class EventLog(SQLModel, table=True):
    """Append-only audit trail of every domain event."""

    id: int | None = Field(default=None, primary_key=True)
    type: str = Field(index=True)
    source: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Webhook(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    url: str
    events: list[str] = Field(default_factory=lambda: ["*"], sa_column=Column(JSON))
    secret: str | None = None
    active: bool = True
    last_status: int | None = None
    last_error: str | None = None
    last_delivery_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(JSON))


# --- Agents --------------------------------------------------------------------


class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str = "New conversation"
    agent: str = "copilot"
    provider: str = "offline"
    # Neutral transcript (see app.agents.runtime) plus provider-native payloads.
    messages: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    # UI-facing event log so the chat can be re-rendered faithfully.
    display: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class ApprovalRequest(SQLModel, table=True):
    """Human-in-the-loop gate for agent write actions."""

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str | None = Field(default=None, index=True)
    agent: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reason: str | None = None
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, index=True)
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None


# --- Users & auth --------------------------------------------------------------


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    STAFF = "staff"
    VIEWER = "viewer"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str
    role: Role = Role.STAFF
    password_hash: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


# --- Warehouse operations ------------------------------------------------------


class CountStatus(StrEnum):
    OPEN = "open"
    POSTED = "posted"
    CANCELLED = "cancelled"


class CycleCount(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)
    warehouse_id: int = Field(foreign_key="warehouse.id")
    scope: str = "all"  # all | A | B | C
    status: CountStatus = Field(default=CountStatus.OPEN, index=True)
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow)
    posted_at: datetime | None = None

    lines: list["CycleCountLine"] = Relationship(back_populates="count", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class CycleCountLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    count_id: int = Field(foreign_key="cyclecount.id", index=True)
    product_id: int = Field(foreign_key="product.id")
    expected: int
    counted: int | None = None

    count: CycleCount = Relationship(back_populates="lines")


# --- Automation logs -------------------------------------------------------------


class WebhookDelivery(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    webhook_id: int = Field(foreign_key="webhook.id", index=True)
    event_type: str
    status_code: int | None = None
    success: bool = False
    attempts: int = 1
    error: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AgentTrace(SQLModel, table=True):
    """One agent run: timeline of LLM calls, hook decisions and tool calls."""

    id: str = Field(primary_key=True)
    conversation_id: str | None = Field(default=None, index=True)
    agent: str
    provider: str
    model: str | None = None
    trigger: str = "chat"  # chat | autopilot | schedule | approval
    input: str = ""
    output: str = ""
    status: str = "running"  # running | ok | error
    steps: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # briefing | anomaly_scan
    title: str
    content: str  # markdown
    created_by: str = "agent:copilot"
    created_at: datetime = Field(default_factory=utcnow, index=True)
