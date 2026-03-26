"""
app/api/routes/chat.py
AI chat endpoint for the Forge command center dashboard.

POST /forge/chat — Claude Sonnet with full Forge context + tool use:
  - Live DB: recent builds with spec_json, file manifests, build logs
  - Knowledge base: semantic retrieval on user's question (pgvector)
  - Tool use: Claude can request actual file content from any build on demand
  - Memory notes and files context from the client

Tool use loop (max 5 iterations):
  1. Send message + tools to Claude
  2. If Claude calls get_file_content or search_file_content, execute against DB
  3. Return result to Claude, continue until stop_reason == "end_turn"
"""

import json
from typing import Optional, Any

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from memory.database import get_db
from memory.models import AgentRegistry, BuildLog, ForgeFile, ForgeRun, ForgeUpdate, KbRecord, PerformanceMetric

router = APIRouter()

_CHAT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4000
_MAX_TOOL_ITERATIONS = 5

# ── Tool definitions ──────────────────────────────────────────────────────────

FORGE_TOOLS = [
    {
        "name": "get_file_content",
        "description": (
            "Retrieve the complete source code content of a specific file from a Forge build. "
            "Use this when the user asks to see, review, explain, or debug a specific file. "
            "The run_id is shown in the build context above. "
            "Returns the full file content as a string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "The run_id of the build (UUID format, shown in LIVE FORGE CONTEXT above)"
                },
                "file_path": {
                    "type": "string",
                    "description": "The file path within the build (e.g. 'app/api/main.py', 'memory/models.py')"
                },
            },
            "required": ["run_id", "file_path"],
        },
    },
    {
        "name": "search_file_content",
        "description": (
            "Search across all generated files for code matching a pattern or keyword. "
            "Useful when the user asks 'where is X implemented', 'find all uses of Y', "
            "or 'which files contain Z'. Returns matching file paths and relevant excerpts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text pattern or keyword to search for in file contents"
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional: limit search to a specific build's run_id"
                },
            },
            "required": ["query"],
        },
    },
]

# ── Tool executors ────────────────────────────────────────────────────────────

async def _exec_get_file_content(run_id: str, file_path: str, session: AsyncSession) -> str:
    """Fetch a specific file's content from the DB."""
    try:
        result = await session.execute(
            select(ForgeFile).where(
                ForgeFile.run_id == run_id,
                ForgeFile.file_path == file_path,
            )
        )
        forge_file = result.scalar_one_or_none()
        if not forge_file:
            # Try partial path match
            result2 = await session.execute(
                select(ForgeFile).where(
                    ForgeFile.run_id == run_id,
                    ForgeFile.file_path.ilike(f"%{file_path.split('/')[-1]}%"),
                ).limit(3)
            )
            candidates = result2.scalars().all()
            if candidates:
                names = ", ".join(f.file_path for f in candidates)
                return f"File '{file_path}' not found. Similar files in this build: {names}"
            return f"File '{file_path}' not found in run {run_id}. Use the file_list from the build context to find the exact path."

        if not forge_file.content:
            return f"File '{file_path}' exists but has no stored content (may have been generated without content storage)."

        return (
            f"File: {forge_file.file_path}\n"
            f"Status: {forge_file.status}\n"
            f"Layer: {forge_file.layer}\n"
            f"Content:\n{forge_file.content}"
        )
    except Exception as exc:
        logger.warning(f"get_file_content failed: {exc}")
        return f"Error retrieving file content: {exc}"


async def _exec_search_file_content(query: str, run_id: Optional[str], session: AsyncSession) -> str:
    """Search file contents across builds for a pattern."""
    try:
        stmt = select(ForgeFile.run_id, ForgeFile.file_path, ForgeFile.content).where(
            ForgeFile.content.isnot(None),
            ForgeFile.content.ilike(f"%{query}%"),
        )
        if run_id:
            stmt = stmt.where(ForgeFile.run_id == run_id)
        stmt = stmt.limit(10)

        result = await session.execute(stmt)
        matches = result.all()

        if not matches:
            scope = f"run {run_id}" if run_id else "all builds"
            return f"No files found containing '{query}' in {scope}."

        lines = [f"Found {len(matches)} file(s) containing '{query}':\n"]
        for m_run_id, m_path, m_content in matches:
            # Find the matching lines
            excerpt_lines = []
            for i, line in enumerate(m_content.splitlines()):
                if query.lower() in line.lower():
                    start = max(0, i - 1)
                    end = min(len(m_content.splitlines()), i + 3)
                    excerpt_lines = m_content.splitlines()[start:end]
                    break
            excerpt = "\n".join(excerpt_lines)[:300]
            lines.append(f"── {m_path} (run: {m_run_id[:8]}...)\n{excerpt}\n")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning(f"search_file_content failed: {exc}")
        return f"Error searching file content: {exc}"


