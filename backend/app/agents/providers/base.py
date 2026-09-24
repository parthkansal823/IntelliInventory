"""Provider interface and the neutral transcript format.

Neutral transcript messages (what we persist per conversation):

    {"role": "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}],
     "provider": str, "native": Any}          # native = provider-specific payload to replay verbatim
    {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}

Each provider converts the neutral transcript to its own wire format and
streams back `ProviderEvent`s, ending with exactly one `message` event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.agents.toolkit import Tool


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class AssistantMessage:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    native: Any = None
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None

    def to_neutral(self, provider: str) -> dict:
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in self.tool_calls],
            "provider": provider,
            "native": self.native,
        }


@dataclass
class ProviderEvent:
    type: str  # text | thinking | message
    text: str = ""
    message: AssistantMessage | None = None


class ProviderError(RuntimeError):
    pass


class Provider(ABC):
    name: str = "base"
    label: str = "Base"
    model: str | None = None

    @classmethod
    @abstractmethod
    def configured(cls) -> bool: ...

    @abstractmethod
    def stream(self, *, system: str, messages: list[dict], tools: list[Tool], agent: str) -> AsyncIterator[ProviderEvent]:
        """Stream one assistant turn."""

    def describe(self) -> dict:
        return {"name": self.name, "label": self.label, "model": self.model, "configured": self.configured()}
