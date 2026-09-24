"""Drive the Hermes and Claude providers through the real agent loop against mocked HTTP.

No network or API keys: each SDK talks to an in-process transport that streams
realistic Server-Sent Events. This checks the exact request shapes we send and
that streamed tool calls are parsed, executed (with hooks) and answered.
"""

import json
import uuid

import httpx
import httpx2
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from openai import AsyncOpenAI

from app.agents.hooks import RunContext
from app.agents.providers.claude import ClaudeProvider
from app.agents.providers.hermes import HermesProvider
from app.agents.registry import get_agent
from app.agents.runtime import Trace, run_agent

from .conftest import MANAGER


def sse(events: list[tuple[str | None, dict | str]]) -> bytes:
    out = []
    for name, data in events:
        if name:
            out.append(f"event: {name}")
        out.append(f"data: {data if isinstance(data, str) else json.dumps(data)}\n")
    return ("\n".join(out) + "\n").encode()


async def drive(provider, message: str, agent: str = "analyst") -> list[dict]:
    spec = get_agent(agent)
    ctx = RunContext(run_id=uuid.uuid4().hex, agent=spec.name, provider=provider.name, user=MANAGER)
    return [e async for e in run_agent(spec, message, [], provider, ctx, Trace(ctx, message, provider.model))]


# --- Hermes (OpenAI-compatible) ---------------------------------------------------------------


def openai_chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "hermes3",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


async def test_hermes_native_tool_calling_through_agent_loop(client):
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if not any(m["role"] == "tool" for m in body["messages"]):
            chunks = [
                openai_chunk({"role": "assistant", "content": "<think>need data</think>Let me check. "}),
                openai_chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_a",
                                "type": "function",
                                "function": {"name": "get_health_score", "arguments": ""},
                            }
                        ]
                    }
                ),
                openai_chunk({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}, "tool_calls"),
            ]
        else:
            chunks = [openai_chunk({"content": "Health is fine."}, "stop")]
        body_bytes = sse([(None, c) for c in chunks] + [(None, "[DONE]")])
        return httpx.Response(200, content=body_bytes, headers={"content-type": "text/event-stream"})

    provider = HermesProvider()
    provider.client = AsyncOpenAI(
        base_url="http://hermes.test/v1", api_key="k", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    events = await drive(provider, "how healthy is inventory?")

    assert requests[0]["tools"] and requests[0]["stream"] is True
    assert {"type": "thinking", "agent": "analyst", "depth": 0, "delta": "need data"} in events
    visible = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "<think>" not in visible and "Let me check." in visible
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["name"] == "get_health_score" and result["ok"] and "score" in result["result"]
    assert requests[1]["messages"][-1]["role"] == "tool" and requests[1]["messages"][-1]["tool_call_id"] == "call_a"
    assert events[-1] == {"type": "agent_end", "agent": "analyst", "depth": 0, "text": "Health is fine."}


async def test_hermes_prompt_mode_parses_xml_tool_calls(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "hermes_tool_mode", "prompt")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls["n"] += 1
        assert "tools" not in body and "<tools>" in body["messages"][0]["content"]
        text = (
            '<tool_call>\n{"name": "search_products", "arguments": {"query": "earbuds"}}\n</tool_call>'
            if calls["n"] == 1
            else "Found them."
        )
        chunks = [openai_chunk({"content": text[i : i + 7]}) for i in range(0, len(text), 7)] + [openai_chunk({}, "stop")]
        return httpx.Response(
            200, content=sse([(None, c) for c in chunks] + [(None, "[DONE]")]), headers={"content-type": "text/event-stream"}
        )

    provider = HermesProvider()
    provider.client = AsyncOpenAI(
        base_url="http://hermes.test/v1", api_key="k", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    events = await drive(provider, "find earbuds")
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["name"] == "search_products" and call["args"] == {"query": "earbuds"}
    assert not any("<tool_call>" in e.get("delta", "") for e in events)
    assert events[-1]["text"] == "Found them."


# --- Claude (Anthropic Messages API) -------------------------------------------------------------


def claude_stream(blocks: list[dict], stop_reason: str) -> bytes:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 12, "output_tokens": 1},
                },
            },
        )
    ]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events += [
                (
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                ),
                (
                    "content_block_delta",
                    {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}},
                ),
            ]
        else:
            events += [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
                    },
                ),
            ]
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 30},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return sse(events)


async def test_claude_streaming_tool_use_through_agent_loop(client):
    requests: list[tuple[dict, dict]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append((dict(request.headers), body))
        has_result = any(
            isinstance(m["content"], list) and any(b.get("type") == "tool_result" for b in m["content"]) for m in body["messages"]
        )
        payload = (
            claude_stream([{"type": "text", "text": "Score looks OK."}], "end_turn")
            if has_result
            else claude_stream(
                [
                    {"type": "text", "text": "Checking. "},
                    {"type": "tool_use", "id": "toolu_1", "name": "get_health_score", "input": {}},
                ],
                "tool_use",
            )
        )
        return httpx2.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    provider = ClaudeProvider()
    provider.client = AsyncAnthropic(
        api_key="test",
        base_url="http://claude.test",
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    events = await drive(provider, "how healthy is inventory?")

    headers, first = requests[0]
    assert first["model"] == "claude-opus-5" and first["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert first["output_config"] == {"effort": "medium"} and first["fallbacks"] == "default"
    assert first["cache_control"] == {"type": "ephemeral"}
    assert all(t["eager_input_streaming"] for t in first["tools"])
    assert "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", "")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["name"] == "get_health_score" and result["ok"]
    _, second = requests[1]
    assert second["messages"][1]["content"][-1]["type"] == "tool_use"  # native blocks replayed
    assert second["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": second["messages"][2]["content"][0]["content"],
    }
    assert events[-1]["text"] == "Score looks OK."
