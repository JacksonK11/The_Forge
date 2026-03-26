#!/usr/bin/env python3
"""
scripts/seed_experience.py
Seeds The Forge's intelligence systems with experience data equivalent to
50+ successful builds. Run once from the project root:

    python scripts/seed_experience.py

Inserts:
  - 80+ knowledge base records (architecture patterns, deployment outcomes)
  - 40 meta-rules (require/prefer/avoid)
  - 17 build templates (proven file patterns)
  - 60 error/fix pairs
  - 5 agent registry entries
  - 5 deployment feedback records
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Bootstrap path so local imports work ─────────────────────────────────────
# Script lives in scripts/, project root is one level up
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ── Imports ───────────────────────────────────────────────────────────────────
from sqlalchemy import text
from loguru import logger

# Must import after path setup and .env load
from memory.database import AsyncSessionLocal, engine
from memory.models import (
    Base, KbRecord, MetaRule, BuildTemplate, DeploymentFeedback, ForgeAgentVersion
)

# ══════════════════════════════════════════════════════════════════════════════
# DATA CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

KB_ARCHITECTURE = [
    ("FastAPI + async SQLAlchemy + asyncpg is the standard backend stack. Use async_sessionmaker with expire_on_commit=False. Pool pre-ping=True. Every agent (BuildRight, ARIA, Trading OS, The Office) uses this pattern.", "proven_5_builds"),
    ("Database models use UUID primary keys (uuid.uuid4), TIMESTAMPTZ for all datetimes with server_default=func.now(), JSONB for flexible metadata fields, and Vector(1536) from pgvector for embedding columns.", "proven_5_builds"),
    ("Every agent has a dedicated database.py with: create_async_engine, AsyncSessionLocal factory, init_db() that calls Base.metadata.create_all, and individual helper functions per table. Never use raw SQL elsewhere.", "proven_5_builds"),
    ("Fly.io deployment: API server on shared-cpu-1x 512MB with min_machines_running=1, worker on shared-cpu-2x 2GB. React dashboard served as static files from the API (no separate dashboard app). All agents share one managed Postgres 'the-forge-db' — each agent gets its own database named {agent_slug}_db. Setup: flyctl postgres attach the-forge-db --app {api_app} --database-name {agent_slug}_db. Primary region syd for Australian businesses, lhr for others.", "proven_5_builds"),
    ("Shared Postgres pattern: the-forge-db is the single managed Postgres instance for all agents in The Office portfolio. Each agent uses a separate database (not schema) named {agent_slug}_db. This gives full isolation (separate connection pools, separate migrations) at zero extra cost vs a new Postgres app ($0 vs ~A$63/month). flyctl postgres attach sets DATABASE_URL automatically on the API app. Copy that value to the worker with flyctl secrets set.", "proven_3_builds"),
    ("LangGraph state machine for multi-step pipelines. State is a dict passed between nodes. Each node has single responsibility. build_graph() returns compiled graph. ainvoke() for async execution. Used in Trading OS, ARIA, The Forge.", "proven_3_builds"),
    ("React dashboard with Tailwind CSS utility classes only. No CSS files. Vite for build. Dark theme standard: bg-gray-950 background, colored accents. Multi-stage Docker: Node build → Nginx Alpine serve. Final image <30MB.", "proven_5_builds"),
    ("RQ (Redis Queue) for background job processing. Worker polls forge-queue. Job functions are sync wrappers around async: def job(id): asyncio.run(_job(id)). Always update status at every step so dashboard shows live progress.", "proven_4_builds"),
    ("APScheduler for scheduled jobs. cron triggers for daily/weekly tasks. All scheduled functions wrapped in try/except — never crash the scheduler. Typical jobs: knowledge collection, meta-rules extraction, performance monitoring.", "proven_5_builds"),
    ("Twilio for SMS: use MessagingService SID, not individual phone numbers. Webhook endpoint for incoming: POST /webhooks/twilio. Always verify Twilio signature in production. Used in BuildRight for lead conversations.", "proven_1_build"),
    ("Anthropic API pattern: AsyncAnthropic client as module-level singleton. api_key from os.getenv. MODEL.get(task_type) for model selection. Always try/except Claude calls.", "proven_5_builds"),
    ("Every agent output package includes: .github/workflows/deploy.yml (auto-deploy on push to main), FLY_SECRETS.txt (every flyctl secrets set command), connection_test.py (verify all API keys), .env.example (every env var).", "proven_5_builds"),
    ("Config pattern: model_config.py with ModelConfig dataclass. primary model (Sonnet) for quality tasks, fast model (Haiku) for classification/scoring. Single env var CLAUDE_MODEL upgrades all agents simultaneously.", "proven_5_builds"),
    ("Intelligence infrastructure standard: 7 files that add to any agent without changing existing code: model_config, knowledge_base, meta_rules, context_assembler, evaluator, verifier, performance_monitor.", "proven_5_builds"),
    ("Knowledge engine standard: 4 files + YAML config + 3 DB tables. collector.py (Tavily + RSS + YouTube), embedder.py (OpenAI text-embedding-3-small), retriever.py (pgvector cosine similarity), live_search.py (on-demand Tavily).", "proven_5_builds"),
    ("Discord webhook for notifications: simple POST with embeds JSON. Green embed for success, red for failure. Include: title, file count, duration, build health summary. No Discord bot needed — webhooks only.", "proven_4_builds"),
    ("GitHub Actions deploy.yml: actions/checkout@v5, superfly/flyctl-actions/setup-flyctl@v2. Deploy each service sequentially (API → Worker → Dashboard). FLY_API_TOKEN as repository secret. Triggers on push to main only.", "proven_5_builds"),
    ("Docker pattern: Python 3.12-slim base. apt-get gcc libpq-dev for psycopg2. pip install --no-cache-dir. COPY requirements.txt first (layer caching). EXPOSE port. CMD uvicorn for API, CMD python -m rq worker for workers.", "proven_5_builds"),
    ("Health check endpoint: GET /health returns {status: healthy, redis: ok}. Check Redis ping in health endpoint. Fly.io [checks] block hits /health every 30s, restarts on 3 consecutive failures.", "proven_5_builds"),
    ("Conversation/chat pattern: WebSocket at /ws/chat for streaming. REST fallback at POST /chat/message. History stored in conversation_history table with session_id index. Context assembler runs before every Claude call.", "proven_3_builds"),
    ("Lead generation agents need: conversation_engine, qualification_scorer, quote_generator, follow_up_scheduler, review_requester. Each as separate service file. Twilio for SMS, SendGrid for email. Redis for deduplication.", "proven_2_builds"),
    # Integration patterns 21-30:
    ("Tavily web search integration: from tavily import TavilyClient. client.search(query, max_results=5, search_depth='advanced'). Wrap in try/except — falls back to cached results if Tavily is unavailable.", "proven_5_builds"),
    ("Google Calendar API: use service account credentials for server-to-server. Scopes: calendar.events. Create events with attendees list. Always use RFC3339 datetime format. Store credentials JSON in env var as base64.", "proven_2_builds"),
    ("SendGrid email: sendgrid.SendGridAPIClient(api_key). Mail object with to, from, subject, html_content. Always set from_email to a verified sender. Use templates for recurring email types.", "proven_3_builds"),
    ("pgvector similarity search: SELECT * FROM table ORDER BY embedding <=> query_embedding LIMIT k. Create index: CREATE INDEX ON table USING ivfflat (embedding vector_cosine_ops). Requires pgvector extension enabled.", "proven_5_builds"),
    ("OpenAI embeddings: openai.AsyncOpenAI(). await client.embeddings.create(model='text-embedding-3-small', input=text). Returns 1536-dimension vector. Always handle rate limits with exponential backoff.", "proven_5_builds"),
    ("Redis caching pattern: redis.Redis.from_url(REDIS_URL). Serialize to JSON for complex objects. TTL on every cache key — never cache indefinitely. Use pipeline() for batch operations. Key naming: service:entity:id.", "proven_5_builds"),
    ("Pydantic request/response models: BaseModel with Field(description=...) for OpenAPI docs. Use Optional[X] = None for optional fields. Use validator for custom validation. Return model from route for automatic serialisation.", "proven_5_builds"),
    ("FastAPI middleware order: MaxBodySize → CORS → Auth → SlowAPI (rate limit). Auth middleware should skip /health and /docs. Rate limit: 60/min general, 10/hour for expensive ops like builds.", "proven_5_builds"),
    ("Loguru configuration: logger.add(sys.stderr, level='INFO', format='{time} | {level} | {name}:{line} | {message}'). For production: JSON format for structured logging. Remove default handler first with logger.remove().", "proven_5_builds"),
    ("Alembic for database migrations: alembic init alembic. Configure env.py with async engine. Use autogenerate for schema changes. Run: alembic upgrade head on deploy. Never drop columns in production migrations.", "proven_3_builds"),
]

META_RULES = [
    # (rule_type, rule_text, confidence)
    # REQUIRE rules:
    ("generation", "Always generate connection_test.py in every output package — run it before deploying to verify all API keys work", 0.99),
    ("generation", "Always generate .env.example listing every env var referenced in code, with descriptions and example values", 0.99),
    ("generation", "Always generate FLY_SECRETS.txt with exact flyctl secrets set commands — developers copy-paste to deploy", 0.99),
    ("generation", "Always include CORS middleware in FastAPI main.py — dashboard cannot call API without it", 0.99),
    ("generation", "Always use UUID primary keys with uuid.uuid4() default, never integer auto-increment", 0.97),
    ("generation", "Always use TIMESTAMPTZ not TIMESTAMP for datetime columns — handles timezone correctly across regions", 0.97),
    ("generation", "Always use async_sessionmaker with expire_on_commit=False — prevents DetachedInstanceError", 0.99),
    ("generation", "Always add pool_pre_ping=True to create_async_engine — detects stale connections before use", 0.95),
    ("generation", "Always wrap every Claude API call in try/except with logger.warning fallback — API calls can fail", 0.99),
    ("generation", "Always include GET /health endpoint that checks Redis connectivity and returns JSON status", 0.99),
    ("generation", "Always run CREATE EXTENSION IF NOT EXISTS vector before creating tables with Vector columns", 0.99),
    ("generation", "Always replace postgresql:// with postgresql+asyncpg:// in DATABASE_URL for async SQLAlchemy", 0.99),
    ("generation", "Always pin exact versions in requirements.txt — floating versions cause non-reproducible builds", 0.95),
    ("generation", "Always generate .github/workflows/deploy.yml for Fly.io auto-deploy on push to main", 0.99),
    ("generation", "Always add feedback_reporter.py to output packages so users can report deployment outcomes", 0.90),
    # PREFER rules:
    ("generation", "Prefer Loguru over standard logging — consistent structured logging across all agents", 0.95),
    ("generation", "Prefer Pydantic BaseModel for all request/response types — type safety and automatic OpenAPI docs", 0.95),
    ("generation", "Prefer JSONB over JSON for PostgreSQL columns — supports GIN indexing and querying", 0.90),
    ("generation", "Prefer shared-cpu-1x 512MB for API servers — sufficient for most FastAPI workloads", 0.85),
    ("generation", "Prefer shared-cpu-2x 1-2GB for worker processes — handles concurrent Claude API calls", 0.90),
    ("generation", "Always set min_machines_running = 1 in fly.toml http_service block — prevents Fly.io from creating 2 machines for HA on first deploy, saving ~A$10/month per agent", 0.99),
    ("generation", "Never generate a separate scheduler fly.toml or Fly.io app for APScheduler — run APScheduler inside the worker process. A separate scheduler service wastes ~A$9/month for zero benefit.", 0.99),
    ("generation", "Always add --ha=false to flyctl deploy commands in GitHub Actions — Fly.io creates 2 machines by default for new apps, doubling cost unnecessarily", 0.99),
    ("generation", "Never generate a separate dashboard Fly.io app or fly.toml for the React dashboard — serve it as static files from the API using FastAPI StaticFiles. Dockerfile.api uses a multi-stage build to compile the React app and copy dist/ into the Python image. This eliminates one Fly machine per agent (~A$4/month saved).", 0.99),
    ("generation", "FastAPI main.py must mount the React dashboard AFTER all routes: app.mount('/', StaticFiles(directory='dist', html=True), name='static'). Only add this mount if the dist/ directory exists at runtime.", 0.95),
    ("generation", "Never generate a separate Fly.io Postgres app for any agent — all agents share the existing managed Postgres 'the-forge-db'. Each agent uses its own database named {agent_slug}_db on that shared instance. Setup: flyctl postgres attach the-forge-db --app {api_app} --database-name {agent_slug}_db. This saves ~A$63/month per agent.", 0.99),
    ("generation", "DATABASE_URL in .env.example must reference a database named {agent_slug}_db (not postgres or default). In docker-compose.yml the local Postgres container should create this database: POSTGRES_DB: {agent_slug}_db.", 0.95),
    ("generation", "Prefer Tailwind utility classes only, no custom CSS files — consistent dark theme: bg-gray-950", 0.90),
    ("generation", "Prefer routing scoring and classification tasks to Haiku — 80% cheaper, equally accurate for classification", 0.95),
    ("generation", "Prefer RQ over Celery for job queues — simpler, lighter, sufficient for single-machine deployments", 0.90),
    ("generation", "Prefer generating seed.py for database initialisation — one command to bootstrap any environment", 0.85),
    ("generation", "Prefer docker-compose.yml for local dev with Postgres 16 + Redis 7 services", 0.90),
    ("generation", "Prefer multi-stage Docker builds for dashboards — Node build stage then Nginx Alpine serve stage", 0.95),
    ("generation", "Prefer storing API keys in Fly secrets, never in committed .env files in production", 0.99),
    ("generation", "Prefer TEXT over VARCHAR for most string columns in PostgreSQL — no arbitrary length limits", 0.85),
    ("generation", "Prefer ARRAY(String) for tag-like fields, JSONB for complex nested data structures", 0.80),
    ("generation", "Prefer NullPool for asyncpg in RQ worker context — each asyncio.run() needs fresh connections", 0.99),
    # AVOID rules:
    ("generation", "Never use blocking calls (requests.get, time.sleep) inside async functions — blocks the event loop", 0.99),
    ("generation", "Never hardcode Claude model names — always use router.get_model(task_type) from model_config", 0.99),
    ("generation", "Never hardcode URLs or ports — use environment variables for all external service endpoints", 0.99),
    ("generation", "Never store secrets in .env files in production repositories — use Fly.io secrets management", 0.99),
    ("generation", "Never use global mutable state in FastAPI — causes race conditions in async context", 0.95),
    ("generation", "Never catch bare Exception and silently pass — always log with logger.warning at minimum", 0.97),
    ("generation", "Never use SQLAlchemy synchronous engine with FastAPI — always use create_async_engine", 0.99),
    ("generation", "Never generate TODO, PLACEHOLDER, or stub comments — every file must be complete and deployable", 0.99),
    ("generation", "Never use >= or ~= in requirements.txt — pin exact versions for reproducible builds", 0.90),
    ("generation", "Never import from circular dependency paths — structure: models → database → services → routes", 0.95),
]

BUILD_TEMPLATES = {
    "fastapi_main": '''\
"""
{AGENT_NAME} API — main.py
FastAPI application entry point.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from redis import Redis

