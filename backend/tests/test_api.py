import json

from mcp import Client

from app.mcp_server import build_server


def test_auth_and_rbac(client, manager, viewer):
    assert client.get("/api/products").status_code == 401
    assert client.post("/api/auth/token", json={"email": "ananya@intelliinventory.dev", "password": "nope"}).status_code == 401
    assert client.get("/api/auth/me", headers=manager).json()["role"] == "manager"
    body = {"sku": "TST-0001", "name": "Test"}
    assert client.post("/api/products", json=body, headers=viewer).status_code == 403
    created = client.post("/api/products", json={**body, "initial_qty": 5}, headers=manager)
    assert created.status_code == 201 and created.json()["on_hand"] == 5
    assert client.post("/api/products", json=body, headers=manager).status_code == 409


def test_core_endpoints(client, manager):
    for path in [
        "/api/analytics/dashboard",
        "/api/analytics/reorder",
        "/api/analytics/abc",
        "/api/analytics/health",
        "/api/analytics/markdowns",
        "/api/analytics/suppliers",
        "/api/alerts",
        "/api/purchase-orders",
        "/api/hooks",
        "/api/jobs",
        "/api/agents",
        "/api/warehouses",
        "/api/system/info",
    ]:
        res = client.get(path, headers=manager)
        assert res.status_code == 200, (path, res.text)
    products = client.get("/api/products", headers=manager).json()
    detail = client.get(f"/api/products/{products[0]['id']}", headers=manager).json()
    assert detail["forecast"]["forecast"] and "warehouses" in detail


def test_scan_and_inventory_errors(client, manager):
    res = client.post("/api/inventory/scan", json={"code": "ii:SNK-404", "action": "receive", "quantity": 4}, headers=manager)
    assert res.status_code == 200 and res.json()["product"]["sku"] == "SNK-404"
    bad = client.post("/api/inventory/scan", json={"code": "NOPE-9999"}, headers=manager)
    assert bad.status_code == 400 and "not found" in bad.json()["detail"]


def test_chat_streams_server_sent_events(client, manager):
    with client.stream(
        "POST", "/api/agents/chat", json={"message": "any anomalies?", "agent": "auditor"}, headers=manager
    ) as res:
        assert res.status_code == 200
        events = [json.loads(line[5:]) for line in res.iter_lines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert types[0] == "conversation" and types[-1] == "done"
    assert any(e["type"] == "tool_call" and e["name"] == "detect_anomalies" for e in events)
    conv = client.get(f"/api/agents/conversations/{events[0]['id']}", headers=manager).json()
    assert conv["display"][0]["type"] == "user"


def test_integration_ingest_requires_token(client, manager):
    assert client.post("/api/integrations/events", json={"type": "ping"}).status_code == 401
    ok = client.post(
        "/api/integrations/events",
        json={"type": "tool_call", "payload": {"tool": "x"}},
        headers={"Authorization": "Bearer hermes-dev-token"},
    )
    assert ok.status_code == 202


def test_mcp_http_requires_token(client):
    assert client.post("/mcp/", json={}).status_code == 401


async def test_mcp_server_exposes_guarded_tools(client):
    async with Client(build_server()) as mcp:
        names = {t.name for t in (await mcp.list_tools()).tools}
        assert {"get_inventory_summary", "adjust_stock", "get_health_score"} <= names
        summary = json.loads((await mcp.call_tool("get_inventory_summary", {})).content[0].text)
        assert summary["kpis"]["total_skus"] > 30
        pending = json.loads(
            (await mcp.call_tool("adjust_stock", {"sku": "SNK-404", "quantity_delta": -1, "reason": "mcp"})).content[0].text
        )
        assert pending["status"] == "pending_approval"
        blocked = json.loads(
            (await mcp.call_tool("adjust_stock", {"sku": "SNK-404", "quantity_delta": -99999, "reason": "x"})).content[0].text
        )
        assert blocked.get("blocked")


def test_autopilot_drafts_po_when_stock_runs_low(client, manager):
    """stock.changed -> alert engine -> stock.low -> autopilot hook -> procurement agent -> draft PO."""
    import time

    products = client.get("/api/products", headers=manager).json()
    open_skus = {ln["sku"] for po in client.get("/api/purchase-orders?status=open", headers=manager).json() for ln in po["lines"]}
    target = next(
        p
        for p in products
        if p["status"] == "healthy" and p["sku"] not in open_skus and p["avg_daily_demand"] > 2 and p["lead_time_days"] >= 5
    )
    assert client.patch("/api/automation/settings", json={"autopilot_enabled": True}, headers=manager).status_code == 200
    try:
        drop = target["on_hand"] - max(1, target["reorder_point"] // 2)
        res = client.post(
            "/api/inventory/adjust",
            json={"product_id": target["id"], "quantity": -drop, "reason": "autopilot test"},
            headers=manager,
        )
        assert res.status_code == 200
        deadline = time.time() + 15
        drafted = []
        while time.time() < deadline and not drafted:
            drafts = client.get("/api/purchase-orders?status=draft", headers=manager).json()
            drafted = [
                po
                for po in drafts
                if po["created_by"] == "agent:procurement" and target["sku"] in {ln["sku"] for ln in po["lines"]}
            ]
            time.sleep(0.3)
        assert drafted, f"autopilot did not draft a PO for {target['sku']}"
        events = client.get("/api/events?type=autopilot", headers=manager).json()
        assert any(e["payload"].get("sku") == target["sku"] for e in events)
    finally:
        client.patch("/api/automation/settings", json={"autopilot_enabled": False}, headers=manager)


def test_cli_resets_passwords_and_creates_admins(client):
    from app.cli import main

    assert main(["create-admin", "owner@shop.test", "secret-123", "--name", "Parth"]) == 0
    assert client.post("/api/auth/token", json={"email": "owner@shop.test", "password": "secret-123"}).status_code == 200
    assert main(["reset-password", "owner@shop.test", "another-456"]) == 0
    assert client.post("/api/auth/token", json={"email": "owner@shop.test", "password": "another-456"}).status_code == 200
    assert main(["reset-password", "nobody@shop.test", "whatever-1"]) == 1
    assert main(["reset-password", "owner@shop.test", "short"]) == 2
