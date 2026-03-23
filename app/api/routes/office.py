"""
app/api/routes/office.py
The Office integration endpoints for The Forge.

These endpoints are called by Agent 5 (The Office) to trigger builds/updates
programmatically and to register deployed agents in the central registry.

POST /forge/webhook/build    — trigger a new agent build from a blueprint
POST /forge/webhook/update   — trigger a targeted codebase update
POST /forge/register-agent   — register a deployed agent in the registry
GET  /forge/agents           — list all registered agents with live health status
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from memory.database import get_db
from memory.models import AgentRegistry, ForgeFile, ForgeRun, ForgeUpdate, RunStatus
from pipeline.pipeline import run_pipeline_sync

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class WebhookBuildRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    blueprint_text: str = Field(..., min_length=50)
    repo_name: Optional[str] = None
    push_to_github: bool = True
    callback_url: Optional[str] = None


class WebhookBuildResponse(BaseModel):
    run_id: str
    status: str


class WebhookUpdateRequest(BaseModel):
    github_repo_url: str = Field(..., min_length=1, max_length=500)
    change_description: str = Field(..., min_length=10)
    callback_url: Optional[str] = None


class WebhookUpdateResponse(BaseModel):
    update_id: str
    status: str


class RegisterAgentRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=255)
    api_url: str = Field(..., min_length=1, max_length=500)
    dashboard_url: Optional[str] = None
    health_url: Optional[str] = None
    repo_url: Optional[str] = None


class RegisterAgentResponse(BaseModel):
    agent_id: str
    agent_name: str
    registered: bool


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/webhook/build", response_model=WebhookBuildResponse)
async def webhook_build(
    request: WebhookBuildRequest,
    session: AsyncSession = Depends(get_db),
) -> WebhookBuildResponse:
    """
    Trigger a new agent build from a blueprint. Called by The Office.
    Creates a ForgeRun with callback_url, queues the build pipeline.
    The callback_url will receive a POST when the build completes or fails.
    """
    from app.api.main import get_build_queue
    import re

    run_id = str(uuid.uuid4())

    def _slug(title: str) -> str:
        s = title.lower().strip()
        s = re.sub(r"[^a-z0-9\s-]", "", s)
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"-+", "-", s)
        return s.strip("-")[:100] or "forge-build"

    resolved_repo_name = request.repo_name or _slug(request.title)

    run = ForgeRun(
        run_id=run_id,
        title=request.title,
        blueprint_text=request.blueprint_text,
        status=RunStatus.QUEUED.value,
        repo_name=resolved_repo_name,
        push_to_github=request.push_to_github,
        callback_url=request.callback_url,
    )
    session.add(run)
    await session.commit()

    try:
        queue = get_build_queue()
        queue.enqueue(
            run_pipeline_sync,
            run_id,
            job_id=f"build-{run_id}",
            job_timeout=3600,
        )
        logger.info(
            f"[office] Webhook build queued: run_id={run_id} "
            f"title='{request.title}' callback={request.callback_url}"
        )
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        run.error_message = f"Failed to queue build: {exc}"
        await session.commit()
        logger.error(f"[office] Failed to queue webhook build {run_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to queue build: {exc}")

    return WebhookBuildResponse(run_id=run_id, status=RunStatus.QUEUED.value)


@router.post("/webhook/update", response_model=WebhookUpdateResponse)
async def webhook_update(
    request: WebhookUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> WebhookUpdateResponse:
    """
    Trigger a targeted codebase update on an existing GitHub repository.
    Called by The Office. Creates a ForgeUpdate with callback_url, queues update pipeline.
    The callback_url will receive a POST when the update completes or fails.
    """
    from app.api.main import get_build_queue
    from pipeline.update_pipeline import run_update_pipeline_sync

    update_id = str(uuid.uuid4())

    forge_update = ForgeUpdate(
        update_id=update_id,
        repo_url=request.github_repo_url,
        change_description=request.change_description,
        title=f"Update: {request.github_repo_url.split('/')[-1]}",
        status="queued",
        callback_url=request.callback_url,
    )
    session.add(forge_update)
    await session.commit()

    try:
        queue = get_build_queue()
        queue.enqueue(
            run_update_pipeline_sync,
            update_id,
            job_id=f"update-{update_id}",
            job_timeout=3600,
        )
        logger.info(
            f"[office] Webhook update queued: update_id={update_id} "
            f"repo={request.github_repo_url} callback={request.callback_url}"
        )
    except Exception as exc:
        forge_update.status = "failed"
        forge_update.error_message = f"Failed to queue update: {exc}"
        await session.commit()
        logger.error(f"[office] Failed to queue webhook update {update_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to queue update: {exc}")

    return WebhookUpdateResponse(update_id=update_id, status="queued")


@router.post("/register-agent", response_model=RegisterAgentResponse)
async def register_agent(
    request: RegisterAgentRequest,
    session: AsyncSession = Depends(get_db),
) -> RegisterAgentResponse:
    """
    Register a deployed agent in the central agents_registry table.
    Upserts by api_url — re-registering an existing agent updates its metadata.
    If OFFICE_WEBHOOK_URL is configured, notifies The Office of the new registration.
    """
    # Check for existing registration by api_url
    existing_result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.api_url == request.api_url)
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.agent_name = request.agent_name
        existing.dashboard_url = request.dashboard_url
        existing.health_url = request.health_url
        existing.repo_url = request.repo_url
        agent_id = existing.agent_id
        logger.info(
            f"[office] Agent re-registered: agent_id={agent_id} "
            f"name='{request.agent_name}' url={request.api_url}"
        )
    else:
        agent_id = str(uuid.uuid4())
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_name=request.agent_name,
            api_url=request.api_url,
            dashboard_url=request.dashboard_url,
            health_url=request.health_url,
            repo_url=request.repo_url,
        )
        session.add(agent)
        logger.info(
            f"[office] New agent registered: agent_id={agent_id} "
            f"name='{request.agent_name}' url={request.api_url}"
        )

    await session.commit()

    # Notify The Office if webhook URL is configured
    if settings.office_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    settings.office_webhook_url,
                    json={
                        "event": "agent_registered",
                        "agent_id": agent_id,
                        "agent_name": request.agent_name,
                        "api_url": request.api_url,
                        "dashboard_url": request.dashboard_url,
                        "health_url": request.health_url,
                        "repo_url": request.repo_url,
                    },
                )
                resp.raise_for_status()
                logger.info(
                    f"[office] Registration event sent to Office: {settings.office_webhook_url}"
                )
        except Exception as exc:
            logger.error(
                f"[office] Failed to notify Office of agent registration (non-blocking): {exc}"
            )

    return RegisterAgentResponse(
        agent_id=agent_id,
        agent_name=request.agent_name,
        registered=True,
    )


@router.get("/agents")
async def list_agents(
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    List all registered agents. For each agent with a health_url, performs
    a live health check (3s timeout) and includes the result in the response.
    Updates the health_status and last_health_check columns in DB.
    """
    result = await session.execute(
        select(AgentRegistry).order_by(AgentRegistry.registered_at)
    )
    agents = result.scalars().all()

    if not agents:
        return []

    # Run health checks concurrently
    import asyncio

    async def _check_health(agent: AgentRegistry) -> dict:
        health_status = agent.health_status or "unknown"
        last_check = agent.last_health_check

        if agent.health_url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(agent.health_url)
                    if resp.status_code < 400:
                        health_status = "healthy"
                    else:
                        health_status = "degraded"
            except Exception as exc:
                health_status = "unreachable"
                logger.debug(
                    f"[office] Health check failed for {agent.agent_name} "
                    f"({agent.health_url}): {exc}"
                )

            last_check = datetime.now(timezone.utc)

            # Persist updated health status
            try:
                from sqlalchemy import update as sa_update
                await session.execute(
                    sa_update(AgentRegistry)
                    .where(AgentRegistry.agent_id == agent.agent_id)
                    .values(
                        health_status=health_status,
                        last_health_check=last_check,
                    )
                )
            except Exception as db_exc:
                logger.error(
                    f"[office] Failed to persist health status for "
                    f"{agent.agent_name}: {db_exc}"
                )

        return {
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "api_url": agent.api_url,
            "dashboard_url": agent.dashboard_url,
            "health_url": agent.health_url,
            "repo_url": agent.repo_url,
            "health_status": health_status,
            "last_health_check": last_check.isoformat() if last_check else None,
            "registered_at": agent.registered_at.isoformat() if agent.registered_at else None,
        }

    results = await asyncio.gather(*[_check_health(a) for a in agents])

    try:
        await session.commit()
    except Exception as commit_exc:
        logger.error(f"[office] Failed to commit health status updates: {commit_exc}")

    return list(results)


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_db)) -> dict:
    """
    Aggregate statistics for The Forge dashboard overview.
    Returns total_builds, successful_builds, total_files_generated, total_agents_registered.
    """
    total_builds_result = await session.execute(select(func.count(ForgeRun.run_id)))
    total_builds = total_builds_result.scalar_one()

    successful_builds_result = await session.execute(
        select(func.count(ForgeRun.run_id)).where(ForgeRun.status == "complete")
    )
    successful_builds = successful_builds_result.scalar_one()

    total_files_result = await session.execute(select(func.count(ForgeFile.file_id)))
    total_files = total_files_result.scalar_one()

    total_agents_result = await session.execute(select(func.count(AgentRegistry.agent_id)))
    total_agents = total_agents_result.scalar_one()

    return {
        "total_builds": total_builds,
        "successful_builds": successful_builds,
        "total_files_generated": total_files,
        "total_agents_registered": total_agents,
    }
