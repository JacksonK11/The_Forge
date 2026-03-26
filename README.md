# The Forge — AI Build Engine

Blueprint document → complete deployable codebase in 15–25 minutes. AI-powered, production-ready, every time.

**Owner:** Jackson Khoury · Sydney, Australia
**Dashboard:** https://the-forge-dashboard-v7.fly.dev
**API:** https://the-forge-api.fly.dev

---

## What It Does

Submit any blueprint document (PDF, Word, plain text) and The Forge generates a complete, deployable AI agent — full codebase, Docker setup, Fly.io config, GitHub Actions CI/CD, secrets management, README — ready to push and run.

**7-stage build pipeline:**
Validate → Parse → Confirm Spec → Architecture → Generate Code (6 layers) → Build QA → Package

**6 code generation layers (dependency order):**
1. Database schema — SQLAlchemy models, asyncpg
2. Infrastructure — requirements.txt, Dockerfiles, docker-compose, .env.example
3. Backend API — FastAPI routes, services, middleware, auth
4. Worker/agent logic — RQ workers, pipeline nodes, APScheduler
5. Web dashboard — React + Vite + Tailwind (served as static files from API)
6. Deployment — fly.toml (API + worker only), GitHub Actions deploy.yml

Every generated agent includes: 7-file intelligence layer, 5-file knowledge engine, performance monitoring, Telegram alerts, pgvector semantic search.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12, async throughout |
| Database | PostgreSQL + pgvector, SQLAlchemy 2.0, asyncpg |
| Queue | Redis + RQ (background builds), APScheduler (scheduled jobs) |
| AI | Claude Opus 4.6 (parse), Sonnet 4.6 (generate + chat), Haiku 4.5 (evaluate) |
| Embeddings | OpenAI text-embedding-3-small |
| Web search | Tavily |
| Notifications | Telegram |
| Frontend | React 18 + Vite + Tailwind CSS |
| Deployment | Fly.io (API + worker), GitHub Actions CI/CD |

---

## Services

| Service | App | Machine | Cost/mo |
|---------|-----|---------|---------|
| API | `the-forge-api` | shared-cpu-4x, 2GB | ~A$37 |
| Worker | `the-forge-worker` | shared-cpu-4x, 4GB | ~A$73 |
| Dashboard | `the-forge-dashboard-v7` | shared-cpu-1x, 512MB | ~A$9 |
| Database | `the-forge-db` (shared Postgres) | managed | ~A$63 ÷ agents |
| Redis | `the-forge-redis` | managed, 256MB | ~A$30 |

**Cost per generated agent:** ~A$23/month (API + worker, no separate Postgres, no separate dashboard, APScheduler inside worker, --ha=false).

---

## Local Development

```bash
# 1. Clone and install
git clone https://github.com/your-org/the-forge
cd the-forge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Start local services
docker-compose up -d  # PostgreSQL + Redis

# 4. Initialise database
python -c "import asyncio; from memory.database import init_db; asyncio.run(init_db())"

# 5. Seed knowledge base (first time only)
python scripts/seed_experience.py

# 6. Start API
uvicorn app.api.main:app --reload --port 8000

# 7. Start worker (separate terminal)
python pipeline/worker.py

# 8. Start dashboard (separate terminal)
cd web-dashboard && npm install && npm run dev
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```
# Required
API_SECRET_KEY=          # openssl rand -hex 32
DATABASE_URL=            # postgresql+asyncpg://user:pass@host/forge_db
REDIS_URL=               # redis://localhost:6379
ANTHROPIC_API_KEY=       # sk-ant-...
OPENAI_API_KEY=          # sk-... (embeddings only)
TELEGRAM_BOT_TOKEN=      # from @BotFather
TELEGRAM_CHAT_ID=        # your chat ID

# Optional
TAVILY_API_KEY=          # web search for knowledge collection
GITHUB_TOKEN=            # auto-push generated code to GitHub
FLY_API_TOKEN=           # auto-deploy generated agents to Fly.io
SENTRY_DSN=              # error tracking
```

---

## Deployment

Deployment is fully automated via GitHub Actions on push to `main`.

**Manual deploy:**
```bash
# API
flyctl deploy --config fly.api.toml --ha=false

# Worker (wait for active builds first)
flyctl deploy --config fly.worker.toml --ha=false

