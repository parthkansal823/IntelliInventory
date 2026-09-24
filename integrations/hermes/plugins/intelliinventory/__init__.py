"""Hermes Agent plugin for IntelliInventory.

Hooks (Hermes plugin API):
  * pre_tool_call  - read-only mode + sanity limits for IntelliInventory write tools
  * post_tool_call - forwards every IntelliInventory tool call to the app's audit trail

Environment:
  INTELLIINVENTORY_URL        default http://localhost:8000
  INTELLIINVENTORY_TOKEN      default hermes-dev-token (INTEGRATION_TOKEN in the app)
  INTELLIINVENTORY_READONLY   "1" blocks every write tool from Hermes
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request

PREFIXES = ("mcp_intelliinventory_", "mcp_intelliinventory_http_")
WRITE_TOOLS = {
    "create_purchase_order", "update_purchase_order_status", "adjust_stock",
    "transfer_stock", "update_reorder_settings", "start_cycle_count",
}
MAX_UNITS = 20_000


def _tool(name: str | None) -> str | None:
    for prefix in PREFIXES:
        if name and name.startswith(prefix):
            return name[len(prefix):]
    return None


def _post(event_type: str, payload: dict) -> None:
    url = os.environ.get("INTELLIINVENTORY_URL", "http://localhost:8000").rstrip("/") + "/api/integrations/events"
    body = json.dumps({"type": event_type, "payload": payload, "source": "hermes-agent"}, default=str).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('INTELLIINVENTORY_TOKEN', 'hermes-dev-token')}",
    })

    def send() -> None:
        try:
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:  # noqa: BLE001 - auditing must never break the agent
            pass

    threading.Thread(target=send, daemon=True).start()


def guard(tool_name=None, args=None, params=None, **kwargs):
    """Block IntelliInventory writes in read-only mode and reject absurd quantities."""
    tool = _tool(tool_name)
    if tool is None or tool not in WRITE_TOOLS:
        return None
    args = args or params or {}
    if os.environ.get("INTELLIINVENTORY_READONLY") == "1":
        return {"action": "block", "message": f"IntelliInventory is read-only for Hermes; '{tool}' was blocked."}
    quantities = [args.get("quantity_delta"), args.get("quantity")] + [i.get("quantity") for i in args.get("items") or [] if isinstance(i, dict)]
    if any(isinstance(q, int) and abs(q) > MAX_UNITS for q in quantities):
        return {"action": "block", "message": f"Quantity above {MAX_UNITS} units blocked by the IntelliInventory plugin."}
    return None


def audit(tool_name=None, args=None, params=None, result=None, duration_ms=None, **kwargs):
    """Forward IntelliInventory tool calls made by Hermes to the app's audit trail."""
    tool = _tool(tool_name)
    if tool is None:
        return
    preview = result if isinstance(result, str) else json.dumps(result, default=str)
    _post("hermes.tool_call", {"tool": tool, "args": args or params or {}, "duration_ms": duration_ms,
                               "result_preview": (preview or "")[:500]})


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_hook("post_tool_call", audit)
