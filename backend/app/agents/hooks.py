"""Agent lifecycle hooks — same names and semantics as Hermes Agent plugins.

    pre_llm_call   (ctx, user_message)            -> {"context": str} | None
    post_llm_call  (ctx, response)                -> None
    pre_tool_call  (ctx, tool, args)              -> {"action": "allow" | "block" | "modify" | "require_approval",
                                                      "message": str, "args": dict} | None
    post_tool_call (ctx, tool, args, result, ok, duration_ms) -> None
    agent:start / agent:step / agent:end (ctx, **data) -> None

Hooks may be sync or async. Exceptions are logged and skipped so a faulty
hook never breaks a run. Every hook can be toggled from the Automation page.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.hooks.bus import bus, toggles

from .toolkit import Tool

log = logging.getLogger("intelliinventory.agents.hooks")

LIFECYCLE_EVENTS = ("pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call", "agent:start", "agent:step", "agent:end")


@dataclass
class RunContext:
    run_id: str
    agent: str
    provider: str
    trigger: str = "chat"  # chat | autopilot | schedule | approval | mcp
    conversation_id: str | None = None
    user: dict | None = None  # {"email", "role", "name"}
    depth: int = 0
    step: int = 0
    notes: list[dict] = field(default_factory=list)


@dataclass
class AgentHook:
    name: str
    event: str
    fn: Callable[..., Any]
    description: str = ""
    priority: int = 100
    builtin: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "event": self.event,
            "description": self.description,
            "priority": self.priority,
            "builtin": self.builtin,
            "enabled": toggles.is_enabled(self.name),
            "kind": "agent",
        }


@dataclass
class ToolDecision:
    action: str = "allow"
    args: dict = field(default_factory=dict)
    message: str | None = None
    applied: list[dict] = field(default_factory=list)  # which hooks acted, for the UI/trace


class AgentHookRegistry:
    def __init__(self) -> None:
        self._hooks: list[AgentHook] = []

    def on(self, event: str, *, name: str | None = None, description: str = "", priority: int = 100, builtin: bool = True):
        if event not in LIFECYCLE_EVENTS:
            raise ValueError(f"Unknown lifecycle event {event!r}; expected one of {LIFECYCLE_EVENTS}")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                AgentHook(
                    name or fn.__name__, event, fn, description or (inspect.getdoc(fn) or "").split("\n")[0], priority, builtin
                )
            )
            return fn

        return decorator

    def register(self, hook: AgentHook) -> None:
        self._hooks = [h for h in self._hooks if h.name != hook.name]
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)

    @property
    def hooks(self) -> list[AgentHook]:
        return list(self._hooks)

    def _active(self, event: str) -> list[AgentHook]:
        return [h for h in self._hooks if h.event == event and toggles.is_enabled(h.name)]

    async def _call(self, hook: AgentHook, *args: Any, **kwargs: Any) -> Any:
        try:
            result = hook.fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception:  # noqa: BLE001 - Hermes semantics: log and continue
            log.exception("agent hook %s (%s) failed", hook.name, hook.event)
            return None

    async def pre_llm_call(self, ctx: RunContext, user_message: str) -> list[str]:
        snippets = []
        for hook in self._active("pre_llm_call"):
            result = await self._call(hook, ctx, user_message)
            if isinstance(result, dict) and result.get("context"):
                snippets.append(str(result["context"]))
        return snippets

    async def post_llm_call(self, ctx: RunContext, response: str) -> None:
        for hook in self._active("post_llm_call"):
            await self._call(hook, ctx, response)

    async def pre_tool_call(self, ctx: RunContext, tool: Tool, args: dict) -> ToolDecision:
        decision = ToolDecision(args=dict(args))
        for hook in self._active("pre_tool_call"):
            result = await self._call(hook, ctx, tool, dict(decision.args))
            if not isinstance(result, dict) or result.get("action", "allow") == "allow":
                continue
            action = result["action"]
            decision.applied.append({"hook": hook.name, "action": action, "message": result.get("message")})
            if action == "modify" and isinstance(result.get("args"), dict):
                decision.args = result["args"]
            elif action == "block":
                decision.action, decision.message = "block", result.get("message") or f"Blocked by {hook.name}"
                return decision
            elif action == "require_approval":
                decision.action = "require_approval"
                decision.message = result.get("message") or decision.message
        return decision

    async def post_tool_call(self, ctx: RunContext, tool: Tool, args: dict, result: Any, ok: bool, duration_ms: int) -> None:
        for hook in self._active("post_tool_call"):
            await self._call(hook, ctx, tool, args, result, ok, duration_ms)

    async def emit(self, event: str, ctx: RunContext, **data: Any) -> None:
        for hook in self._active(event):
            await self._call(hook, ctx, **data)


agent_hooks = AgentHookRegistry()


# --- built-in hooks ------------------------------------------------------------------------

MAX_ADJUSTMENT = 5_000
MAX_ORDER_LINE = 20_000


@agent_hooks.on("pre_tool_call", name="sku_normalizer", description="Normalize SKU arguments (trim, upper-case)", priority=10)
def sku_normalizer(ctx: RunContext, tool: Tool, args: dict) -> dict | None:
    changed = False
    if isinstance(args.get("sku"), str) and args["sku"] != args["sku"].strip().upper() and "-" in args["sku"]:
        args["sku"], changed = args["sku"].strip().upper(), True
    for item in args.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("sku"), str) and item["sku"] != item["sku"].strip().upper():
            item["sku"], changed = item["sku"].strip().upper(), True
    return {"action": "modify", "args": args, "message": "Normalized SKU casing"} if changed else None


@agent_hooks.on("pre_tool_call", name="role_guard", description="Viewers cannot run write tools", priority=20)
def role_guard(ctx: RunContext, tool: Tool, args: dict) -> dict | None:
    if tool.mutates and ctx.user and ctx.user.get("role") == "viewer":
        return {"action": "block", "message": "Your role (viewer) is read-only; ask a staff member or manager."}
    return None


@agent_hooks.on(
    "pre_tool_call", name="quantity_guardrail", description="Block implausible quantities before they hit the ledger", priority=30
)
def quantity_guardrail(ctx: RunContext, tool: Tool, args: dict) -> dict | None:
    delta = args.get("quantity_delta")
    if isinstance(delta, int) and abs(delta) > MAX_ADJUSTMENT:
        return {"action": "block", "message": f"Adjustment of {delta} exceeds the ±{MAX_ADJUSTMENT} safety limit."}
    for item in args.get("items") or []:
        qty = item.get("quantity") if isinstance(item, dict) else None
        if isinstance(qty, int) and qty > MAX_ORDER_LINE:
            return {"action": "block", "message": f"Order line of {qty} units exceeds the {MAX_ORDER_LINE} unit limit."}
    return None


@agent_hooks.on("pre_tool_call", name="approval_gate", description="Route sensitive write tools to a human approver", priority=50)
def approval_gate(ctx: RunContext, tool: Tool, args: dict) -> dict | None:
    if tool.requires_approval and ctx.trigger != "approval":
        return {"action": "require_approval", "message": f"{tool.name} changes stock or orders and needs a manager's approval."}
    return None


@agent_hooks.on("post_tool_call", name="tool_audit", description="Publish every agent tool call to the audit trail", priority=10)
def tool_audit(ctx: RunContext, tool: Tool, args: dict, result: Any, ok: bool, duration_ms: int) -> None:
    bus.emit(
        "agent.tool_called",
        {
            "agent": ctx.agent,
            "tool": tool.name,
            "args": args,
            "ok": ok,
            "duration_ms": duration_ms,
            "trigger": ctx.trigger,
            "conversation_id": ctx.conversation_id,
            "provider": ctx.provider,
        },
        source=f"agent:{ctx.agent}",
    )


@agent_hooks.on(
    "pre_llm_call", name="inventory_context", description="Inject a live inventory snapshot into each turn", priority=10
)
def inventory_context(ctx: RunContext, user_message: str) -> dict | None:
    from sqlalchemy import func
    from sqlmodel import select

    from app.db import session_scope
    from app.models import Alert, ApprovalRequest, ApprovalStatus, POStatus, PurchaseOrder, utcnow
    from app.services.analytics import compute_metrics

    with session_scope() as s:
        metrics = compute_metrics(s)
        drafts = s.exec(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == POStatus.DRAFT)).one()
        alerts = s.exec(select(func.count()).select_from(Alert).where(Alert.resolved == False)).one()  # noqa: E712
        pending = s.exec(
            select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == ApprovalStatus.PENDING)
        ).one()
    counts = {k: sum(1 for m in metrics if m.status == k) for k in ("out", "critical", "low", "overstock")}
    who = f" User: {ctx.user['name']} ({ctx.user['role']})." if ctx.user else ""
    return {
        "context": (
            f"Today is {utcnow():%A %d %B %Y}.{who} Live snapshot: {len(metrics)} active SKUs; "
            f"{counts['out']} out of stock, {counts['critical']} critical, {counts['low']} low, {counts['overstock']} overstocked; "
            f"{alerts} open alerts; {drafts} draft POs awaiting approval; {pending} agent actions awaiting approval."
        )
    }


@agent_hooks.on("agent:end", name="run_reporter", description="Publish agent.run.completed events", priority=90)
def run_reporter(ctx: RunContext, response: str = "", **data: Any) -> None:
    if ctx.depth == 0:
        bus.emit(
            "agent.run.completed",
            {
                "agent": ctx.agent,
                "provider": ctx.provider,
                "trigger": ctx.trigger,
                "conversation_id": ctx.conversation_id,
                "chars": len(response or ""),
            },
            source=f"agent:{ctx.agent}",
        )
