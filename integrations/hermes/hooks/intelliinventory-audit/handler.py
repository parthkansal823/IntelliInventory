"""Hermes gateway hook: forward agent:start / agent:end to IntelliInventory's event stream."""

import json
import os
import urllib.request


async def handle(event_type: str, context: dict):
    url = os.environ.get("INTELLIINVENTORY_URL", "http://localhost:8000").rstrip("/") + "/api/integrations/events"
    payload = {
        "platform": context.get("platform"),
        "user_id": context.get("user_id"),
        "message": str(context.get("message", ""))[:500],
    }
    if event_type == "agent:end":
        payload["response"] = str(context.get("response", ""))[:1000]
    body = json.dumps({"type": f"hermes.{event_type.replace(':', '_')}", "payload": payload, "source": "hermes-gateway"}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('INTELLIINVENTORY_TOKEN', 'hermes-dev-token')}",
    })
    try:
        urllib.request.urlopen(req, timeout=3).close()
    except Exception:  # noqa: BLE001 - never break the gateway
        pass
