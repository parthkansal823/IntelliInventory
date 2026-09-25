# IntelliInventory

**AI inventory, GST billing and udhaar khata for Indian shops — free to run, with a Hermes AI copilot that asks before it acts.**

Make GST bills in 3 steps, collect by UPI QR (no gateway fee), track udhaar, plan Diwali stock, and ask
*"aaj ki sale kitni hui?"* in Hinglish. Demand forecasts, reorder points and purchase orders are computed from your own sales.
The AI runs on **Hermes** (Nous Research, free and local via Ollama) or a built-in **offline planner** — no paid API anywhere.
Every AI action passes through lifecycle **hooks**, and anything that changes stock waits for a human to approve it.

> 📘 **New here? Read the step-by-step [Hinglish tutorial](docs/TUTORIAL.md)** — run it on Windows, make bills, GST,
> khata, AI copilot, and put it online for free (a demo link + your real shop).

![Dashboard](docs/screenshots/dashboard.png)

| Billing (UPI QR, split, udhaar) | GST tax invoice (print / WhatsApp) |
|---|---|
| ![Billing](docs/screenshots/billing.png) | ![Invoice](docs/screenshots/invoice.png) |
| **Festival planner (Diwali stock-up)** | **AI Copilot in Hinglish** |
| ![Festivals](docs/screenshots/festivals.png) | ![Copilot](docs/screenshots/copilot.png) |
| **Purchase order with GST, e-way bill, UPI** | **Stock drawer (forecast, GST, policy)** |
| ![PO](docs/screenshots/purchase-order.png) | ![Inventory](docs/screenshots/inventory.png) |
| **Dark mode** | **Mobile billing (PWA)** |
| ![Dark](docs/screenshots/dashboard-dark.png) | <img src="docs/screenshots/mobile-billing.png" width="260"> |

---

## Features

### Made for India
- **Billing**: tax invoice / bill of supply / zero-rated export invoice, CGST+SGST or IGST from the place of supply,
  MRP-style GST-inclusive prices, line discounts, round-off, amount in words (lakh/crore), numbering per financial year
  (`INV/26-27/00001`, ≤ 16 characters), A4 and 80 mm thermal print, WhatsApp share, cancel with stock return.
- **Payments without a gateway**: UPI QR with the exact amount (money goes straight to your bank), UTR capture,
  cash with change, card, split cash + UPI, and **udhaar** (credit) on the customer's **khata** with WhatsApp reminders.
- **GST, optional**: switch it off if you are not registered; editable slabs (GST 2.0 default 0/5/18/40%); the AI fills
  HSN + rate from the product name later and never overwrites a rate a person entered; GSTIN checksum validation;
  GSTR-3B style report; GSTR-1 friendly sales register CSV for your CA; e-way bill warnings above ₹50,000.
- **Festival planner**: Navratri, Dussehra, Dhanteras, Diwali, Chhath, Holi, Eid, Rakhi, Ganesh Chaturthi, Onam…
  category demand lift, festival-aware forecasts, "order by" dates from supplier lead times, one-click festival POs.
- **Indian everywhere**: ₹ with lakh/crore grouping, IST dates, Indian states (or "Outside India"), phone numbers
  auto-formatted to +91 while international numbers still work, Hindi voice, Hinglish copilot.
- **Two deployments**: `DEMO_MODE=true` (sample shop, demo logins) and `DEMO_MODE=false` (your real shop, one admin).

### Inventory core
- Products, categories, suppliers and **multiple warehouses**, with stock tracked per warehouse.
- An append-only **movement ledger**: receipts, sales, adjustments, transfers and returns, each recording who or which agent did it.
- **Purchase-order lifecycle**: draft → approved → ordered → received, where receiving posts stock. Purchase orders are printable.
- **Cycle counts** with a blind-count mode. Variances are posted as audited adjustments.
- **Barcode/QR scan mode** for phones: camera scanning with ZXing, printable QR labels, and installable as a PWA.
- CSV **import with a dry-run preview**, plus CSV export of inventory and movements.
- **RBAC** with JWT auth and four roles: viewer, staff, manager and admin.

### Intelligence (deterministic, works offline)

| Feature | How |
|---|---|
| Demand forecast | Holt-Winters with weekly seasonality, an 80% band and backtest MAPE |
| Replenishment policy | Safety stock = z·σ·√L, reorder point, and EOQ rounded to the supplier's MOQ |
| **What-if simulator** | Monte-Carlo (300 runs) of the (s, Q) policy under changed demand, lead time, service level or order quantity |
| **Inventory health score** | A single 0–100 score that explains itself: availability, service risk, capital efficiency, replenishment coverage and accuracy |
| **Stockout radar** | When each item runs out, compared with supplier lead time. It shows whether an order placed today still arrives too late. |
| **Smart markdown advisor** | Discounts that clear excess stock in about 60 days and never price below cost + 5% |
| Anomaly detection | Demand spikes (z-score), demand collapse, and shrinkage or write-offs |
| ABC analysis, supplier scorecards, margins | Pareto classes; on-time rate and actual vs promised lead time; gross margin by category |