from config.settings import settings
from memory.database import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("{AGENT_NAME} API starting")
    await init_db()
    yield
    await close_db()
    logger.info("{AGENT_NAME} API shutdown complete")


app = FastAPI(
    title="{AGENT_NAME}",
    description="{AGENT_NAME} API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if os.getenv("APP_ENV") == "development" else [
        "https://{FLY_APP_NAME}-dashboard.fly.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_redis = Redis.from_url(settings.redis_url)


@app.get("/health", tags=["health"])
async def health() -> dict:
    try:
        _redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "status": "healthy" if redis_ok else "degraded",
        "service": "{FLY_APP_NAME}-api",
        "env": os.getenv("APP_ENV", "production"),
        "redis": "ok" if redis_ok else "unreachable",
    }
''',

    "sqlalchemy_models": '''\
"""
{AGENT_NAME} — database models.
"""
import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class {TABLE_NAME_1}(Base):
    """Primary entity table."""
    __tablename__ = "{TABLE_NAME_1_LOWER}"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
''',

    "database_helpers": '''\
"""
{AGENT_NAME} — database engine and session management.
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from memory.models import Base

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
''',

    "dockerfile_api": '''\
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential libpq-dev curl \\
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
EXPOSE {API_PORT}

RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "{API_PORT}"]
''',

    "dockerfile_worker": '''\
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential libpq-dev git curl \\
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

CMD ["python", "-m", "pipeline.worker"]
''',

    "dockerfile_dashboard": '''\
# Stage 1: Build React app
FROM node:20-alpine AS builder

WORKDIR /app

COPY web-dashboard/package*.json ./
RUN npm ci --silent

COPY web-dashboard/ .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
''',

    "fly_toml_api": '''\
app = "{FLY_APP_NAME}-api"
primary_region = "syd"

[build]
  dockerfile = "Dockerfile.api"

[env]
  APP_ENV = "production"
  PORT = "{API_PORT}"

[http_service]
  internal_port = {API_PORT}
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

[[http_service.checks]]
  grace_period = "10s"
  interval = "30s"
  method = "GET"
  path = "/health"
  timeout = "10s"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
''',

    "fly_toml_worker": '''\
app = "{FLY_APP_NAME}-worker"
primary_region = "syd"

[build]
  dockerfile = "Dockerfile.worker"

[env]
  APP_ENV = "production"

# Worker runs APScheduler internally — no separate scheduler service needed
[[vm]]
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 2048
''',

    "dockerfile_api_with_dashboard": '''\
# ── Stage 1: Build React dashboard ───────────────────────────────────────────
FROM node:22-alpine AS dashboard-build
WORKDIR /dashboard
COPY dashboard/package.json ./
RUN npm install
COPY dashboard/ .
RUN npm run build

# ── Stage 2: Python API (serves both API and dashboard) ──────────────────────
FROM python:3.12-alpine AS api
RUN apk add --no-cache build-base postgresql-dev libxml2-dev libxslt-dev && rm -rf /var/cache/apk/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=dashboard-build /dashboard/dist /app/dist
RUN adduser -D -u 1000 agent && chown -R agent:agent /app
USER agent
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "{API_PORT}"]
''',

    "github_actions_deploy": '''\
name: Deploy {AGENT_NAME}

on:
  push:
    branches: [main]

jobs:
  deploy-api:
    name: Deploy API
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: superfly/flyctl-actions/setup-flyctl@v2
      - name: Deploy {AGENT_NAME} API
        run: flyctl deploy --app {FLY_APP_NAME}-api --config fly.{FLY_APP_NAME}-api.toml --ha=false
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

  deploy-worker:
    name: Deploy Worker
    runs-on: ubuntu-latest
    needs: deploy-api
    steps:
      - uses: actions/checkout@v5
      - uses: superfly/flyctl-actions/setup-flyctl@v2
      - name: Deploy {AGENT_NAME} Worker
        run: flyctl deploy --app {FLY_APP_NAME}-worker --config fly.{FLY_APP_NAME}-worker.toml --ha=false
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
''',

    "docker_compose_dev": '''\
version: "3.9"

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "{API_PORT}:{API_PORT}"
    env_file: .env
    depends_on:
      - postgres
      - redis
    volumes:
      - .:/app
    command: uvicorn app.api.main:app --host 0.0.0.0 --port {API_PORT} --reload

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    env_file: .env
    depends_on:
      - postgres
      - redis
    volumes:
      - .:/app

  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: {AGENT_SLUG}_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
''',

    "env_example": '''\
# {AGENT_NAME} — Environment Variables
# Copy to .env and fill in real values

# ── Core ──────────────────────────────────────────────────────────────────────
APP_ENV=development
SECRET_KEY=change-me-to-a-random-32-char-string
API_SECRET_KEY=change-me

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/{AGENT_SLUG}_db

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379

# ── AI APIs ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001

# ── Notifications ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# ── External APIs ─────────────────────────────────────────────────────────────
TAVILY_API_KEY=tvly-...
GITHUB_TOKEN=ghp_...
FLY_API_TOKEN=...
''',

    "gitignore": '''\
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/
*.egg
venv/
.venv/
env/

# Environment
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# Node.js
node_modules/
web-dashboard/dist/
web-dashboard/.cache/

# Logs
*.log
logs/

# OS
.DS_Store
Thumbs.db

# Docker
*.override.yml

# Temporary
tmp/
temp/
*.tmp
''',

    "model_config": '''\
"""
config/model_config.py
Routes Claude API calls to the appropriate model based on task type.
Haiku for fast/cheap tasks, Sonnet for quality tasks.
"""
import os
from dataclasses import dataclass
from typing import Optional


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")

_HAIKU_TASKS = frozenset([
    "evaluation", "classification", "scoring", "validation",
    "summarisation", "intent_detection", "blueprint_validation",
])

_SONNET_TASKS = frozenset([
    "generation", "synthesis", "reasoning", "architecture",
    "parsing", "verification", "research", "strategy",
])


class ModelRouter:
    def get_model(self, task_type: str) -> str:
        if task_type in _HAIKU_TASKS:
            return CLAUDE_FAST_MODEL
        return CLAUDE_MODEL

    def get_max_tokens(self, task_type: str) -> int:
        if task_type in _HAIKU_TASKS:
            return 4000
        return 16000


router = ModelRouter()
''',

    "retry_decorator": '''\
"""
Exponential backoff retry decorator for async functions.
"""
import asyncio
import functools
from typing import Callable, Optional, Tuple, Type

from loguru import logger


async def retry_async(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff: float = 2.0,
    label: str = "",
    no_retry_on: Tuple[Type[Exception], ...] = (),
    **kwargs,
):
    """
    Retry an async function with exponential backoff.
    Raises the last exception if all attempts fail.
    """
    last_exc: Optional[Exception] = None
    delay = base_delay

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except no_retry_on:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt == max_attempts:
                logger.error(f"{label}: all {max_attempts} attempts failed — {exc}")
                raise

            wait = min(delay * (backoff ** (attempt - 1)), max_delay)
            logger.warning(f"{label}: attempt {attempt}/{max_attempts} failed ({exc}) — retry in {wait:.1f}s")
            await asyncio.sleep(wait)

    raise last_exc
''',

    "nginx_spa_config": '''\
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing — serve index.html for all routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets aggressively
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";

    gzip on;
    gzip_types text/plain application/javascript text/css application/json;
    gzip_min_length 1000;
}
''',
}

ERROR_FIXES = [
    # Python errors (15)
    "ERROR: ImportError: cannot import name X from Y. FIX: Check the exact class or function name exported by the source file. Common cause: file exports UserModel but import statement says User. Run grep -r 'class User' . to find exact name.",
    "ERROR: SyntaxError: invalid syntax on async def or match statement. FIX: Ensure Python 3.12+ is used in Dockerfile (FROM python:3.12-slim). Python 3.10 does not support all 3.12 syntax features.",
    "ERROR: RuntimeError: no running event loop. FIX: Wrap async code with asyncio.run() in synchronous context (e.g., RQ job functions). Never call await directly from a sync function.",
    "ERROR: TypeError: object dict cannot be used in await expression. FIX: The called function is not async. Either remove the await keyword or convert the function to async def.",
    "ERROR: ModuleNotFoundError: No module named X. FIX: Add the package to requirements.txt. Check PyPI spelling (e.g., 'pillow' not 'PIL', 'psycopg2-binary' not 'psycopg2'). Rebuild Docker image.",
    "ERROR: ImportError: circular import between models.py and database.py. FIX: Move Base class to a separate base.py. Import Base in models.py and database.py separately. Never import models from database.py.",
    "ERROR: ModuleNotFoundError despite package being installed — missing __init__.py. FIX: Add empty __init__.py to every Python package directory. Python 3 requires __init__.py for packages to be importable.",
    "ERROR: asyncpg ConnectionRefusedError or could not connect to server. FIX: Check DATABASE_URL format (must be postgresql+asyncpg://). Verify Postgres is running. Check firewall/security group. Use pool_pre_ping=True.",
    "ERROR: pydantic ValidationError: field required / value is not a valid type. FIX: Check request body matches Pydantic model exactly. Use Optional[X] = None for optional fields. Check date format (ISO 8601).",
    "ERROR: TypeError: Object of type UUID is not JSON serializable. FIX: Convert UUID to str before JSON serialization: str(obj.id). Add custom JSON encoder or use model_config with json_encoders.",
    "ERROR: SQLAlchemy DetachedInstanceError: Instance is not bound to a Session. FIX: Use async_sessionmaker with expire_on_commit=False. Access all attributes within the session context or load them eagerly.",
    "ERROR: Missing await on async session execute call — function returns coroutine not result. FIX: Add await before all async SQLAlchemy calls: await session.execute(), await session.commit(), await session.scalar().",
    "ERROR: psycopg2 OperationalError: could not load library libpq.so. FIX: Add libpq-dev to apt-get install in Dockerfile. Also install libpq5 for the runtime library.",
    "ERROR: redis.exceptions.ConnectionError: Error connecting to Redis. FIX: Check REDIS_URL format (must include password if auth enabled). Format: redis://default:PASSWORD@host:6379. Verify Redis is running.",
    "ERROR: anthropic.AuthenticationError: Invalid API key. FIX: Check ANTHROPIC_API_KEY env var is set and not expired. Use flyctl secrets set ANTHROPIC_API_KEY=... to set in production.",
    # FastAPI errors (10)
    "ERROR: CORS error — blocked by CORS policy. FIX: Add CORSMiddleware to FastAPI app with allow_origins=[dashboard_url], allow_methods=['*'], allow_headers=['*']. Must be added before any route includes.",
    "ERROR: FastAPI route not found — returns 404. FIX: Check route decorator prefix matches router registration. @router.get('/items') with app.include_router(router, prefix='/api') gives /api/items.",
    "ERROR: FastAPI 422 Unprocessable Entity on POST request. FIX: Ensure request body type hint is present in function signature: async def create(body: MyModel). Without type hint FastAPI ignores body.",
    "ERROR: FastAPI 422 on integer field sent as string. FIX: Pydantic coerces types in V1 but is strict in V2. Add model_config = ConfigDict(coerce_numbers_to_str=True) or use Union[int, str].",
    "ERROR: Background task vs RQ confusion — task not persisting after response. FIX: FastAPI BackgroundTasks run in-process — good for quick tasks. Use RQ for tasks >5s or that need persistence across restarts.",
    "ERROR: FastAPI startup event deprecated warning. FIX: Replace @app.on_event('startup') with @asynccontextmanager lifespan function passed to FastAPI(lifespan=lifespan).",
    "ERROR: FastAPI dependency injection returning same instance in async context. FIX: Use Depends() for request-scoped dependencies. Never use module-level mutable state — use dependency injection.",
    "ERROR: WebSocket connection closes immediately. FIX: Keep WebSocket handler alive with while True loop. Catch WebSocketDisconnect exception to clean up. Use asyncio.sleep(0) to yield to event loop.",
    "ERROR: File upload UploadFile returns empty content. FIX: Read file content with await file.read(). File position resets after first read — call await file.seek(0) to read again.",
    "ERROR: SlowAPI rate limit middleware blocks all requests with 500. FIX: Add app.state.limiter = limiter and app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler). Order matters.",
    # Fly.io errors (10)
    "ERROR: Fly.io machine won't start — exits immediately. FIX: Check logs with flyctl logs --app NAME. Common cause: OOM (bump memory_mb), missing env var (check flyctl secrets list), bad CMD in Dockerfile.",
    "ERROR: Fly.io health check timeout — machine restarts in loop. FIX: Increase grace_period to '30s' in fly.toml [checks] block. App needs time to initialise database connections on first start.",
    "ERROR: Fly.io Postgres connection refused from app. FIX: DATABASE_URL must use internal Fly.io hostname (*.flycast or .internal). External URL uses different port. Use flyctl postgres attach to get correct URL.",
    "ERROR: Fly.io Redis auth failed. FIX: Redis URL must include password: redis://default:PASSWORD@fly-redis-name.upstash.io:6379. Get exact URL from flyctl redis status --app NAME.",
    "ERROR: Fly.io app cold starts causing request timeouts. FIX: Set auto_stop_machines = false in fly.toml http_service block. Cold starts add 3-5s latency. Keep alive for production APIs.",
    "ERROR: Fly.io volume not mounting correctly. FIX: Check [mounts] section in fly.toml: source = 'data', destination = '/data'. Create volume first: flyctl volumes create data --region syd --size 1.",
    "ERROR: Fly.io secrets not available during Docker build. FIX: Build-time values use ARG in Dockerfile. Runtime secrets use Fly secrets. Never use Fly secrets as Docker build args — they are runtime only.",
    "ERROR: Fly.io deploy timeout on large Docker image. FIX: Use .dockerignore to exclude node_modules, .git, __pycache__. Pin base image digest for reproducibility. Use multi-stage builds.",
    "ERROR: Fly.io shared-cpu-1x machine crashing on memory spikes. FIX: Upgrade to shared-cpu-2x for workers handling Claude API calls. Each Claude call can use 50-200MB during processing.",
    "ERROR: Fly.io region latency for Australian users. FIX: Set primary_region = 'syd' in fly.toml. Use flyctl regions add syd. Fly.io Sydney region (syd) is lowest latency for Australia/NZ.",
    # Docker errors (10)
    "ERROR: Docker layer cache invalidated on every build. FIX: COPY requirements.txt . then RUN pip install before COPY . . This caches the pip install layer and only rebuilds when requirements.txt changes.",
    "ERROR: Docker image too large — build slow. FIX: Add rm -rf /var/lib/apt/lists/* after apt-get. Use --no-cache-dir for pip. Use python:3.12-slim not python:3.12. Consider multi-stage builds.",
    "ERROR: pip install creates large bloated layers. FIX: Always use pip install --no-cache-dir -r requirements.txt. The cache is useless in Docker since each build starts fresh.",
    "ERROR: Multi-stage Docker COPY --from fails. FIX: Name the build stage: FROM node:20-alpine AS builder. Then COPY --from=builder /app/dist /usr/share/nginx/html in the next stage.",
    "ERROR: Docker ENV vs ARG confusion — variable not available. FIX: ARG is build-time only (use for VITE_ vars). ENV is runtime (use for app config). ARG can set ENV: ARG X / ENV X=$X.",
    "ERROR: Docker WORKDIR not set — files in wrong location. FIX: Always set WORKDIR /app before any COPY or RUN commands. All relative paths resolve from WORKDIR.",
    "ERROR: Python package install fails — missing gcc or libffi-dev. FIX: Add to apt-get: gcc libpq-dev libffi-dev build-essential. Required for packages that compile C extensions (cryptography, psycopg2).",
    "ERROR: Dashboard Docker build fails — node_modules bloating image. FIX: Add node_modules to .dockerignore. Let npm ci install fresh in the container. Multi-stage build discards node_modules anyway.",
    "ERROR: CMD shell form vs exec form difference. FIX: Prefer exec form CMD [\"uvicorn\", ...] — gets PID 1, handles signals correctly. Shell form CMD uvicorn ... spawns shell wrapper, SIGTERM not forwarded.",
    "ERROR: Dockerfile health check vs fly.toml health check — both defined. FIX: Use fly.toml [checks] block only. Dockerfile HEALTHCHECK is redundant on Fly.io and can conflict with orchestration.",
    # React/Dashboard errors (10)
    "ERROR: Tailwind CSS classes not applying — elements unstyled. FIX: Check tailwind.config.js content array includes all .jsx/.tsx files: content: ['./src/**/*.{js,jsx,ts,tsx}']. Run npm run build to verify.",
    "ERROR: Vite environment variables not available in React app. FIX: All client-side env vars must start with VITE_. Access with import.meta.env.VITE_API_URL. Pass as Docker build ARG: ARG VITE_API_URL.",
    "ERROR: React useEffect running too many times — infinite loop. FIX: Check dependency array. Empty [] runs once on mount. Missing dependency causes stale closure. Add all values used inside effect.",
    "ERROR: React Router routes return 404 on page refresh. FIX: Configure Nginx to serve index.html for all routes: try_files $uri $uri/ /index.html. Without this, Nginx tries to find the file literally.",
    "ERROR: React fetch API calls fail — base URL not configured. FIX: Use environment variable for API base URL: const API = import.meta.env.VITE_API_BASE_URL. Default to '' for same-origin in development.",
    "ERROR: CORS blocked from React dashboard to FastAPI. FIX: Add dashboard origin to FastAPI CORS allow_origins. In development use '*'. In production use exact URL: https://your-dashboard.fly.dev.",
    "ERROR: React build fails on strict TypeScript errors. FIX: Add skipLibCheck: true to tsconfig.json. Or fix type errors. Never use @ts-ignore — fix the underlying type issue properly.",
    "ERROR: React list rendering without key prop — console warning and bad performance. FIX: Add unique key prop to each element in .map(): items.map(item => <div key={item.id}>). Never use index as key.",
    "ERROR: React useState setter in async function — state update after unmount. FIX: Use cleanup function in useEffect: let mounted = true; ... if (mounted) setState(data); return () => { mounted = false; }",
    "ERROR: Tailwind dark mode not working. FIX: Add darkMode: 'class' to tailwind.config.js. Add 'dark' class to <html> element. Or use darkMode: 'media' for automatic system preference detection.",
    # Intelligence layer errors (5)
    "ERROR: pgvector extension does not exist — CREATE TABLE fails. FIX: Run CREATE EXTENSION IF NOT EXISTS vector BEFORE creating tables. Add this to init_db() before Base.metadata.create_all().",
    "ERROR: pgvector dimension mismatch — expected 1536 got 768. FIX: OpenAI text-embedding-3-small produces 1536 dimensions. text-embedding-ada-002 also 1536. text-embedding-3-large is 3072. Match Vector(N) to model output.",
    "ERROR: SQLAlchemy cannot find Vector column type. FIX: Install pgvector Python package: pip install pgvector. Import: from pgvector.sqlalchemy import Vector. Requires pgvector extension in Postgres.",
    "ERROR: meta_rules extraction returns invalid JSON — KeyError on parse. FIX: Add JSON fallback: try: data = json.loads(response) except: data = {}. Always validate JSON before accessing keys.",
    "ERROR: APScheduler job overlaps — previous job still running when next fires. FIX: Add max_instances=1 to job: scheduler.add_job(func, 'cron', hour=9, max_instances=1). Prevents concurrent execution.",
]

AGENT_VERSIONS = [
    {
        "run_id": "seed-buildright",
        "agent_name": "buildright",
        "spec_json": {
            "agent_name": "BuildRight AI Agent",
            "agent_slug": "buildright",
            "description": "Sydney construction business lead generation, qualification, and conversion system",
            "stack": "Next.js 14, TypeScript, Prisma, Python FastAPI, Fly.io",
            "fly_services": ["buildright-api", "buildright-worker", "buildright-dashboard"],
            "database_tables": ["leads", "conversations", "quotes", "jobs", "reviews", "material_prices"],
            "external_apis": ["Twilio", "SendGrid", "Google Calendar", "NSW Planning Portal"],
            "features": ["60s SMS response", "lead scoring 0-100", "6-touch follow-up", "DA monitor", "competitor analysis"],
        },
        "file_manifest": {
            "app/api/main.py": {"layer": 3, "chars": 4200},
            "memory/models.py": {"layer": 1, "chars": 8500},
            "memory/database.py": {"layer": 1, "chars": 2100},
            "app/api/routes/leads.py": {"layer": 3, "chars": 3800},
            "app/api/routes/conversations.py": {"layer": 3, "chars": 5200},
            "services/conversation_engine.py": {"layer": 4, "chars": 9800},
            "services/qualification_scorer.py": {"layer": 4, "chars": 4200},
            "services/quote_generator.py": {"layer": 4, "chars": 6100},
            "services/follow_up_scheduler.py": {"layer": 4, "chars": 5300},
            "monitoring/da_monitor.py": {"layer": 4, "chars": 3900},
            "web-dashboard/src/App.jsx": {"layer": 5, "chars": 2100},
            ".github/workflows/deploy.yml": {"layer": 6, "chars": 1800},
            "Dockerfile.api": {"layer": 2, "chars": 890},
            "requirements.txt": {"layer": 2, "chars": 620},
        },
        "version": 1,
    },
    {
        "run_id": "seed-aria",
        "agent_name": "aria",
        "spec_json": {
            "agent_name": "ARIA — AI Research Intelligence Agent",
            "agent_slug": "aria",
            "description": "Continuously scans 12 intelligence domains and surfaces actionable insights",
            "stack": "Python 3.12, FastAPI, asyncpg, RQ, APScheduler, Fly.io",
            "fly_services": ["aria-api", "aria-worker", "aria-dashboard"],
            "database_tables": ["research_reports", "opportunities", "action_queue", "knowledge_domains"],
            "external_apis": ["Tavily", "Anthropic", "OpenAI"],
            "domains": ["Models & LLMs", "Agent Frameworks", "Memory & Context", "Trading AI", "Real Estate AI", "Business Automation", "Coding & Dev AI", "Competitive Intelligence", "Market Gaps", "Opportunities", "APIs & Connectors", "Accuracy & Safety"],
        },
        "file_manifest": {
            "app/api/main.py": {"layer": 3, "chars": 3800},
            "memory/models.py": {"layer": 1, "chars": 7200},
            "pipeline/research_engine.py": {"layer": 4, "chars": 11200},
            "pipeline/synthesis_engine.py": {"layer": 4, "chars": 8900},
            "pipeline/opportunity_radar.py": {"layer": 4, "chars": 5600},
            "knowledge/collector.py": {"layer": 4, "chars": 6800},
            "knowledge/embedder.py": {"layer": 4, "chars": 3200},
            "knowledge/retriever.py": {"layer": 4, "chars": 2800},
            "intelligence/evaluator.py": {"layer": 4, "chars": 4100},
            "web-dashboard/src/App.jsx": {"layer": 5, "chars": 3200},
            ".github/workflows/deploy.yml": {"layer": 6, "chars": 1800},
        },
        "version": 1,
    },
    {
        "run_id": "seed-trading-os",
        "agent_name": "trading-os",
        "spec_json": {
            "agent_name": "AI Trading Operating System",
            "agent_slug": "trading-os",
            "description": "Autonomous trading research, strategy development, validation, and live execution for FTMO prop firm accounts",
            "stack": "Python 3.12, FastAPI, LangGraph, asyncpg, RQ, Optuna, Fly.io",
            "fly_services": ["trading-os-api", "trading-os-worker"],
            "database_tables": ["strategies", "backtests", "live_trades", "research_notes", "risk_events"],
            "external_apis": ["Alpaca", "ForexFactory", "CFTC COT", "Anthropic", "OpenAI"],
            "safety_rules": ["weekly_loss_limit_2pct", "daily_loss_limit_1pct", "max_3_concurrent_positions", "no_trading_15min_news"],
        },
        "file_manifest": {
            "app/api/main.py": {"layer": 3, "chars": 3600},
            "memory/models.py": {"layer": 1, "chars": 9800},
            "pipeline/research_agent.py": {"layer": 4, "chars": 12100},
            "pipeline/strategy_architect.py": {"layer": 4, "chars": 10800},
            "pipeline/validator.py": {"layer": 4, "chars": 8900},
            "pipeline/optimizer.py": {"layer": 4, "chars": 7200},
            "pipeline/live_router.py": {"layer": 4, "chars": 5600},
            "intelligence/risk_officer.py": {"layer": 4, "chars": 6800},
            ".github/workflows/deploy.yml": {"layer": 6, "chars": 1800},
        },
        "version": 1,
    },
    {
        "run_id": "seed-the-office",
        "agent_name": "the-office",
        "spec_json": {
            "agent_name": "The Office — Unified AI Command Center",
            "agent_slug": "the-office",
            "description": "Single executive dashboard above every business and agent — one view, one chat, one notification stream",
            "stack": "Python 3.12, FastAPI, asyncpg, React + Vite + Tailwind, Fly.io",
            "fly_services": ["the-office-api", "the-office-worker", "the-office-dashboard"],
            "database_tables": ["business_health_scores", "anomaly_predictions", "financial_consolidation", "chat_sessions"],
            "features": ["health_score_0_100", "anomaly_prediction_2_4h", "cross_portfolio_financials", "unified_chat", "daily_brief_7am"],
        },
        "file_manifest": {
            "app/api/main.py": {"layer": 3, "chars": 4100},
            "memory/models.py": {"layer": 1, "chars": 6800},
            "services/health_scorer.py": {"layer": 4, "chars": 7200},
            "services/anomaly_detector.py": {"layer": 4, "chars": 5900},
            "services/financial_consolidator.py": {"layer": 4, "chars": 6100},
            "services/chat_bridge.py": {"layer": 4, "chars": 4800},
            "web-dashboard/src/App.jsx": {"layer": 5, "chars": 4200},
            ".github/workflows/deploy.yml": {"layer": 6, "chars": 1800},
        },
        "version": 1,
    },
    {
        "run_id": "seed-the-forge",
        "agent_name": "the-forge",
        "spec_json": {
            "agent_name": "The Forge — AI Build Engine",
            "agent_slug": "the-forge",
            "description": "Blueprint document to complete deployable codebase in 15-25 minutes",
            "stack": "Python 3.12, FastAPI, asyncpg, LangGraph, RQ, APScheduler, React + Vite, Fly.io",
            "fly_services": ["the-forge-api", "the-forge-worker", "the-forge-dashboard"],
            "database_tables": ["forge_runs", "forge_files", "kb_records", "meta_rules", "knowledge_articles", "build_costs"],
            "pipeline_stages": ["validate", "parse", "confirm", "architecture", "generate", "package", "github_push", "notify"],
        },
        "file_manifest": {
            "app/api/main.py": {"layer": 3, "chars": 5800},
            "memory/models.py": {"layer": 1, "chars": 15200},
            "pipeline/nodes/codegen_node.py": {"layer": 4, "chars": 18900},
            "pipeline/nodes/layer_generator.py": {"layer": 4, "chars": 14200},
            "pipeline/services/build_doctor.py": {"layer": 4, "chars": 12100},
            "pipeline/services/sandbox.py": {"layer": 4, "chars": 9800},
            "intelligence/knowledge_base.py": {"layer": 4, "chars": 7200},
            "intelligence/evaluator.py": {"layer": 4, "chars": 5600},
            "web-dashboard/src/App.jsx": {"layer": 5, "chars": 3800},
            ".github/workflows/deploy.yml": {"layer": 6, "chars": 1800},
        },
        "version": 1,
    },
]

DEPLOYMENT_FEEDBACKS = [
    {"run_id": "seed-buildright", "deployed_successfully": True, "payload": {"run_id": "seed-buildright", "deployed_successfully": True, "files_modified": [], "deployment_errors": [], "notes": "Seeded from master document — BuildRight deployed cleanly to Fly.io Sydney region. All 22 modules operational."}},
    {"run_id": "seed-aria", "deployed_successfully": True, "payload": {"run_id": "seed-aria", "deployed_successfully": True, "files_modified": [], "deployment_errors": [], "notes": "Seeded from master document — ARIA research engine deployed with all 12 intelligence domains active."}},
    {"run_id": "seed-trading-os", "deployed_successfully": True, "payload": {"run_id": "seed-trading-os", "deployed_successfully": True, "files_modified": [], "deployment_errors": [], "notes": "Seeded from master document — Trading OS deployed with all 6 validation gates and Optuna optimiser active."}},
    {"run_id": "seed-the-office", "deployed_successfully": True, "payload": {"run_id": "seed-the-office", "deployed_successfully": True, "files_modified": [], "deployment_errors": [], "notes": "Seeded from master document — The Office command center deployed with cross-portfolio dashboard active."}},
    {"run_id": "seed-the-forge", "deployed_successfully": True, "payload": {"run_id": "seed-the-forge", "deployed_successfully": True, "files_modified": [], "deployment_errors": [], "notes": "Seeded from master document — The Forge build engine deployed with all 11 build capabilities active."}},
]


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDDING HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def _get_embedding(text: str) -> list[float] | None:
    """Get OpenAI embedding or return None if not configured."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.embeddings.create(model="text-embedding-3-small", input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Knowledge Base Records (Architecture Patterns)
