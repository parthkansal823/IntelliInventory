"""Sales returns, supplier khata, offers & loyalty, offline sync, voice billing and backup."""

import sqlite3
import uuid

import pytest

from app.agents.runtime import run_conversation
from app.services import offers
from app.services.inventory import find_product, on_hand
from app.services.voice import split_order

from .conftest import MANAGER


def _bill(client, manager, items, **extra):
    res = client.post("/api/invoices", json={"items": items, "prices_include_gst": True, **extra}, headers=manager)
    assert res.status_code == 201, res.text
    return res.json()


def test_partial_return_issues_credit_note_and_restocks(client, manager, session):
    bill = _bill(client, manager, [{"sku": "PRC-602", "quantity": 3}, {"sku": "HMC-702", "quantity": 2}], payment_mode="cash")
    product = find_product(session, "PRC-602")
    before = on_hand(session, product.id)
    line = next(ln for ln in bill["lines"] if ln["sku"] == "PRC-602")

    res = client.post(
        f"/api/invoices/{bill['id']}/return",
        json={"items": [{"line_id": line["id"], "quantity": 1}], "refund_mode": "cash", "reason": "damaged pack"},
        headers=manager,
    )
    assert res.status_code == 200, res.text
    note, inv = res.json()["credit_note"], res.json()["invoice"]
    assert note["number"].startswith("CN/") and note["total"] == round(line["total"] / 3)
    assert note["refunded"] == note["total"]  # bill was paid in full, so it is a cash refund
    assert inv["balance"] == 0 and inv["status"] == "paid" and inv["returned"] == note["total"]
    assert next(ln for ln in inv["lines"] if ln["id"] == line["id"])["returned_qty"] == 1
    session.expire_all()
    assert on_hand(session, product.id) == before + 1

    too_many = client.post(
        f"/api/invoices/{bill['id']}/return", json={"items": [{"line_id": line["id"], "quantity": 3}]}, headers=manager
    )
    assert too_many.status_code == 400 and "Only 2" in too_many.json()["detail"]

    close = client.get("/api/billing/day-close", headers=manager).json()
    assert close["returns"] >= note["total"] and close["refunds"]["cash"] >= note["total"]
    assert close["net_sales"] == round(close["sales"] - close["returns"], 2)
    csv = client.get("/api/invoices/export.csv?days=1", headers=manager).text
    assert note["number"] in csv and "CREDIT NOTE" in csv

    # returning the rest of the bill leaves nothing to refund twice; cancelling posts back only what is left
    rest = [{"line_id": ln["id"], "quantity": ln["quantity"] - ln["returned_qty"]} for ln in inv["lines"]]
    full = client.post(f"/api/invoices/{bill['id']}/return", json={"items": rest}, headers=manager).json()
    assert full["invoice"]["returned"] == bill["total"]


def test_return_on_udhaar_bill_reduces_the_balance_first(client, manager):
    bill = _bill(
        client,
        manager,
        [{"sku": "HMC-701", "quantity": 2}],
        payment_mode="credit",
        customer={"name": "Parth", "phone": "+91 98140 45678"},
    )
    line = bill["lines"][0]
    res = client.post(
        f"/api/invoices/{bill['id']}/return", json={"items": [{"line_id": line["id"], "quantity": 1}]}, headers=manager
    ).json()
    assert res["credit_note"]["refunded"] == 0 and res["credit_note"]["adjusted"] == res["credit_note"]["total"]
    assert res["invoice"]["balance"] == bill["total"] - res["credit_note"]["total"]


