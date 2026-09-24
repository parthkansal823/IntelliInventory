"""Agent runtime: the streaming tool-use loop shared by every provider.

    user msg -> pre_llm_call hooks (context) -> provider turn (streamed)
      -> for each tool call: pre_tool_call hooks (block / modify / approval)
         -> execute (threadpool) -> post_tool_call hooks -> tool result
      -> repeat until the model answers without tools -> post_llm_call, agent:end

The orchestrator can `delegate` to specialists; their events stream inline
(depth 1). Every run is traced; conversations persist an append-only neutral
transcript so any provider can continue any conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from pydantic import Field
from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.hooks.bus import bus
from app.models import AgentTrace, ApprovalRequest, ApprovalStatus, Conversation, utcnow
from app.services.inventory import InventoryError

from . import tools as _register_tools  # noqa: F401  (registers inventory tools)
from .hooks import RunContext, agent_hooks
from .providers import Provider, ProviderError, get_provider
from .registry import AGENTS, AgentSpec, get_agent
from .toolkit import Tool, ToolInputError, ToolRegistry, current_actor, to_json, tools

log = logging.getLogger("intelliinventory.agents")

# --- delegation tool (orchestrator only; deliberately not in the shared/MCP registry) ------

_private = ToolRegistry()


def delegate(
    agent: Annotated[
        Literal["analyst", "forecaster", "procurement", "auditor"], Field(description="Specialist to hand the task to")
    ],
    task: Annotated[str, Field(description="Self-contained instruction for the specialist, including any SKUs or constraints")],
) -> dict:
    """Delegate a focused task to a specialist agent and receive its answer."""
    raise RuntimeError("delegate is executed by the runtime")


DELEGATE_TOOL: Tool = _private.add(delegate)


# --- tracing ------------------------------------------------------------------------------


class Trace:
    def __init__(self, ctx: RunContext, user_input: str, model: str | None) -> None:
        self.id = ctx.run_id
        self.ctx = ctx
        self.input = user_input
        self.model = model
        self.started = time.perf_counter()
        self.steps: list[dict] = []
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, kind: str, **data: Any) -> None:
        self.steps.append({"kind": kind, "at_ms": int((time.perf_counter() - self.started) * 1000), **data})

    def save(self, status: str, output: str) -> None:
        trace = AgentTrace(
            id=self.id,
            conversation_id=self.ctx.conversation_id,
            agent=self.ctx.agent,
            provider=self.ctx.provider,
            model=self.model,
            trigger=self.ctx.trigger,
            input=self.input[:4000],
            output=output[:8000],
            status=status,
            steps=self.steps,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            duration_ms=int((time.perf_counter() - self.started) * 1000),
        )
        with session_scope() as s:
            s.merge(trace)
            s.commit()


def _preview(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else to_json(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _display_result(result: Any) -> Any:
    text = to_json(result)
    return result if len(text) <= 12_000 else {"truncated": True, "preview": text[:4000]}


# --- tool execution & approvals -------------------------------------------------------------


async def execute_tool(tool: Tool, args: dict, actor: str) -> tuple[Any, bool]:
    token = current_actor.set(actor)
    try:
        return await asyncio.to_thread(tool.run, args), True
    except (ToolInputError, InventoryError, ValueError) as exc:
        return {"error": str(exc)}, False
    except Exception as exc:  # noqa: BLE001
        log.exception("tool %s crashed", tool.name)
        return {"error": f"{type(exc).__name__}: {exc}"}, False
    finally:
        current_actor.reset(token)


def approval_to_dict(a: ApprovalRequest) -> dict:
    return {
        "id": a.id,
        "conversation_id": a.conversation_id,
        "agent": a.agent,
        "tool": a.tool,
        "args": a.args,
        "reason": a.reason,
        "status": a.status,
        "result": a.result,
        "created_at": a.created_at.isoformat(),
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


def _create_approval(ctx: RunContext, tool: Tool, args: dict, reason: str | None) -> dict:
    with session_scope() as s:
        approval = ApprovalRequest(conversation_id=ctx.conversation_id, agent=ctx.agent, tool=tool.name, args=args, reason=reason)
        s.add(approval)
        s.commit()
        s.refresh(approval)
        data = approval_to_dict(approval)
    bus.emit("approval.requested", data, source=f"agent:{ctx.agent}")
    return data


# --- the loop ---------------------------------------------------------------------------------


def _event(type: str, ctx: RunContext, **data: Any) -> dict:
    return {"type": type, "agent": ctx.agent, "depth": ctx.depth, **data}


async def run_agent(
    spec: AgentSpec, user_message: str, transcript: list[dict], provider: Provider, ctx: RunContext, trace: Trace
) -> AsyncIterator[dict]:
    agent_tools = spec.tools() + ([DELEGATE_TOOL] if spec.can_delegate and ctx.depth == 0 else [])
    by_name = {t.name: t for t in agent_tools}
    yield _event("agent_start", ctx, title=spec.title, provider=provider.name, model=provider.model, color=spec.color)
    await agent_hooks.emit("agent:start", ctx, message=user_message)

    snippets = await agent_hooks.pre_llm_call(ctx, user_message)
    for snippet in snippets:
        trace.add("hook", agent=ctx.agent, hook="pre_llm_call", action="context", message=_preview(snippet, 300))
    content = user_message if not snippets else f"{user_message}\n\n<context>\n" + "\n".join(snippets) + "\n</context>"
    transcript.append({"role": "user", "content": content})

    final_text = ""
    for step in range(get_settings().agent_max_steps):
        ctx.step = step
        started = time.perf_counter()
        message = None
        async for pev in provider.stream(system=spec.system_prompt, messages=transcript, tools=agent_tools, agent=spec.name):
            if pev.type == "message":
                message = pev.message
            elif pev.text:
                yield _event(pev.type, ctx, delta=pev.text)
        if message is None:
            raise ProviderError("Provider ended the turn without a message")
        transcript.append(message.to_neutral(provider.name))
        trace.input_tokens += message.input_tokens
        trace.output_tokens += message.output_tokens
        trace.add(
            "llm",
            agent=ctx.agent,
            depth=ctx.depth,
            step=step,
            model=message.model,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stop_reason=message.stop_reason,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            tool_calls=[c.name for c in message.tool_calls],
            text=_preview(message.content, 300),
        )
        if not message.tool_calls:
            final_text = message.content
            break

        await agent_hooks.emit("agent:step", ctx, iteration=step, tool_names=[c.name for c in message.tool_calls])
        for call in message.tool_calls:
            yield _event("tool_call", ctx, id=call.id, name=call.name, args=call.args)
            t0 = time.perf_counter()
            ok, result, decision_label = True, None, "allow"

            if call.name == "delegate" and "delegate" in by_name:
                holder: dict = {}
                async for sub in _delegate(call.args, ctx, provider, trace, holder):
                    yield sub
                result, ok = holder.get("result", {"error": "delegation failed"}), "error" not in holder.get("result", {})
            elif (tool := by_name.get(call.name)) is None:
                result, ok = {"error": f"Unknown tool '{call.name}'. Available: {', '.join(by_name)}"}, False
            else:
                decision = await agent_hooks.pre_tool_call(ctx, tool, call.args)
                for applied in decision.applied:
                    trace.add(
                        "hook",
                        agent=ctx.agent,
                        hook=applied["hook"],
                        action=applied["action"],
                        tool=tool.name,
                        message=applied["message"],
                    )
                    yield _event("hook", ctx, tool=tool.name, **applied)
                decision_label = decision.action
                if decision.action == "block":
                    result, ok = {"error": decision.message, "blocked": True}, False
                elif decision.action == "require_approval":
                    try:
                        validated = tool.validate(decision.args)
                    except ToolInputError as exc:
                        result, ok = {"error": str(exc)}, False
                    else:
                        approval = await asyncio.to_thread(_create_approval, ctx, tool, validated, decision.message)
                        trace.add("approval", agent=ctx.agent, tool=tool.name, approval_id=approval["id"])
                        yield _event("approval", ctx, approval=approval)
                        result = {
                            "status": "pending_approval",
                            "approval_id": approval["id"],
                            "message": "Queued for human approval. It will run once a manager approves it.",
                        }
                else:
                    result, ok = await execute_tool(tool, decision.args, f"agent:{ctx.agent}")
                await agent_hooks.post_tool_call(ctx, tool, decision.args, result, ok, int((time.perf_counter() - t0) * 1000))

            duration = int((time.perf_counter() - t0) * 1000)
            trace.add(
                "tool",
                agent=ctx.agent,
                depth=ctx.depth,
                name=call.name,
                args=call.args,
                ok=ok,
                decision=decision_label,
                duration_ms=duration,
                result=_preview(result),
            )
            yield _event(
                "tool_result", ctx, id=call.id, name=call.name, ok=ok, duration_ms=duration, result=_display_result(result)
            )
            transcript.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": to_json(result), "is_error": not ok}
            )
    else:
        final_text = (message.content if message else "") or "I stopped after reaching the step limit for this request."

    await agent_hooks.post_llm_call(ctx, final_text)
    await agent_hooks.emit("agent:end", ctx, response=final_text)
    yield _event("agent_end", ctx, text=final_text)


async def _delegate(args: dict, parent: RunContext, provider: Provider, trace: Trace, holder: dict) -> AsyncIterator[dict]:
    target, task = args.get("agent"), (args.get("task") or "").strip()
    spec = AGENTS.get(target) if target != "copilot" else None
    if spec is None or not task:
        holder["result"] = {
            "error": f"Cannot delegate to '{target}'. Choose analyst, forecaster, procurement or auditor with a task."
        }
        return
    sub_ctx = RunContext(
        run_id=parent.run_id,
        agent=spec.name,
        provider=parent.provider,
        trigger=parent.trigger,
        conversation_id=parent.conversation_id,
        user=parent.user,
        depth=parent.depth + 1,
    )
    trace.add("delegate", agent=parent.agent, to=spec.name, task=_preview(task, 300))
    answer = ""
    async for event in run_agent(spec, task, [], provider, sub_ctx, trace):
        if event["type"] == "agent_end" and event["depth"] == sub_ctx.depth:
            answer = event["text"]
        yield event
    holder["result"] = {"agent": spec.name, "answer": answer}


# --- conversations -------------------------------------------------------------------------------


def repair_transcript(transcript: list[dict]) -> None:
    """Close dangling tool calls (e.g. after a disconnect) so every provider accepts the history."""
    answered = {m["tool_call_id"] for m in transcript if m["role"] == "tool"}
    for i in range(len(transcript) - 1, -1, -1):
        m = transcript[i]
        if m["role"] == "assistant":
            missing = [c for c in m.get("tool_calls", []) if c["id"] not in answered]
            for c in missing:
                transcript.append(
                    {
                        "role": "tool",
                        "tool_call_id": c["id"],
                        "name": c["name"],
                        "content": to_json({"error": "Interrupted before this tool ran"}),
                        "is_error": True,
                    }
                )
            break


def _record_display(display: list[dict], event: dict) -> None:
    if event["type"] in ("text", "thinking"):
        last = display[-1] if display else None
        if last and last["type"] == event["type"] and last.get("agent") == event["agent"] and last.get("depth") == event["depth"]:
            last["text"] += event["delta"]
        else:
            display.append({"type": event["type"], "agent": event["agent"], "depth": event["depth"], "text": event["delta"]})
    else:
        display.append(event)


def _load_conversation(conversation_id: str | None, agent: str, provider: str, title: str) -> Conversation:
    with session_scope() as s:
        conv = s.get(Conversation, conversation_id) if conversation_id else None
        if conv is None:
            conv = Conversation(
                id=conversation_id or uuid.uuid4().hex, title=title[:80] or "New conversation", agent=agent, provider=provider
            )
            s.add(conv)
            s.commit()
            s.refresh(conv)
        return conv


def _save_conversation(conv_id: str, transcript: list[dict], display: list[dict], agent: str, provider: str) -> None:
    with session_scope() as s:
        conv = s.get(Conversation, conv_id)
        if conv is None:
            return
        conv.messages, conv.display = list(transcript), list(display)
        conv.agent, conv.provider, conv.updated_at = agent, provider, utcnow()
        s.add(conv)
        s.commit()


async def run_conversation(
    message: str,
    *,
    conversation_id: str | None = None,
    agent: str | None = None,
    provider: str | None = None,
    user: dict | None = None,
    trigger: str = "chat",
    title: str | None = None,
) -> AsyncIterator[dict]:
    """Run one user turn inside a persisted conversation, streaming UI events."""
    prov = get_provider(provider)
    spec = get_agent(agent)
    conv = await asyncio.to_thread(_load_conversation, conversation_id, spec.name, prov.name, title or message)
    transcript, display = list(conv.messages or []), list(conv.display or [])
    repair_transcript(transcript)
    ctx = RunContext(
        run_id=uuid.uuid4().hex, agent=spec.name, provider=prov.name, trigger=trigger, conversation_id=conv.id, user=user
    )
    trace = Trace(ctx, message, prov.model)
    display.append({"type": "user", "text": message, "ts": utcnow().isoformat(), "user": (user or {}).get("name")})
    yield {
        "type": "conversation",
        "id": conv.id,
        "title": conv.title,
        "agent": spec.name,
        "provider": prov.name,
        "model": prov.model,
        "run_id": ctx.run_id,
    }

    status, output = "ok", ""
    try:
        async for event in run_agent(spec, message, transcript, prov, ctx, trace):
            _record_display(display, event)
            if event["type"] == "agent_end" and event["depth"] == 0:
                output = event["text"]
            yield event
    except ProviderError as exc:
        status = "error"
        event = {
            "type": "error",
            "agent": spec.name,
            "depth": 0,
            "message": str(exc),
            "hint": "Switch to the free Offline or Hermes (Ollama) provider in the Copilot header.",
        }
        display.append(event)
        yield event
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run failed")
        status = "error"
        event = {"type": "error", "agent": spec.name, "depth": 0, "message": f"{type(exc).__name__}: {exc}"}
        display.append(event)
        yield event
    finally:
        repair_transcript(transcript)
        try:
            _save_conversation(conv.id, transcript, display, spec.name, prov.name)
            trace.save(status, output)
        except Exception:  # noqa: BLE001
            log.exception("failed to persist conversation %s", conv.id)

    yield {
        "type": "done",
        "conversation_id": conv.id,
        "trace_id": trace.id,
        "status": status,
        "usage": {"input_tokens": trace.input_tokens, "output_tokens": trace.output_tokens},
    }


async def run_autonomous(agent: str, task: str, *, trigger: str, title: str | None = None, provider: str | None = None) -> str:
    """Run an agent without a human in the loop (autopilot, scheduled jobs). Returns the final answer."""
    answer = ""
    async for event in run_conversation(task, agent=agent, provider=provider, trigger=trigger, title=title or task):
        if event["type"] == "agent_end" and event["depth"] == 0:
            answer = event["text"]
    return answer


# --- approvals ----------------------------------------------------------------------------------


def _append_note(conversation_id: str | None, approval: dict, note: str) -> None:
    if not conversation_id:
        return
    with session_scope() as s:
        conv = s.get(Conversation, conversation_id)
        if conv is None:
            return
        conv.messages = [*conv.messages, {"role": "user", "content": note}]
        conv.display = [
            *conv.display,
            {"type": "approval_resolved", "agent": approval["agent"], "depth": 0, "approval": approval},
        ]
        conv.updated_at = utcnow()
        s.add(conv)
        s.commit()


async def resolve_approval(approval_id: int, approve: bool, user: dict, note: str | None = None) -> dict:
    with session_scope() as s:
        approval = s.get(ApprovalRequest, approval_id)
        if approval is None:
            raise InventoryError("Approval not found")
        if approval.status != ApprovalStatus.PENDING:
            raise InventoryError(f"Approval #{approval_id} is already {approval.status}")
        data = approval_to_dict(approval)

    tool = tools.get(data["tool"])
    if not approve:
        status, result = ApprovalStatus.REJECTED, {"rejected_by": user["email"], "note": note}
    elif tool is None:
        status, result = ApprovalStatus.FAILED, {"error": f"Tool {data['tool']} no longer exists"}
    else:
        ctx = RunContext(
            run_id=uuid.uuid4().hex,
            agent=data["agent"],
            provider="human",
            trigger="approval",
            conversation_id=data["conversation_id"],
            user=user,
        )
        decision = await agent_hooks.pre_tool_call(ctx, tool, data["args"])
        if decision.action == "block":
            status, result = ApprovalStatus.FAILED, {"error": decision.message}
        else:
            t0 = time.perf_counter()
            result, ok = await execute_tool(tool, decision.args, f"agent:{data['agent']}~{user['email']}")
            await agent_hooks.post_tool_call(ctx, tool, decision.args, result, ok, int((time.perf_counter() - t0) * 1000))
            status = ApprovalStatus.APPROVED if ok else ApprovalStatus.FAILED

    with session_scope() as s:
        approval = s.get(ApprovalRequest, approval_id)
        approval.status, approval.result, approval.decided_at = status, json.loads(to_json(result)), utcnow()
        s.add(approval)
        s.commit()
        data = approval_to_dict(approval)

    verb = {"approved": "approved and executed", "rejected": "rejected", "failed": "approved but failed"}[status]
    note_text = (
        f"[System notice] Approval #{approval_id} for `{data['tool']}` was {verb} by {user['name']}."
        f" Result: {to_json(result, 2000)}"
    )
    await asyncio.to_thread(_append_note, data["conversation_id"], data, note_text)
    bus.emit(f"approval.{status}", data, source=f"user:{user['email']}")
    return data


def pending_approvals() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING)
            .order_by(ApprovalRequest.created_at.desc())
        ).all()
        return [approval_to_dict(a) for a in rows]
