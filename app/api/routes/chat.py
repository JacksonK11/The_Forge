"""
app/api/routes/chat.py
AI chat endpoint for the Forge command center dashboard.

POST /forge/chat — proxies messages to GPT-4o with a Forge-specialist system prompt.
Uses OpenAI so chat capacity is completely separate from the Anthropic quota used
by the build pipeline (Claude Opus/Sonnet/Haiku for code generation).
The frontend passes its localStorage memory notes and uploaded file metadata
so the AI has full context of the user's workspace.
"""

from typing import Optional

from fastapi import APIRouter
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

from config.settings import settings

router = APIRouter()

# GPT-4o: OpenAI's flagship model — 128k context, best reasoning, fast response.
# Separate quota from Anthropic so chat never impacts build pipeline capacity.
_CHAT_MODEL = "gpt-4o-mini"

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
- OpenAI GPT-4o for this chat interface (separate quota from build pipeline)
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
- GET /forge/runs/{id}/package — download generated ZIP
- POST /forge/runs/{id}/approve — approve parsed spec to start code generation
- POST /forge/register-agent — register a deployed agent in the registry
- GET /forge/agents — all registered agents with health status
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
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Proxy chat messages to GPT-4o with Forge-specialist context.
    Uses OpenAI quota — completely isolated from the Anthropic build pipeline.
    """
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Build dynamic system prompt with user context
        system_parts = [FORGE_SYSTEM_PROMPT]
        if req.memory_notes and req.memory_notes.strip():
            system_parts.append(
                f"\n\nUSER MEMORY NOTES (always respect these):\n{req.memory_notes}"
            )
        if req.files_context and req.files_context.strip():
            system_parts.append(
                f"\n\nUSER UPLOADED FILES (available for reference):\n{req.files_context}"
            )
        system_prompt = "".join(system_parts)

        messages = [{"role": "system", "content": system_prompt}]
        for msg in req.messages:
            if msg.role in ("user", "assistant"):
                messages.append({"role": msg.role, "content": msg.content})

        response = await client.chat.completions.create(
            model=_CHAT_MODEL,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
        )

        reply = response.choices[0].message.content or "No response."
        logger.info(
            f"Chat: model={_CHAT_MODEL} "
            f"input={response.usage.prompt_tokens} output={response.usage.completion_tokens}"
        )

        return ChatResponse(reply=reply, model=_CHAT_MODEL)

    except Exception as exc:
        logger.error(f"Chat endpoint error: {exc}")
        return ChatResponse(
            reply=f"Chat error: {exc}",
            model=_CHAT_MODEL,
        )
