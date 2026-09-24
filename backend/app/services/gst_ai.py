"""AI GST classification: suggest an HSN code and GST 2.0 rate from a product name.

Two free engines:
* Hermes (if a model is reachable, e.g. local Ollama) - asked for a strict JSON answer, then validated.
* Built-in rules - keyword table of common Indian retail goods with GST 2.0 rates (w.e.f. 22 Sep 2025).

Suggestions are saved with gst_source="ai" so a human can review them. Always confirm with your CA.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from sqlmodel import select

from app.db import session_scope
from app.models import Category, Product

log = logging.getLogger("intelliinventory.gst_ai")
DEFAULT_SLABS = [0, 3, 5, 18, 40]  # GST 2.0 (22 Sep 2025); editable in Settings because rates change


def current_slabs() -> list[float]:
    from app.services.settings import get_setting

    return [float(x) for x in (get_setting("gst.slabs") or DEFAULT_SLABS)]


def nearest_slab(rate: float, slabs: list[float]) -> float:
    return min(slabs, key=lambda s: (abs(s - rate), -s))


# (pattern, HSN, rate, reason) - first match wins, so specific rules come before generic ones.
RULES: list[tuple[str, str, float, str]] = [
    (r"gold|silver|jewel", "7113", 3, "Jewellery of precious metal (3%)"),
    (r"cigarette|tobacco|gutkha|pan masala|bidi", "2402", 40, "Tobacco products (40% special rate)"),
    (r"\bcola\b|soft drink|aerated|\bsoda\b|energy drink", "2202", 40, "Aerated / caffeinated beverages (40%)"),
    (
        r"exercise book|notebook|pencil|eraser|sharpener|crayon|textbook|\bbooks?\b",
        "4820",
        0,
        "Exercise books, notebooks & pencils are nil-rated",
    ),
    (r"\bmilk\b(?!.*(chocolate|powder))|\bcurd\b|\bdahi\b|lassi|buttermilk", "0401", 0, "Fresh milk & curd are nil-rated"),
    (r"paneer|chhena", "0406", 0, "Paneer is nil-rated"),
    (r"\bbread\b|\broti\b|chapati|paratha|khakhra", "1905", 0, "Indian breads are nil-rated"),
    (r"\beggs?\b", "0407", 0, "Eggs are nil-rated"),
    (r"fresh (fruit|vegetable)|vegetables?\b|onion|potato|tomato", "0709", 0, "Fresh vegetables are nil-rated"),
    (r"insulin|medicine|tablet|capsule|syrup|\bdrug", "3004", 5, "Medicines (5%)"),
    (r"flask|thermos", "9617", 18, "Vacuum flasks (18%)"),
    (r"\b(bags?|backpack|sleeve|suitcase|wallet|purse|pouch)\b", "4202", 18, "Bags & cases (18%)"),
    (r"electric toothbrush|trimmer|shaver|hair dryer|straightener", "8509", 18, "Electric personal-care appliances (18%)"),
    (r"toothpaste|tooth ?powder|toothbrush", "3306", 5, "Oral care (5% under GST 2.0)"),
    (r"shampoo|hair oil|conditioner", "3305", 5, "Hair care (5% under GST 2.0)"),
    (r"\bsoap\b|handwash|body wash", "3401", 5, "Soap (5% under GST 2.0)"),
    (r"talc|face powder", "3304", 5, "Talcum & face powder (5%)"),
    (r"sanitary|napkin|diaper|nappy", "9619", 5, "Sanitary products (5%)"),
    (r"detergent|washing powder|dishwash|floor clean|phenyl|sanitizer|disinfect", "3402", 18, "Cleaning products (18%)"),
    (r"cream|lotion|serum|lipstick|make-?up|kajal|perfume|deo", "3304", 18, "Cosmetics (18%)"),
    (r"\bmugs?\b|\bcups?\b|plates?\b|bowls?\b|crockery|dinner ?set|tea ?set", "6912", 5, "Tableware & kitchenware (5%)"),
    (
        r"utensil|kadai|tawa|\bpan\b|cooker|bottle|lunch ?box|tiffin|thali|cutting board|spoon|ladle|kitchenware",
        "7323",
        5,
        "Household utensils (5% under GST 2.0)",
    ),
    (r"\btea\b|\bchai\b", "0902", 5, "Tea (5%)"),
    (r"coffee", "0901", 5, "Coffee (5%)"),
    (r"ghee|butter|cheese", "0405", 5, "Ghee, butter & cheese (5% under GST 2.0)"),
    (r"(edible|cooking|mustard|sunflower|groundnut|olive|coconut) oil", "1508", 5, "Edible oils (5%)"),
    (r"rice|wheat|\batta\b|flour|maida|besan|\bdal\b|pulses?", "1006", 5, "Packaged cereals & pulses (5%)"),
    (r"sugar|jaggery|\bgur\b", "1701", 5, "Sugar & jaggery (5%)"),
    (r"almond|cashew|kaju|badam|raisin|kishmish|pista|walnut|dry ?fruit|\bdates\b", "0802", 5, "Dry fruits (5% under GST 2.0)"),
    (r"spice|masala|haldi|turmeric|chilli|jeera|cumin", "0910", 5, "Spices (5%)"),
    (r"namkeen|bhujia|mixture|chips|snack", "2106", 5, "Namkeen & snacks (5% under GST 2.0)"),
    (r"biscuit|cookie|\bcake\b|pastry|rusk", "1905", 5, "Biscuits & bakery (5% under GST 2.0)"),
    (r"chocolate|cocoa|toffee|candy|\bsweets?\b|mithai", "1806", 5, "Chocolates & sweets (5% under GST 2.0)"),
    (r"\bjam\b|ketchup|sauce|pickle|achar|juice|noodle|pasta|protein bar", "2106", 5, "Food preparations (5%)"),
    (r"ice cream", "2105", 5, "Ice cream (5% under GST 2.0)"),
    (r"mineral water|packaged water|bottled water", "2201", 18, "Packaged drinking water (18%)"),
    (r"sewing machine", "8452", 5, "Sewing machines (5%)"),
    (r"bicycle|\bcycle\b", "8712", 5, "Bicycles (5%)"),
    (r"\btoys?\b|doll|puzzle|board game|lego|blocks|teddy|\brc\b", "9503", 5, "Toys (5% under GST 2.0)"),
    (r"yoga|dumbbell|cricket|\bbat\b|football|badminton|racket|\bgym\b|sports?", "9506", 5, "Sports goods (5% under GST 2.0)"),
    (
        r"t-?shirt|shirt|kurta|kurti|saree|\bsari\b|jeans|trouser|dress|legging|socks?\b|apparel|garment",
        "6109",
        5,
        "Apparel up to ₹2,500 per piece (5%)",
    ),
    (r"shoes?\b|sandal|slipper|chappal|footwear", "6403", 5, "Footwear up to ₹2,500 per pair (5%)"),
    (r"agarbatti|incense|\bdiya\b|candle|handicraft", "3307", 5, "Agarbatti & handicrafts (5%)"),
    (r"fertili[sz]er|pesticide|\bseeds?\b", "3105", 5, "Agricultural inputs (5%)"),
    (
        r"air ?conditioner|\bac\b|television|\btv\b|monitor|projector|dishwasher",
        "8528",
        18,
        "TVs, ACs & monitors (18% under GST 2.0)",
    ),
    (r"phone|mobile|smartphone|smart ?watch", "8517", 18, "Phones & smart watches (18%)"),
    (r"earbud|earphone|headphone|speaker|soundbar|neckband", "8518", 18, "Audio devices (18%)"),
    (r"laptop|computer|\bssd\b|hard disk|pen ?drive|keyboard|\bmouse\b|printer", "8471", 18, "Computers & peripherals (18%)"),
    (r"charg|adapter|power supply", "8504", 18, "Chargers & adapters (18%)"),
    (r"power ?bank|battery", "8507", 18, "Batteries & power banks (18%)"),
    (r"cable|\bwire\b|usb", "8544", 18, "Cables (18%)"),
    (r"camera|webcam", "8525", 18, "Cameras (18%)"),
    (
        r"fridge|refrigerator|washing machine|microwave|oven|air fryer|mixer|grinder|\biron\b|kettle|heater|geyser|\bfan\b|toaster|appliance",
        "8516",
        18,
        "Home appliances (18%)",
    ),
    (r"bulb|led light|tube ?light|\blamp\b", "8539", 18, "Lighting (18%)"),
    (r"chair|sofa|table|desk|furniture|\bbed\b|mattress|wardrobe|almirah", "9403", 18, "Furniture (18%)"),
    (r"\bpens?\b|marker|highlighter|stapler|\bfiles?\b|folder", "9608", 18, "Pens & office supplies (18%)"),
    (r"paper|\ba4\b|sticky|envelope|carton", "4802", 18, "Paper products (18%)"),
    (r"cement|paint|tiles?\b|plywood", "2523", 18, "Building materials (18% under GST 2.0)"),
    (r"\bwatch\b|\bclock\b", "9102", 18, "Watches & clocks (18%)"),
    (r"\bcar\b|motorcycle|scooter|\bbike\b", "8703", 18, "Small vehicles (18%; large cars 40%)"),
]
DEFAULT = ("", 18.0, "No specific rule matched — most goods fall in the 18% standard slab; please review")


def suggest_by_rules(name: str, category: str | None = None) -> dict:
    text = f"{name} {category or ''}".lower()
    slabs = current_slabs()
    for pattern, hsn, rate, reason in RULES:
        if re.search(pattern, text):
            # If the government has since changed the slabs (edited in Settings), snap to the nearest valid one.
            snapped = nearest_slab(float(rate), slabs)
            note = reason if snapped == rate else f"{reason} — snapped to current {snapped:g}% slab"
            return {"hsn_code": hsn, "gst_rate": snapped, "source": "rules", "confidence": "medium", "reason": note}
    hsn, rate, reason = DEFAULT
    return {
        "hsn_code": hsn or None,
        "gst_rate": nearest_slab(rate, slabs),
        "source": "rules",
        "confidence": "low",
        "reason": reason,
    }


PROMPT = """You are an Indian GST expert. The GST rate slabs currently in force are: {slabs} (percent).
Classify this product and answer with ONLY a JSON object, no other text:
{{"hsn_code": "<4 to 8 digit HSN>", "gst_rate": <one of {slabs}>, "reason": "<one short sentence>"}}

