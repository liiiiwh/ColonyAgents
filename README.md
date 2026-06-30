<div align="center">

<img src="frontend/public/logo.svg" alt="Colony" width="72" height="72" onerror="this.style.display='none'"/>

# Colony

### Most AI agents are built for demos. Colony is built to put them to work.

Self-hosted platform for autonomous task agents that run on a schedule, call shared tools, and improve themselves.

English | [简体中文](README_zh.md)

[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)
![Status](https://img.shields.io/badge/status-beta-orange.svg)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20Next.js-555.svg)

</div>

---

Describe a goal in one sentence ("run my Xiaohongshu account", "monitor these feeds and surface what matters", "keep my knowledge base current"). Colony designs the assistant and workers it needs, schedules them, and runs them. They work unattended, ask for approval before anything consequential, and improve over time.

You supply an API key for any LLM provider. Colony is self-hosted and handles orchestration, scheduling, memory, and approvals.

**Why it's different**

- **A workforce, not a chat.** You set a goal; Colony builds the agents and runs them on a schedule. Not a one-off conversation.
- **Persistent operation, controlled cost.** Agents run on a schedule, or when you trigger them. History context is compressed automatically, in tiers.
- **Shared capabilities.** A capability such as "publish to Xiaohongshu" is built once. Every agent that needs it reuses it.
- **Safe self-improvement.** Underperforming workers are rewritten automatically. A compatibility check protects everything else relying on them.
- **Autonomy with control.** Agents run on their own. The decisions that matter are escalated to you.

## How it works

```
You ─describe a goal→ Builder (the first Super)
                         │ designs
                         ▼
                  Super (role template) ──instantiated as──▶ Mission (running instance)
                         │ dispatches                              │ runs on a schedule
                         ▼                                         ▼
                  Workers (shared capabilities)            reports back / asks approval
                         ▲                                         │
                         └──── self-iteration loop ◀───────────────┘
```

- **Super** — a role template (skills + capabilities + protocol + model). One Super → many **Missions**.
- **Mission** — a running instance with its own schedule, memory, and message **threads** (a `main` conversation + one persistent thread per super↔worker pair + a health self-check).
- **Worker** — a shared, strongly-scoped capability invoked by Supers, reused across the platform.
- **Builder** — the first Super; you talk to it to design new Supers and workers.

**The self-iteration loop:** a scheduled health-check thread tracks each worker's success rate and, through the Builder, rewrites the protocol of under-performing workers. Every rewrite passes a cross-caller compatibility gate ([ADR-015](docs/adr/015-worker-self-iteration-and-system-objects.md)), so an upgrade can't break another mission that depends on the same worker. Reversible changes apply automatically; genuinely irreversible ones escalate to a human.

**Token-frugal by design:** each scheduled tick assembles only the inbox + memory + payload — not the full history — with near-duplicate memory folding and tiered context compression.

See [CONTEXT.md](CONTEXT.md) for the glossary and [docs/adr/](docs/adr/) for architecture decisions.

## Demo

![Colony tour](docs/media/colony-tour.gif)

*From one sentence, the Builder designs a Super with reusable workers and a daily schedule, pauses for your approval to install tools, then activates it — and the new Super starts running and plans its own work. ([mp4](docs/media/colony-tour.mp4))*

## What you can build

Each of these is one sentence to the Builder:

| You say… | Colony builds… |
| --- | --- |
| "Run my Xiaohongshu account — post daily and patrol comments" | A social-ops Super + content / publish / comment workers on a 9am schedule |
| "Watch these RSS feeds and summarize anything important" | A monitoring Super that digests and escalates only what matters |
| "Draft weekly competitor research" | A research Super that fans out search workers and assembles a report |
| "Keep my knowledge base tidy and answer questions from it" | A KB-ops Super wired to the pgvector knowledge base |

### Super agent vs Worker agent

The core distinction in Colony:

| | **Super agent** | **Worker agent** |
| --- | --- | --- |
| Role | Orchestrator — a role *template* | A single shared *capability* |
| Who calls it | You talk to it; it runs itself on a schedule | A Super calls it via `invoke_worker(capability, action, params)` |
| Reuse | One Super → **N missions** (instances) | One Worker → reused by **many Supers** |
| Owns | goal, plan, memory, schedule, your conversation | one narrow skill (e.g. "publish to Xiaohongshu", "fetch RSS") |
| Decides | *what* to do and *when*; asks for approval on risky steps | *how* to execute one action, returns a result |
| Upgrade scope | per-Super | platform-wide — an upgrade is blocked if it would break any Super that uses it ([ADR-009](docs/adr/009-builder-governance.md)) |

A Super is a self-running assistant you create by describing a goal. Workers are shared tools any Super can call.

### Why capabilities are workers, not skills

A skill is a fixed tool: one function the agent calls. Building a real capability ("operate a Xiaohongshu account") out of skills alone means ever more rigid tool definitions and branching for every variation. The skill layer turns bloated and brittle, and each new case needs code.

A worker is an agent with its own reasoning loop. It exposes a capability through a contract of actions, and handles messy, varied input by reasoning: it adapts, asks for clarification, and recovers, instead of a hard-coded branch per case. One worker is shared by every Super, versioned by its contract, and improved in one place.

Colony keeps skills for thin, deterministic tools. Capabilities that need judgment are workers. The tool layer stays small; the flexibility lives in the workers.

### Modules

| Module | What it does | How it works |
| --- | --- | --- |
| **Builder** | The first Super; designs every other Super + Worker | You describe a goal → it drafts a plan, asks you to confirm, then creates the Super, reuses or designs Workers, and activates it |
| **Agents** (Super / Worker) | Manage all agents in one place | Super tab: role templates + their missions (click **Enter** → workbench). Worker tab: shared capabilities + success-rate stats (click **Observe**) |
| **Mission workbench** | Where a Super runs | Three columns — left (this Super's **missions** + the mission's message **threads**, both deletable) / live chat stream (interrupt anytime) / right panel (schedules, live worker calls, memory). Per-mission **Manual / Full-auto** approval switch |
| **Skills** | Tools agents can call | Built-in skills + one-click install from **ClawHub**; bound to agents by scope (super / worker / builder) |
| **MCP servers** | External tool integration | Register a stdio subprocess or http MCP server; bind it to the workers that need it |
| **LLM providers** | Model sources | Add OpenAI / Anthropic / Gemini / DeepSeek / Ollama / any OpenAI-compatible endpoint, sync models, pick defaults |
| **Approval channels** | Human-in-the-loop gate | Bind a WeChat bot; a Super sends an approval card to your reviewers when it hits a high-risk action |
| **Knowledge base** | Long-term retrieval | pgvector store; agents query it via `knowledge_search`; scopes: mission / super / platform |
| **Material library** | Structured assets | Components, modules, reference images keyed by id; agents pull them via `material_lookup` |
| **Object storage** | Artifacts | S3 / MinIO browser for everything agents produce |
| **System settings** | Global tunables | Compression, quotas, timeouts, dev guards — each takes effect on save |

## Quick start

Requires Docker + Docker Compose v2.20+.

```bash
git clone https://github.com/liiiiwh/ColonyAgents.git colony && cd colony
cp backend/.env.example backend/.env       # set SECRET_KEY and ENCRYPTION_KEY (gen commands are in the file)
docker compose up -d                        # postgres + minio + backend + frontend
```

Then:

1. Open **http://localhost:3022** and log in (`admin` / `admin123` — change this).
2. A setup dialog opens (and stays until a default model is configured): pick your **language** (English / 中文 — sets your UI and the language the system agents speak), then add an **LLM provider** (OpenAI / Anthropic / Gemini / DeepSeek / any OpenAI-compatible endpoint) and sync its models.
3. Pick your default supervisor / worker models — the platform initializes itself (seeding the system agents in your chosen language) and drops you into the Builder.
4. Tell the Builder what you want.

> `scripts/install.sh` wraps the same steps with a health check. For CI / headless, set `AUTO_INSTALL=true` to skip the manual provider step.

### Deployment options

| File | Use it when |
| --- | --- |
| `docker-compose.yml` | **Full stack** — bundles postgres + minio + backend + frontend with their own volumes. One command, runs with its own data. |
| `docker-compose.app.yml` | **App only** — backend + frontend; point at your own managed Postgres (with pgvector) and S3 via `backend/.env`. |
| `docker-compose.infra.yml` | **Infra only** — postgres + minio, for running the backend/frontend directly on the host during development. |

<details>
<summary>Manual setup (development) — run code on the host</summary>

```bash
docker compose -f docker-compose.infra.yml up -d   # postgres (pgvector) + minio

# backend
cd backend
cp .env.example .env                                # SECRET_KEY / ENCRYPTION_KEY / DB / S3
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --port 9022

# frontend (new shell)
cd frontend
npm install
BACKEND_URL=http://localhost:9022 npm run dev       # http://localhost:3022
```
</details>

## Configuration

Key env vars (see [backend/.env.example](backend/.env.example)):

| Var | Purpose |
| --- | --- |
| `SECRET_KEY` | JWT signing — set a strong random value |
| `ENCRYPTION_KEY` | Fernet key encrypting provider API keys at rest |
| `DATABASE_URL` | Postgres (pgvector) connection |
| `S3_*` | Object storage (MinIO/S3) for artifacts |
| `AUTO_INSTALL` | `true` to auto-initialize on boot (CI/dev) |

**Supported LLM providers:** OpenAI · Anthropic · Google Gemini / AI Studio · Azure OpenAI · DeepSeek · Ollama (local) · any OpenAI-compatible endpoint (Qwen / Volcengine / Bailian / proxies — set `base_url`). Colony never silently downgrades models ([ADR-014](docs/adr/014-no-model-degradation-compat.md)).

## Security

- Change the default admin password (`INIT_ADMIN_PASSWORD`) and MinIO credentials before any non-local use.
- Provide LLM keys via the UI or env — never commit them. `.env` is gitignored.
- Generate fresh `SECRET_KEY` / `ENCRYPTION_KEY`.

## Roadmap

- More approval channels (Slack / Telegram / email) beyond WeChat
- Versioned worker capability contracts
- A marketplace for shared Super/Worker templates

## License

[MIT](LICENSE) © 2026 李文华 (Li Wenhua)

Free for commercial use, modification, and distribution. The only requirement is that the copyright notice and license text are retained (attribution).

## Star History

<div align="center">

<a href="https://www.star-history.com/?repos=liiiiwh%2FColonyAgents&type=date&legend=top-left">
  <img src="https://api.star-history.com/svg?repos=liiiiwh/ColonyAgents&type=Date" alt="Star History Chart" width="600"/>
</a>

</div>
