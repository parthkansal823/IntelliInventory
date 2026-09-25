"""The agent team: one orchestrator plus four specialists."""

from __future__ import annotations

from dataclasses import dataclass

from .toolkit import Tool, tools

READ_CORE = ["get_inventory_summary", "search_products", "get_product_details", "list_alerts"]

SHARED_RULES = """\
Operating rules:
- Ground every number in tool results; never invent SKUs, quantities or prices. Call a tool when unsure.
- Refer to products as "Name (SKU)". Use compact markdown: short paragraphs, bullet lists, and tables for 3+ rows.
- Write actions: draft purchase orders are safe to create. Stock adjustments, transfers, PO status changes and
  reorder-setting changes are routed to a human approver — when a tool returns `pending_approval`, tell the user
  it is queued (with the approval id) and do not retry it.
- If a tool errors, explain briefly and try a sensible alternative once.
- Finish with a one-line recommendation or next step when it adds value. Be concise."""


@dataclass
class AgentSpec:
    name: str
    title: str
    description: str
    instructions: str
    tool_names: list[str]
    color: str
    icon: str
    can_delegate: bool = False

    @property
    def system_prompt(self) -> str:
        return f"You are {self.title}, part of IntelliInventory's AI operations team.\n{self.instructions}\n\n{SHARED_RULES}"

    def tools(self) -> list[Tool]:
        return tools.subset(self.tool_names)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "icon": self.icon,
            "tools": self.tool_names + (["delegate"] if self.can_delegate else []),
            "can_delegate": self.can_delegate,
        }


AGENTS: dict[str, AgentSpec] = {
    "copilot": AgentSpec(
        name="copilot",
        title="Copilot",
        description="Orchestrator — answers directly or delegates to the right specialist.",
        instructions=(
            "You are the user's single point of contact. Answer quick questions yourself with your read tools. "
            "Delegate focused work with the `delegate` tool: forecasting / what-if → forecaster; reordering, purchase "
            "orders, suppliers and festival stock-ups → procurement; anomalies, stock adjustments, transfers and cycle counts → auditor; "
            "deep analysis (ABC, margins, movement history) → analyst. You may delegate to several specialists in "
            "sequence, then synthesise one clear answer. Don't repeat the specialist's answer verbatim if it is long."
        ),
        tool_names=READ_CORE
        + [
            "get_low_stock_items",
            "get_reorder_recommendations",
            "list_purchase_orders",
            "get_health_score",
            "plan_festival_stock",
            "billing_summary",
            "customer_dues",
            "get_invoice",
        ],
        color="#6366f1",
        icon="sparkles",
        can_delegate=True,
    ),
    "analyst": AgentSpec(
        name="analyst",
        title="Analyst",
        description="KPIs, search, ABC classes, margins and movement history.",
        instructions="You analyse inventory health and sales performance and explain what the numbers mean for the business.",
        tool_names=READ_CORE
        + [
            "abc_analysis",
            "margin_report",
            "get_stock_movements",
            "get_low_stock_items",
            "get_health_score",
            "get_markdown_suggestions",
            "gst_summary",
            "suggest_gst",
            "billing_summary",
            "customer_dues",
            "get_invoice",
        ],
        color="#0ea5e9",
        icon="chart",
    ),
    "forecaster": AgentSpec(
        name="forecaster",
        title="Forecaster",
        description="Demand forecasts, stockout risk and what-if simulations.",
        instructions=(
            "You forecast demand and quantify risk. Always mention forecast method and error (MAPE) when you give a "
            "forecast. For what-if questions use simulate_policy and compare against the current policy when useful."
        ),
        tool_names=[
            "search_products",
            "get_product_details",
            "forecast_demand",
            "simulate_policy",
            "get_reorder_recommendations",
            "plan_festival_stock",
        ],
        color="#10b981",
        icon="trending",
    ),
    "procurement": AgentSpec(
        name="procurement",
        title="Procurement",
        description="Reorder planning, draft purchase orders and supplier management.",
        instructions=(
            "You keep shelves stocked at minimum cost. Use get_reorder_recommendations for quantities (EOQ, MOQ-rounded). "
            "Group lines by supplier — one draft PO per supplier. Consider supplier scorecards when relevant. "
            "Never approve or send orders yourself unless the user explicitly asks (that requires approval)."
        ),
        tool_names=[
            "get_reorder_recommendations",
            "get_low_stock_items",
            "search_products",
            "get_product_details",
            "list_suppliers",
            "list_purchase_orders",
            "create_purchase_order",
            "update_purchase_order_status",
            "update_reorder_settings",
            "plan_festival_stock",
        ],
        color="#f59e0b",
        icon="truck",
    ),
    "auditor": AgentSpec(
        name="auditor",
        title="Auditor",
        description="Anomalies, shrinkage, adjustments, transfers and cycle counts.",
        instructions=(
            "You protect inventory accuracy. Investigate anomalies with the movement ledger, quantify impact in units "
            "and value, and propose corrective actions (adjustments, transfers, cycle counts)."
        ),
        tool_names=[
            "detect_anomalies",
            "get_stock_movements",
            "get_product_details",
            "search_products",
            "list_alerts",
            "adjust_stock",
            "transfer_stock",
            "start_cycle_count",
        ],
        color="#ec4899",
        icon="shield",
    ),
}


def get_agent(name: str | None) -> AgentSpec:
    return AGENTS.get(name or "copilot", AGENTS["copilot"])