# ══════════════════════════════════════════════════════════════════════════════

async def seed_knowledge_base(session) -> int:
    """Insert architecture and integration pattern KB records."""
    inserted = 0
    for content, outcome in KB_ARCHITECTURE:
        try:
            embedding = await _get_embedding(content)
            record = KbRecord(
                record_type="architecture_pattern",
                content=content,
                outcome=outcome,
                embedding=embedding,
            )
            session.add(record)
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"KB architecture record skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"KB architecture commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Meta Rules
# ══════════════════════════════════════════════════════════════════════════════

async def seed_meta_rules(session) -> int:
    """Insert meta-rules into the meta_rules table."""
    inserted = 0
    for rule_type, rule_text, confidence in META_RULES:
        try:
            rule = MetaRule(
                rule_type=rule_type,
                rule_text=rule_text,
                confidence=confidence,
                is_active=True,
                applied_count=0,
            )
            session.add(rule)
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"Meta rule skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"Meta rules commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Build Templates
# ══════════════════════════════════════════════════════════════════════════════

async def seed_templates(session) -> int:
    """Insert build templates using INSERT ... ON CONFLICT DO UPDATE."""
    inserted = 0
    for file_type, template_content in BUILD_TEMPLATES.items():
        try:
            await session.execute(
                text("""
                    INSERT INTO build_templates (file_type, template_content, successful_deployments, created_at, updated_at)
                    VALUES (:file_type, :template_content, :successful_deployments, NOW(), NOW())
                    ON CONFLICT (file_type) DO UPDATE
                        SET template_content = EXCLUDED.template_content,
                            updated_at = NOW()
                """),
                {"file_type": file_type, "template_content": template_content, "successful_deployments": 1},
            )
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"Template '{file_type}' skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"Build templates commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Error / Fix Pairs
# ══════════════════════════════════════════════════════════════════════════════

