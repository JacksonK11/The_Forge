"""
config/knowledge_config.py
Defines the knowledge domains, search queries, RSS feeds, and refresh schedules
for The Forge's knowledge engine.

6 domains covering The Forge's full technical stack:
  1. fastapi_python    — FastAPI, Pydantic v2, SQLAlchemy 2.0, asyncpg
  2. fly_io_deployment — Fly.io, Docker, deployment patterns
  3. rq_redis          — RQ, Redis Queue, background job patterns
  4. react_vite        — React 18, Vite, Tailwind CSS
  5. claude_api        — Anthropic API, Claude SDK, prompt engineering
  6. pgvector_postgres — pgvector, PostgreSQL async, vector search

Each domain sweeps daily. Claude summarises each article found.
Duplicate content is detected by SHA256 hash and skipped.
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
]

# Quick lookup by domain name
DOMAIN_MAP: dict[str, KnowledgeDomain] = {d.name: d for d in KNOWLEDGE_DOMAINS}