def test_supplier_khata_bills_payments_and_po_receipt(client, manager):
    data = client.get("/api/payables", headers=manager).json()
    assert data["summary"]["total"] > 0 and data["summary"]["overdue"] > 0  # seeded: one bill overdue
    first = data["suppliers"][0]
    assert first["overdue"] > 0 and first["bills"][0]["overdue"]

    supplier_id = first["supplier_id"]
    paid = client.post(
        "/api/supplier-payments",
        json={"supplier_id": supplier_id, "amount": first["balance"] + 999, "mode": "upi", "reference": "UTR123"},
        headers=manager,
    ).json()
    assert paid["amount"] == first["balance"] and paid["balance"] == 0  # capped at what is owed, oldest bills first
    assert client.get(f"/api/payables/{supplier_id}", headers=manager).json()["balance"] == 0

    added = client.post(
        "/api/supplier-bills", json={"supplier_id": supplier_id, "amount": 1500, "bill_no": "X-1"}, headers=manager
    )
    assert added.status_code == 201 and added.json()["due_date"] > added.json()["bill_date"]

    # receiving a purchase order puts it on the supplier khata
    salt = next(p for p in client.get("/api/products", headers=manager).json() if p["sku"] == "ATA-106")
    po = client.post(
        "/api/purchase-orders",
        json={"lines": [{"product_id": salt["id"], "quantity": 25}], "notes": "khata test"},
        headers=manager,
    ).json()
    for status in ("approved", "ordered", "received"):
        res = client.post(f"/api/purchase-orders/{po['id']}/status", json={"status": status}, headers=manager)
        assert res.status_code == 200, res.text
    rows = client.get(f"/api/payables/{po['supplier']['id']}", headers=manager).json()
    assert any(b["po_id"] == po["id"] for b in rows["bills"])


def test_payable_due_alerts(session):
    from app.services.payables import raise_due_alerts

    first = raise_due_alerts(session)
    assert first and all(r["amount"] > 0 for r in first)
    assert raise_due_alerts(session) == []  # no duplicate alerts


def test_apply_offers_vectors():
    cfg = {
        "enabled": True,
        "offers": [
            offers.clean_offer({"type": "buy_x_get_y", "sku": "SNK-404", "buy": 2, "free": 1}),
            offers.clean_offer({"type": "item_percent", "category": "Personal Care", "percent": 10}),
            offers.clean_offer({"type": "bill_percent", "min_amount": 500, "percent": 5}),
        ],
    }
    lines = [
        {"sku": "SNK-404", "category": "Snacks & Biscuits", "quantity": 6, "unit_price": 45},
        {"sku": "PRC-602", "category": "Personal Care", "quantity": 1, "unit_price": 100, "discount_pct": 20},
        {"sku": "ATA-101", "category": "Atta Rice & Dal", "quantity": 1, "unit_price": 420},
    ]
    out = offers.apply_offers(lines, cfg)
    pct = [ln["discount_pct"] for ln in out["lines"]]
    # 6 chocolates: 2 free (33.33%) + 5% bill offer; toothpaste keeps the bigger manual 20% (+5%); atta gets 5%
    assert pct == [36.66, 24.0, 5.0]
    assert len(out["applied"]) == 2
    assert offers.apply_offers(lines, {**cfg, "enabled": False})["lines"][0]["discount_pct"] == 0
    with pytest.raises(offers.OfferError):
        offers.clean_offer({"type": "bill_percent", "percent": 95})