async def _execute_tool(name: str, tool_input: dict[str, Any], session: AsyncSession) -> str:
    """Dispatch tool call to the appropriate executor."""
    if name == "get_file_content":
        return await _exec_get_file_content(
            tool_input.get("run_id", ""),
            tool_input.get("file_path", ""),
            session,
        )
    if name == "search_file_content":
        return await _exec_search_file_content(
            tool_input.get("query", ""),
            tool_input.get("run_id"),
            session,
        )
    return f"Unknown tool: {name}"

# ── DB context builder ────────────────────────────────────────────────────────

FORGE_SYSTEM_PROMPT = """You are The Forge's AI assistant — a deep specialist in The Forge AI build engine \
and the full The Office agent portfolio. You help Jackson Khoury (Sydney, Australia) build, deploy, \
debug, and improve AI agents.

You have two powerful capabilities:
1. The full live state of The Forge is injected below — every build, spec, file manifest, build logs
2. You have tools to fetch the actual source code of any file from any build on demand

When the user asks about specific file contents, implementation details, or code — use get_file_content \
to pull the exact code and reference it directly in your answer. When searching for where something is \
implemented across builds, use search_file_content.

THE FORGE ARCHITECTURE:
- 7-stage build pipeline: Validate → Parse → Confirm → Architecture → Generate (6 layers) → Recovery → Build QA → Package → GitHub Push → Notify
- FastAPI + Python 3.12 backend at https://the-forge-api.fly.dev
- React + Vite + Tailwind dashboard at https://the-forge-dashboard-v8.fly.dev
- RQ workers for background builds (15-25 minutes per build)
- PostgreSQL + pgvector for storage and semantic retrieval
- Claude Opus 4.6 for spec parsing, Sonnet 4.6 for code generation and chat
- OpenAI text-embedding-3-small for KB embeddings, Tavily for web search

6 CODE GENERATION LAYERS:
1. Database Schema — SQLAlchemy models, database.py
2. Infrastructure — requirements.txt, docker-compose, Dockerfiles, .env.example
3. Backend API — FastAPI routes, services, middleware, auth
4. Worker/Agent Logic — RQ workers, pipeline nodes, background processors
5. Web Dashboard — React JSX, Tailwind, API client (served as static files from API)
6. Deployment — fly.toml (API + worker only, --ha=false), GitHub Actions deploy.yml

INTELLIGENCE LAYER (all 7 files in every generated agent):
- config/model_config.py — routes Claude calls, reduces API cost 35-40%
- intelligence/knowledge_base.py — stores outcomes, retrieves via pgvector
- intelligence/meta_rules.py — weekly job extracts operational rules, auto-updates prompts
- intelligence/context_assembler.py — assembles optimal context before every Claude call
- intelligence/evaluator.py — scores every output against domain rubric
- intelligence/verifier.py — independent adversarial Claude review
- monitoring/performance_monitor.py — tracks 5 KPIs every 6h, detects 15%+ degradation

KNOWLEDGE BASE (8 domains, continuously updated):
- fastapi_python — FastAPI, Pydantic v2, SQLAlchemy 2.0 patterns
- fly_io_deployment — Fly.io, Docker, GitHub Actions, production config
- rq_redis — RQ, background jobs, APScheduler
- react_vite — React 18, Vite, Tailwind CSS
- claude_api — Anthropic API, prompt engineering, tool use
- pgvector_postgres — pgvector, vector similarity search, embeddings
- build_issues — code generation failures, import errors, deployment fixes
- ai_agent_market — who buys agents, competitor pricing, market demand by industry

FLY.IO INFRASTRUCTURE:
- the-forge-api: shared-cpu-4x, 2GB, min_machines_running=1
- the-forge-worker: shared-cpu-4x, 4GB (runs APScheduler internally — no separate scheduler)
- the-forge-dashboard-v8: shared-cpu-1x, 512MB
- the-forge-db: Fly.io managed Postgres (SHARED across all agents — each agent gets own database)
- the-forge-redis: Fly.io managed Redis

THE OFFICE PORTFOLIO:
1. The Forge — AI build engine, blueprint → deployable codebase in 15-25 min
2. BuildRight — Sydney construction lead machine (22 modules)
3. Trading OS — autonomous trading for prop firm accounts (FTMO A$100k)
4. ARIA — research intelligence, 12 domains
5. The Office — unified command center above all agents

Be direct, technical, and specific. Reference exact file paths and run IDs. Use AUD for costs."""


