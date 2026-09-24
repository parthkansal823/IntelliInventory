---
name: intelliinventory
description: Operate the IntelliInventory system through its MCP tools — check stock health, forecast demand, plan replenishment, draft purchase orders and investigate anomalies. Use whenever the user asks about inventory, stock, reorders, suppliers or warehouse operations.
---

# IntelliInventory operations

IntelliInventory tools are exposed through MCP as `mcp_intelliinventory_<tool>`.

## Ground rules
- Never guess numbers — call a tool. Refer to products as "Name (SKU)".
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

## Resources & prompts
- Resources: `inventory://summary`, `inventory://reorder`
- Prompts: `daily_briefing`, `investigate_sku(sku)`
