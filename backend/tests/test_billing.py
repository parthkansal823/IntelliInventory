from datetime import date

import pytest

from app.agents.runtime import run_conversation
from app.services import billing, india
from app.services.inventory import find_product, on_hand

from .conftest import MANAGER


def test_amount_in_words_and_financial_year():
    assert (
        billing.amount_in_words(123456.5) == "Rupees One Lakh Twenty-Three Thousand Four Hundred Fifty-Six and Fifty Paise Only"
    )
    assert billing.amount_in_words(25_00_00_000) == "Rupees Twenty-Five Crore Only"
    assert billing.amount_in_words(0) == "Rupees Zero Only"
    assert billing.financial_year(date(2026, 9, 24)) == "26-27"
    assert billing.financial_year(date(2027, 3, 31)) == "26-27"
    assert billing.financial_year(date(2027, 4, 1)) == "27-28"


def test_phone_state_and_upi_normalisation():
    assert india.normalize_phone("98200 12345") == "+91 98200 12345"
    assert india.normalize_phone("+91-98200-12345") == "+91 98200 12345"
    assert india.normalize_phone("098200 12345") == "+91 98200 12345"
    assert india.normalize_phone("+971 50 123 4567") == "+971 50 123 4567"  # foreign customers are fine
    assert india.normalize_phone("0044 20 7946 0958") == "+442079460958"
    with pytest.raises(ValueError):
        india.normalize_phone("12345")
    assert india.normalize_state("tamil nadu") == "Tamil Nadu"
    assert india.normalize_state("Foreign") == "Outside India"
    with pytest.raises(ValueError):
        india.normalize_state("California")
    assert india.normalize_upi("shop@okaxis") == "shop@okaxis"
    with pytest.raises(ValueError):
        india.normalize_upi("not a upi")


def test_demo_has_bills_khata_and_export(client, manager):
    invoices = client.get("/api/invoices", headers=manager).json()
    assert len(invoices) >= 10 and invoices[0]["number"].startswith("INV/")
    assert all(len(i["number"]) <= 16 for i in invoices)  # GST rule 46
    dues = client.get("/api/billing/dues", headers=manager).json()
    assert dues and dues[0]["name"] == "Parth" and dues[0]["balance"] > 0
    export = next(i for i in invoices if i["customer_name"] == "Ananya")
    detail = client.get(f"/api/invoices/{export['id']}", headers=manager).json()
    assert detail["kind"] == "export_invoice" and detail["tax"] == 0 and "LUT" in detail["notes"][0]
    summary = client.get("/api/billing/summary?days=7", headers=manager).json()
    assert summary["period"]["bills"] >= 10 and summary["outstanding"] == pytest.approx(sum(d["balance"] for d in dues))


def test_bill_gst_inclusive_counter_sale_posts_stock(client, manager, session):
    product = find_product(session, "HOM-4001")  # 5% GST
    before = on_hand(session, product.id)
    res = client.post(
        "/api/invoices",
        json={
            "items": [{"sku": "HOM-4001", "quantity": 2, "unit_price": 472.5, "discount_pct": 0}],
            "prices_include_gst": True,
            "payment_mode": "upi",
        },
        headers=manager,
    )
    assert res.status_code == 201, res.text
    inv = res.json()
    assert inv["kind"] == "tax_invoice" and inv["status"] == "paid" and inv["customer_name"] == "Walk-in customer"
    assert inv["taxable"] == 900.0 and inv["cgst"] == inv["sgst"] == 22.5 and inv["igst"] == 0 and inv["total"] == 945.0
    assert inv["amount_in_words"] == "Rupees Nine Hundred Forty-Five Only"
    session.expire_all()
    assert on_hand(session, product.id) == before - 2
    # cancelling puts the stock back
    cancelled = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "test"}, headers=manager).json()
    assert cancelled["status"] == "cancelled" and cancelled["balance"] == 0
    session.expire_all()
    assert on_hand(session, product.id) == before


def test_interstate_b2b_credit_and_payments(client, manager):
    gstin = india.make_gstin("Karnataka", "AAACT4821K")  # buyer in Karnataka, seller in Maharashtra -> IGST
    res = client.post(
        "/api/invoices",
        json={
            "items": [{"sku": "ACC-2002", "quantity": 10, "discount_pct": 10}],
            "customer": {"name": "Ananya", "phone": "+91 99000 11122", "gstin": gstin},
            "payment_mode": "credit",
        },
        headers=manager,
    )
    inv = res.json()
    assert res.status_code == 201, inv
    assert inv["place_of_supply"] == "Karnataka" and inv["interstate"] and inv["igst"] > 0 and inv["cgst"] == 0
    assert inv["status"] == "unpaid" and inv["balance"] == inv["total"] and inv["upi_link"].startswith("upi://pay?")
    assert inv["discount"] == pytest.approx(0.1 * inv["subtotal"], abs=0.01)
    part = client.post(f"/api/invoices/{inv['id']}/payments", json={"amount": 500, "mode": "upi"}, headers=manager).json()
    assert part["status"] == "partial" and part["balance"] == pytest.approx(inv["total"] - 500)
    paid = client.post(f"/api/invoices/{inv['id']}/payments", json={"amount": 10**6, "mode": "cash"}, headers=manager).json()
    assert paid["status"] == "paid" and paid["balance"] == 0 and len(paid["payments"]) == 2


def test_billing_validation(client, manager, viewer):
    walk_in_credit = client.post(
        "/api/invoices", json={"items": [{"sku": "ACC-2002", "quantity": 1}], "payment_mode": "credit"}, headers=manager
    )
    assert walk_in_credit.status_code == 400 and "udhaar" in walk_in_credit.json()["detail"]
    too_many = client.post("/api/invoices", json={"items": [{"sku": "ELC-1004", "quantity": 5}]}, headers=manager)
    assert too_many.status_code == 400 and "Insufficient stock" in too_many.json()["detail"]
    assert client.post("/api/invoices", json={"items": [{"sku": "ACC-2002", "quantity": 1}]}, headers=viewer).status_code == 403
    bad_phone = client.post("/api/customers", json={"name": "Parth", "phone": "123"}, headers=manager)
    assert bad_phone.status_code == 400


def test_business_profile_and_bill_of_supply(client, manager):
    profile = client.patch("/api/billing/profile", json={"invoice_prefix": "sl", "upi_id": "shop@okaxis"}, headers=manager)
    assert profile.json()["invoice_prefix"] == "SL"
    client.patch("/api/india/settings", json={"gst_enabled": False}, headers=manager)
    try:
        inv = client.post("/api/invoices", json={"items": [{"sku": "ACC-2002", "quantity": 1}]}, headers=manager).json()
        assert inv["number"].startswith("SL/") and inv["kind"] == "bill_of_supply" and inv["tax"] == 0
        assert inv["title"] == "Bill of Supply"
    finally:
        client.patch("/api/india/settings", json={"gst_enabled": True}, headers=manager)
        client.patch("/api/billing/profile", json={"invoice_prefix": "INV"}, headers=manager)


async def test_offline_agent_answers_billing_in_hinglish(client):
    async def tool_calls(msg):
        return [e["name"] for e in [e async for e in run_conversation(msg, user=MANAGER)] if e["type"] == "tool_call"]

    assert "customer_dues" in await tool_calls("kiska udhaar baaki hai?")
    assert "billing_summary" in await tool_calls("aaj ki sale kitni hui?")
    assert "get_invoice" in await tool_calls("show invoice INV/26-27/00003")