### Multi-agent AI
- **Copilot** is the orchestrator. It delegates to four specialists: **Analyst**, **Forecaster**, **Procurement** and **Auditor**. Specialists stream their work inline as nested cards.
- The agents share **28 typed tools** (plus any a plugin adds): one registry that also backs the MCP server.
- **Human in the loop:** stock adjustments, transfers, PO status changes and reorder-setting changes become approval requests. They run only when a manager clicks *Approve & run*.
- The **procurement autopilot** is an event-driven agent. When stock drops below the reorder point, it drafts a PO for approval, with a per-SKU cooldown and deduplication against open POs.
- A **daily AI briefing** is written by the Copilot on a schedule, and can be read aloud.
- **Voice**: speak to the Copilot and hear its answers. This uses the browser's built-in Web Speech API, so it is free.
- **Hinglish** is understood even by the free offline planner, e.g. *"kya order karna hai?"* or *"kaunsa stock kam hai?"*.
- **Traces**: a timeline of every run, covering LLM steps, hook decisions, tools, durations and tokens.

### Hooks everywhere
| Layer | Hooks |
|---|---|
| **Agent lifecycle** (same contract as Hermes Agent plugins) | `pre_llm_call` (inject context) · `pre_tool_call` (block / modify / require approval) · `post_tool_call` · `post_llm_call` · `agent:start/step/end` |
| Built-in agent hooks | `sku_normalizer`, `role_guard`, `quantity_guardrail`, `approval_gate`, `tool_audit`, `inventory_context`, `run_reporter` |
| **Event hooks** (glob patterns) | `audit_log`, `stock_alerts`, `webhook_dispatch`, `autopilot_replenish` |
| **Webhooks** | HMAC-SHA256 signed, 3 retries, delivery log; Slack and Discord URLs are auto-formatted |
| **Plugins** | Drop a `register(ctx)` module into `backend/app/plugins/` to add agent hooks, event hooks and tools. See the `budget_guard` example. |
| **Hermes Agent** | Plugin (`pre_tool_call` guardrail, `post_tool_call` audit), gateway hook and skill in `integrations/hermes/` |

Every hook can be toggled live from the **Automation** page.

### UX
The UI has:
- a ⌘K command palette and `g` + key navigation shortcuts
- live updates over SSE, with toasts for alerts, approvals and agent actions
- light and dark themes
- responsive layout and PWA install
- accessible charts (validated colour-blind-safe palette, legends and tooltips)

---

## Quick start

