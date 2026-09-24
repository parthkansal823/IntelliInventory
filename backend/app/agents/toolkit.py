"""Tool registry: plain typed Python functions -> JSON-schema tools.

A single registry backs the in-app agents (Hermes / offline) *and*
the MCP server, so every client sees identical tools, schemas, validation and
guardrails.
"""

from __future__ import annotations

import contextvars
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("current_actor", default="agent")


def get_actor() -> str:
    return current_actor.get()


class ToolInputError(ValueError):
    pass


def _inline_refs(schema: dict) -> dict:
    """Resolve local $refs and drop pydantic titles for compact, portable schemas."""
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    model: type[BaseModel]
    requires_approval: bool = False
    mutates: bool = False
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def parameters(self) -> dict:
        schema = _inline_refs(self.model.model_json_schema())
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        schema["type"] = "object"
        return schema

    def validate(self, args: dict | None) -> dict:
        try:
            return self.model.model_validate(args or {}).model_dump()
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors())
            raise ToolInputError(f"Invalid arguments for {self.name}: {problems}") from exc

    def run(self, args: dict | None) -> Any:
        return self.fn(**self.validate(args))

    # -- provider formats ---------------------------------------------------

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "requires_approval": self.requires_approval,
            "mutates": self.mutates,
            "tags": sorted(self.tags),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(
        self, *, requires_approval: bool = False, mutates: bool = False, tags: tuple[str, ...] = (), name: str | None = None
    ):
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.add(fn, requires_approval=requires_approval, mutates=mutates or requires_approval, tags=tags, name=name)
            return fn

        return decorator

    def add(
        self,
        fn: Callable[..., Any],
        *,
        requires_approval: bool = False,
        mutates: bool = False,
        tags: tuple[str, ...] = (),
        name: str | None = None,
        description: str | None = None,
    ) -> Tool:
        sig = inspect.signature(fn, eval_str=True)  # resolve `from __future__ import annotations`
        fields: dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
            default = param.default if param.default is not inspect.Parameter.empty else ...
            fields[pname] = (annotation, default)
        tool_name = name or fn.__name__
        model = create_model(f"{tool_name}_args", **fields)
        tool = Tool(
            name=tool_name,
            description=description or inspect.cleandoc(fn.__doc__ or tool_name),
            fn=fn,
            model=model,
            requires_approval=requires_approval,
            mutates=mutates,
            tags=frozenset(tags),
        )
        self._tools[tool_name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def subset(self, names: list[str]) -> list[Tool]:
        return [self._tools[n] for n in names if n in self._tools]


def to_json(value: Any, limit: int = 24_000) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + '..."(truncated)"'


tools = ToolRegistry()
