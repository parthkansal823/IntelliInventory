"""India-specific endpoints: festival planner, GST report, GSTIN validation."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import Product
from app.security import CurrentUser, DbSession, ManagerUser, StaffUser, actor
from app.services import gst_ai, india, purchasing
from app.services.settings import set_setting

router = APIRouter(prefix="/api/india", tags=["india"])


@router.get("/festivals")
def festivals(_: CurrentUser) -> list[dict]:
    return india.festival_calendar()


@router.get("/festival-plan")
def festival_plan(session: DbSession, _: CurrentUser, festival: str | None = None) -> dict:
    return india.festival_plan(session, festival)


@router.get("/gst")
def gst(session: DbSession, _: CurrentUser, days: int = 30) -> dict:
    return india.gst_report(session, max(7, min(days, 365)))


@router.get("/gstin/{gstin}")
def validate(gstin: str, _: CurrentUser) -> dict:
    ok, info = india.validate_gstin(gstin)
    return {"gstin": gstin.upper(), "valid": ok, "state": info if ok else None, "error": None if ok else info}


class FestivalPOIn(BaseModel):
    festival: str | None = None
    product_ids: list[int] | None = None


@router.post("/festival-orders", status_code=201)
def festival_orders(session: DbSession, body: FestivalPOIn, user: StaffUser) -> list[dict]:
    """Draft one purchase order per supplier covering the festival stock-up plan."""
    plan = india.festival_plan(session, body.festival)
    items = [i for i in plan["items"] if i["suggested_order_qty"] and i["supplier_id"]]
    if body.product_ids:
        items = [i for i in items if i["product_id"] in body.product_ids]
    if not items:
        raise HTTPException(400, "Nothing to order for this festival — stock already covers the expected demand")
    by_supplier: dict[int, list] = {}
    for i in items:
        by_supplier.setdefault(i["supplier_id"], []).append(i)
    name = plan["festival"]["name"]
    created = []
    for supplier_id, rows in by_supplier.items():
        lines = [(session.get(Product, r["product_id"]), r["suggested_order_qty"]) for r in rows]
        po = purchasing.create_po(
            session,
            lines,
            supplier_id=supplier_id,
            created_by=actor(user),
            notes=f"{name} stock-up — order by {rows[0]['order_by']}",
        )
        created.append(purchasing.po_summary(session, po))
    return created


# --- GST settings & AI auto-fill ------------------------------------------------------------


class GstSettingsIn(BaseModel):
    gst_enabled: bool | None = None
    slabs: list[float] | None = None


@router.get("/settings")
def gst_settings(_: CurrentUser) -> dict:
    return {
        "gst_enabled": india.gst_enabled(),
        "slabs": gst_ai.current_slabs(),
        "default_slabs": gst_ai.DEFAULT_SLABS,
        "states": sorted(india.STATE_CODES),
    }


@router.patch("/settings")
def update_gst_settings(body: GstSettingsIn, user: ManagerUser) -> dict:
    if body.gst_enabled is not None:
        set_setting("gst.enabled", body.gst_enabled)
    if body.slabs is not None:
        slabs = sorted({round(float(s), 2) for s in body.slabs if 0 <= s <= 100})
        if not slabs:
            raise HTTPException(422, "Provide at least one GST slab")
        set_setting("gst.slabs", slabs)
    return gst_settings(user)


class SuggestIn(BaseModel):
    name: str
    category: str | None = None


@router.post("/gst/suggest")
async def suggest(body: SuggestIn, _: CurrentUser) -> dict:
    """AI suggestion for one product name (used by the product form's "Suggest with AI" button)."""
    return await gst_ai.suggest_gst(body.name, body.category)


class AutofillIn(BaseModel):
    product_ids: list[int] | None = None
    refresh_ai: bool = False  # after a GST rate change: re-check everything the AI filled earlier


@router.post("/gst/autofill")
async def autofill(body: AutofillIn, _: ManagerUser) -> dict:
    filled = await gst_ai.autofill_missing(body.product_ids, refresh_ai=body.refresh_ai)
    return {"filled": len(filled), "items": filled}
