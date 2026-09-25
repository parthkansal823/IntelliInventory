---
name: intelliinventory
description: Operate the IntelliInventory system (Indian shops) through its MCP tools — stock health, forecasts, reorders, purchase orders, anomalies, billing and udhaar (khata), GST and festival stock planning. Use whenever the user asks about inventory, stock, reorders, suppliers, sales, bills, udhaar, GST or festival preparation — in English, Hindi or Hinglish.
---

# IntelliInventory operations

IntelliInventory tools are exposed through MCP as `mcp_intelliinventory_<tool>`.

## Ground rules
- Never guess numbers — call a tool. Refer to products as "Name (SKU)".
- Money is Indian rupees: write ₹1,23,456 (lakh/crore grouping). Dates are IST. Reply in the user's language
  (English, Hindi or Hinglish).
- Draft purchase orders are safe. `adjust_stock`, `transfer_stock`, `update_purchase_order_status` and
  `update_reorder_settings` return `pending_approval`: tell the user a manager must approve it in the
  IntelliInventory UI (Copilot → Approvals). Do not retry.

## Playbooks

**Morning check-in**
1. `get_inventory_summary`
2. `list_alerts` (limit 10)
3. `get_reorder_recommendations`
4. Reply with: headline (2 sentences), stock risks, what to reorder, today's 3 priorities.

**"What should I reorder?"**
1. `get_reorder_recommendations` (optionally filter by `supplier`)
2. Group by supplier → `create_purchase_order` once per supplier with the suggested quantities.
3. Report PO numbers and totals; remind the user drafts need approval.

**Forecast / what-if**
1. `forecast_demand` for the SKU (mention method + MAPE).
2. For scenarios ("demand +20%", "lead time 3 weeks") use `simulate_policy` and compare fill rate,
   stockout risk and costs against the default policy.

**Investigate an anomaly**
1. `detect_anomalies`
2. `get_stock_movements` for the SKU (14–30 days)
3. Quantify impact in units and value; propose `start_cycle_count` (scope `A`) or an `adjust_stock`.

**"Aaj ki sale?" / sales today**
1. `billing_summary` (days 1 or 7) → today's sales, bills, UPI vs cash, udhaar outstanding.

**"Kiska udhaar baaki hai?" / who owes money**
1. `customer_dues` → list customers, balance, days outstanding; suggest a WhatsApp reminder from Billing → Khata.
2. For one bill: `get_invoice` with the number (e.g. `INV/26-27/00007`).

**"Aaj ka hisaab" / day-end closing**
1. `day_close` (optionally a date YYYY-MM-DD) → bills, sale, cash in the galla, UPI/card, udhaar given/collected, top items.

**Expiring stock ("kaunsa maal expire hone wala hai?")**
1. `expiring_products` (days 15) → sell first / discount / return to supplier.

**Festival preparation ("Diwali ke liye kya stock karna hai?")**
1. `plan_festival_stock` (festival name optional — defaults to the next one).
2. Festivals follow the shop's state (regional ones like Lohri, Durga Puja, Pongal are included only there).
   Report products to order, quantities and **order-by dates**; offer to draft POs with `create_purchase_order`.

**GST**
1. `gst_summary` for output tax vs input tax credit by slab (GST can be switched off by the shop).
2. `suggest_gst` for the HSN code and slab of a product name — always add "confirm with your CA".

## Resources & prompts
- Resources: `inventory://summary`, `inventory://reorder`
- Prompts: `daily_briefing`, `investigate_sku(sku)`