# Dashboard
cd web-dashboard && flyctl deploy --ha=false
```

**Fly.io secrets** (set once):
```bash
flyctl secrets set \
  API_SECRET_KEY=... \
  DATABASE_URL=... \
  REDIS_URL=... \
  ANTHROPIC_API_KEY=... \
  OPENAI_API_KEY=... \
  TELEGRAM_BOT_TOKEN=... \
  TELEGRAM_CHAT_ID=... \
  --app the-forge-api

# Same for the-forge-worker (same values)
```

---

## Shared Postgres Pattern

All agents built by The Forge share a single `the-forge-db` Fly.io Postgres instance. Each agent gets its own database within that instance (`{slug}_db`).

```bash
# Attach shared Postgres to a new agent
flyctl postgres attach the-forge-db --app {new-agent-api} --database-name {slug}_db
flyctl postgres attach the-forge-db --app {new-agent-worker} --database-name {slug}_db
```

This saves ~A$63/month per agent compared to provisioning dedicated Postgres.

---

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest tests/ -v

# Run specific test class
pytest tests/test_pipeline_integration.py::TestArchitectureNode -v
```

---

## API Reference

**Auth:** All requests require `Authorization: Bearer {API_SECRET_KEY}`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/forge/submit` | Submit blueprint text |
| POST | `/forge/submit-file` | Upload blueprint document |
| POST | `/forge/runs/{id}/approve` | Approve spec, start generation |
| GET | `/forge/runs` | List all runs |
| GET | `/forge/runs/{id}` | Run detail + status |
| GET | `/forge/runs/{id}/files` | Generated file list |
| GET | `/forge/runs/{id}/package` | Download completed ZIP |
| POST | `/forge/chat` | Chat with Forge AI (non-streaming) |
| POST | `/forge/chat/stream` | Chat with Forge AI (SSE streaming) |
| GET | `/forge/stats` | Build statistics |
| GET | `/health` | Health check |
| GET | `/docs` | Interactive API docs (Swagger) |

---

## Intelligence Layer

Every generated agent includes 7 intelligence files. The Forge itself uses the same system for its own operations:

| File | Purpose |
|------|---------|
| `config/model_config.py` | Routes Claude calls by task type — saves 35–40% API cost |
| `intelligence/knowledge_base.py` | Stores build outcomes in pgvector, retrieves similar patterns |
| `intelligence/meta_rules.py` | Weekly Claude extraction of operational rules from outcomes |
| `intelligence/context_assembler.py` | Assembles optimal context before every major Claude call |
| `intelligence/evaluator.py` | Scores every generated file against production rubric |
| `intelligence/verifier.py` | Adversarial second-pass review before shipping |
| `monitoring/performance_monitor.py` | 5 KPIs every 6h, degradation alerts via Telegram |

---

## Knowledge Base

The Forge continuously collects and embeds content across 8 domains (daily at 02:00 UTC):

- `fastapi_python` — FastAPI, Pydantic v2, SQLAlchemy 2.0
- `fly_io_deployment` — Fly.io, Docker, GitHub Actions
- `rq_redis` — RQ, background jobs, APScheduler
- `react_vite` — React 18, Vite, Tailwind CSS
- `claude_api` — Anthropic API, prompt engineering, tool use
- `pgvector_postgres` — pgvector, embeddings, similarity search
- `build_issues` — common failures, import errors, deployment fixes
- `ai_agent_market` — industry demand, competitor pricing, agent use cases

To seed the KB on a fresh deployment:
```bash
python scripts/seed_experience.py
```

---

## Architecture

```
the-forge/
├── app/api/          # FastAPI routes, middleware, services
├── pipeline/         # 9-stage build orchestrator + 19 nodes
├── intelligence/     # 7-file intelligence layer
├── knowledge/        # 5-file knowledge engine
├── memory/           # 14 SQLAlchemy models, database setup
├── monitoring/       # KPI tracking, APScheduler, scheduler
├── config/           # Settings, model routing, knowledge domains
├── scripts/          # seed_experience.py (KB seeding)
├── tests/            # Integration tests
└── web-dashboard/    # React 18 + Vite + Tailwind dashboard
```

For full architecture details, see [CLAUDE.md](CLAUDE.md).