async def seed_error_fixes(session) -> int:
    """Insert error/fix pair KB records."""
    inserted = 0
    for content in ERROR_FIXES:
        try:
            embedding = await _get_embedding(content)
            record = KbRecord(
                record_type="error_fix_pair",
                content=content,
                outcome="error_fix_proven",
                embedding=embedding,
            )
            session.add(record)
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"Error/fix record skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"Error/fix commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Agent Registry (ForgeAgentVersion)
# ══════════════════════════════════════════════════════════════════════════════

async def seed_agent_registry(session) -> int:
    """Insert agent versions into forge_agent_versions via raw SQL ON CONFLICT DO NOTHING."""
    inserted = 0
    for av in AGENT_VERSIONS:
        try:
            await session.execute(
                text("""
                    INSERT INTO forge_agent_versions
                        (run_id, agent_name, spec_json, file_manifest, version, created_at)
                    VALUES
                        (:run_id, :agent_name, :spec_json, :file_manifest, :version, NOW())
                    ON CONFLICT DO NOTHING
                """),
                {
                    "run_id": av["run_id"],
                    "agent_name": av["agent_name"],
                    "spec_json": json.dumps(av["spec_json"]),
                    "file_manifest": json.dumps(av["file_manifest"]),
                    "version": av["version"],
                },
            )
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"Agent version '{av['agent_name']}' skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"Agent registry commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Deployment Feedback
# ══════════════════════════════════════════════════════════════════════════════

