"""IntelliInventory MCP server (Model Context Protocol, SDK v2).

Exposes the same tool registry the in-app agents use - with the same lifecycle
hooks, guardrails and human approvals - to any MCP client: Hermes Agent,
Cursor, VS Code, any MCP-capable client ...

    stdio:  uv run --directory backend python -m app.mcp_server
    HTTP:   served by the API at http://localhost:8000/mcp/  (Bearer INTEGRATION_TOKEN)
"""

from __future__ import annotations

import inspect
import json
import time
import uuid

from mcp.server.mcpserver import MCPServer

from app.agents import tools as _register_tools  # noqa: F401
from app.agents.hooks import RunContext, agent_hooks
from app.agents.runtime import _create_approval, execute_tool
from app.agents.toolkit import Tool, ToolInputError, to_json, tools
from app.db import init_db, session_scope

INSTRUCTIONS = """IntelliInventory: an AI-native inventory system. Use these tools to check stock health, forecast demand,
plan replenishment and investigate anomalies. Draft purchase orders are safe to create. Stock adjustments, transfers,
PO status changes and reorder-setting changes are queued for human approval and return `pending_approval`."""


def _wrap(tool: Tool):
    async def handler(**kwargs):
        ctx = RunContext(
            run_id=uuid.uuid4().hex,
            agent="mcp",
            provider="mcp",
            trigger="mcp",
            user={"name": "MCP client", "email": "mcp@local", "role": "staff"},
        )
        try:
            args = tool.validate(kwargs)  # plain JSON-shaped dicts for hooks, same as in-app agents
        except ToolInputError as exc:
            return to_json({"error": str(exc)})
        decision = await agent_hooks.pre_tool_call(ctx, tool, args)
        if decision.action == "block":
            return to_json({"error": decision.message, "blocked": True})
        if decision.action == "require_approval":
            approval = _create_approval(ctx, tool, tool.validate(decision.args), decision.message)
            return to_json(
                {
                    "status": "pending_approval",
                    "approval_id": approval["id"],
                    "message": "Queued for human approval in the IntelliInventory UI (Copilot → Approvals).",
                }
            )
        started = time.perf_counter()
        result, ok = await execute_tool(tool, decision.args, "mcp:client")
        await agent_hooks.post_tool_call(ctx, tool, decision.args, result, ok, int((time.perf_counter() - started) * 1000))
        return to_json(result)

    handler.__name__ = tool.name
    handler.__doc__ = tool.description
    handler.__signature__ = inspect.signature(tool.fn, eval_str=True).replace(return_annotation=str)
    return handler


def build_server() -> MCPServer:
    server = MCPServer(name="intelliinventory", title="IntelliInventory", instructions=INSTRUCTIONS, version="1.0.0")
    for tool in tools.all():
        server.add_tool(_wrap(tool), name=tool.name, description=tool.description, structured_output=False)

    @server.resource(
        "inventory://summary", name="inventory-summary", description="Live KPI snapshot", mime_type="application/json"
    )
    def summary_resource() -> str:
        return json.dumps(tools.get("get_inventory_summary").run({}), default=str)

    @server.resource(
        "inventory://reorder", name="reorder-list", description="Current reorder recommendations", mime_type="application/json"
    )
    def reorder_resource() -> str:
        return json.dumps(tools.get("get_reorder_recommendations").run({"limit": 50}), default=str)

    @server.prompt(name="daily_briefing", description="Write a morning inventory briefing")
    def daily_briefing_prompt() -> str:
        from app.services.scheduler import BRIEFING_TASK

        return BRIEFING_TASK

    @server.prompt(name="investigate_sku", description="Deep-dive one product: stock, forecast, anomalies, action")
    def investigate_prompt(sku: str) -> str:
        return (
            f"Investigate {sku}: get product details, forecast 30 days, check recent movements for anomalies, "
            "then recommend one concrete action (reorder, transfer, adjust or leave)."
        )

    return server


mcp = build_server()


def main() -> None:
    init_db()
    with session_scope() as s:
        from app.seed import seed_demo

        seed_demo(s)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
