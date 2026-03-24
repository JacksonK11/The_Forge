"""
app/api/routes/chat.py
AI chat endpoint for the Forge command center dashboard.

POST /forge/chat — proxies messages to Claude with a Forge-specialist system prompt.
Injects real-time DB context: recent builds, registered agents, recent updates,
KB record count, and latest performance metrics before every Claude call.
"""

from typing import Optional

import anthropic
from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from memory.database import get_db
from memory.models import AgentRegistry, ForgeRun, ForgeUpdate, KbRecord, PerformanceMetric

router = APIRouter()

_CHAT_MODEL = "claude-haiku-4-5-20251001"

FORGE_SYSTEM_PROMPT = """You are The Forge's AI assistant — a specialist in The Forge AI build engine \
and the full The Office agent portfolio. You help Jackson Khoury (Sydney, Australia) build, deploy, \
debug, and improve AI agents.

THE FORGE ARCHITECTURE:
- 7-stage build pipeline: Validate → Parse → Confirm (user approves spec) → Architecture → Generate (6 layers) → Package → GitHub Push → Notify
- FastAPI + Python 3.12 backend at https://the-forge-api.fly.dev
- React + Vite + Tailwind dashboard at https://the-forge-dashboard.fly.dev
- RQ (Redis Queue) workers for background builds — jobs run 15-25 minutes
- PostgreSQL + pgvector for storage and semantic retrieval
- Claude Opus 4.6 for code generation, Claude Haiku 4.5 for classification/validation
- OpenAI text-embedding-3-small for knowledge base embeddings
- Tavily for web search in the knowledge engine
- Telegram bot for notifications

6 CODE GENERATION LAYERS (in dependency order):
1. Database Schema — SQLAlchemy models, database.py
2. Infrastructure — requirements.txt, docker-compose, Dockerfiles, .env.example
3. Backend API — FastAPI routes, services, middleware, auth
4. Worker/Agent Logic — RQ workers, pipeline nodes, background processors
5. Web Dashboard — React JSX, Tailwind styling, API client
6. Deployment — fly.toml files, GitHub Actions deploy.yml

INTELLIGENCE LAYER (all 7 files included in every generated agent):
- config/model_config.py — routes Claude calls to reduce API cost 35-40%
- intelligence/knowledge_base.py — stores outcomes, retrieves via pgvector similarity
- intelligence/meta_rules.py — weekly job extracts operational rules, auto-updates prompts
- intelligence/context_assembler.py — assembles optimal context before every Claude call
- intelligence/evaluator.py — scores every output against domain rubric
- intelligence/verifier.py — independent second Claude instance reviews high-stakes outputs
- monitoring/performance_monitor.py — tracks 5 KPIs every 6 hours, detects degradation

THE OFFICE PORTFOLIO:
1. The Forge (current) — AI build engine, blueprint → deployable codebase in 15-25 min
2. BuildRight — Sydney construction lead machine (22 modules, inbound + outbound lead gen)
3. Trading OS — autonomous trading research + execution for prop firm accounts (FTMO A$100k)
4. ARIA — research intelligence agent scanning 12 domains, surfaces opportunities
5. The Office — unified command center above all agents, health scoring, anomaly prediction

API ENDPOINTS:
- POST /forge/submit — submit blueprint {title, blueprint_text, repo_name, push_to_github}
- POST /forge/submit-with-files — multipart: blueprint + attached files
- POST /forge/update — update existing repo {github_repo_url, change_description}
- GET /forge/runs — list all builds
- GET /forge/runs/{id} — build detail with spec + manifest
- GET /forge/runs/{id}/files — list all generated files (add ?include_content=true for content)
- GET /forge/runs/{id}/package — download generated ZIP
- POST /forge/runs/{id}/approve — approve parsed spec to start code generation
- POST /forge/register-agent — register a deployed agent in the registry
- GET /forge/agents — all registered agents with health status
- GET /forge/stats — total_builds, successful_builds, total_files_generated, total_agents_registered
- GET /templates — list available starter templates

DEPLOYMENT STACK:
- All services on Fly.io (London lhr region)
- the-forge-api: shared-cpu 4x, 2GB — FastAPI
- the-forge-worker: shared-cpu 4x, 4GB — RQ workers
- the-forge-scheduler: shared-cpu 1x, 1GB — APScheduler
- the-forge-dashboard: shared-cpu 1x, 1GB — Nginx serving React SPA
- the-forge-db: Fly.io managed Postgres HA with pgvector extension
- the-forge-redis: Fly.io managed Redis (Upstash)

Be direct, technical, and specific. You know this codebase intimately. When asked about costs, use \
AUD. When asked about deployment, give exact flyctl commands. When explaining the pipeline, reference \
specific file paths."""