async def seed_deployment_feedback(session) -> int:
    """Insert deployment feedback records, skipping duplicates."""
    inserted = 0
    for fb in DEPLOYMENT_FEEDBACKS:
        try:
            await session.execute(
                text("""
                    INSERT INTO deployment_feedback
                        (run_id, deployed_successfully, payload, created_at)
                    VALUES
                        (:run_id, :deployed_successfully, :payload, NOW())
                    ON CONFLICT DO NOTHING
                """),
                {
                    "run_id": fb["run_id"],
                    "deployed_successfully": fb["deployed_successfully"],
                    "payload": json.dumps(fb["payload"]),
                },
            )
            await session.flush()
            inserted += 1
        except Exception as e:
            logger.warning(f"Deployment feedback '{fb['run_id']}' skipped: {e}")
            await session.rollback()
    try:
        await session.commit()
    except Exception as e:
        logger.warning(f"Deployment feedback commit failed: {e}")
        await session.rollback()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    logger.info("=" * 60)
    logger.info("The Forge — Experience Seeding Script")
    logger.info("=" * 60)

    openai_configured = bool(os.environ.get("OPENAI_API_KEY"))
    logger.info(f"OpenAI embeddings: {'enabled' if openai_configured else 'disabled (will store NULL)'}")

    # ── Section 1: Architecture Knowledge Base ────────────────────────────────
    logger.info("\n[1/6] Seeding architecture + integration patterns...")
    async with AsyncSessionLocal() as session:
        n = await seed_knowledge_base(session)
    print(f"    [1/6] KB architecture records inserted: {n} / {len(KB_ARCHITECTURE)}")

    # ── Section 2: Meta Rules ─────────────────────────────────────────────────
    logger.info("[2/6] Seeding meta-rules...")
    async with AsyncSessionLocal() as session:
        n = await seed_meta_rules(session)
    print(f"    [2/6] Meta rules inserted:              {n} / {len(META_RULES)}")

    # ── Section 3: Build Templates ────────────────────────────────────────────
    logger.info("[3/6] Seeding build templates...")
    async with AsyncSessionLocal() as session:
        n = await seed_templates(session)
    print(f"    [3/6] Build templates upserted:         {n} / {len(BUILD_TEMPLATES)}")

    # ── Section 4: Error / Fix Pairs ─────────────────────────────────────────
    logger.info("[4/6] Seeding error/fix pairs...")
    async with AsyncSessionLocal() as session:
        n = await seed_error_fixes(session)
    print(f"    [4/6] Error/fix pairs inserted:         {n} / {len(ERROR_FIXES)}")

    # ── Section 5: Agent Registry ─────────────────────────────────────────────
    logger.info("[5/6] Seeding agent registry...")
    async with AsyncSessionLocal() as session:
        n = await seed_agent_registry(session)
    print(f"    [5/6] Agent versions inserted:          {n} / {len(AGENT_VERSIONS)}")

    # ── Section 6: Deployment Feedback ───────────────────────────────────────
    logger.info("[6/6] Seeding deployment feedback...")
    async with AsyncSessionLocal() as session:
        n = await seed_deployment_feedback(session)
    print(f"    [6/6] Deployment feedback inserted:     {n} / {len(DEPLOYMENT_FEEDBACKS)}")

    # ── Summary ───────────────────────────────────────────────────────────────
    total_expected = (
        len(KB_ARCHITECTURE)
        + len(META_RULES)
        + len(BUILD_TEMPLATES)
        + len(ERROR_FIXES)
        + len(AGENT_VERSIONS)
        + len(DEPLOYMENT_FEEDBACKS)
    )
    print("\n" + "=" * 60)
    print("Seeding complete.")
    print(f"  Architecture patterns : {len(KB_ARCHITECTURE)}")
    print(f"  Meta-rules            : {len(META_RULES)}")
    print(f"  Build templates       : {len(BUILD_TEMPLATES)}")
    print(f"  Error/fix pairs       : {len(ERROR_FIXES)}")
    print(f"  Agent versions        : {len(AGENT_VERSIONS)}")
    print(f"  Deployment feedbacks  : {len(DEPLOYMENT_FEEDBACKS)}")
    print(f"  Total records targeted: {total_expected}")
    print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
