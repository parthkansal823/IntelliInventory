"""What-if simulator: Monte-Carlo replay of an (s, Q) replenishment policy.

Given a product's forecast and a set of overrides (demand multiplier, lead
time, service level, order quantity) the simulator runs N stochastic demand
paths and reports fill rate, stockout days, average inventory and costs, plus
percentile bands of the projected stock level for charting.
"""

from __future__ import annotations

import math
import random
import statistics
from statistics import NormalDist

from sqlmodel import Session

from app.services.analytics import (
    HISTORY_DAYS,
    HOLDING_RATE,
    ORDERING_COST,
    daily_sales,
    forecast_series,
    metrics_for,
)
from app.services.inventory import InventoryError


def _demand(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(
    session: Session,
    product_id: int,
    *,
    horizon: int = 60,
    demand_multiplier: float = 1.0,
    lead_time_days: int | None = None,
    service_level: float = 0.95,
    order_qty: int | None = None,
    runs: int = 300,
    seed: int = 7,
) -> dict:
    m = metrics_for(session, product_id)
    if m is None:
        raise InventoryError("Product not found")
    horizon = max(7, min(horizon, 180))
    service_level = min(max(service_level, 0.5), 0.999)
    series = daily_sales(session, HISTORY_DAYS, [product_id]).get(product_id, [0.0] * HISTORY_DAYS)
    fc = forecast_series(series, horizon)
    daily = [f * demand_multiplier for f in fc.forecast]

    lead = max(1, lead_time_days or m.lead_time_days)
    z = NormalDist().inv_cdf(service_level)
    sigma = max(m.demand_std, math.sqrt(max(statistics.fmean(daily), 0.01))) * demand_multiplier
    lead_demand = sum(daily[:lead]) if len(daily) >= lead else statistics.fmean(daily) * lead
    safety = math.ceil(z * sigma * math.sqrt(lead))
    rop = math.ceil(lead_demand + safety)
    annual = statistics.fmean(daily) * 365
    holding_unit = max(m.unit_cost * HOLDING_RATE, 0.01)
    eoq = math.ceil(math.sqrt(2 * annual * ORDERING_COST / holding_unit)) if annual > 0 else 0
    q = max(order_qty or eoq, 1)

    rng = random.Random(seed)
    paths: list[list[int]] = []
    fill, stockout_days, avg_inv, orders_placed, lost_units = [], [], [], [], []
    for _ in range(runs):
        stock = m.on_hand
        pipeline: list[tuple[int, int]] = [(math.ceil(lead / 2), m.on_order)] if m.on_order else []
        demand_total = sold_total = out_days = orders = 0
        path = []
        for day in range(horizon):
            arrived = sum(qty for d, qty in pipeline if d == day)
            pipeline = [(d, qty) for d, qty in pipeline if d != day]
            stock += arrived
            demand = _demand(rng, daily[day])
            sold = min(stock, demand)
            stock -= sold
            demand_total += demand
            sold_total += sold
            if sold < demand:
                out_days += 1
            if stock + sum(qty for _, qty in pipeline) <= rop:
                pipeline.append((day + lead, q))
                orders += 1
            path.append(stock)
        paths.append(path)
        fill.append(sold_total / demand_total if demand_total else 1.0)
        stockout_days.append(out_days)
        avg_inv.append(statistics.fmean(path))
        orders_placed.append(orders)
        lost_units.append(demand_total - sold_total)

    def pct(values: list[int], p: float) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(p * len(ordered)))]

    projection = [
        {
            "day": d + 1,
            "p10": pct([p[d] for p in paths], 0.1),
            "p50": pct([p[d] for p in paths], 0.5),
            "p90": pct([p[d] for p in paths], 0.9),
            "demand": round(daily[d], 2),
        }
        for d in range(horizon)
    ]
    mean_inv = statistics.fmean(avg_inv)
    return {
        "product": {"id": m.product_id, "sku": m.sku, "name": m.name, "on_hand": m.on_hand, "on_order": m.on_order},
        "policy": {
            "lead_time_days": lead,
            "service_level": service_level,
            "z": round(z, 2),
            "safety_stock": safety,
            "reorder_point": rop,
            "order_qty": q,
            "eoq": eoq,
            "demand_multiplier": demand_multiplier,
        },
        "results": {
            "fill_rate": round(statistics.fmean(fill) * 100, 1),
            "stockout_probability": round(sum(1 for s in stockout_days if s > 0) / runs * 100, 1),
            "expected_stockout_days": round(statistics.fmean(stockout_days), 1),
            "avg_inventory": round(mean_inv, 1),
            "orders_placed": round(statistics.fmean(orders_placed), 1),
            "holding_cost": round(mean_inv * holding_unit / 365 * horizon, 2),
            "ordering_cost": round(statistics.fmean(orders_placed) * ORDERING_COST, 2),
            "lost_sales_value": round(statistics.fmean(lost_units) * m.unit_price, 2),
        },
        "projection": projection,
        "runs": runs,
        "horizon": horizon,
    }
