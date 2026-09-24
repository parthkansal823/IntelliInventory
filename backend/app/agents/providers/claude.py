"""Claude provider (Anthropic SDK): streaming, adaptive thinking, tool use."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from app.agents.toolkit import Tool
from app.config import get_settings

from .base import AssistantMessage, Provider, ProviderError, ProviderEvent, ToolCall


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Neutral transcript -> Messages API format.

    Claude-native assistant turns are replayed verbatim (thinking blocks included,
    unchanged) so multi-turn tool use stays valid; turns produced by other
    providers are rebuilt from text + tool calls. Consecutive tool results are
    merged into a single user message, as the API expects.
    """
    out: list[dict] = []
    results: list[dict] = []

    def flush() -> None:
        nonlocal results
        if results:
            out.append({"role": "user", "content": results})
            results = []

    for m in messages:
        role = m["role"]
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"] or "(empty)"}
            if m.get("is_error"):
                block["is_error"] = True
            results.append(block)
            continue
        flush()
        if role == "user":
            out.append({"role": "user", "content": m["content"] or "(empty)"})
        elif role == "assistant":
            if m.get("provider") == "claude" and m.get("native"):
                content = m["native"]
            else:
                content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                content += [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("tool_calls", [])
                ]
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": "(no response)"}]})
    flush()
    return out


class ClaudeProvider(Provider):
    name = "claude"
    label = "Claude"

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.claude_model
        # Zero-arg client resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login` profiles.
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else AsyncAnthropic()

    @classmethod
    def configured(cls) -> bool:
        return bool(
            get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    async def stream(self, *, system: str, messages: list[dict], tools: list[Tool], agent: str) -> AsyncIterator[ProviderEvent]:
        settings = get_settings()
        request: dict = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": to_anthropic_messages(messages),
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": settings.claude_effort},
            "cache_control": {"type": "ephemeral"},  # auto-cache the stable prefix (tools + system + history)
        }
        if tools:
            request["tools"] = [t.to_anthropic() for t in tools]
        if settings.claude_fallbacks == "default":
            request["betas"] = ["server-side-fallback-2026-07-01"]
            request["fallbacks"] = "default"

        final = None
        for attempt in range(3):
            try:
                async with self.client.beta.messages.stream(**request) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield ProviderEvent("text", event.text)
                        elif event.type == "thinking":
                            yield ProviderEvent("thinking", event.thinking)
                    final = await stream.get_final_message()
                break
            except ValueError:
                # Eager tool-input streaming produced JSON the SDK could not parse; re-issue the turn.
                if attempt == 2:
                    raise ProviderError("Claude returned malformed tool input three times") from None
            except anthropic.AuthenticationError as exc:
                raise ProviderError("Claude authentication failed — check ANTHROPIC_API_KEY") from exc
            except anthropic.RateLimitError as exc:
                raise ProviderError("Claude rate limit reached — please retry shortly") from exc
            except anthropic.APIStatusError as exc:
                raise ProviderError(f"Claude API error {exc.status_code}: {exc.message}") from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderError("Could not reach the Claude API") from exc

        blocks = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
        text = "".join(b.text for b in final.content if b.type == "text")
        calls = [
            ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else {}) for b in final.content if b.type == "tool_use"
        ]

        if final.stop_reason == "refusal":
            text = (text + "\n\n" if text else "") + "_The model declined this request._"
            calls = []
        elif final.stop_reason == "max_tokens" and calls:
            text = (text + "\n\n" if text else "") + "_Response was cut off before the tool call completed._"
            calls = []
        if not calls:
            # Never persist tool_use blocks we won't answer - the next request would be rejected.
            blocks = [b for b in blocks if b.get("type") != "tool_use"] or [{"type": "text", "text": text or "(no response)"}]
        # Eagerly streamed inputs are not validated server-side; the runtime validates every call
        # against the tool's pydantic model (Tool.validate) and returns an error tool_result if invalid.

        yield ProviderEvent(
            "message",
            message=AssistantMessage(
                content=text,
                tool_calls=calls,
                native=blocks,
                stop_reason=final.stop_reason,
                input_tokens=getattr(final.usage, "input_tokens", 0) or 0,
                output_tokens=getattr(final.usage, "output_tokens", 0) or 0,
                model=final.model,
            ),
        )
