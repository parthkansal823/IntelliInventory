import json

from app.agents.providers.hermes import TagStreamFilter, parse_tool_payload, to_openai_messages
from app.agents.runtime import pending_approvals, resolve_approval, run_conversation
from app.agents.toolkit import tools
from app.services import inventory

from .conftest import MANAGER, VIEWER


async def collect(message: str, **kwargs) -> list[dict]:
    return [e async for e in run_conversation(message, **kwargs)]


def calls(events: list[dict]) -> list[str]:
    return [e["name"] for e in events if e["type"] == "tool_call"]


async def test_offline_copilot_answers_with_tools(client):
    events = await collect("Give me an inventory overview", user=MANAGER)
    assert "get_inventory_summary" in calls(events)
    assert events[-1]["type"] == "done" and events[-1]["status"] == "ok"
    final = next(e for e in events if e["type"] == "agent_end" and e["depth"] == 0)
    assert "Inventory snapshot" in final["text"]


async def test_delegation_drafts_purchase_order(client):
    events = await collect("draft a PO for Aggarwal", user=MANAGER)
    assert calls(events)[:1] == ["delegate"]
    specialist = [e for e in events if e["type"] == "agent_start" and e["depth"] == 1]
    assert specialist and specialist[0]["agent"] == "procurement"
    created = [e for e in events if e["type"] == "tool_result" and e["name"] == "create_purchase_order"]
    assert created and created[0]["ok"]
    assert created[0]["result"]["purchase_order"]["status"] == "draft"


async def test_write_tools_require_approval_then_execute(client, session):
    before = inventory.on_hand(session, inventory.find_product(session, "PRC-602").id)
    events = await collect("write off 2 units of prc-602 damaged", user=MANAGER)
    hooks = [e for e in events if e["type"] == "hook"]
    assert any(h["hook"] == "approval_gate" for h in hooks)
    approval = next(e["approval"] for e in events if e["type"] == "approval")
    assert approval["tool"] == "adjust_stock" and approval["args"]["quantity_delta"] == -2
    assert any(a["id"] == approval["id"] for a in pending_approvals())

    resolved = await resolve_approval(approval["id"], True, MANAGER)
    assert resolved["status"] == "approved"
    session.expire_all()
    assert inventory.on_hand(session, inventory.find_product(session, "PRC-602").id) == before - 2


async def test_guardrails_block_viewers_and_absurd_quantities(client):
    events = await collect("write off 3 units of PRC-602 damaged", user=VIEWER)
    blocked = [e for e in events if e["type"] == "hook" and e["action"] == "block"]
    assert blocked and blocked[0]["hook"] == "role_guard"

    events = await collect("remove 90000 units of PRC-602 lost", user=MANAGER)
    blocked = [e for e in events if e["type"] == "hook" and e["action"] == "block"]
    assert blocked and blocked[0]["hook"] == "quantity_guardrail"


async def test_hinglish_intents(client):
    assert "get_reorder_recommendations" in calls(await collect("kya order karna hai?", user=MANAGER))
    assert "get_low_stock_items" in calls(await collect("kaunsa stock kam hai?", user=MANAGER))


def test_tool_registry_schemas_are_portable():
    names = {t.name for t in tools.all()}
    assert {"get_inventory_summary", "forecast_demand", "create_purchase_order", "adjust_stock"} <= names
    for tool in tools.all():
        schema = tool.parameters
        assert schema["type"] == "object" and "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert tools.get("adjust_stock").requires_approval and not tools.get("create_purchase_order").requires_approval


def test_hermes_stream_filter_handles_split_tags():
    f = TagStreamFilter()
    out = []
    for chunk in [
        "Hello <thi",
        "nk>plan it</th",
        "ink> world <tool",
        '_call>{"name": "search_products", ',
        '"arguments": {"query": "tea"}}</tool_call> done',
    ]:
        out += f.feed(chunk)
    out += f.finish()
    text = "".join(t for k, t in out if k == "text")
    thinking = "".join(t for k, t in out if k == "thinking")
    assert text == "Hello  world  done" and thinking == "plan it"
    call = parse_tool_payload(f.tool_payloads[0])
    assert call.name == "search_products" and call.args == {"query": "tea"}


def test_provider_message_conversion():
    transcript = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [{"id": "call_1", "name": "a", "args": {"x": 1}}, {"id": "call_2", "name": "b", "args": {}}],
            "provider": "hermes",
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "a", "content": "{}", "is_error": False},
        {"role": "tool", "tool_call_id": "call_2", "name": "b", "content": "{}", "is_error": True},
        {
            "role": "assistant",
            "content": "done",
            "tool_calls": [],
            "provider": "offline",
        },
    ]
    native = to_openai_messages("sys", transcript, [], "native")
    assert native[2]["tool_calls"][0]["function"]["name"] == "a" and native[3]["role"] == "tool"
    prompt = to_openai_messages("sys", transcript, [tools.get("search_products")], "prompt")
    assert "<tools>" in prompt[0]["content"] and "<tool_call>" in prompt[2]["content"]
    assert prompt[3]["content"].startswith("<tool_response>")