async def _build_db_context(session: AsyncSession, user_message: str) -> str:
    """
    Build rich DB context: recent builds with specs + file manifests + logs,
    KB semantic search, registered agents, performance metrics.
    """
    lines: list[str] = ["\n\n═══ LIVE FORGE CONTEXT ═══"]

    # ── Recent builds ─────────────────────────────────────────────────────────
    try:
        runs_result = await session.execute(
            select(ForgeRun).order_by(ForgeRun.created_at.desc()).limit(8)
        )
        runs = runs_result.scalars().all()
        total_result = await session.execute(select(func.count(ForgeRun.run_id)))
        total_runs = total_result.scalar_one()

        lines.append(f"\n── BUILDS ({total_runs} total, showing last {len(runs)}) ──")
        for r in runs:
            duration_str = ""
            if r.updated_at and r.created_at:
                secs = (r.updated_at - r.created_at).total_seconds()
                duration_str = f" [{int(secs // 60)}m{int(secs % 60)}s]"
            repo_str = f" → github:{r.repo_name}" if r.repo_name else ""
            lines.append(
                f"\n[{r.status.upper()}] {r.title}{repo_str}{duration_str}"
                f"\n  run_id: {r.run_id}"
                f"\n  files: {r.files_complete}/{r.file_count}"
                f"\n  created: {r.created_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )

            if r.spec_json and isinstance(r.spec_json, dict):
                spec = r.spec_json
                if spec.get("description"):
                    lines.append(f"  description: {spec['description'][:200]}")
                tables = spec.get("database_tables", [])
                routes = spec.get("api_routes", [])
                services = spec.get("fly_services", [])
                if tables:
                    names = [t.get("name", t) if isinstance(t, dict) else str(t) for t in tables[:12]]
                    lines.append(f"  db_tables: {', '.join(names)}")
                if routes:
                    rnames = [
                        f"{r2.get('method','?')} {r2.get('path','?')}" if isinstance(r2, dict) else str(r2)
                        for r2 in routes[:15]
                    ]
                    lines.append(f"  api_routes: {', '.join(rnames)}")
                if services:
                    snames = [s.get("name", s) if isinstance(s, dict) else str(s) for s in services]
                    lines.append(f"  fly_services: {', '.join(snames)}")

            # File manifest (paths only)
            try:
                files_result = await session.execute(
                    select(ForgeFile.file_path, ForgeFile.status, ForgeFile.layer)
                    .where(ForgeFile.run_id == r.run_id)
                    .order_by(ForgeFile.layer, ForgeFile.file_path)
                )
                files = files_result.all()
                if files:
                    ok = sum(1 for f in files if f.status == "complete")
                    paths = [f.file_path for f in files[:50]]
                    lines.append(f"  file_manifest ({ok}/{len(files)} complete): {', '.join(paths)}")
                    if len(files) > 50:
                        lines.append(f"    ... and {len(files) - 50} more")
            except Exception:
                pass

            # Recent build logs
            try:
                logs_result = await session.execute(
                    select(BuildLog.stage, BuildLog.message, BuildLog.level)
                    .where(BuildLog.run_id == r.run_id)
                    .order_by(BuildLog.created_at.desc())
                    .limit(8)
                )
                logs = list(reversed(logs_result.all()))
                if logs:
                    lines.append("  pipeline_logs:")
                    for log in logs:
                        prefix = "⚠" if log.level == "WARNING" else "✗" if log.level == "ERROR" else "·"
                        lines.append(f"    {prefix} [{log.stage}] {log.message[:120]}")
            except Exception:
                pass

    except Exception as exc:
        logger.warning(f"Chat context: runs query failed: {exc}")

    # ── Registered agents ─────────────────────────────────────────────────────
    try:
        agents_result = await session.execute(
            select(AgentRegistry).order_by(AgentRegistry.registered_at.desc())
        )
        agents = agents_result.scalars().all()
        lines.append(f"\n── REGISTERED AGENTS ({len(agents)}) ──")
        for a in agents:
            lines.append(f"  {a.agent_name} [{a.health_status or 'unknown'}] {a.api_url}")
        if not agents:
            lines.append("  None registered yet.")
    except Exception as exc:
        logger.warning(f"Chat context: agents query failed: {exc}")

    # ── Recent updates ────────────────────────────────────────────────────────
    try:
        updates_result = await session.execute(
            select(ForgeUpdate).order_by(ForgeUpdate.created_at.desc()).limit(5)
        )
        updates = updates_result.scalars().all()
        if updates:
            lines.append(f"\n── RECENT UPGRADES ──")
            for u in updates:
                lines.append(
                    f"  [{u.status.upper()}] {u.title or u.repo_url} "
                    f"(+{u.files_created} ~{u.files_modified}) "
                    f"[{u.created_at.strftime('%Y-%m-%d %H:%M')}]"
                )
    except Exception as exc:
        logger.warning(f"Chat context: updates query failed: {exc}")

    # ── KB semantic search ────────────────────────────────────────────────────
    try:
        from knowledge.retriever import retrieve_relevant_chunks
        kb_chunks = await retrieve_relevant_chunks(user_message, top_k=6)
        kb_count_result = await session.execute(select(func.count(KbRecord.id)))
        kb_count = kb_count_result.scalar_one()
        lines.append(f"\n── KNOWLEDGE BASE ({kb_count} records) — Most relevant to this question ──")
        if kb_chunks:
            for i, chunk in enumerate(kb_chunks, 1):
                lines.append(f"  [{i}] {chunk[:300]}")
        else:
            lines.append("  (KB empty or retrieval unavailable)")
    except Exception as exc:
        logger.warning(f"Chat context: KB retrieval failed: {exc}")

    # ── Performance metrics ───────────────────────────────────────────────────
    try:
        metrics_result = await session.execute(
            select(PerformanceMetric).order_by(PerformanceMetric.recorded_at.desc()).limit(20)
        )
        all_metrics = metrics_result.scalars().all()
        seen: set[str] = set()
        latest = []
        for m in all_metrics:
            if m.metric_name not in seen:
                seen.add(m.metric_name)
                latest.append(m)
        if latest:
            lines.append("\n── PERFORMANCE METRICS ──")
            for m in latest:
                lines.append(f"  {m.metric_name}: {m.metric_value:.2f} [{m.recorded_at.strftime('%Y-%m-%d %H:%M')}]")
    except Exception as exc:
        logger.warning(f"Chat context: metrics query failed: {exc}")

    lines.append("\n═══════════════════════════")
    lines.append("\nTo see file content, use the get_file_content tool with the run_id and file_path shown above.")
    return "\n".join(lines)


# ── Request / Response models ─────────────────────────────────────────────────

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
    tool_calls_made: int = 0


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Chat with Claude Sonnet — full Forge context + tool use for live file content.
    """
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        last_user_msg = next(
            (m.content for m in reversed(req.messages) if m.role == "user"), ""
        )
        db_context = await _build_db_context(session, last_user_msg)

        system_parts = [FORGE_SYSTEM_PROMPT, db_context]
        if req.memory_notes and req.memory_notes.strip():
            system_parts.append(f"\n\nUSER MEMORY NOTES (always respect these):\n{req.memory_notes}")
        if req.files_context and req.files_context.strip():
            system_parts.append(f"\n\nUSER UPLOADED FILES:\n{req.files_context}")
        system_prompt = "".join(system_parts)

        # Build message list for Anthropic (tool use loop extends this)
        messages: list[dict] = [
            {"role": msg.role, "content": msg.content}
            for msg in req.messages
            if msg.role in ("user", "assistant")
        ]

        tool_calls_made = 0
        reply = ""

        for iteration in range(_MAX_TOOL_ITERATIONS + 1):
            response = await client.messages.create(
                model=_CHAT_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=FORGE_TOOLS,
            )

            logger.info(
                f"Chat iter {iteration}: stop_reason={response.stop_reason} "
                f"input={response.usage.input_tokens} output={response.usage.output_tokens}"
            )

            if response.stop_reason == "end_turn":
                # Final response — extract text
                reply = next(
                    (block.text for block in response.content if hasattr(block, "text")),
                    "No response."
                )
                break

            if response.stop_reason == "tool_use":
                if iteration >= _MAX_TOOL_ITERATIONS:
                    # Safety cap — extract whatever text Claude has so far
                    reply = next(
                        (block.text for block in response.content if hasattr(block, "text")),
                        "Reached tool call limit."
                    )
                    break

                # Execute all requested tools
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_calls_made += 1
                        logger.info(f"Chat tool call: {block.name}({block.input})")
                        result = await _execute_tool(block.name, block.input, session)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Append assistant turn + tool results and continue loop
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                reply = next(
                    (block.text for block in response.content if hasattr(block, "text")),
                    f"Stopped: {response.stop_reason}"
                )
                break

        if not reply:
            reply = "I couldn't generate a response. Please try again."

        return ChatResponse(reply=reply, model=_CHAT_MODEL, tool_calls_made=tool_calls_made)

    except Exception as exc:
        logger.error(f"Chat endpoint error: {exc}")
        return ChatResponse(reply=f"Chat error: {exc}", model=_CHAT_MODEL)


# ── Streaming chat endpoint ────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Streaming chat — emits SSE events as Claude responds.

    Event types:
      {"type": "start"}                                   — context built, first call starting
      {"type": "text_delta", "text": "..."}               — token from Claude
      {"type": "tool_use", "name": "...", "input": {...}} — Claude calling a tool
      {"type": "tool_result", "name": "..."}              — tool execution complete
      {"type": "done", "tool_calls_made": N}              — finished
      {"type": "error", "message": "..."}                 — something failed
    """
    async def generate():
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            last_user_msg = next(
                (m.content for m in reversed(req.messages) if m.role == "user"), ""
            )
            db_context = await _build_db_context(session, last_user_msg)

            system_parts = [FORGE_SYSTEM_PROMPT, db_context]
            if req.memory_notes and req.memory_notes.strip():
                system_parts.append(f"\n\nUSER MEMORY NOTES (always respect these):\n{req.memory_notes}")
            if req.files_context and req.files_context.strip():
                system_parts.append(f"\n\nUSER UPLOADED FILES:\n{req.files_context}")
            system_prompt = "".join(system_parts)

            messages: list[dict] = [
                {"role": msg.role, "content": msg.content}
                for msg in req.messages
                if msg.role in ("user", "assistant")
            ]

            tool_calls_made = 0
            yield f"data: {json.dumps({'type': 'start'})}\n\n"

            for iteration in range(_MAX_TOOL_ITERATIONS + 1):
                async with client.messages.stream(
                    model=_CHAT_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=system_prompt,
                    messages=messages,
                    tools=FORGE_TOOLS,
                ) as stream:
                    # Stream text tokens to the frontend in real time
                    async for text in stream.text_stream:
                        yield f"data: {json.dumps({'type': 'text_delta', 'text': text})}\n\n"

                    final_message = await stream.get_final_message()

                logger.info(
                    f"Chat stream iter {iteration}: stop_reason={final_message.stop_reason} "
                    f"input={final_message.usage.input_tokens} output={final_message.usage.output_tokens}"
                )

                if final_message.stop_reason == "end_turn":
                    break

                if final_message.stop_reason == "tool_use":
                    if iteration >= _MAX_TOOL_ITERATIONS:
                        break

                    tool_results = []
                    for block in final_message.content:
                        if block.type == "tool_use":
                            tool_calls_made += 1
                            yield f"data: {json.dumps({'type': 'tool_use', 'name': block.name, 'input': block.input})}\n\n"
                            result = await _execute_tool(block.name, block.input, session)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            })
                            yield f"data: {json.dumps({'type': 'tool_result', 'name': block.name})}\n\n"

                    messages.append({
                        "role": "assistant",
                        "content": [b.model_dump() for b in final_message.content],
                    })
                    messages.append({"role": "user", "content": tool_results})
                else:
                    break

            yield f"data: {json.dumps({'type': 'done', 'tool_calls_made': tool_calls_made})}\n\n"

        except Exception as exc:
            logger.error(f"Chat stream error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