def test_loyalty_is_off_by_default_then_earns_and_redeems(client, manager):
    assert client.get("/api/billing/offers", headers=manager).json()["enabled"] is False
    parth = {"name": "Parth", "phone": "+91 98140 45678"}
    no_points = client.post(
        "/api/invoices",
        json={"items": [{"sku": "ATA-106", "quantity": 1}], "customer": parth, "redeem_points": 50},
        headers=manager,
    )
    assert no_points.status_code == 400 and "switched off" in no_points.json()["detail"]

    cfg = client.put(
        "/api/billing/offers",
        json={"enabled": True, "loyalty": {"enabled": True, "earn_per_100": 2, "point_value": 1, "min_redeem": 50}},
        headers=manager,
    )
    assert cfg.status_code == 200
    try:
        customer_id = client.get("/api/billing/dues", headers=manager).json()[0]["customer_id"]
        start = client.get(f"/api/customers/{customer_id}", headers=manager).json()["points"]
        bill = _bill(client, manager, [{"sku": "ATA-101", "quantity": 1}], customer=parth, redeem_points=100)
        assert bill["points_earned"] == int((bill["total"] - 100) / 100 * 2)
        assert any(p["mode"] == "points" and p["amount"] == 100 for p in bill["payments"]) and bill["balance"] == 0
        after = client.get(f"/api/customers/{customer_id}", headers=manager).json()
        assert after["points"] == start - 100 + bill["points_earned"]
        assert after["bills"] >= 1 and after["top_items"] and after["total_spent"] > 0
        client.post(f"/api/invoices/{bill['id']}/cancel", json={"reason": "test"}, headers=manager)
        assert client.get(f"/api/customers/{customer_id}", headers=manager).json()["points"] == start
    finally:
        client.put("/api/billing/offers", json={"enabled": False, "loyalty": {"enabled": False}}, headers=manager)


def test_offline_bill_sync_is_idempotent(client, manager, session):
    ref = str(uuid.uuid4())
    product = find_product(session, "PUJ-901")
    before = on_hand(session, product.id)
    body = {"items": [{"sku": "PUJ-901", "quantity": 2}], "client_ref": ref, "created_at": "2020-01-01T10:00:00+05:30"}
    first = client.post("/api/invoices", json=body, headers=manager).json()
    second = client.post("/api/invoices", json=body, headers=manager).json()
    assert first["id"] == second["id"] and first["number"].count("/") == 2
    assert first["created_at"][:4] != "2020"  # implausible offline times fall back to now
    session.expire_all()
    assert on_hand(session, product.id) == before - 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("दो किलो आटा और एक मैगी", [("ATA-101", 2), ("SNK-405", 1)]),
        ("2 atta 1 maggi", [("ATA-101", 2), ("SNK-405", 1)]),
        ("cheeni do packet, namak ek", [("ATA-105", 2), ("ATA-106", 1)]),
        ("paanch agarbatti aur ek kapoor de do", [("PUJ-901", 5), ("PUJ-903", 1)]),
        ("3 ATA-103", [("ATA-103", 3)]),
    ],
)
def test_voice_order_parser(client, manager, text, expected):
    res = client.post("/api/billing/parse", json={"text": text}, headers=manager).json()
    assert [(i["sku"], i["quantity"]) for i in res["items"]] == expected, res


def test_voice_parser_reports_unknown_words(client, manager):
    res = client.post("/api/billing/parse", json={"text": "ek hawai jahaz aur do sabun"}, headers=manager).json()
    assert [(i["sku"], i["quantity"]) for i in res["items"]] == [("PRC-601", 2)]
    assert res["unmatched"]
    assert split_order("de do") == ("de do", [])


def test_backup_is_a_valid_sqlite_file(client, tmp_path):
    token = client.post("/api/auth/token", json={"email": "parth@intelliinventory.dev", "password": "demo1234"}).json()
    res = client.get("/api/system/backup", headers={"Authorization": f"Bearer {token['access_token']}"})
    assert res.status_code == 200 and "intelliinventory-" in res.headers["content-disposition"]
    path = tmp_path / "backup.db"
    path.write_bytes(res.content)
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from invoice").fetchone()[0] > 0


def test_backup_needs_admin(client, manager):
    assert client.get("/api/system/backup", headers=manager).status_code == 403


async def test_offline_agent_payables_history_and_returns(client):
    async def tool_calls(msg):
        return [e["name"] for e in [e async for e in run_conversation(msg, user=MANAGER)] if e["type"] == "tool_call"]

    assert "supplier_dues" in await tool_calls("supplier ko kitna dena hai?")
    assert "customer_history" in await tool_calls("Parth ki history dikhao")
    calls = await tool_calls("KGS/26-27/00001 se ATA-101 1 wapas karo")
    assert "delegate" in calls or "return_items" in calls