async def _build_db_context(session: AsyncSession) -> str:
    """Query the database and return a formatted context string for the chat system prompt."""
    lines: list[str] = ["\n\nLIVE DATABASE CONTEXT (current state of The Forge):"]

    # Recent forge runs (last 10)
    try:
        runs_result = await session.execute(
            select(ForgeRun)
            .order_by(ForgeRun.created_at.desc())
            .limit(10)
        )
        runs = runs_result.scalars().all()
        total_runs_result = await session.execute(select(func.count(ForgeRun.run_id)))
        total_runs = total_runs_result.scalar_one()
        completed_runs = sum(1 for r in runs if r.status == "complete")

        lines.append(f"\nRecent Builds (showing last 10 of {total_runs} total):")
        if runs:
            for r in runs:
                duration = ""
                if r.status in ("complete", "failed"):
                    secs = (r.updated_at - r.created_at).total_seconds()
                    duration = f" [{int(secs // 60)}m {int(secs % 60)}s]"
                repo = f" → {r.repo_name}" if r.repo_name else ""
                lines.append(
                    f"  - [{r.status.upper()}] {r.title}{repo}{duration} "
                    f"({r.files_complete}/{r.file_count} files) [{r.created_at.strftime('%Y-%m-%d %H:%M')}]"
                )
        else:
            lines.append("  No builds yet.")
    except Exception as exc:
        logger.warning(f"Chat DB context: failed to query forge_runs: {exc}")
        lines.append("\nRecent Builds: (query failed)")

    # Registered agents
    try:
        agents_result = await session.execute(
            select(AgentRegistry).order_by(AgentRegistry.registered_at.desc())
        )
        agents = agents_result.scalars().all()
        lines.append(f"\nRegistered Agents ({len(agents)} total):")
        if agents:
            for a in agents:
                health = a.health_status or "unknown"
                lines.append(f"  - {a.agent_name} [{health}] {a.api_url}")
        else:
            lines.append("  None registered yet.")
    except Exception as exc:
        logger.warning(f"Chat DB context: failed to query agents_registry: {exc}")
        lines.append("\nRegistered Agents: (query failed)")

    # Recent updates (last 5)
    try:
        updates_result = await session.execute(
            select(ForgeUpdate)
            .order_by(ForgeUpdate.created_at.desc())
            .limit(5)
        )
        updates = updates_result.scalars().all()
        lines.append(f"\nRecent Updates (last 5):")
        if updates:
            for u in updates:
                lines.append(
                    f"  - [{u.status.upper()}] {u.title or u.repo_url} "
                    f"(+{u.files_created} ~{u.files_modified} -{u.files_deleted}) "
                    f"[{u.created_at.strftime('%Y-%m-%d %H:%M')}]"
                )
        else:
            lines.append("  No updates yet.")
    except Exception as exc:
        logger.warning(f"Chat DB context: failed to query forge_updates: {exc}")
        lines.append("\nRecent Updates: (query failed)")

    # KB records count
    try:
        kb_count_result = await session.execute(select(func.count(KbRecord.id)))
        kb_count = kb_count_result.scalar_one()
        lines.append(f"\nKnowledge Base: {kb_count} records stored")
    except Exception as exc:
        logger.warning(f"Chat DB context: failed to count kb_records: {exc}")

    # Latest performance metrics (most recent value per metric_name)
    try:
        metrics_result = await session.execute(
            select(PerformanceMetric)
            .order_by(PerformanceMetric.recorded_at.desc())
            .limit(20)
        )
        all_metrics = metrics_result.scalars().all()
        seen: set[str] = set()
        latest: list[PerformanceMetric] = []
        for m in all_metrics:
            if m.metric_name not in seen:
                seen.add(m.metric_name)
                latest.append(m)
        if latest:
            lines.append("\nLatest Performance Metrics:")
            for m in latest:
                lines.append(f"  - {m.metric_name}: {m.metric_value:.2f} [{m.recorded_at.strftime('%Y-%m-%d %H:%M')}]")
    except Exception as exc:
        logger.warning(f"Chat DB context: failed to query performance_metrics: {exc}")

    return "\n".join(lines)


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    memory_notes: Optional[str] = None
    files_context: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Proxy chat messages to Claude with Forge-specialist context and live DB state.
    """
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        db_context = await _build_db_context(session)

        system_parts = [FORGE_SYSTEM_PROMPT, db_context]
        if req.memory_notes and req.memory_notes.strip():
            system_parts.append(f"\n\nUSER MEMORY NOTES (always respect these):\n{req.memory_notes}")
        if req.files_context and req.files_context.strip():
            system_parts.append(f"\n\nUSER UPLOADED FILES (available for reference):\n{req.files_context}")
        system_prompt = "".join(system_parts)

        anthropic_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in req.messages
            if msg.role in ("user", "assistant")
        ]

        response = await client.messages.create(
            model=_CHAT_MODEL,
            max_tokens=800,
            system=system_prompt,
            messages=anthropic_messages,
        )

        reply = response.content[0].text if response.content else "No response."
        logger.info(
            f"Chat: model={_CHAT_MODEL} "
            f"input={response.usage.input_tokens} output={response.usage.output_tokens}"
        )

        return ChatResponse(reply=reply, model=_CHAT_MODEL)

    except Exception as exc:
        logger.error(f"Chat endpoint error: {exc}")
        return ChatResponse(reply=f"Chat error: {exc}", model=_CHAT_MODEL)
