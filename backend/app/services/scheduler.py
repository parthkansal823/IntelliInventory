"""Tiny asyncio job scheduler (no extra infrastructure): anomaly scan, alert sweep, AI briefing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import select

from app.db import session_scope
from app.hooks.bus import bus
from app.models import Alert, AlertSeverity, Product, Report, utcnow
from app.services.settings import get_setting, set_setting

log = logging.getLogger("intelliinventory.scheduler")


@dataclass
class Job:
    name: str
    description: str
    interval: timedelta
    fn: Callable[[], Awaitable[str]]

    @property
    def key(self) -> str:
        return f"scheduler.last.{self.name}"

    def last_run(self) -> datetime | None:
        value = get_setting(self.key)
        return datetime.fromisoformat(value) if value else None

    def to_dict(self) -> dict:
        last = self.last_run()
        return {
            "name": self.name,
            "description": self.description,
            "interval_minutes": int(self.interval.total_seconds() // 60),
            "last_run": last.isoformat() if last else None,
            "next_run": (last + self.interval).isoformat() if last else None,
            "last_result": get_setting(f"{self.key}.result"),
        }


# --- jobs ---------------------------------------------------------------------------------


def _anomaly_scan_sync() -> str:
    from app.services.analytics import detect_anomalies

    new: list[dict] = []
    with session_scope() as s:
        skus = {p.sku: p.id for p in s.exec(select(Product))}
        open_msgs = {a.message for a in s.exec(select(Alert).where(Alert.kind == "anomaly", Alert.resolved == False))}  # noqa: E712
        findings = detect_anomalies(s)
        for f in findings:
            if f["message"] in open_msgs:
                continue
            s.add(
                Alert(kind="anomaly", severity=AlertSeverity(f["severity"]), product_id=skus.get(f["sku"]), message=f["message"])
            )
            new.append(f)
        s.commit()
    for f in new:
        bus.emit("anomaly.detected", f, source="scheduler")
    return f"{len(findings)} findings, {len(new)} new alerts"


async def anomaly_scan() -> str:
    return await asyncio.to_thread(_anomaly_scan_sync)


def _alert_sweep_sync() -> str:
    from app.hooks.builtin import evaluate_alerts

    with session_scope() as s:
        events = evaluate_alerts(s)
    return f"{len(events)} alert changes"


async def alert_sweep() -> str:
    return await asyncio.to_thread(_alert_sweep_sync)


BRIEFING_TASK = (
    "Write this morning's inventory briefing for the operations team. Use your tools to gather: the inventory "
    "summary, items that need reordering, open alerts and any anomalies. Format: a 2-sentence headline, then "
    "sections **Stock risks**, **Replenishment**, **Anomalies** and **Today's priorities** (3 numbered actions). "
    "Keep it under 250 words."
)


async def daily_briefing() -> str:
    from app.agents.runtime import run_autonomous

    content = await run_autonomous("copilot", BRIEFING_TASK, trigger="schedule", title=f"Briefing · {utcnow():%d %b}")
    title = f"Inventory briefing — {utcnow():%A %d %B}"

    def save() -> int:
        with session_scope() as s:
            report = Report(kind="briefing", title=title, content=content or "_No content_", created_by="agent:copilot")
            s.add(report)
            s.commit()
            s.refresh(report)
            return report.id

    report_id = await asyncio.to_thread(save)
    bus.emit("report.created", {"id": report_id, "kind": "briefing", "title": title, "content": content}, source="scheduler")
    return f"report #{report_id}"


JOBS: dict[str, Job] = {
    j.name: j
    for j in (
        Job("anomaly_scan", "Scan for demand spikes, drops and shrinkage; raise alerts", timedelta(hours=6), anomaly_scan),
        Job("alert_sweep", "Re-evaluate stock alerts for every product", timedelta(hours=1), alert_sweep),
        Job("daily_briefing", "Copilot writes the morning inventory briefing", timedelta(hours=24), daily_briefing),
    )
}


async def run_job(name: str) -> str:
    job = JOBS[name]
    started = utcnow()
    try:
        result = await job.fn()
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", name)
        result = f"failed: {exc}"
    await asyncio.to_thread(set_setting, job.key, started.isoformat())
    await asyncio.to_thread(set_setting, f"{job.key}.result", result)
    bus.emit("job.completed", {"job": name, "result": result}, source="scheduler")
    return result


async def scheduler_loop(poll_seconds: int = 60) -> None:
    await asyncio.sleep(3)  # let the app finish starting
    while True:
        for job in JOBS.values():
            last = await asyncio.to_thread(job.last_run)
            if last is None or utcnow() - last >= job.interval:
                await run_job(job.name)
        await asyncio.sleep(poll_seconds)
