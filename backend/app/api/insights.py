"""Analytics, forecasts, simulations, alerts and AI reports."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from app.models import Alert, Product, Report, utcnow
from app.security import CurrentUser, DbSession, StaffUser
from app.services import analytics, simulator, suppliers

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/analytics/dashboard")
def dashboard(session: DbSession, _: CurrentUser) -> dict:
    return analytics.dashboard(session)


@router.get("/analytics/reorder")
def reorder(session: DbSession, _: CurrentUser) -> list[dict]:
    return analytics.reorder_recommendations(session, 100)


@router.get("/analytics/forecast/{product_id}")
def forecast(session: DbSession, product_id: int, _: CurrentUser, horizon: int = 30) -> dict:
    if session.get(Product, product_id) is None:
        raise HTTPException(404, "Product not found")
    return analytics.product_forecast(session, product_id, max(7, min(horizon, 90)))


@router.get("/analytics/health")
def health(session: DbSession, _: CurrentUser) -> dict:
    return analytics.health_score(session)


@router.get("/analytics/markdowns")
def markdowns(session: DbSession, _: CurrentUser, clear_days: int = 60) -> list[dict]:
    return analytics.markdown_suggestions(session, max(14, min(clear_days, 180)))


@router.get("/analytics/expiring")
def expiring(session: DbSession, _: CurrentUser, days: int = 15) -> list[dict]:
    return analytics.expiring_products(session, max(1, min(days, 180)))


@router.get("/analytics/abc")
def abc(session: DbSession, _: CurrentUser) -> dict:
    return analytics.abc_summary(session)


@router.get("/analytics/anomalies")
def anomalies(session: DbSession, _: CurrentUser, window_days: int = 7) -> list[dict]:
    return analytics.detect_anomalies(session, window_days)


@router.get("/analytics/suppliers")
def supplier_scores(session: DbSession, _: CurrentUser) -> list[dict]:
    return suppliers.supplier_scorecards(session)


@router.get("/analytics/margins")
def margins(session: DbSession, _: CurrentUser, days: int = 30) -> list[dict]:
    return suppliers.margin_by_category(session, days)


class SimulateIn(BaseModel):
    product_id: int
    horizon: int = Field(default=60, ge=7, le=180)
    demand_multiplier: float = Field(default=1.0, ge=0.1, le=5)
    lead_time_days: int | None = Field(default=None, ge=1, le=120)
    service_level: float = Field(default=0.95, ge=0.5, le=0.999)
    order_qty: int | None = Field(default=None, ge=1)


@router.post("/analytics/simulate")
def simulate(session: DbSession, body: SimulateIn, _: CurrentUser) -> dict:
    return simulator.simulate(session, body.product_id, **body.model_dump(exclude={"product_id"}))


@router.get("/alerts")
def list_alerts(session: DbSession, _: CurrentUser, include_resolved: bool = False, limit: int = 100) -> list[dict]:
    stmt = select(Alert, Product).outerjoin(Product).order_by(Alert.created_at.desc())
    if not include_resolved:
        stmt = stmt.where(Alert.resolved == False)  # noqa: E712
    order = {"critical": 0, "warning": 1, "info": 2}
    rows = sorted(session.exec(stmt.limit(limit)).all(), key=lambda r: (r[0].resolved, order.get(r[0].severity, 3)))
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "severity": a.severity,
            "message": a.message,
            "resolved": a.resolved,
            "product": {"id": p.id, "sku": p.sku, "name": p.name} if p else None,
            "created_at": a.created_at.isoformat(),
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        }
        for a, p in rows
    ]


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(session: DbSession, alert_id: int, _: StaffUser) -> dict:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.resolved, alert.resolved_at = True, utcnow()
    session.add(alert)
    session.commit()
    return {"resolved": True}


@router.get("/reports")
def list_reports(session: DbSession, _: CurrentUser, kind: str | None = None, limit: int = 20) -> list[dict]:
    stmt = select(Report).order_by(Report.created_at.desc())
    if kind:
        stmt = stmt.where(Report.kind == kind)
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "content": r.content,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat(),
        }
        for r in session.exec(stmt.limit(limit))
    ]