Product: {name}
Category: {category}"""


async def suggest_by_hermes(name: str, category: str | None) -> dict | None:
    from app.agents.providers.hermes import HermesProvider

    if not HermesProvider.configured():
        return None
    provider = HermesProvider()
    try:
        resp = await asyncio.wait_for(
            provider.client.chat.completions.create(
                model=provider.model,
                messages=[
                    {
                        "role": "user",
                        "content": PROMPT.format(
                            name=name, category=category or "unknown", slabs=", ".join(f"{s:g}" for s in current_slabs())
                        ),
                    }
                ],
                temperature=0,
            ),
            timeout=90,
        )
        text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S)
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        rate = float(data["gst_rate"])
        hsn = re.sub(r"\D", "", str(data.get("hsn_code", "")))[:8]
        if rate not in current_slabs() or not 4 <= len(hsn) <= 8:
            return None
        return {
            "hsn_code": hsn,
            "gst_rate": rate,
            "source": "hermes",
            "confidence": "high",
            "reason": str(data.get("reason", ""))[:200],
        }
    except Exception as exc:  # noqa: BLE001 - fall back to rules on any model/parse failure
        log.info("Hermes GST suggestion failed for %r: %s", name, exc)
        return None


async def suggest_gst(name: str, category: str | None = None, use_llm: bool = True) -> dict:
    return (await suggest_by_hermes(name, category) if use_llm else None) or suggest_by_rules(name, category)


def _missing(product_ids: list[int] | None, refresh_ai: bool = False) -> list[tuple[int, str, str | None]]:
    """Products without GST - plus, when refreshing after a rate change, ones the AI filled earlier (never manual ones)."""
    with session_scope() as s:
        needs = Product.gst_rate.is_(None) | (Product.gst_source == "ai") if refresh_ai else Product.gst_rate.is_(None)
        stmt = select(Product, Category).outerjoin(Category).where(Product.is_active, needs)
        if product_ids:
            stmt = stmt.where(Product.id.in_(product_ids))
        return [(p.id, p.name, c.name if c else None) for p, c in s.exec(stmt.limit(200))]


def _save(product_id: int, suggestion: dict) -> dict | None:
    with session_scope() as s:
        p = s.get(Product, product_id)
        if p is None or p.gst_source == "manual":  # a human set it - never overwrite
            return None
        p.hsn_code = suggestion["hsn_code"] if p.gst_source == "ai" else (p.hsn_code or suggestion["hsn_code"])
        p.gst_rate = suggestion["gst_rate"]
        p.gst_source = "ai"
        s.add(p)
        s.commit()
        return {"product_id": p.id, "sku": p.sku, "name": p.name, **suggestion}


async def autofill_missing(product_ids: list[int] | None = None, use_llm: bool = True, refresh_ai: bool = False) -> list[dict]:
    """Fill HSN + GST for products that don't have them yet (refresh_ai=True also re-checks AI-filled ones)."""
    from app.hooks.bus import bus

    filled = []
    for pid, name, category in await asyncio.to_thread(_missing, product_ids, refresh_ai):
        suggestion = await suggest_gst(name, category, use_llm)
        saved = await asyncio.to_thread(_save, pid, suggestion)
        if saved:
            filled.append(saved)
            bus.emit("product.gst_autofilled", saved, source=f"ai:{suggestion['source']}")
    return filled
