"""Offline planner: a zero-cost, deterministic stand-in for an LLM.

It maps the user's request to tool calls with intent rules, then turns tool
results into markdown answers with templates. Because it speaks the same
provider protocol, the full agent pipeline - delegation, lifecycle hooks,
guardrails, approvals, traces - works with no API key and no model download.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from rapidfuzz import fuzz, process
from sqlmodel import select

from app.agents.toolkit import Tool
from app.db import session_scope
from app.models import Product, Warehouse
from app.money import inr

from .base import AssistantMessage, Provider, ProviderEvent, ToolCall

SKU_RE = re.compile(r"\b([A-Za-z]{3}-\d{4})\b")
PO_RE = re.compile(r"\b(PO-\d{4}-\d{4})\b", re.IGNORECASE)
NUM_RE = re.compile(r"(?<![\w-])(\d{1,6})(?![\w-])")


def _call(name: str, **args: Any) -> ToolCall:
    return ToolCall(id=f"call_{uuid.uuid4().hex[:16]}", name=name, args={k: v for k, v in args.items() if v is not None})


def _catalog() -> tuple[list[tuple[str, str]], list[str]]:
    with session_scope() as s:
        products = [(p.sku, p.name) for p in s.exec(select(Product).where(Product.is_active))]
        warehouses = [w.code for w in s.exec(select(Warehouse))]
    return products, warehouses


def find_sku(text: str) -> str | None:
    if m := SKU_RE.search(text):
        return m.group(1).upper()
    products, _ = _catalog()
    if not products:
        return None
    names = {sku: name for sku, name in products}
    hit = process.extractOne(text, names, scorer=fuzz.partial_ratio, score_cutoff=82)
    return hit[2] if hit else None


# Common Hinglish phrasings mapped onto English intent keywords, so the free planner
# understands e.g. "kya order karna hai?" or "kaunsa stock kam hai?".
HINGLISH = [
    (r"\b(aaj ki sale|aaj ki bikri|aaj ka collection|aaj ka galla|bikri kitni|sale kitni)\b", " billing "),
    (r"\b(udhar|udhaar|baaki paise|paise baaki|kitna lena hai)\b", " udhaar "),
    (r"\b(kam|kami|thoda bacha)\b", " low "),
    (r"\b(khatam|khtm|nahi bacha|zero stock)\b", " out of stock "),
    (r"\b(mangana|mangwana|mangwao|order karna|order karo|kharidna)\b", " reorder "),
    (r"\b(banao|bana do|taiyar karo)\b", " create "),
    (r"\b(anumaan|andaza|bhavishya|agle hafte|agle mahine)\b", " forecast "),
    (r"\b(gadbad|chori|ajeeb|galat)\b", " anomaly "),
    (r"\b(munafa|fayda|profit kitna)\b", " margin "),
    (r"\b(aaj ka|aaj ki|subah ki)\b", " briefing "),
    (r"\b(sehat|health kaisi|haal)\b", " health "),
    (r"\b(sasta|discount|chhoot|sale lagao|clearance)\b", " markdown "),
    (r"\b(kitna stock|stock kitna|kitne bache)\b", " details "),
    (r"\b(tyohar|tyohaar|tehwar|tyohar ke liye|festive season)\b", " festival "),
    (r"\b(tax kitna|kitna tax|jiesti)\b", " gst "),
]


def normalize(text: str) -> str:
    text = text.lower()
    for pattern, repl in HINGLISH:
        text = re.sub(pattern, repl, text)
    return text


def _d(iso: str, year: bool = False) -> str:
    """Indian-style short date: 2026-10-04 -> "4 Oct" (or "4 Oct 2026")."""
    day = date.fromisoformat(iso[:10])
    return f"{day.day} {day:%b}" + (f" {day.year}" if year else "")


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text) for w in words)


class OfflineProvider(Provider):
    name = "offline"
    label = "Offline planner"
    model = "rules-v1"

    @classmethod
    def configured(cls) -> bool:
        return True

    def describe(self) -> dict:
        return {**super().describe(), "free": True}

    # -- protocol -------------------------------------------------------------------

    async def stream(self, *, system: str, messages: list[dict], tools: list[Tool], agent: str) -> AsyncIterator[ProviderEvent]:
        available = {t.name for t in tools}
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        request = messages[last_user]["content"].split("<context>")[0].strip()
        turn = messages[last_user + 1 :]
        results = [m for m in turn if m["role"] == "tool"]
        steps = sum(1 for m in turn if m["role"] == "assistant")

        if steps == 0:
            calls, intro = self.plan(request, available, agent)
        else:
            calls, intro = self.follow_up(request, results, available, steps)

        if calls:
            msg = AssistantMessage(content=intro, tool_calls=calls, stop_reason="tool_use", model=self.model)
        else:
            text = self.compose(request, results, agent) if results else intro or self.help_text(agent)
            msg = AssistantMessage(content=text, stop_reason="end_turn", model=self.model)
        if msg.content:
            for chunk in re.findall(r"\S+\s*|\s+", msg.content):
                yield ProviderEvent("text", chunk)
        yield ProviderEvent("message", message=msg)

    # -- planning ---------------------------------------------------------------------

    def plan(self, request: str, available: set[str], agent: str) -> tuple[list[ToolCall], str]:
        text = normalize(request)
        sku = find_sku(request)
        _, warehouses = _catalog()
        wh_mentions = [w for w in warehouses if re.search(rf"\b{w.lower()}\b", text)]

        def delegate(to: str, why: str) -> tuple[list[ToolCall], str]:
            return [_call("delegate", agent=to, task=request)], f"Handing this to the **{to.title()}** agent ({why}).\n\n"

        can = available.__contains__
        if _has(text, "briefing", "digest", "morning report") and can("get_inventory_summary"):
            calls = [_call("get_inventory_summary")]
            if can("get_reorder_recommendations"):
                calls.append(_call("get_reorder_recommendations", limit=6))
            if can("list_alerts"):
                calls.append(_call("list_alerts", limit=20))
            return calls, ""
        wants_write_po = _has(text, "create", "draft", "raise", "make", "place", "prepare", "generate") and _has(
            text, "po", "purchase order", "order"
        )
        po_status = PO_RE.search(request)

        # --- write intents ---
        if po_status and _has(text, "approve", "mark", "set", "cancel", "receive", "send", "order"):
            status = (
                "cancelled"
                if "cancel" in text
                else "received"
                if "receiv" in text
                else "ordered"
                if _has(text, "send", "ordered", "place")
                else "approved"
            )
            if can("update_purchase_order_status"):
                return [_call("update_purchase_order_status", po_number=po_status.group(1).upper(), status=status)], ""
            if can("delegate"):
                return delegate("procurement", "purchase orders")
        if _has(text, "transfer", "move") and sku and len(wh_mentions) >= 2 and (n := NUM_RE.search(text)):
            if can("transfer_stock"):
                return [
                    _call(
                        "transfer_stock",
                        sku=sku,
                        quantity=int(n.group(1)),
                        from_warehouse=wh_mentions[0],
                        to_warehouse=wh_mentions[1],
                    )
                ], ""
            if can("delegate"):
                return delegate("auditor", "stock transfers")
        if (
            _has(text, "adjust", "write off", "write-off", "damaged", "lost", "found", "add", "remove")
            and sku
            and (n := NUM_RE.search(text.replace(sku.lower(), "")))
        ):
            negative = _has(text, "write", "damaged", "lost", "remove", "broken", "expired", "stolen", "minus")
            qty = -int(n.group(1)) if negative else int(n.group(1))
            if can("adjust_stock"):
                return [
                    _call(
                        "adjust_stock",
                        sku=sku,
                        quantity_delta=qty,
                        reason=request[:200],
                        warehouse=wh_mentions[0] if wh_mentions else None,
                    )
                ], ""
            if can("delegate"):
                return delegate("auditor", "stock adjustments")
        if _has(text, "cycle count", "stock take", "stocktake", "count"):
            if can("start_cycle_count"):
                scope = (
                    "all"
                    if "all" in text
                    else next((c for c in "ABC" if f"class {c.lower()}" in text or f" {c.lower()} items" in text), "A")
                )
                return [_call("start_cycle_count", warehouse=wh_mentions[0] if wh_mentions else "MAIN", scope=scope)], ""
            if can("delegate"):
                return delegate("auditor", "cycle counts")
        if wants_write_po or (_has(text, "reorder", "restock", "replenish") and _has(text, "draft", "create", "po")):
            if can("get_reorder_recommendations") and can("create_purchase_order"):
                return [_call("get_reorder_recommendations", limit=20)], "Checking what needs reordering first.\n\n"
            if can("delegate"):
                return delegate("procurement", "purchasing")

        # --- specialist read intents ---
        if _has(text, "what if", "what-if", "simulat", "scenario") or ("%" in text and _has(text, "demand", "lead")):
            if can("simulate_policy"):
                target = sku or self._top_sku()
                if not target:
                    return [], "There are no products yet — add some on the Inventory page first."
                mult = self._multiplier(text)
                lead = re.search(r"lead[ -]?time[^\d]{0,12}(\d{1,3})", text)
                return [
                    _call(
                        "simulate_policy", sku=target, demand_multiplier=mult, lead_time_days=int(lead.group(1)) if lead else None
                    )
                ], ""
            if can("delegate"):
                return delegate("forecaster", "what-if simulation")
        if _has(text, "forecast", "predict", "demand", "next week", "next month", "projection"):
            if can("forecast_demand"):
                target = sku or self._top_sku()
                if not target:
                    return [], "There are no products yet — add some on the Inventory page first."
                return [_call("forecast_demand", sku=target, horizon_days=30)], ""
            if can("delegate"):
                return delegate("forecaster", "demand forecasting")
        if _has(text, "anomal", "unusual", "suspicious", "shrink", "theft", "spike", "strange", "fraud"):
            if can("detect_anomalies"):
                return [_call("detect_anomalies", window_days=7)], ""
            if can("delegate"):
                return delegate("auditor", "anomaly detection")
        if _has(text, "supplier", "vendor", "scorecard"):
            if can("list_suppliers"):
                return [_call("list_suppliers")], ""
            if can("delegate"):
                return delegate("procurement", "supplier performance")
        invoice_no = re.search(r"\b[a-z0-9]{1,4}/\d{2}-\d{2}/\d{1,5}\b", text)
        if invoice_no and can("get_invoice"):
            return [_call("get_invoice", number=invoice_no.group(0).upper())], ""
        if _has(text, "udhaar", "udhar", "khata", "dues", "baki", "baaki", "outstanding", "owes me", "credit sale"):
            if can("customer_dues"):
                return [_call("customer_dues", limit=10)], ""
            if can("delegate"):
                return delegate("analyst", "customer dues (khata)")
        if _has(text, "billing", "invoice", "bills", "bikri", "aaj ki sale", "today's sale", "todays sale", "sales today"):
            if can("billing_summary"):
                return [_call("billing_summary", days=7)], ""
            if can("delegate"):
                return delegate("analyst", "billing summary")
        festival_names = (
            "diwali",
            "deepavali",
            "dhanteras",
            "navratri",
            "dussehra",
            "karwa",
            "chhath",
            "christmas",
            "holi",
            "eid",
            "rakhi",
            "raksha",
            "ganesh",
            "onam",
            "pongal",
            "sankranti",
            "bhai dooj",
            "republic day",
        )
        if _has(text, "festival", "festive", *festival_names):
            if can("plan_festival_stock"):
                named = next((f for f in festival_names if f in text), None)
                return [_call("plan_festival_stock", festival=named)], ""
            if can("delegate"):
                return delegate("procurement", "festival stock planning")
        if _has(text, "hsn", "gst rate", "gst on", "gst for", "gst lagega", "kitna gst", "which gst", "tax rate"):
            if can("suggest_gst"):
                item = re.sub(
                    r"\b(what|which|is|the|hsn|code|gst|rate|on|for|of|kitna|lagega|kya|hai|tax|slab|and)\b|[?]", " ", text
                )
                return [_call("suggest_gst", product_name=" ".join(item.split()) or request)], ""
            if can("delegate"):
                return delegate("analyst", "GST classification")
        if _has(text, "gst", "itc", "input tax", "output tax", "gstr"):
            if can("gst_summary"):
                return [_call("gst_summary", days=30)], ""
            if can("delegate"):
                return delegate("analyst", "GST summary")
        if _has(text, "health", "score", "grade") and not _has(text, "supplier"):
            if can("get_health_score"):
                return [_call("get_health_score")], ""
            if can("delegate"):
                return delegate("analyst", "inventory health score")
        if _has(text, "markdown", "overstock", "dead stock", "slow mov", "excess", "liquidat", "promotion"):
            if can("get_markdown_suggestions"):
                return [_call("get_markdown_suggestions", clear_days=60)], ""
            if can("delegate"):
                return delegate("analyst", "markdown pricing")
        if _has(text, "abc", "pareto", "classif"):
            if can("abc_analysis"):
                return [_call("abc_analysis")], ""
            if can("delegate"):
                return delegate("analyst", "ABC analysis")
        if _has(text, "margin", "profit", "revenue by", "gross"):
            if can("margin_report"):
                return [_call("margin_report", days=30)], ""
            if can("delegate"):
                return delegate("analyst", "margin analysis")
        if _has(text, "movement", "history", "ledger", "activity", "transactions"):
            if can("get_stock_movements"):
                return [_call("get_stock_movements", sku=sku, days=14, limit=15)], ""
            if can("delegate"):
                return delegate("analyst", "movement history")

        # --- read intents any agent can usually serve ---
        if _has(text, "reorder", "restock", "replenish", "buy", "what should i order", "running out", "run out"):
            if can("get_reorder_recommendations"):
                return [_call("get_reorder_recommendations", limit=10)], ""
        if _has(text, "low stock", "low-stock", "out of stock", "stockout", "shortage", "low"):
            if can("get_low_stock_items"):
                return [_call("get_low_stock_items", limit=15)], ""
        if _has(text, "purchase order", "open po", "pos", "orders"):
            if can("list_purchase_orders"):
                return [_call("list_purchase_orders", status="open")], ""
        if _has(text, "alert", "warning", "issue", "problem"):
            if can("list_alerts"):
                return [_call("list_alerts")], ""
        if sku and can("get_product_details"):
            return [_call("get_product_details", sku=sku)], ""
        if _has(
            text,
            "summary",
            "overview",
            "status",
            "how are",
            "how is",
            "dashboard",
            "kpi",
            "health",
            "briefing",
            "report",
            "today",
        ):
            if can("get_inventory_summary"):
                calls = [_call("get_inventory_summary")]
                if _has(text, "briefing", "report", "morning", "digest") and can("get_low_stock_items"):
                    calls.append(_call("get_low_stock_items", limit=8))
                if _has(text, "briefing", "report", "morning", "digest") and can("list_alerts"):
                    calls.append(_call("list_alerts", limit=8))
                return calls, ""
        if _has(text, "find", "search", "show", "list", "which", "where") and can("search_products"):
            query = re.sub(r"\b(find|search|show|list|me|all|the|products?|items?|for|which|where|is|are)\b", " ", text)
            return [_call("search_products", query=" ".join(query.split()), limit=10)], ""
        if _has(text, "hi", "hello", "hey", "help", "what can you"):
            return [], self.help_text(agent)
        if can("search_products") and len(text.split()) <= 6:
            return [_call("search_products", query=request, limit=8)], ""
        if can("get_inventory_summary"):
            return [_call("get_inventory_summary")], ""
        return [], self.help_text(agent)

    def follow_up(self, request: str, results: list[dict], available: set[str], steps: int) -> tuple[list[ToolCall], str]:
        """Second step of multi-step intents (e.g. recommendations -> draft PO)."""
        if steps != 1 or not results:
            return [], ""
        last = results[-1]
        if last["name"] == "get_reorder_recommendations" and "create_purchase_order" in available and not last.get("is_error"):
            text = normalize(request)
            if not (_has(text, "create", "draft", "raise", "make", "place", "prepare", "generate", "po")):
                return [], ""
            items = json.loads(last["content"]).get("items", [])
            sku = find_sku(request)
            if sku:
                items = [i for i in items if i["sku"] == sku] or items
            supplier_hint = next(
                (i["supplier"] for i in items if i["supplier"] and i["supplier"].split()[0].lower() in text), None
            )
            if supplier_hint:
                items = [i for i in items if i["supplier"] == supplier_hint]
            if not items:
                return [], ""
            supplier = items[0]["supplier"]
            lines = [{"sku": i["sku"], "quantity": i["suggested_order_qty"]} for i in items if i["supplier"] == supplier][:10]
            return [
                _call(
                    "create_purchase_order",
                    items=lines,
                    supplier=supplier,
                    notes="Drafted by the procurement agent from reorder recommendations",
                )
            ], (f"Drafting a purchase order for **{supplier}** ({len(lines)} line{'s' if len(lines) != 1 else ''}).\n\n")
        return [], ""

    # -- answers -------------------------------------------------------------------------

    def compose(self, request: str, results: list[dict], agent: str) -> str:
        names = {r["name"] for r in results}
        if _has(normalize(request), "briefing", "digest", "morning report") and "get_inventory_summary" in names:
            return self._briefing({r["name"]: json.loads(r["content"]) for r in results if not r.get("is_error")})
        parts = []
        for r in results:
            try:
                data = json.loads(r["content"])
            except (json.JSONDecodeError, TypeError):
                data = {"raw": r["content"]}
            renderer = getattr(self, f"_r_{r['name']}", None)
            if r.get("is_error"):
                parts.append(f"⚠️ `{r['name']}` failed: {data.get('error', data)}")
            elif isinstance(data, dict) and data.get("status") == "pending_approval":
                parts.append(
                    f"🛡️ **Approval required** — `{r['name']}` was queued as approval **#{data['approval_id']}**. "
                    f"A manager can approve it from the card below or the Approvals panel."
                )
            elif renderer:
                parts.append(renderer(data))
            elif r["name"] == "delegate":
                # The specialist's answer already streamed above; keep the orchestrator's wrap-up short.
                parts.append(f"_✔ {str(data.get('agent', 'specialist')).title()} agent finished — details above._")
            else:
                parts.append(f"```json\n{json.dumps(data, indent=2)[:1500]}\n```")
        return "\n\n".join(p for p in parts if p).strip()

    def _briefing(self, data: dict) -> str:
        k = data["get_inventory_summary"]["kpis"]
        recs = data.get("get_reorder_recommendations", {}).get("items", [])
        alerts = data.get("list_alerts", {}).get("alerts", [])
        stock_alerts = [a for a in alerts if a["kind"] in ("stockout", "low_stock")]
        anomalies = [a for a in alerts if a["kind"] == "anomaly"]
        change = f" ({k['revenue_change_pct']:+.1f}% vs the prior 30 days)" if k.get("revenue_change_pct") is not None else ""
        lines = [
            f"**{k['out_of_stock']} SKUs are out of stock and {k['low_stock']} are running low**, with {k['reorder_needed']} "
            f"items due for reorder. Revenue over the last 30 days was {self._money(k['revenue_30d'])}{change}.",
            "",
            "**Stock risks**",
        ]
        lines += [f"- {a['message']}" for a in stock_alerts[:5]] or ["- No stock risks today ✅"]
        lines += ["", "**Replenishment**"]
        lines += [
            f"- {r['name']} ({r['sku']}): order **{r['suggested_order_qty']}** from {r['supplier']} — {r['reason']}"
            for r in recs[:5]
        ] or ["- Nothing needs reordering ✅"]
        lines += ["", "**Anomalies**"]
        lines += [f"- {a['message']}" for a in anomalies[:4]] or ["- None detected ✅"]
        priorities = []
        if recs:
            suppliers = sorted({r["supplier"] for r in recs if r["supplier"]})
            priorities.append(f"Approve draft POs for {', '.join(suppliers[:3])}{' and others' if len(suppliers) > 3 else ''}.")
        if anomalies:
            priorities.append(
                f"Investigate {anomalies[0]['message'].split(' sold')[0].split(':')[0]} and run a cycle count if needed."
            )
        if k["overstock"]:
            priorities.append(f"Plan promotions or transfers for {k['overstock']} overstocked SKUs.")
        priorities.append("Review open alerts and resolve anything already handled.")
        lines += ["", "**Today's priorities**"] + [f"{i}. {p}" for i, p in enumerate(priorities[:3], 1)]
        return "\n".join(lines)

    @staticmethod
    def _money(v: float) -> str:
        return inr(v)

    def _table(self, rows: list[dict], cols: list[tuple[str, str]]) -> str:
        head = "| " + " | ".join(label for label, _ in cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n"
        body = "\n".join("| " + " | ".join(self._fmt(r.get(key)) for _, key in cols) + " |" for r in rows)
        return head + body

    @staticmethod
    def _fmt(v: Any) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:,.1f}"
        return str(v)

    def _r_get_inventory_summary(self, d: dict) -> str:
        k = d["kpis"]
        change = f" ({k['revenue_change_pct']:+.1f}% vs prior 30d)" if k.get("revenue_change_pct") is not None else ""
        movers = ", ".join(f"{m['name']} ({m['sku']})" for m in d["top_movers"][:3])
        return (
            f"### Inventory snapshot\n"
            f"- **{k['total_skus']} SKUs**, {k['total_units']:,} units worth **{self._money(k['inventory_value'])}**\n"
            f"- 🔴 **{k['out_of_stock']}** out of stock · 🟠 **{k['low_stock']}** low/critical · 🔵 {k['overstock']} overstocked\n"
            f"- {k['reorder_needed']} items need reordering · {k['open_purchase_orders']} open POs · {k['open_alerts']} open alerts\n"
            f"- Revenue last 30 days: **{self._money(k['revenue_30d'])}**{change}\n"
            f"- Top movers: {movers}\n\n"
            f"**Next step:** {'review the reorder list and draft POs' if k['reorder_needed'] else 'stock levels look healthy'}."
        )

    def _r_search_products(self, d: dict) -> str:
        if not d["products"]:
            return "No matching products found."
        return f"Found **{d['count']}** product(s):\n\n" + self._table(
            d["products"],
            [("SKU", "sku"), ("Name", "name"), ("On hand", "on_hand"), ("Status", "status"), ("Days cover", "days_of_cover")],
        )

    def _r_get_product_details(self, d: dict) -> str:
        wh = ", ".join(f"{w['code']}: {w['quantity']}" for w in d["warehouses"]) or "none"
        return (
            f"### {d['name']} ({d['sku']})\n"
            f"- Status **{d['status']}** · {d['on_hand']} on hand ({wh}) · {d['on_order']} on order\n"
            f"- Demand ≈ {d['avg_daily_demand']}/day · cover {self._fmt(d['days_of_cover'])} days · stockout ≈ {d['stockout_date'] or 'n/a'}\n"
            f"- Policy: safety stock {d['safety_stock']}, reorder point {d['reorder_point']}, EOQ {d['eoq']}, lead time {d['lead_time_days']}d\n"
            f"- 14-day forecast: **{d['forecast_14d']['total']:g} units** ({d['forecast_14d']['method']}, MAPE {self._fmt(d['forecast_14d']['mape'])}%)"
            + (f"\n\n**Recommendation:** reorder **{d['suggested_order_qty']}** units." if d["suggested_order_qty"] else "")
        )

    def _r_get_low_stock_items(self, d: dict) -> str:
        if not d["items"]:
            return "✅ No items are below their reorder point."
        return f"**{d['count']}** item(s) need attention:\n\n" + self._table(
            d["items"],
            [
                ("SKU", "sku"),
                ("Name", "name"),
                ("Status", "status"),
                ("On hand", "on_hand"),
                ("ROP", "reorder_point"),
                ("Days cover", "days_of_cover"),
            ],
        )

    def _r_get_reorder_recommendations(self, d: dict) -> str:
        if not d["items"]:
            return "✅ Nothing needs reordering right now."
        return (
            f"**{d['count']}** item(s) should be reordered — est. **{self._money(d['total_estimated_cost'])}** total:\n\n"
            + self._table(
                d["items"],
                [
                    ("SKU", "sku"),
                    ("Name", "name"),
                    ("Supplier", "supplier"),
                    ("Status", "status"),
                    ("Order qty", "suggested_order_qty"),
                    ("Est. cost", "estimated_cost"),
                ],
            )
            + "\n\nSay **“draft a PO for <supplier>”** and I'll prepare it for approval."
        )

    def _r_forecast_demand(self, d: dict) -> str:
        trend = "rising 📈" if d["trend_per_day"] > 0.02 else "falling 📉" if d["trend_per_day"] < -0.02 else "flat"
        return (
            f"### {d['horizon_days']}-day forecast — {d['name']} ({d['sku']})\n"
            f"- Expected demand **{d['forecast_total']:g} units** (≈{d['avg_daily']}/day), trend {trend}\n"
            f"- Last 30 days actual: {d['last_30_days_actual']:g} units · method {d['method']}, backtest MAPE {self._fmt(d['mape_pct'])}%\n"
            f"- Weekly totals: {', '.join(f'{w:g}' for w in d['weekly_totals'])}\n"
            f"- On hand {d['on_hand']} → {self._fmt(d['days_of_cover'])} days of cover (stockout ≈ {d['projected_stockout_date'] or 'n/a'})"
        )

    def _r_simulate_policy(self, d: dict) -> str:
        p, r = d["policy"], d["results"]
        return (
            f"### What-if — {d['product']['name']} ({d['product']['sku']})\n"
            f"Demand ×{p['demand_multiplier']}, lead time {p['lead_time_days']}d, service level {p['service_level']:.0%} "
            f"→ safety stock **{p['safety_stock']}**, reorder point **{p['reorder_point']}**, order qty **{p['order_qty']}**\n\n"
            + self._table(
                [r],
                [
                    ("Fill rate %", "fill_rate"),
                    ("Stockout risk %", "stockout_probability"),
                    ("Stockout days", "expected_stockout_days"),
                    ("Avg inventory", "avg_inventory"),
                    ("Holding ₹", "holding_cost"),
                    ("Lost sales ₹", "lost_sales_value"),
                ],
            )
            + f"\n\n_{d['runs']} Monte-Carlo runs over {d['horizon']} days._"
        )

    def _r_detect_anomalies(self, d: dict) -> str:
        if not d["anomalies"]:
            return "✅ No anomalies detected in the recent window."
        icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
        lines = "\n".join(
            f"- {icon.get(a['severity'], '•')} **{a['kind'].replace('_', ' ')}** — {a['message']}" for a in d["anomalies"][:10]
        )
        return f"Found **{d['count']}** anomal{'y' if d['count'] == 1 else 'ies'}:\n\n{lines}\n\n**Next step:** review the movement ledger for write-offs and consider a cycle count."

    def _r_get_stock_movements(self, d: dict) -> str:
        if not d["movements"]:
            return "No movements in that window."
        return f"Latest **{d['count']}** movements:\n\n" + self._table(
            d["movements"],
            [("When", "timestamp"), ("SKU", "sku"), ("Type", "type"), ("Qty", "quantity"), ("Ref", "reference"), ("By", "actor")],
        )

    def _r_list_purchase_orders(self, d: dict) -> str:
        if not d["purchase_orders"]:
            return "There are no matching purchase orders."
        rows = [{**po, "supplier_name": po["supplier"]["name"], "lines_n": len(po["lines"])} for po in d["purchase_orders"]]
        return f"**{d['count']}** purchase order(s):\n\n" + self._table(
            rows,
            [
                ("PO", "number"),
                ("Supplier", "supplier_name"),
                ("Status", "status"),
                ("Lines", "lines_n"),
                ("Total ₹", "total"),
                ("By", "created_by"),
            ],
        )

    def _r_list_suppliers(self, d: dict) -> str:
        rows = [{**s, "lead": f"{s['promised_lead_time']}d → {self._fmt(s['actual_lead_time'])}d"} for s in d["suppliers"]]
        return "### Supplier scorecards\n\n" + self._table(
            rows,
            [
                ("Supplier", "name"),
                ("Grade", "grade"),
                ("Score", "score"),
                ("On-time %", "on_time_rate"),
                ("Lead time (promised → actual)", "lead"),
                ("Spend ₹", "spend"),
            ],
        )

    def _r_get_health_score(self, d: dict) -> str:
        bars = "\n".join(f"- **{c['label']}** {c['score']:.0f}/100 — {c['detail']}" for c in d["components"])
        return f"### Inventory health: **{d['score']:.0f}/100 (grade {d['grade']})**\n{bars}\n\n**{d['focus']}**"

    def _r_get_markdown_suggestions(self, d: dict) -> str:
        if not d["items"]:
            return "✅ No overstock worth marking down right now."
        return (
            f"**{d['count']}** item(s) tie up **{self._money(d['capital_tied'])}** in excess stock:\n\n"
            + self._table(
                d["items"],
                [
                    ("SKU", "sku"),
                    ("Name", "name"),
                    ("Excess", "excess_units"),
                    ("Tied ₹", "capital_tied"),
                    ("Discount %", "suggested_discount_pct"),
                    ("New price", "new_price"),
                    ("Days to clear", "projected_days_to_clear"),
                ],
            )
            + "\n\n_Discounts never go below cost + 5%. Assumes price elasticity of −2._"
        )

    def _r_abc_analysis(self, d: dict) -> str:
        return (
            "### ABC analysis\n\n"
            + self._table(
                d["classes"],
                [
                    ("Class", "class"),
                    ("SKUs", "count"),
                    ("Monthly consumption ₹", "consumption_value"),
                    ("Stock value ₹", "stock_value"),
                ],
            )
            + "\n\n**Tip:** count class A items most often and keep their service level highest."
        )

    def _r_margin_report(self, d: dict) -> str:
        return f"### Margins — last {d['days']} days\n\n" + self._table(
            d["categories"],
            [
                ("Category", "category"),
                ("Revenue ₹", "revenue"),
                ("Gross profit ₹", "gross_profit"),
                ("Margin %", "margin_pct"),
                ("Units", "units"),
            ],
        )

    def _r_list_alerts(self, d: dict) -> str:
        if not d["alerts"]:
            return "✅ No open alerts."
        icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
        return f"**{d['count']}** open alert(s):\n\n" + "\n".join(
            f"- {icon.get(a['severity'], '•')} {a['message']}" for a in d["alerts"][:10]
        )

    def _r_create_purchase_order(self, d: dict) -> str:
        po = d["purchase_order"]
        lines = "\n".join(f"  - {ln['name']} ({ln['sku']}) × {ln['quantity']} = {self._money(ln['total'])}" for ln in po["lines"])
        return (
            f"📝 Drafted **{po['number']}** for **{po['supplier']['name']}** — {po['units']} units, **{self._money(po['total'])}** + GST "
            f"{self._money(po['tax']['tax'])} ({'IGST' if po['tax']['interstate'] else 'CGST + SGST'}) = **{self._money(po['grand_total'])}**:\n{lines}\n\n"
            + (
                "🚚 Value is above ₹50,000 — an **e-way bill** is needed when the goods move.\n\n"
                if po["tax"]["eway_bill_required"]
                else ""
            )
            + "It's a **draft**: a manager can approve it on the Purchase Orders page."
        )

    def _r_plan_festival_stock(self, d: dict) -> str:
        f = d.get("festival")
        if not f:
            return "No upcoming festivals in the calendar."
        s = d["summary"]
        cats = ", ".join(f"{k} ×{v:g}" for k, v in list(f["categories"].items())[:4])
        head = (
            f"### {f['emoji']} {f['name']} — {_d(f['date'], year=True)} ({f['days_away']} days away)\n"
            f"Buying window starts **{_d(f['buying_starts'])}**. Demand lift: {cats}.\n\n"
            f"- {s['products_affected']} products affected · ~{s['extra_units']:,} extra units · "
            f"~{self._money(s['extra_revenue'])} extra revenue\n"
            f"- **{s['products_to_order']}** need stock-up · order value {self._money(s['order_value'])}"
            + (f" · first order by **{_d(s['earliest_order_by'])}**" if s["earliest_order_by"] else "")
            + "\n\n"
        )
        rows = [{**i, "when": ("⚠️ " if i["urgent"] else "") + _d(i["order_by"])} for i in d["items"]]
        table = (
            self._table(
                rows,
                [
                    ("SKU", "sku"),
                    ("Name", "name"),
                    ("Lift", "uplift"),
                    ("Extra units", "extra_units"),
                    ("Order qty", "suggested_order_qty"),
                    ("Order by", "when"),
                ],
            )
            if rows
            else "✅ Stock already covers the festival demand."
        )
        nxt = ", ".join(f"{u['name']} ({u['days_away']}d)" for u in d.get("upcoming", [])[:5])
        return (
            head
            + table
            + (f"\n\nComing up: {nxt}." if nxt else "")
            + "\n\nSay **“draft festival POs”** on the Insights → Festival planner tab to order in one click."
        )

    def _r_suggest_gst(self, d: dict) -> str:
        hsn = f"HSN **{d['hsn_code']}**, " if d.get("hsn_code") else ""
        return (
            f"🧾 **{d['product']}** → {hsn}GST **{d['gst_rate']:g}%** ({d['confidence']} confidence)\n\n{d['reason']}.\n\n"
            "_Rates change from time to time — confirm with your CA. Slabs can be updated in Settings → Business._"
        )

    def _r_billing_summary(self, d: dict) -> str:
        modes = ", ".join(f"{m.upper()} {self._money(v)}" for m, v in d["collected_by_mode"].items()) or "—"
        p = d["period"]
        return (
            f"### 🧾 Billing — last {d['days']} days\n"
            f"- Today: **{self._money(d['today']['sales'])}** from {d['today']['bills']} bill(s)\n"
            f"- Period: **{self._money(p['sales'])}** from {p['bills']} bills · average bill {self._money(p['avg_bill'])}"
            f" · GST collected {self._money(p['tax'])}\n"
            f"- Collected: {modes}\n"
            f"- Udhaar still to collect: **{self._money(d['outstanding'])}** from {d['customers_with_dues']} customer(s)"
        )

    def _r_customer_dues(self, d: list) -> str:
        if not d:
            return "✅ Koi udhaar baaki nahi — no customer owes you money right now."
        rows = [
            {**r, "bills": len(r["invoices"]), "since": f"{r['days_outstanding']} days", "phone": r["phone"] or "—"} for r in d
        ]
        total = sum(r["balance"] for r in d)
        return (
            f"### 📒 Khata — {len(d)} customer(s) owe **{self._money(total)}**\n\n"
            + self._table(
                rows,
                [("Customer", "name"), ("Phone", "phone"), ("Balance ₹", "balance"), ("Bills", "bills"), ("Oldest", "since")],
            )
            + "\n\n_Send a free WhatsApp reminder from Billing → Khata._"
        )

    def _r_get_invoice(self, d: dict) -> str:
        tax = (
            f"IGST {self._money(d['igst'])}"
            if d["interstate"]
            else f"CGST {self._money(d['cgst'])} + SGST {self._money(d['sgst'])}"
        )
        lines = "\n".join(f"- {line['name']} × {line['quantity']} = {self._money(line['total'])}" for line in d["lines"])
        return (
            f"### {d['title']} {d['number']} — {d['customer_name']}\n{lines}\n\n"
            f"Taxable {self._money(d['taxable'])} · {tax} · **Total {self._money(d['total'])}**\n\n"
            f"Status: **{d['status']}** · paid {self._money(d['amount_paid'])} · balance **{self._money(d['balance'])}**"
        )

    def _r_gst_summary(self, d: dict) -> str:
        rows = [{**r, "slab": f"{r['rate']:g}%"} for r in d["slabs"]]
        return (
            f"### GST estimate — last {d['days']} days\n"
            f"- Output tax on sales: **{self._money(d['output_tax'])}**\n"
            f"- Input tax credit (received purchases): **{self._money(d['input_tax_credit'])}**\n"
            f"- Net payable: **{self._money(d['net_payable'])}**"
            + (f" · credit carried forward {self._money(d['carry_forward_credit'])}" if d["carry_forward_credit"] else "")
            + "\n\n"
            + self._table(
                rows,
                [
                    ("Slab", "slab"),
                    ("Sales (taxable) ₹", "sales_taxable"),
                    ("Output tax ₹", "output_tax"),
                    ("Purchases ₹", "purchase_taxable"),
                    ("ITC ₹", "input_tax"),
                ],
            )
            + f"\n\n_{d['note']}_"
        )

    def _r_update_purchase_order_status(self, d: dict) -> str:
        po = d["purchase_order"]
        return f"✅ {po['number']} is now **{po['status']}**."

    def _r_adjust_stock(self, d: dict) -> str:
        return f"✅ Adjusted {d['sku']} by {d['delta']:+d}; on hand is now **{d['on_hand']}**."

    def _r_transfer_stock(self, d: dict) -> str:
        wh = ", ".join(f"{w['code']}: {w['quantity']}" for w in d["warehouses"])
        note = f"\n\n🚚 {d['eway']['note']}" if d.get("eway", {}).get("note") else ""
        return f"✅ Transferred {d['quantity']} × {d['sku']}. Stock now — {wh}.{note}"

    def _r_update_reorder_settings(self, d: dict) -> str:
        return f"✅ Updated {d['sku']}: reorder point {d['reorder_point']}, safety stock {d['safety_stock']}."

    def _r_start_cycle_count(self, d: dict) -> str:
        return (
            f"📋 Opened cycle count **{d['number']}** for {d['warehouse']['name']} "
            f"({d['progress']['total']} lines, scope {d['scope']}). Staff can enter counts on the Cycle Counts page."
        )

    # -- helpers ---------------------------------------------------------------------------

    @staticmethod
    def _multiplier(text: str) -> float:
        if m := re.search(r"([+-]?\d{1,3})\s*%", text):
            return round(max(0.1, 1 + int(m.group(1)) / 100), 2)
        if m := re.search(r"(\d+(?:\.\d+)?)\s*x\b", text):
            return float(m.group(1))
        if _has(text, "double"):
            return 2.0
        if _has(text, "half", "halve"):
            return 0.5
        return 1.0

    @staticmethod
    def _top_sku() -> str | None:
        from app.services.analytics import compute_metrics

        with session_scope() as s:
            metrics = compute_metrics(s)
        return max(metrics, key=lambda m: m.avg_daily_demand * m.unit_price).sku if metrics else None

    @staticmethod
    def help_text(agent: str) -> str:
        return (
            "I'm running in **offline mode** — free, no API key needed. I can:\n"
            "- 📊 give an inventory **summary** or **briefing**\n"
            "- 🛒 show **what to reorder** and **draft purchase orders**\n"
            "- 📈 **forecast** demand for a product, or run a **what-if** (e.g. *what if demand for ELC-1001 rises 30%?*)\n"
            "- 🔎 detect **anomalies**, show **movements**, **ABC** classes, **margins**, **supplier** scorecards\n"
            "- 💯 score overall inventory **health**, and suggest **markdowns** for overstock\n"
            "- 🪔 plan **festival** stock (Diwali, Dhanteras, Holi, Eid…) and estimate **GST** payable\n"
            "- ✍️ **adjust stock**, **transfer** between warehouses, start a **cycle count** (with approval)\n\n"
            'Hinglish bhi chalega — *"kya order karna hai?"*, *"kaunsa stock kam hai?"*.\n\n'
            "For free natural-language reasoning, run a Hermes model locally with Ollama (`ollama pull hermes3`)."
        )
