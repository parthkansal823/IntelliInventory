"""Budget guard: large purchase orders need approval; logs every received PO.

An example plugin showing all three extension points. Copy it as a template.
"""

from __future__ import annotations

import logging
import os

PLUGIN_NAME = "budget_guard"
PO_BUDGET_LIMIT = float(os.environ.get("PO_BUDGET_LIMIT", "2000000"))  # ₹20 lakh
log = logging.getLogger("intelliinventory.plugins.budget_guard")


def register(ctx) -> None:
    from app.db import session_scope
    from app.money import inr
    from app.services.inventory import find_product

    def large_po_needs_approval(run, tool, args):
        """Route draft POs above the budget limit to a human approver."""
        if tool.name != "create_purchase_order" or run.trigger == "approval":
            return None
        total = 0.0
        with session_scope() as s:
            for item in args.get("items") or []:
                try:
                    total += find_product(s, item["sku"]).unit_cost * int(item["quantity"])
                except Exception:  # noqa: BLE001 - validation happens in the tool itself
                    continue
        if total > PO_BUDGET_LIMIT:
            return {
                "action": "require_approval",
                "message": f"PO value {inr(total)} exceeds the {inr(PO_BUDGET_LIMIT)} budget limit.",
            }
        return None

    def log_received(event):
        """Log received purchase orders (swap for an ERP/accounting sync)."""
        log.info(
            "PO %s received from %s (%s units)",
            event.payload.get("number"),
            (event.payload.get("supplier") or {}).get("name"),
            event.payload.get("units"),
        )

    def budget_status() -> dict:
        """Current purchase-order budget limit enforced by the budget_guard plugin."""
        return {"po_budget_limit": PO_BUDGET_LIMIT, "currency": "INR"}

    ctx.register_hook("pre_tool_call", large_po_needs_approval, name="budget_guard", priority=40)
    ctx.on_event("po.received", log_received, name="budget_guard.log_received")
    ctx.register_tool(budget_status, tags=("read",))
