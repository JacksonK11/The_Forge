"""
config/knowledge_config.py
Defines the knowledge domains, search queries, RSS feeds, and refresh schedules
for The Forge's knowledge engine.

8 domains covering The Forge's full technical stack and business context:
  1. fastapi_python    — FastAPI, Pydantic v2, SQLAlchemy 2.0, asyncpg
  2. fly_io_deployment — Fly.io, Docker, deployment patterns
  3. rq_redis          — RQ, Redis Queue, background job patterns
  4. react_vite        — React 18, Vite, Tailwind CSS
  5. claude_api        — Anthropic API, Claude SDK, prompt engineering
  6. pgvector_postgres — pgvector, PostgreSQL async, vector search
  7. build_issues      — Code generation failures, import errors, deployment issues
  8. ai_agent_market   — AI agent market demand, pricing, competitive landscape

Each domain sweeps daily (or per its refresh schedule). Claude summarises each
article found. Duplicate content is detected by SHA256 hash and skipped.
"""

from dataclasses import dataclass, field


@dataclass
class KnowledgeDomain:
    name: str
    description: str
    search_queries: list[str]
    rss_feeds: list[str]
    refresh_hours: int = 24
    max_articles_per_sweep: int = 10


KNOWLEDGE_DOMAINS: list[KnowledgeDomain] = [
    KnowledgeDomain(
        name="fastapi_python",
        description="FastAPI, Pydantic v2, SQLAlchemy 2.0, asyncpg, Python 3.12 async patterns",
        search_queries=[
            "FastAPI async SQLAlchemy 2.0 asyncpg best practices",
            "Pydantic v2 FastAPI production patterns 2025",
            "FastAPI background tasks RQ Redis production deployment",
            "Python asyncpg connection pooling performance tips",
            "FastAPI middleware authentication JWT production",
        ],
        rss_feeds=[],
        refresh_hours=24,
    ),
    KnowledgeDomain(
        name="fly_io_deployment",
        description="Fly.io deployment, Docker, GitHub Actions CI/CD, production configuration",
        search_queries=[
            "Fly.io FastAPI Python deployment production 2025",
            "Fly.io postgres pgvector setup Python",
            "Fly.io GitHub Actions auto deploy secrets",
            "Docker Python 3.12 slim production Dockerfile best practices",
            "Fly.io machine sizing performance-cpu memory configuration",
        ],
        rss_feeds=[
            "https://fly.io/blog/feed.xml",
        ],
        refresh_hours=48,
    ),
    KnowledgeDomain(
        name="rq_redis",
        description="RQ (Redis Queue), background job patterns, worker scaling, APScheduler",
        search_queries=[
            "RQ Redis Queue Python async production patterns",
            "Python RQ worker long-running jobs timeout configuration",
            "APScheduler cron job async FastAPI Python production",
            "Redis Queue job retry error handling Python",
            "RQ worker scale multiple workers Redis production",
        ],
        rss_feeds=[],
        refresh_hours=72,
    ),
    KnowledgeDomain(
        name="react_vite",
        description="React 18, Vite 5, Tailwind CSS v3, React Router v6, production patterns",
        search_queries=[
            "React 18 Vite production best practices 2025",
            "React Router v6 SPA nginx deployment",
            "Tailwind CSS v3 dark theme production patterns",
            "React hooks state management production patterns",
            "Vite build optimisation code splitting production",
        ],
        rss_feeds=[],
        refresh_hours=72,
    ),
    KnowledgeDomain(
        name="claude_api",
        description="Anthropic Claude API, prompt engineering, context management, cost optimisation",
        search_queries=[
            "Anthropic Claude API prompt engineering best practices 2025",
            "Claude claude-sonnet-4-6 code generation prompts",
            "Anthropic API rate limits retry patterns Python",
            "Claude system prompt code generation no placeholders",
            "Anthropic API token counting cost optimisation Python",
        ],
        rss_feeds=[
            "https://www.anthropic.com/rss.xml",
        ],
        refresh_hours=24,
    ),
    KnowledgeDomain(
        name="pgvector_postgres",
        description="pgvector extension, PostgreSQL async, vector similarity search, embeddings",
        search_queries=[
            "pgvector SQLAlchemy 2.0 async cosine similarity Python",
            "pgvector production setup PostgreSQL Fly.io",
            "OpenAI text-embedding-3-small pgvector search patterns",
            "PostgreSQL asyncpg vector similarity search performance",
            "pgvector HNSW index setup production",
        ],
        rss_feeds=[],
        refresh_hours=72,
    ),
    KnowledgeDomain(
        name="build_issues",
        description=(
            "Common code generation failures, Python import errors, deployment issues, "
            "async patterns, SQLAlchemy gotchas, FastAPI common mistakes, Docker/Fly.io "
            "failures, React build errors, and their fixes"
        ),
        search_queries=[
            "Python import error common causes fixes 2026",
            "SQLAlchemy async session common mistakes",
            "FastAPI async endpoint common errors",
            "Fly.io deployment failure troubleshooting",
            "Docker build fails Python slim image fixes",
            "React Tailwind CSS build errors solutions",
            "Python circular import detection resolution",
            "LangGraph state machine common implementation errors",
            "code generation AI common failure patterns",
            "production Python deployment checklist critical errors",
        ],
        rss_feeds=[
            "https://python.org/blogs/rss",
        ],
        refresh_hours=24,
    ),
    KnowledgeDomain(
        name="ai_agent_market",
        description=(
            "Who is buying AI agents, what they pay, competitor pricing and positioning, "
            "which industries adopt AI agents fastest, buyer objections and sales cycles"
        ),
        search_queries=[
            "AI agent development market demand 2026",
            "custom AI agent pricing freelancer agency rates",
            "AI automation agency competitor landscape 2026",
            "industries adopting AI agents fastest growth",
            "AI agent buyer objections enterprise sales",
            "no-code AI agent platforms vs custom development comparison",
            "AI agent development cost breakdown client pricing",
            "AI automation ROI case studies by industry 2026",
        ],
        rss_feeds=[],
        refresh_hours=168,  # Weekly
    ),
]

# Quick lookup by domain name
DOMAIN_MAP: dict[str, KnowledgeDomain] = {d.name: d for d in KNOWLEDGE_DOMAINS}
