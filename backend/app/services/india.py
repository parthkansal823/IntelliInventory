"""India-specific intelligence: GST, e-way bills and the festival demand calendar.

* GST        - optional (toggle for non-registered businesses). GST 2.0 slabs (w.e.f. 22 Sep 2025):
               0 / 5 / 18 / 40% (+3% gold). CGST + SGST intra-state, IGST inter-state; GSTIN checksum.
* E-way bill - required when a consignment worth more than ₹50,000 moves by road.
* Festivals  - Navratri, Dhanteras, Diwali, Chhath, Christmas, Sankranti, Eid, Holi, Rakhi, Ganesh
               Chaturthi, Onam ... with category-level demand uplift, used for festival-aware forecasts
               and a "what to stock, by when" planner.

GST rates on seeded products are illustrative - confirm rates for your HSN codes with your CA.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import quote, urlencode

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    MovementType,
    POStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
    Supplier,
    Warehouse,
    day_start,
    ist_today,
    utcnow,
)
from app.money import inr

EWAY_BILL_THRESHOLD = 50_000  # ₹, consignment value incl. GST
GST_SLABS = (0, 3, 5, 18, 40)  # GST 2.0: 12% and 28% slabs abolished from 22 Sep 2025


def gst_enabled() -> bool:
    """Business-level switch: unregistered sellers (turnover under the threshold) charge no GST."""
    from app.config import get_settings
    from app.services.settings import get_setting

    value = get_setting("gst.enabled")
    return get_settings().gst_enabled if value is None else bool(value)


# --- GSTIN -----------------------------------------------------------------------------

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
STATE_CODES = {
    "Jammu and Kashmir": "01",
    "Himachal Pradesh": "02",
    "Punjab": "03",
    "Chandigarh": "04",
    "Uttarakhand": "05",
    "Haryana": "06",
    "Delhi": "07",
    "Rajasthan": "08",
    "Uttar Pradesh": "09",
    "Bihar": "10",
    "Sikkim": "11",
    "Arunachal Pradesh": "12",
    "Nagaland": "13",
    "Manipur": "14",
    "Mizoram": "15",
    "Tripura": "16",
    "Meghalaya": "17",
    "Assam": "18",
    "West Bengal": "19",
    "Jharkhand": "20",
    "Odisha": "21",
    "Chhattisgarh": "22",
    "Madhya Pradesh": "23",
    "Gujarat": "24",
    "Dadra and Nagar Haveli and Daman and Diu": "26",
    "Maharashtra": "27",
    "Karnataka": "29",
    "Goa": "30",
    "Lakshadweep": "31",
    "Kerala": "32",
    "Tamil Nadu": "33",
    "Puducherry": "34",
    "Andaman and Nicobar Islands": "35",
    "Telangana": "36",
    "Andhra Pradesh": "37",
    "Ladakh": "38",
}
CODE_TO_STATE = {v: k for k, v in STATE_CODES.items()}


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = _GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> tuple[bool, str]:
    g = (gstin or "").strip().upper()
    if len(g) != 15 or any(c not in _GSTIN_CHARS for c in g):
        return False, "GSTIN must be 15 letters/digits"
    if g[:2] not in CODE_TO_STATE:
        return False, f"Unknown state code {g[:2]}"
    if not (g[2:7].isalpha() and g[7:11].isdigit() and g[11].isalpha() and g[13] == "Z"):
        return False, "GSTIN does not follow the PAN-based format (e.g. 27AAACT1234F1Z?)"
    if gstin_check_digit(g[:14]) != g[14]:
        return False, "GSTIN checksum digit is invalid"
    return True, CODE_TO_STATE[g[:2]]


OUTSIDE_INDIA = "Outside India"  # foreign supplier / customer: imports attract IGST


def normalize_state(state: str | None) -> str | None:
    """Canonical Indian state / UT name ("tamil nadu" -> "Tamil Nadu"), or "Outside India"; else ValueError."""
    if not state or not state.strip():
        return None
    wanted = " ".join(state.split()).lower().replace("&", "and")
    if wanted in {"outside india", "foreign", "import", "overseas", "international"}:
        return OUTSIDE_INDIA
    for name in STATE_CODES:
        if name.lower() == wanted:
            return name
    raise ValueError(f"'{state}' is not an Indian state / union territory (use \"{OUTSIDE_INDIA}\" for foreign parties)")


def normalize_phone(phone: str | None) -> str | None:
    """Indian numbers -> "+91 98200 12345"; international numbers (+1, +971, +44 ...) are kept as entered."""
    if not phone or not phone.strip():
        return None
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    international = raw.startswith("+") or raw.startswith("00")
    if international and raw.startswith("00"):
        digits = digits[2:]
    if international and not digits.startswith("91"):
        if not 7 <= len(digits) <= 15:
            raise ValueError("International numbers need a country code and 7-15 digits, e.g. +1 415 555 0100")
        return "+" + " ".join(re.sub(r"[^\d ]", " ", raw.lstrip("+0")).split()) if raw.startswith("+") else f"+{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Enter a 10-digit Indian number, or an international number starting with + and the country code")
    return f"+91 {digits[:5]} {digits[5:]}"


UPI_RE = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z][a-zA-Z0-9]{1,63}$")


def normalize_upi(upi_id: str | None) -> str | None:
    """UPI VPA such as "freshfarm@okhdfcbank"."""
    if not upi_id or not upi_id.strip():
        return None
    vpa = upi_id.strip()
    if not UPI_RE.match(vpa):
        raise ValueError("UPI ID must look like name@bank (e.g. freshfarm@okhdfcbank)")
    return vpa


def upi_link(upi_id: str, payee: str, amount: float, note: str) -> str:
    """Standard UPI deep link - any UPI app (GPay, PhonePe, Paytm, BHIM) can scan it. Free, no gateway."""
    params = {"pa": upi_id, "pn": payee[:50], "am": f"{amount:.2f}", "cu": "INR", "tn": note[:80]}
    return "upi://pay?" + urlencode(params, quote_via=quote)


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    first14 = f"{STATE_CODES[state]}{pan.upper()}{entity}Z"
    return first14 + gstin_check_digit(first14)


# --- GST maths -----------------------------------------------------------------------------


def gst_split(taxable: float, rate: float, interstate: bool) -> dict:
    tax = taxable * rate / 100
    if interstate:
        return {"cgst": 0.0, "sgst": 0.0, "igst": round(tax, 2), "tax": round(tax, 2)}
    half = round(tax / 2, 2)
    return {"cgst": half, "sgst": half, "igst": 0.0, "tax": round(half * 2, 2)}


def is_interstate(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().lower() != b.strip().lower())


def po_tax(session: Session, po: PurchaseOrder) -> dict:
    """GST breakup and e-way bill check for a purchase order (all zero when GST is switched off)."""
    enabled = gst_enabled()
    supplier = session.get(Supplier, po.supplier_id)
    warehouse = session.get(Warehouse, po.warehouse_id)
    interstate = is_interstate(supplier.state if supplier else None, warehouse.state if warehouse else None)
    totals = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "tax": 0.0}
    lines = {}
    for line in po.lines:
        product = session.get(Product, line.product_id)
        rate = (product.gst_rate or 0.0) if (product and enabled) else 0.0
        taxable = line.quantity * line.unit_cost
        split = gst_split(taxable, rate, interstate)
        lines[line.id] = {
            "gst_rate": product.gst_rate if product else None,
            "hsn_code": product.hsn_code if product else None,
            **split,
        }
        totals["taxable"] += taxable
        for k in ("cgst", "sgst", "igst", "tax"):
            totals[k] += split[k]
    totals = {k: round(v, 2) for k, v in totals.items()}
    grand = round(totals["taxable"] + totals["tax"], 2)
    return {
        "enabled": enabled,
        "lines": lines,
        "interstate": interstate,
        "supplier_state": supplier.state if supplier else None,
        "warehouse_state": warehouse.state if warehouse else None,
        **totals,
        "grand_total": grand,
        "eway_bill_required": enabled and grand > EWAY_BILL_THRESHOLD,
    }


def transfer_eway(session: Session, product: Product, qty: int, src: Warehouse, dst: Warehouse) -> dict:
    value = qty * product.unit_cost * (1 + (product.gst_rate or 0) / 100)
    interstate = is_interstate(src.state, dst.state)
    required = gst_enabled() and value > EWAY_BILL_THRESHOLD
    note = None
    if required:
        note = f"Consignment value {inr(value)} exceeds {inr(EWAY_BILL_THRESHOLD)} — generate an e-way bill before dispatch" + (
            f" (inter-state {src.state} → {dst.state}: a stock transfer between GSTINs is a taxable supply)."
            if interstate
            else "."
        )
    return {"value": round(value, 2), "interstate": interstate, "eway_bill_required": required, "note": note}


def gst_report(session: Session, days: int = 30) -> dict:
    """GSTR-3B style estimate: output tax on sales vs input tax credit on received purchases, by slab."""
    if not gst_enabled():
        return {
            "enabled": False,
            "days": days,
            "slabs": [],
            "output_tax": 0,
            "input_tax_credit": 0,
            "net_payable": 0,
            "carry_forward_credit": 0,
            "missing_rates": 0,
            "note": "GST is switched off (not GST-registered).",
        }
    since = day_start(utcnow().date() - timedelta(days=days - 1))
    slabs: dict[float, dict] = {}

    def slab(rate: float) -> dict:
        return slabs.setdefault(
            rate, {"rate": rate, "sales_taxable": 0.0, "output_tax": 0.0, "purchase_taxable": 0.0, "input_tax": 0.0}
        )

    sales = session.exec(
        select(Product.gst_rate, func.sum(-StockMovement.quantity * Product.unit_price))
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.type == MovementType.SALE, StockMovement.created_at >= since, Product.gst_rate.is_not(None))
        .group_by(Product.gst_rate)
    ).all()
    for rate, taxable in sales:
        s = slab(float(rate))
        s["sales_taxable"] += float(taxable or 0)
        s["output_tax"] += float(taxable or 0) * float(rate) / 100

    received = session.exec(
        select(PurchaseOrderLine, Product)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .where(PurchaseOrder.status == POStatus.RECEIVED, PurchaseOrder.received_at >= since)
    ).all()
    for line, product in received:
        if product.gst_rate is None:
            continue
        s = slab(product.gst_rate)
        taxable = line.quantity * line.unit_cost
        s["purchase_taxable"] += taxable
        s["input_tax"] += taxable * product.gst_rate / 100

    rows = [{k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()} for _, s in sorted(slabs.items())]
    output_tax = round(sum(r["output_tax"] for r in rows), 2)
    input_tax = round(sum(r["input_tax"] for r in rows), 2)
    missing = session.exec(select(func.count()).select_from(Product).where(Product.is_active, Product.gst_rate.is_(None))).one()
    return {
        "enabled": True,
        "missing_rates": missing,
        "days": days,
        "slabs": rows,
        "output_tax": output_tax,
        "input_tax_credit": input_tax,
        "net_payable": round(max(0.0, output_tax - input_tax), 2),
        "carry_forward_credit": round(max(0.0, input_tax - output_tax), 2),
        "note": "Estimate for planning only - sales assumed intra-state and prices GST-exclusive. File returns with your CA.",
    }


# --- Festivals -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Festival:
    slug: str
    name: str
    day: date
    window: int  # buying days before the festival where demand is lifted
    uplift: dict[str, float] = field(default_factory=dict)  # category key -> demand multiplier
    emoji: str = "🎉"
    note: str = ""


# Dates cross-checked against panchang calendars (lunar festivals can shift by a day regionally).
FESTIVALS: tuple[Festival, ...] = (
    Festival("navratri-2026", "Navratri", date(2026, 10, 11), 10, {"grocery": 1.3, "beauty": 1.2, "home": 1.2}, "🪔"),
    Festival("dussehra-2026", "Dussehra", date(2026, 10, 20), 7, {"electronics": 1.3, "home": 1.2, "toys": 1.2}, "🏹"),
    Festival("karwa-chauth-2026", "Karwa Chauth", date(2026, 10, 29), 5, {"beauty": 1.5, "accessories": 1.2}, "🌙"),
    Festival(
        "dhanteras-2026",
        "Dhanteras",
        date(2026, 11, 6),
        7,
        {"home": 1.8, "electronics": 1.6},
        "🪙",
        "Utensils, appliances & gold-buying day",
    ),
    Festival(
        "diwali-2026",
        "Diwali",
        date(2026, 11, 8),
        14,
        {"electronics": 1.9, "grocery": 1.8, "home": 1.6, "accessories": 1.5, "toys": 1.4, "beauty": 1.4, "office": 1.1},
        "🪔",
        "Biggest retail season of the year",
    ),
    Festival("bhai-dooj-2026", "Bhai Dooj", date(2026, 11, 10), 3, {"grocery": 1.3, "accessories": 1.2}, "🎁"),
    Festival("chhath-2026", "Chhath Puja", date(2026, 11, 15), 5, {"grocery": 1.4}, "🌅", "Strong in Bihar, Jharkhand, UP"),
    Festival("christmas-2026", "Christmas", date(2026, 12, 25), 10, {"toys": 1.7, "electronics": 1.3, "grocery": 1.3}, "🎄"),
    Festival("new-year-2027", "New Year", date(2027, 1, 1), 5, {"grocery": 1.3, "electronics": 1.2}, "🎆"),
    Festival("sankranti-2027", "Makar Sankranti / Pongal", date(2027, 1, 14), 5, {"grocery": 1.5, "home": 1.2}, "🪁"),
    Festival(
        "republic-day-2027",
        "Republic Day sales",
        date(2027, 1, 26),
        7,
        {"electronics": 1.5, "accessories": 1.4, "home": 1.3},
        "🇮🇳",
    ),
    Festival(
        "eid-2027",
        "Eid al-Fitr",
        date(2027, 3, 10),
        10,
        {"grocery": 1.6, "beauty": 1.3, "accessories": 1.2},
        "🌙",
        "Date depends on moon sighting",
    ),
    Festival("holi-2027", "Holi", date(2027, 3, 22), 7, {"grocery": 1.4, "beauty": 1.3}, "🎨"),
    Festival(
        "rakhi-2027", "Raksha Bandhan", date(2027, 8, 17), 7, {"grocery": 1.5, "accessories": 1.3, "electronics": 1.2}, "🧵"
    ),
    Festival(
        "ganesh-2027", "Ganesh Chaturthi", date(2027, 9, 4), 7, {"grocery": 1.3, "home": 1.2}, "🐘", "Strong in Maharashtra"
    ),
    Festival("onam-2027", "Onam", date(2027, 9, 12), 7, {"grocery": 1.4, "home": 1.3}, "🌼", "Strong in Kerala"),
)

_CATEGORY_KEYS = (
    ("grocery", ("grocer", "food", "sweet", "snack", "dry fruit", "beverage", "fmcg")),
    ("electronics", ("electron", "mobile", "appliance", "gadget")),
    ("home", ("home", "kitchen", "utensil", "decor")),
    ("beauty", ("beauty", "health", "cosmetic", "personal care")),
    ("accessories", ("accessor", "jewel", "fashion", "gift")),
    ("toys", ("toy", "game")),
    ("office", ("office", "stationer")),
    ("sports", ("sport", "fitness", "outdoor")),
)


def category_key(category: str | None) -> str | None:
    name = (category or "").lower()
    return next((key for key, words in _CATEGORY_KEYS if any(w in name for w in words)), None)


def upcoming_festivals(today: date | None = None, horizon_days: int = 365) -> list[Festival]:
    today = today or ist_today()
    return [f for f in FESTIVALS if today <= f.day <= today + timedelta(days=horizon_days)]


def festival_multiplier(category: str | None, day: date) -> tuple[float, str | None]:
    """Demand multiplier for a category on a given day (max over overlapping festival windows)."""
    key = category_key(category)
    best, name = 1.0, None
    if key is None:
        return best, name
    for f in FESTIVALS:
        if f.day - timedelta(days=f.window) <= day <= f.day and f.uplift.get(key, 1.0) > best:
            best, name = f.uplift[key], f.name
    return best, name


def festival_calendar(today: date | None = None) -> list[dict]:
    today = today or ist_today()
    return [
        {
            "slug": f.slug,
            "name": f.name,
            "date": f.day.isoformat(),
            "days_away": (f.day - today).days,
            "window_days": f.window,
            "buying_starts": (f.day - timedelta(days=f.window)).isoformat(),
            "emoji": f.emoji,
            "note": f.note,
            "categories": {k: v for k, v in sorted(f.uplift.items(), key=lambda kv: -kv[1])},
        }
        for f in upcoming_festivals(today)
    ]


def festival_plan(session: Session, slug: str | None = None, today: date | None = None) -> dict:
    """What to stock, and by when, for an upcoming festival."""
    from app.services.analytics import compute_metrics  # local import: analytics imports this module

    today = today or ist_today()
    upcoming = upcoming_festivals(today, 180)
    festival = next((f for f in upcoming if slug and (f.slug == slug or slug.lower() in f.name.lower())), None)
    if festival is None:
        festival = next((f for f in upcoming if f.slug.startswith("diwali")), None) if slug is None else None
        festival = festival or (upcoming[0] if upcoming else None)
    if festival is None:
        return {"festival": None, "items": []}

    window_start = festival.day - timedelta(days=festival.window)
    items = []
    for m in compute_metrics(session):
        uplift = festival.uplift.get(category_key(m.category) or "", 1.0)
        if uplift <= 1.0 or m.avg_daily_demand <= 0:
            continue
        days_to_festival = max((festival.day - today).days, 0)
        base_need = m.avg_daily_demand * days_to_festival
        extra = m.avg_daily_demand * (uplift - 1) * festival.window
        available = m.on_hand + m.on_order
        shortfall = base_need + extra + m.safety_stock - available
        order_by = window_start - timedelta(days=m.lead_time_days)
        moq = 1
        qty = 0
        if shortfall > 0:
            product = session.get(Product, m.product_id)
            moq = max(product.min_order_qty, 1) if product else 1
            qty = int(math.ceil(shortfall / moq) * moq)
        items.append(
            {
                "product_id": m.product_id,
                "sku": m.sku,
                "name": m.name,
                "category": m.category,
                "supplier": m.supplier,
                "supplier_id": m.supplier_id,
                "uplift": uplift,
                "avg_daily_demand": m.avg_daily_demand,
                "extra_units": int(round(extra)),
                "extra_revenue": round(extra * m.unit_price, 2),
                "on_hand": m.on_hand,
                "on_order": m.on_order,
                "suggested_order_qty": qty,
                "estimated_cost": round(qty * m.unit_cost, 2),
                "order_by": order_by.isoformat(),
                "days_left_to_order": (order_by - today).days,
                "urgent": qty > 0 and order_by <= today + timedelta(days=3),
            }
        )
    items.sort(key=lambda i: (i["suggested_order_qty"] == 0, i["order_by"], -i["extra_revenue"]))
    need = [i for i in items if i["suggested_order_qty"]]
    return {
        "festival": festival_calendar(today)[[f.slug for f in upcoming_festivals(today)].index(festival.slug)],
        "items": items,
        "summary": {
            "products_affected": len(items),
            "products_to_order": len(need),
            "extra_units": sum(i["extra_units"] for i in items),
            "extra_revenue": round(sum(i["extra_revenue"] for i in items), 2),
            "order_value": round(sum(i["estimated_cost"] for i in need), 2),
            "earliest_order_by": min((i["order_by"] for i in need), default=None),
        },
    }
