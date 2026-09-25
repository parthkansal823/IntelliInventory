import json
from datetime import date

from app.agents.runtime import run_conversation
from app.money import inr
from app.services import india, purchasing
from app.services.inventory import find_product

from .conftest import MANAGER


def test_inr_uses_indian_digit_grouping():
    assert inr(15368990) == "₹1,53,68,990"
    assert inr(123456) == "₹1,23,456"
    assert inr(9.5) == "₹9.50"
    assert inr(-2500) == "-₹2,500"


def test_gstin_checksum_and_state():
    assert india.validate_gstin("27AAPFU0939F1ZV") == (True, "Maharashtra")  # published sample GSTIN
    assert india.validate_gstin("27AAPFU0939F1ZX")[0] is False
    assert india.validate_gstin("99AAPFU0939F1ZV")[0] is False
    generated = india.make_gstin("Karnataka", "AAACT4821K")
    assert generated.startswith("29") and india.validate_gstin(generated) == (True, "Karnataka")


def test_gst_split_intra_vs_inter_state():
    assert india.gst_split(1000, 18, interstate=False) == {"cgst": 90.0, "sgst": 90.0, "igst": 0.0, "tax": 180.0}
    assert india.gst_split(1000, 18, interstate=True) == {"cgst": 0.0, "sgst": 0.0, "igst": 180.0, "tax": 180.0}


def test_purchase_orders_carry_gst_and_eway_flag(session):
    local = purchasing.create_po(
        session, [(find_product(session, "ATA-105"), 500)], created_by="test"
    )  # Aggarwal, Punjab -> Punjab
    summary = purchasing.po_summary(session, local)
    assert not summary["tax"]["interstate"] and summary["tax"]["cgst"] == summary["tax"]["sgst"] > 0
    assert summary["lines"][0]["gst_rate"] == 5 and summary["lines"][0]["hsn_code"] == "1701"
    assert summary["grand_total"] == round(summary["total"] * 1.05, 2)
    assert summary["tax"]["eway_bill_required"] == (summary["grand_total"] > 50_000)

    remote = purchasing.create_po(session, [(find_product(session, "SNK-401"), 200)], created_by="test")  # Chandigarh -> Punjab
    tax = purchasing.po_summary(session, remote)["tax"]
    assert tax["interstate"] and tax["igst"] > 0 and tax["cgst"] == 0


def test_festival_calendar_and_multipliers():
    punjab = [f["name"] for f in india.festival_calendar(date(2026, 9, 24), state="Punjab")]
    assert punjab[:5] == ["Navratri", "Dussehra", "Karwa Chauth", "Dhanteras", "Diwali"]
    assert {"Guru Nanak Gurpurab", "Lohri", "Baisakhi"} <= set(punjab) and "Onam" not in punjab
    bengal = [f["name"] for f in india.festival_calendar(date(2026, 9, 24), state="West Bengal")]
    assert "Durga Puja" in bengal and "Lohri" not in bengal and "Karwa Chauth" not in bengal
    assert "Onam" in [f["name"] for f in india.festival_calendar(date(2026, 9, 24), state="Kerala")]
    assert len(india.festival_calendar(date(2026, 9, 24), state=None)) == len(
        india.upcoming_festivals(date(2026, 9, 24), state=None)
    )
    assert india.festival_multiplier("Puja Samagri", date(2026, 11, 5)) == (2.5, "Diwali")
    assert india.festival_multiplier("Snacks & Biscuits", date(2026, 11, 5)) == (1.8, "Diwali")
    assert india.festival_multiplier("Stationery", date(2026, 12, 1)) == (1.0, None)
    assert india.category_key("Atta, Rice & Dal") == "grocery" and india.category_key("Home Care") == "home"


def test_festival_plan_and_one_click_orders(client, manager, session):
    plan = india.festival_plan(session, "diwali", today=date(2026, 9, 24))
    assert plan["festival"]["name"] == "Diwali" and plan["summary"]["products_affected"] > 5
    assert all(i["uplift"] > 1 for i in plan["items"])
    res = client.get("/api/india/festival-plan?festival=diwali", headers=manager)
    assert res.status_code == 200
    if res.json()["summary"]["products_to_order"]:
        created = client.post("/api/india/festival-orders", json={"festival": "diwali"}, headers=manager)
        assert created.status_code == 201 and all("Diwali" in po["notes"] for po in created.json())