Prerequisites: **[uv](https://docs.astral.sh/uv/)** (installs Python for you) and **Node 20+**.

- **Windows:** double-click `scripts\start-windows.bat`
- **macOS / Linux:** `./scripts/start.sh`

Both build the app on first run and open http://localhost:8000. For development with hot reload:

```bash
make install     # uv sync + npm install
make dev         # API on :8000 + web on :5173
```

Dev server: http://localhost:5173. Sign in as **parth@intelliinventory.dev** (owner/admin) or **ananya@intelliinventory.dev** (manager) with password **demo1234**. Demo data (37 products, 120 days of history) is seeded on first start.

**Single container:**

```bash
docker compose up --build                     # http://localhost:8000
docker compose --profile hermes up --build    # + Ollama, then: docker compose exec ollama ollama pull hermes3
docker compose --profile postgres up --build  # + PostgreSQL 17 (set DATABASE_URL)
```

Production build without Docker: `make build`, then `make api`. FastAPI serves the SPA from `frontend/dist`.

## Free deployment (demo link + your real shop) — CI/CD

```
push to main → CI (tests, lint, build, Docker smoke test) → ✅ → Deploy workflow → your server over SSH (that exact commit)
```

**Recommended: one free Oracle Cloud Always Free server (2 ARM CPU / 12 GB) for both links, both with Hermes.**

| | URL | AI | Data |
|---|---|---|---|
| **Your shop** | `https://<ip>.sslip.io` | Hermes via Ollama | PostgreSQL |
| **Public demo** | `https://demo.<ip>.sslip.io` (compose profile `demo`) | Hermes (shared) | fresh sample shop on every deploy |

- On a fresh Ubuntu server: `curl -fsSL https://raw.githubusercontent.com/parthkansal823/IntelliInventory/main/deploy/server/setup.sh | bash`
  (Docker; app + demo + Ollama/Hermes + Postgres + Caddy auto-HTTPS on sslip.io).
- Add GitHub secrets `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY` → every green CI run on `main` deploys.
- No server? Demo only on **Koyeb** free (Dockerfile, port 8000) or **Render** (`render.yaml`, if your workspace has free
  hours left); shop on your own PC shared with `cloudflared tunnel --url http://localhost:8000`.

Step by step: [tutorial §15](docs/TUTORIAL.md#15-free-deploy--2-links). Forgot the admin password?
`uv run python -m app.cli reset-password <email> <new>`.

## AI providers: free first

`AI_PROVIDER=auto` (the default) picks the first available provider:

1. **Hermes**, if you configured an endpoint *or* a local Ollama is serving a Hermes model. Hermes is auto-detected and needs no key.
2. **Offline planner** otherwise. It is deterministic, instant and free, and understands Hinglish ("Diwali ke liye kya stock karna hai?").

You can switch providers per chat in the Copilot header, or globally in **Settings → AI providers**.

| Provider | Setup | Cost |
|---|---|---|
| Offline planner | nothing | free |
| **Hermes via Ollama** | `ollama pull hermes3:3b` (8 GB laptop) or `hermes3` (16 GB) and keep Ollama running | **free, local, private** |
| Hermes via vLLM / LM Studio / llama.cpp (self-hosted) | `HERMES_BASE_URL`, `HERMES_MODEL` | free |

The Hermes provider supports native OpenAI-style tool calling. It also supports Hermes' own `<tool_call>` XML format (`HERMES_TOOL_MODE=prompt`) for servers without tool support. Hermes 4 `<think>` reasoning is streamed separately, so it never leaks into answers.

---

## Hermes Agent and MCP

The same tools, guardrails and approvals are exposed over the **Model Context Protocol**:

```bash
make mcp                                   # stdio
# or HTTP: http://localhost:8000/mcp/  with  Authorization: Bearer $INTEGRATION_TOKEN
```

**Hermes Agent** (Nous Research): run `./integrations/hermes/install.sh`, then add this to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  intelliinventory:
    command: "uv"
    args: ["run", "--directory", "/path/to/IntelliInventory/backend", "python", "-m", "app.mcp_server"]
```

The tools then appear as `mcp_intelliinventory_*`. With the Hermes gateway you can ask about your inventory from Telegram, Discord, Slack or WhatsApp. The pack also installs a guardrail plugin, a gateway audit hook and a skill with operating playbooks.

**Other MCP clients** (Cursor, VS Code, Continue, LM Studio…): the repo ships a `.mcp.json`; or point any client at `http://localhost:8000/mcp/` with the bearer token.

---

## Architecture

```mermaid
flowchart LR
  UI[React 19 SPA<br/>TanStack Query · SSE] -->|REST + SSE| API[FastAPI]
  API --> SVC[Services<br/>inventory · purchasing · analytics · simulator]
  SVC --> DB[(SQLite / Postgres)]
  SVC -->|domain events| BUS{{Event bus}}
  BUS --> H1[audit_log] & H2[stock_alerts] & H3[webhooks] & H4[autopilot]
  H4 --> RT
  API --> RT[Agent runtime<br/>copilot + 4 specialists]
  RT -->|pre/post hooks| HK[Lifecycle hooks<br/>guardrails · approvals]
  RT --> P1[Hermes] & P3[Offline]
  RT --> TOOLS[Tool registry · 28 tools]
  MCP[MCP server] --> TOOLS
  HERMES[Hermes Agent / any MCP client] --> MCP
  TOOLS --> SVC
```

```
backend/app
  agents/      toolkit.py (typed tool registry) · tools.py · hooks.py · registry.py · runtime.py · providers/
  hooks/       bus.py (event bus) · builtin.py · webhooks.py
  services/    inventory · purchasing · billing · india (GST, festivals) · gst_ai · analytics · simulator · suppliers · counts · importer · scheduler
  api/         auth · catalog · operations · insights · india · billing · agents · automation
  plugins/     drop-in plugins (budget_guard example)
  mcp_server.py · seed.py · models.py · security.py · main.py
frontend/src
  pages/ · components/ (ui kit, charts, copilot) · hooks/ (useAgentChat, useLiveEvents, queries…) · lib/
integrations/hermes   Hermes Agent plugin, gateway hook, skill, installer
```

## Development

```bash
make test    # pytest (analytics, lifecycle, billing, GST, festivals, hooks, agents, Hermes provider over mocked HTTP, API, MCP, autopilot e2e) + vitest
make lint    # ruff + oxlint + tsc
make migrate # Alembic migrations (backend/migrations) for Postgres / production
```

Configuration lives in [`.env.example`](.env.example). Every value is optional.

## Tech stack
**Backend:**
- Python 3.11, FastAPI, SQLModel / SQLAlchemy 2, Pydantic v2
- uv, Ruff, pytest, Alembic
- PyJWT + Argon2
- sse-starlette, the MCP Python SDK v2
- the `openai` SDK (for Hermes / Ollama endpoints)

**Frontend:**
- React 19, Vite 8, TypeScript 6, Tailwind CSS v4
- Radix UI, TanStack Query, React Router
- Recharts, cmdk, sonner, react-markdown, ZXing
- vite-plugin-pwa, Vitest, oxlint

**Ops:**
- Docker (multi-stage) and docker-compose, with optional Ollama and Postgres
- GitHub Actions CI
- CI/CD: GitHub Actions → Render (demo) and SSH deploy of a Docker Compose stack (app + Ollama + Postgres + Caddy)

## License
MIT
