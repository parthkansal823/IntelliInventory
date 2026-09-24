import math

from app.services import analytics, simulator
from app.services.analytics import forecast_series


def test_holt_winters_tracks_weekly_seasonality():
    week = [10, 10, 10, 10, 12, 20, 18]
    series = [float(v) for _ in range(12) for v in week]
    fc = forecast_series(series, horizon=14)
    assert fc.method == "holt-winters"
    assert len(fc.forecast) == 14
    assert all(lo <= f <= hi for f, lo, hi in zip(fc.forecast, fc.lower, fc.upper, strict=True))
    # Saturday (index 5 of the week) should be forecast higher than Monday.
    n = len(series)
    sat = next(h for h in range(14) if (n + h) % 7 == 5)
    mon = next(h for h in range(14) if (n + h) % 7 == 0)
    assert fc.forecast[sat] > fc.forecast[mon]
    assert fc.mape is not None and fc.mape < 5


def test_forecast_handles_empty_and_short_series():
    assert forecast_series([0.0] * 30, 7).method == "none"
    short = forecast_series([3, 4, 5, 6], 5)
    assert short.method == "holt" and all(v >= 0 for v in short.forecast)


def test_policy_metrics_for_seeded_scenarios(session):
    metrics = {m.sku: m for m in analytics.compute_metrics(session)}
    assert metrics["ELC-1004"].status == "out"
    assert metrics["OFF-3004"].status == "overstock"
    assert metrics["ACC-2001"].status in ("critical", "low")
    for m in metrics.values():
        assert m.reorder_point >= m.safety_stock >= 0
        if m.suggested_order_qty:
            assert m.on_hand + m.on_order <= m.reorder_point
    assert {m.abc_class for m in metrics.values()} == {"A", "B", "C"}


def test_eoq_formula(session):
    m = next(m for m in analytics.compute_metrics(session) if m.avg_daily_demand > 0)
    expected = math.ceil(
        math.sqrt(2 * m.avg_daily_demand * 365 * analytics.ORDERING_COST / (m.unit_cost * analytics.HOLDING_RATE))
    )
    assert m.eoq == expected


def test_reorder_recommendations_are_sorted_by_urgency(session):
    recs = analytics.reorder_recommendations(session)
    order = {"out": 0, "critical": 1, "low": 2, "healthy": 3, "overstock": 4}
    ranks = [order[r["status"]] for r in recs]
    assert ranks == sorted(ranks) and recs
    assert all(r["estimated_cost"] == round(r["suggested_order_qty"] * r["unit_cost"], 2) for r in recs)


def test_anomalies_detect_seeded_spike_shrinkage_and_drop(session):
    kinds = {(a["kind"], a["sku"]) for a in analytics.detect_anomalies(session)}
    assert ("demand_spike", "HLT-5001") in kinds
    assert ("shrinkage", "ELC-1002") in kinds
    assert ("demand_drop", "TOY-8003") in kinds


def test_health_score_and_markdowns(session):
    health = analytics.health_score(session)
    assert 0 <= health["score"] <= 100 and health["grade"] in "ABCDE"
    assert sum(c["weight"] for c in health["components"]) == 100
    markdowns = analytics.markdown_suggestions(session)
    assert markdowns, "seeded overstock should produce markdown suggestions"
    for md in markdowns:
        assert md["new_price"] <= md["current_price"]
        assert md["margin_after_pct"] >= 4.7  # price >= cost * 1.05  =>  margin >= 4.76%


def test_simulator_more_demand_hurts_service(session):
    pid = next(m.product_id for m in analytics.compute_metrics(session) if m.sku == "ELC-1005")
    base = simulator.simulate(session, pid, runs=120)
    stressed = simulator.simulate(session, pid, runs=120, demand_multiplier=2.5, lead_time_days=30)
    assert len(base["projection"]) == base["horizon"]
    assert stressed["results"]["fill_rate"] <= base["results"]["fill_rate"]
    assert stressed["policy"]["reorder_point"] > base["policy"]["reorder_point"]