def test_india_endpoints_and_gstin_validation(client, manager):
    report = client.get("/api/india/gst?days=30", headers=manager).json()
    assert report["output_tax"] > 0 and {s["rate"] for s in report["slabs"]} >= {5.0, 18.0}
    assert not {12.0, 28.0} & {s["rate"] for s in report["slabs"]}  # GST 2.0: those slabs are gone
    assert client.get("/api/india/gstin/27AAPFU0939F1ZV", headers=manager).json()["valid"]
    bad = client.post("/api/suppliers", json={"name": "Bad GST Co", "gstin": "27AAPFU0939F1ZX"}, headers=manager)
    assert bad.status_code == 422 and "checksum" in bad.json()["detail"]
    good = client.post("/api/suppliers", json={"name": "Good GST Co", "gstin": "27aapfu0939f1zv"}, headers=manager)
    assert good.status_code == 201 and good.json()["state"] == "Maharashtra" and good.json()["gstin"] == "27AAPFU0939F1ZV"
    product = client.get("/api/products", headers=manager).json()[0]
    assert product["gst_rate"] > 0 and product["price_incl_gst"] > product["unit_price"]


async def test_offline_agent_handles_festivals_and_gst_in_hinglish(client):
    async def tool_calls(msg):
        return [e["name"] for e in [e async for e in run_conversation(msg, user=MANAGER)] if e["type"] == "tool_call"]

    assert "plan_festival_stock" in await tool_calls("Diwali ke liye kya stock karna hai?")
    assert "gst_summary" in await tool_calls("is mahine GST kitna banega?")
    assert "plan_festival_stock" in await tool_calls("tyohar ki taiyari")


def test_forecast_payload_lists_festival_uplift(client, manager):
    products = {p["sku"]: p for p in client.get("/api/products", headers=manager).json()}
    fc = client.get(f"/api/analytics/forecast/{products['ATA-103']['id']}?horizon=90", headers=manager).json()
    assert isinstance(fc["festivals"], list)
    json.dumps(fc)


def test_ai_rules_classify_common_indian_goods():
    from app.services.gst_ai import suggest_by_rules

    cases = {
        "Colgate toothpaste 200g": (5, "3306"),
        "Amul Ghee 1L": (5, "0405"),
        "Samsung 43 inch LED TV": (18, "8528"),
        "Stainless steel lunch box": (5, "7323"),
        "Classmate exercise notebook": (0, "4820"),
        "Coca Cola 750ml": (40, "2202"),
        "Gold chain 22K": (3, "7113"),
        "Laptop sleeve 14 inch": (18, "4202"),
        "Kids RC racing car": (5, "9503"),
        "Mystery gadget": (18, None),
    }
    for name, (rate, hsn) in cases.items():
        got = suggest_by_rules(name)
        assert (got["gst_rate"], got["hsn_code"]) == (rate, hsn), (name, got)


def test_new_product_gets_gst_filled_by_ai_later(client, manager):
    import time

    res = client.post(
        "/api/products",
        json={"sku": "NEW-GHEE", "name": "Desi Cow Ghee 1L", "unit_cost": 450, "unit_price": 649},
        headers=manager,
    )
    assert res.status_code == 201 and res.json()["gst_rate"] is None  # GST is optional at creation
    pid = res.json()["id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        p = client.get(f"/api/products/{pid}", headers=manager).json()
        if p["gst_rate"] is not None:
            break
        time.sleep(0.2)
    assert (p["gst_rate"], p["hsn_code"], p["gst_source"]) == (5.0, "0405", "ai")
    # A human confirming the value turns it into a manual rate that the AI never overwrites.
    client.patch(f"/api/products/{pid}", json={"gst_rate": 5}, headers=manager)
    client.patch("/api/india/settings", json={"slabs": [0, 5, 18]}, headers=manager)
    try:
        refreshed = client.post("/api/india/gst/autofill", json={"refresh_ai": True}, headers=manager).json()
        assert all(item["sku"] != "NEW-GHEE" for item in refreshed["items"])
    finally:
        client.patch("/api/india/settings", json={"slabs": [0, 3, 5, 18, 40]}, headers=manager)


def test_slab_changes_snap_ai_suggestions(client, manager):
    from app.services.gst_ai import suggest_by_rules

    client.patch("/api/india/settings", json={"slabs": [0, 5, 12, 18]}, headers=manager)
    try:
        assert suggest_by_rules("Coca Cola 750ml")["gst_rate"] == 18  # 40% no longer configured -> nearest slab
    finally:
        client.patch("/api/india/settings", json={"slabs": [0, 3, 5, 18, 40]}, headers=manager)


def test_gst_can_be_switched_off(client, manager, session):
    assert client.patch("/api/india/settings", json={"gst_enabled": False}, headers=manager).json()["gst_enabled"] is False
    try:
        po = purchasing.create_po(session, [(find_product(session, "SNK-401"), 200)], created_by="test")
        summary = purchasing.po_summary(session, po)
        assert summary["tax"]["tax"] == 0 and summary["grand_total"] == summary["total"]
        assert not summary["tax"]["eway_bill_required"] and summary["tax"]["enabled"] is False
        assert client.get("/api/india/gst", headers=manager).json()["enabled"] is False
    finally:
        client.patch("/api/india/settings", json={"gst_enabled": True}, headers=manager)
