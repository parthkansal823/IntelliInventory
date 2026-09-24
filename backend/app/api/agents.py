"""AI agents: streaming chat (SSE), conversations, approvals, traces, providers."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select
from sse_starlette.sse import EventSourceResponse

from app.agents.hooks import agent_hooks
from app.agents.providers import describe_providers, resolve_provider_name
from app.agents.registry import AGENTS
from app.agents.runtime import approval_to_dict, resolve_approval, run_conversation
from app.agents.toolkit import tools
from app.models import AgentTrace, ApprovalRequest, ApprovalStatus, Conversation
from app.security import CurrentUser, DbSession, ManagerUser
from app.services.inventory import InventoryError
from app.services.settings import set_setting

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _user(u) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


@router.get("")
def overview(_: CurrentUser) -> dict:
    return {
        "agents": [a.to_dict() for a in AGENTS.values()],
        "tools": [t.to_dict() for t in tools.all()],
        "providers": describe_providers(),
        "active_provider": resolve_provider_name(),
        "hooks": [h.to_dict() for h in agent_hooks.hooks],
    }


class ProviderIn(BaseModel):
    provider: str = Field(pattern="^(auto|hermes|offline)$")


@router.put("/provider")
def set_provider(body: ProviderIn, _: ManagerUser) -> dict:
    set_setting("agents.provider", None if body.provider == "auto" else body.provider)
    return {"active_provider": resolve_provider_name()}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    agent: str | None = None
    provider: str | None = None


@router.post("/chat")
async def chat(body: ChatIn, user: CurrentUser) -> EventSourceResponse:
    """Stream an agent turn as Server-Sent Events (one JSON object per `data:` line)."""

    async def events():
        async for event in run_conversation(
            body.message, conversation_id=body.conversation_id, agent=body.agent, provider=body.provider, user=_user(user)
        ):
            yield {"data": json.dumps(event, default=str)}

    return EventSourceResponse(events(), ping=15)


@router.get("/conversations")
def conversations(session: DbSession, _: CurrentUser, limit: int = 50) -> list[dict]:
    rows = session.exec(select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "agent": c.agent,
            "provider": c.provider,
            "updated_at": c.updated_at.isoformat(),
            "turns": sum(1 for d in c.display if d.get("type") == "user"),
        }
        for c in rows
    ]


@router.get("/conversations/{conversation_id}")
def conversation(session: DbSession, conversation_id: str, _: CurrentUser) -> dict:
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    return {
        "id": conv.id,
        "title": conv.title,
        "agent": conv.agent,
        "provider": conv.provider,
        "display": conv.display,
        "updated_at": conv.updated_at.isoformat(),
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(session: DbSession, conversation_id: str, _: CurrentUser) -> dict:
    conv = session.get(Conversation, conversation_id)
    if conv:
        session.delete(conv)
        session.commit()
    return {"deleted": True}


@router.get("/approvals")
def approvals(session: DbSession, _: CurrentUser, status: str | None = "pending", limit: int = 50) -> list[dict]:
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status and status != "all":
        stmt = stmt.where(ApprovalRequest.status == ApprovalStatus(status))
    return [approval_to_dict(a) for a in session.exec(stmt.limit(limit))]


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/approvals/{approval_id}")
async def decide(approval_id: int, body: DecisionIn, user: ManagerUser) -> dict:
    try:
        return await resolve_approval(approval_id, body.approve, _user(user), body.note)
    except InventoryError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/traces")
def traces(session: DbSession, _: CurrentUser, limit: int = 50, conversation_id: str | None = None) -> list[dict]:
    stmt = select(AgentTrace).order_by(AgentTrace.created_at.desc())
    if conversation_id:
        stmt = stmt.where(AgentTrace.conversation_id == conversation_id)
    return [
        {
            "id": t.id,
            "conversation_id": t.conversation_id,
            "agent": t.agent,
            "provider": t.provider,
            "model": t.model,
            "trigger": t.trigger,
            "input": t.input[:200],
            "status": t.status,
            "duration_ms": t.duration_ms,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "steps": len(t.steps),
            "tool_calls": sum(1 for s in t.steps if s.get("kind") == "tool"),
            "created_at": t.created_at.isoformat(),
        }
        for t in session.exec(stmt.limit(limit))
    ]


@router.get("/traces/{trace_id}")
def trace(session: DbSession, trace_id: str, _: CurrentUser) -> AgentTrace:
    t = session.get(AgentTrace, trace_id)
    if t is None:
        raise HTTPException(404, "Trace not found")
    return t
