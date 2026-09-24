"""Nous Research Hermes provider (Hermes 3 / Hermes 4) over any OpenAI-compatible API.

Works with Nous Portal, OpenRouter, vLLM, SGLang, llama.cpp, LM Studio and Ollama.

Two tool-calling modes:

* ``native`` (default) - standard OpenAI ``tools``; if the server returns
  Hermes-style ``<tool_call>`` markup as plain text (e.g. vLLM without a tool
  parser), it is parsed transparently.
* ``prompt`` - Hermes function-calling prompt format: tool signatures in a
  ``<tools>`` block in the system prompt, calls emitted as
  ``<tool_call>{"name": ..., "arguments": {...}}</tool_call>`` and results fed
  back as ``<tool_response>``. Works with any Hermes model, even on servers
  without tool-calling support.

Hermes 4 hybrid reasoning (``<think>...</think>``) is streamed as thinking and
kept out of the answer.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import openai
from openai import AsyncOpenAI

from app.agents.toolkit import Tool
from app.config import get_settings

from .base import AssistantMessage, Provider, ProviderError, ProviderEvent, ToolCall

HERMES_TOOL_PROMPT = """You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags. \
You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. \
Here are the available tools: <tools> {tools} </tools>
For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:
<tool_call>
{{"name": <function-name>, "arguments": <args-dict>}}
</tool_call>"""

_ollama_cache: dict[str, tuple[float, str | None]] = {}


def detect_ollama_hermes() -> str | None:
    """Return the name of a Hermes model served by a local Ollama, if any (cached 60s)."""
    settings = get_settings()
    if not settings.ollama_autodetect:
        return None
    now = time.monotonic()
    cached = _ollama_cache.get(settings.ollama_url)
    if cached and now - cached[0] < 60:
        return cached[1]
    found = None
    try:
        resp = httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=0.4)
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        preferred = settings.hermes_model.split(":")[0]
        found = next((n for n in names if n.split(":")[0] == preferred), None) or next(
            (n for n in names if "hermes" in n.lower()), None
        )
    except (httpx.HTTPError, ValueError):
        found = None
    _ollama_cache[settings.ollama_url] = (now, found)
    return found


class TagStreamFilter:
    """Incrementally split streamed text into visible text, <think> reasoning and <tool_call> payloads.

    Handles tags split across chunk boundaries by holding back a possible partial tag.
    """

    TAGS = {"think": "thinking", "tool_call": "tool_call"}

    def __init__(self) -> None:
        self.buffer = ""
        self.mode = "text"  # text | thinking | tool_call
        self.tool_payloads: list[str] = []
        self._capture = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.buffer += chunk
        out: list[tuple[str, str]] = []
        while self.buffer:
            if self.mode == "text":
                idx = self.buffer.find("<")
                if idx == -1:
                    out.append(("text", self.buffer))
                    self.buffer = ""
                    break
                if idx:
                    out.append(("text", self.buffer[:idx]))
                    self.buffer = self.buffer[idx:]
                opened = next((tag for tag in self.TAGS if self.buffer.startswith(f"<{tag}>")), None)
                if opened:
                    self.buffer = self.buffer[len(opened) + 2 :]
                    self.mode = self.TAGS[opened]
                    continue
                if any(f"<{tag}>".startswith(self.buffer) for tag in self.TAGS):
                    break  # possible partial tag - wait for more input
                out.append(("text", "<"))
                self.buffer = self.buffer[1:]
            else:
                tag = "think" if self.mode == "thinking" else "tool_call"
                close = f"</{tag}>"
                idx = self.buffer.find(close)
                if idx == -1:
                    keep = next((n for n in range(len(close) - 1, 0, -1) if self.buffer.endswith(close[:n])), 0)
                    emit, self.buffer = self.buffer[: len(self.buffer) - keep], self.buffer[len(self.buffer) - keep :]
                    self._emit_inner(emit, out)
                    break
                self._emit_inner(self.buffer[:idx], out)
                if self.mode == "tool_call":
                    self.tool_payloads.append(self._capture)
                    self._capture = ""
                self.buffer = self.buffer[idx + len(close) :]
                self.mode = "text"
        return [(kind, text) for kind, text in out if text]

    def _emit_inner(self, text: str, out: list[tuple[str, str]]) -> None:
        if self.mode == "thinking":
            out.append(("thinking", text))
        else:
            self._capture += text

    def finish(self) -> list[tuple[str, str]]:
        out = []
        if self.mode == "text" and self.buffer:
            out.append(("text", self.buffer))
        elif self.mode == "thinking" and self.buffer:
            out.append(("thinking", self.buffer))
        elif self.mode == "tool_call":
            self.tool_payloads.append(self._capture + self.buffer)
        self.buffer = ""
        return out


def parse_tool_payload(payload: str) -> ToolCall | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "name" not in data:
        return None
    args = data.get("arguments", data.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    return ToolCall(id=f"call_{uuid.uuid4().hex[:16]}", name=str(data["name"]), args=args if isinstance(args, dict) else {})


def to_openai_messages(system: str, messages: list[dict], tools: list[Tool], mode: str) -> list[dict]:
    if mode == "prompt" and tools:
        schemas = json.dumps([t.to_openai() for t in tools])
        system = f"{system}\n\n{HERMES_TOOL_PROMPT.format(tools=schemas)}"
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            calls = m.get("tool_calls", [])
            if mode == "prompt":
                markup = "".join(
                    f"<tool_call>\n{json.dumps({'name': c['name'], 'arguments': c['args']})}\n</tool_call>" for c in calls
                )
                out.append({"role": "assistant", "content": (m.get("content") or "") + markup})
            else:
                msg: dict = {"role": "assistant", "content": m.get("content") or None}
                if calls:
                    msg["tool_calls"] = [
                        {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                        for c in calls
                    ]
                out.append(msg)
        elif m["role"] == "tool":
            if mode == "prompt":
                body = json.dumps({"name": m["name"], "content": m["content"]})
                out.append({"role": "user", "content": f"<tool_response>\n{body}\n</tool_response>"})
            else:
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out


class HermesProvider(Provider):
    name = "hermes"
    label = "Hermes"

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.hermes_model
        self.mode = settings.hermes_tool_mode
        base_url = settings.hermes_base_url
        if not base_url:
            # Free, local default: Ollama's OpenAI-compatible endpoint with an auto-detected Hermes model.
            base_url = f"{settings.ollama_url.rstrip('/')}/v1"
            self.model = detect_ollama_hermes() or settings.hermes_model
        self.base_url = base_url
        self.client = AsyncOpenAI(base_url=base_url, api_key=settings.hermes_api_key or "ollama", timeout=180)

    @classmethod
    def configured(cls) -> bool:
        settings = get_settings()
        return bool(settings.hermes_api_key or settings.hermes_base_url or detect_ollama_hermes())

    def describe(self) -> dict:
        return {
            **super().describe(),
            "base_url": self.base_url,
            "free": "localhost" in self.base_url or "127.0.0.1" in self.base_url or ":free" in (self.model or ""),
        }

    async def stream(self, *, system: str, messages: list[dict], tools: list[Tool], agent: str) -> AsyncIterator[ProviderEvent]:
        request: dict = {"model": self.model, "messages": to_openai_messages(system, messages, tools, self.mode), "stream": True}
        if tools and self.mode == "native":
            request["tools"] = [t.to_openai() for t in tools]

        filt = TagStreamFilter()
        text_parts: list[str] = []
        native_calls: dict[int, dict] = {}
        finish_reason = None
        usage_in = usage_out = 0
        model = self.model
        try:
            stream = await self.client.chat.completions.create(**request)
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage_in = chunk.usage.prompt_tokens or usage_in
                    usage_out = chunk.usage.completion_tokens or usage_out
                model = chunk.model or model
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning:
                    yield ProviderEvent("thinking", reasoning)
                if delta.content:
                    for kind, text in filt.feed(delta.content):
                        if kind == "text":
                            text_parts.append(text)
                        yield ProviderEvent(kind, text)
                for tc in delta.tool_calls or []:
                    slot = native_calls.setdefault(tc.index, {"id": None, "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        except openai.AuthenticationError as exc:
            raise ProviderError("Hermes endpoint rejected the API key — check HERMES_API_KEY") from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"Model '{self.model}' not found at the Hermes endpoint — check HERMES_MODEL") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"Hermes endpoint error {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not reach the Hermes endpoint — check HERMES_BASE_URL") from exc

        for kind, text in filt.finish():
            if kind == "text":
                text_parts.append(text)
            yield ProviderEvent(kind, text)

        calls: list[ToolCall] = []
        for slot in native_calls.values():
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": slot["arguments"]}
            calls.append(ToolCall(id=slot["id"] or f"call_{uuid.uuid4().hex[:16]}", name=slot["name"], args=args))
        calls += [c for c in (parse_tool_payload(p) for p in filt.tool_payloads) if c]

        yield ProviderEvent(
            "message",
            message=AssistantMessage(
                content="".join(text_parts).strip(),
                tool_calls=calls,
                native=None,
                stop_reason=finish_reason,
                input_tokens=usage_in,
                output_tokens=usage_out,
                model=model,
            ),
        )
