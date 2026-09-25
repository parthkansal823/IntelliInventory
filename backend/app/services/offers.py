"""Optional offers (schemes) and customer loyalty points. Everything is OFF until the shop switches it on in Settings.

Offer types (all become line discounts, so GST is charged on the discounted value):
* bill_percent  - {min_amount, percent}: X% off the whole bill above a bill value (best matching offer wins)
* buy_x_get_y   - {sku, buy, free}: e.g. buy 2 get 1 free
* item_percent  - {sku | category, percent}: X% off one item or a whole category

Loyalty: customers earn `earn_per_100` points per Rs 100 billed; each point is worth `point_value` rupees and can be
used (min `min_redeem` points) as a "points" payment on a later bill.

`apply_offers` is mirrored exactly in frontend/src/lib/offers.ts (same test vectors on both sides).
"""

from __future__ import annotations

import math

from app.services.settings import get_setting, set_setting

OFFERS_KEY = "billing.offers"
OFFER_TYPES = ("bill_percent", "buy_x_get_y", "item_percent")
DEFAULTS = {
    "enabled": False,
    "loyalty": {"enabled": False, "earn_per_100": 1.0, "point_value": 1.0, "min_redeem": 50},
    "offers": [],
}


class OfferError(ValueError):
    pass


def offers_config() -> dict:
    stored = get_setting(OFFERS_KEY) or {}
    return {
        "enabled": bool(stored.get("enabled", False)),
        "loyalty": {**DEFAULTS["loyalty"], **(stored.get("loyalty") or {})},
        "offers": list(stored.get("offers") or []),
    }


def loyalty_on(cfg: dict | None = None) -> bool:
    cfg = cfg or offers_config()
    return cfg["enabled"] and cfg["loyalty"]["enabled"]


def _num(value, name: str, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise OfferError(f"{name} must be a number") from exc
    if not lo <= n <= hi:
        raise OfferError(f"{name} must be between {lo:g} and {hi:g}")
    return n


def clean_offer(raw: dict) -> dict:
    kind = raw.get("type")
    if kind not in OFFER_TYPES:
        raise OfferError(f"Offer type must be one of {', '.join(OFFER_TYPES)}")
    offer = {"type": kind, "label": (raw.get("label") or "").strip()[:60], "active": bool(raw.get("active", True))}
    if kind == "bill_percent":
        offer["min_amount"] = _num(raw.get("min_amount") or 0, "Minimum bill", 0, 10_000_000)
        offer["percent"] = _num(raw.get("percent"), "Percent", 0.1, 90)
        offer["label"] = offer["label"] or f"{offer['percent']:g}% off above Rs {offer['min_amount']:g}"
    elif kind == "buy_x_get_y":
        sku = (raw.get("sku") or "").strip().upper()
        if not sku:
            raise OfferError("Pick the item for the buy X get Y offer")
        offer.update(sku=sku, buy=int(_num(raw.get("buy"), "Buy", 1, 100)), free=int(_num(raw.get("free"), "Free", 1, 100)))
        offer["label"] = offer["label"] or f"{sku}: buy {offer['buy']} get {offer['free']} free"
    else:
        sku = (raw.get("sku") or "").strip().upper() or None
        category = (raw.get("category") or "").strip() or None
        if not sku and not category:
            raise OfferError("Pick an item or a category for the discount")
        offer.update(sku=sku, category=category, percent=_num(raw.get("percent"), "Percent", 0.1, 90))
        offer["label"] = offer["label"] or f"{offer['percent']:g}% off {sku or category}"
    return offer


def update_offers_config(changes: dict) -> dict:
    cfg = offers_config()
    if "enabled" in changes:
        cfg["enabled"] = bool(changes["enabled"])
    if changes.get("loyalty") is not None:
        lo = {**cfg["loyalty"], **changes["loyalty"]}
        cfg["loyalty"] = {
            "enabled": bool(lo.get("enabled")),
            "earn_per_100": _num(lo.get("earn_per_100"), "Points per Rs 100", 0, 100),
            "point_value": _num(lo.get("point_value"), "Value of one point", 0.01, 100),
            "min_redeem": int(_num(lo.get("min_redeem"), "Minimum points to use", 0, 100_000)),
        }
    if changes.get("offers") is not None:
        cfg["offers"] = [clean_offer(o) for o in changes["offers"]][:50]
    set_setting(OFFERS_KEY, cfg)
    return cfg


def apply_offers(lines: list[dict], cfg: dict | None = None) -> dict:
    """Apply the active offers to bill lines ({sku, category?, quantity, unit_price, discount_pct?}).

    Returns {"lines": [{..., discount_pct, offer}], "applied": [labels]}. An offer never lowers a discount the
    cashier already gave. Pure function - no database access.
    """
    cfg = cfg or offers_config()
    out = [{**ln, "discount_pct": float(ln.get("discount_pct") or 0), "offer": None} for ln in lines]
    if not cfg.get("enabled"):
        return {"lines": out, "applied": []}
    offers = [o for o in cfg.get("offers") or [] if o.get("active", True)]
    applied: list[str] = []

    for o in offers:
        if o["type"] == "item_percent":
            hit = False
            for ln in out:
                match = (o.get("sku") and (ln.get("sku") or "").upper() == o["sku"]) or (
                    o.get("category") and (ln.get("category") or "").lower() == o["category"].lower()
                )
                if match and o["percent"] > ln["discount_pct"]:
                    ln["discount_pct"], ln["offer"], hit = round(o["percent"], 2), o["label"], True
            if hit:
                applied.append(o["label"])
        elif o["type"] == "buy_x_get_y":
            for ln in out:
                qty = int(ln.get("quantity") or 0)
                if (ln.get("sku") or "").upper() != o["sku"] or qty < o["buy"] + o["free"]:
                    continue
                free_units = (qty // (o["buy"] + o["free"])) * o["free"]
                pct = round(free_units / qty * 100, 2)
                if pct > ln["discount_pct"]:
                    ln["discount_pct"], ln["offer"] = pct, o["label"]
                    applied.append(o["label"])

    gross = sum(float(ln["unit_price"]) * int(ln["quantity"]) * (1 - ln["discount_pct"] / 100) for ln in out)
    best = max(
        (o for o in offers if o["type"] == "bill_percent" and gross >= o["min_amount"]),
        key=lambda o: o["percent"],
        default=None,
    )
    if best:
        for ln in out:
            combined = 100 - (100 - ln["discount_pct"]) * (100 - best["percent"]) / 100
            ln["discount_pct"] = round(combined, 2)
            ln["offer"] = best["label"] if ln["offer"] is None else f"{ln['offer']} + {best['label']}"
        applied.append(best["label"])
    return {"lines": out, "applied": applied}


def points_for(amount: float, cfg: dict | None = None) -> int:
    cfg = cfg or offers_config()
    return max(0, math.floor(amount / 100 * float(cfg["loyalty"]["earn_per_100"]) + 1e-9))
