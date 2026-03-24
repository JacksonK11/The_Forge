"""
app/api/routes/runs.py
Run status and file retrieval routes.

GET /forge/runs                     — list all runs (paginated)
GET /forge/runs/{id}                — run detail with status and progress
GET /forge/runs/{id}/files          — all generated files for a run
GET /forge/runs/{id}/spec           — parsed spec JSON
GET /forge/runs/{id}/logs           — structured per-stage build logs
GET /forge/runs/{id}/cost           — token usage and cost breakdown
GET /forge/runs/{id}/versions       — version history for this agent
GET /forge/queue                    — current queue status (queued / in-progress / recent)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memory.database import get_db
from memory.models import BuildCost, BuildLog, BuildVersion, ForgeFile, ForgeRun

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class RunSummary(BaseModel):
    run_id: str
    title: str
    status: str
    file_count: int
    files_complete: int
    files_failed: int
    repo_name: Optional[str]
    github_repo_url: Optional[str]
    blueprint_text: Optional[str]
    duration_seconds: Optional[float]
    package_ready: bool
    created_at: str
    updated_at: str


class RunDetail(BaseModel):
    run_id: str
    title: str
    status: str
    spec_json: Optional[dict]
    manifest_json: Optional[dict]
    error_message: Optional[str]
    file_count: int
    files_complete: int
    files_failed: int
    repo_name: Optional[str]
    github_repo_url: Optional[str]
    blueprint_text: Optional[str]
    push_to_github: bool
    github_push_status: Optional[str]
    duration_seconds: Optional[float]
    package_ready: bool
    created_at: str
    updated_at: str


class FileDetail(BaseModel):
    file_id: str
    file_path: str
    layer: int
    purpose: Optional[str]
    status: str
    content: Optional[str]
    token_count: Optional[int]
    error_message: Optional[str]


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int
    page: int
    page_size: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=RunListResponse)
async def list_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> RunListResponse:
    """List all forge runs, newest first. Optional status filter."""
    query = select(ForgeRun).order_by(ForgeRun.created_at.desc())
    count_query = select(func.count(ForgeRun.run_id))

    if status:
        query = query.where(ForgeRun.status == status)
        count_query = count_query.where(ForgeRun.status == status)

    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    runs = result.scalars().all()

    return RunListResponse(
        runs=[
            RunSummary(
                run_id=r.run_id,
                title=r.title,
                status=r.status,
                file_count=r.file_count,
                files_complete=r.files_complete,
                files_failed=r.files_failed,
                repo_name=r.repo_name,
                github_repo_url=r.github_repo_url,
                blueprint_text=r.blueprint_text,
                duration_seconds=(
                    (r.updated_at - r.created_at).total_seconds()
                    if r.status in ("complete", "failed") else None
                ),
                package_ready=bool(r.package_data or r.package_path),
                created_at=r.created_at.isoformat(),
                updated_at=r.updated_at.isoformat(),
            )
            for r in runs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> RunDetail:
    """Get full run detail including spec JSON and progress counters."""
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunDetail(
        run_id=run.run_id,
        title=run.title,
        status=run.status,
        spec_json=run.spec_json,
        manifest_json=run.manifest_json,
        error_message=run.error_message,
        file_count=run.file_count,
        files_complete=run.files_complete,
        files_failed=run.files_failed,
        repo_name=run.repo_name,
        github_repo_url=run.github_repo_url,
        blueprint_text=run.blueprint_text,
        push_to_github=run.push_to_github,
        github_push_status=run.github_push_status,
        duration_seconds=(
            (run.updated_at - run.created_at).total_seconds()
            if run.status in ("complete", "failed") else None
        ),
        package_ready=bool(run.package_data or run.package_path),
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
    )


@router.get("/{run_id}/files", response_model=list[FileDetail])
async def get_run_files(
    run_id: str,
    include_content: bool = Query(default=False),
    layer: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[FileDetail]:
    """
    List all files generated for a run.
    Set include_content=true to include full file contents (large response).
    Optionally filter by layer (1-7).
    """
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    query = (
        select(ForgeFile)
        .where(ForgeFile.run_id == run_id)
        .order_by(ForgeFile.layer, ForgeFile.file_path)
    )
    if layer is not None:
        query = query.where(ForgeFile.layer == layer)

    result = await session.execute(query)
    files = result.scalars().all()

    return [
        FileDetail(
            file_id=f.file_id,
            file_path=f.file_path,
            layer=f.layer,
            purpose=f.purpose,
            status=f.status,
            content=f.content if include_content else None,
            token_count=f.token_count,
            error_message=f.error_message,
        )
        for f in files
    ]


@router.get("/{run_id}/files/{file_path:path}", response_model=FileDetail)
async def get_file_content(
    run_id: str,
    file_path: str,
    session: AsyncSession = Depends(get_db),
) -> FileDetail:
    """Get full content of a single generated file."""
    result = await session.execute(
        select(ForgeFile).where(
            ForgeFile.run_id == run_id, ForgeFile.file_path == file_path
        )
    )
    forge_file = result.scalar_one_or_none()
    if not forge_file:
        raise HTTPException(status_code=404, detail="File not found")

    return FileDetail(
        file_id=forge_file.file_id,
        file_path=forge_file.file_path,
        layer=forge_file.layer,
        purpose=forge_file.purpose,
        status=forge_file.status,
        content=forge_file.content,
        token_count=forge_file.token_count,
        error_message=forge_file.error_message,
    )


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    stage: Optional[str] = Query(default=None),
    level: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Get structured build logs for a run, optionally filtered by stage or level.
    Used by the Results tab log viewer.
    """
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    query = (
        select(BuildLog)
        .where(BuildLog.run_id == run_id)
        .order_by(BuildLog.created_at.asc())
        .limit(limit)
    )
    if stage:
        query = query.where(BuildLog.stage == stage)
    if level:
        query = query.where(BuildLog.level == level.upper())

    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "stage": log.stage,
            "message": log.message,
            "level": log.level,
            "details": log.details_json,
            "duration_ms": log.duration_ms,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/{run_id}/cost")
async def get_run_cost(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get full token usage and cost breakdown for a build.
    Shows per-model, per-stage breakdown plus totals in USD and AUD.
    """
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(BuildCost)
        .where(BuildCost.run_id == run_id)
        .order_by(BuildCost.created_at.asc())
    )
    costs = result.scalars().all()

    total_usd = sum(c.cost_usd for c in costs)
    total_aud = sum(c.cost_aud for c in costs)
    total_input = sum(c.input_tokens for c in costs)
    total_output = sum(c.output_tokens for c in costs)

    by_model: dict[str, dict] = {}
    by_stage: dict[str, dict] = {}
    for c in costs:
        m = c.model
        s = c.stage
        if m not in by_model:
            by_model[m] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_aud": 0.0}
        by_model[m]["calls"] += 1
        by_model[m]["input_tokens"] += c.input_tokens
        by_model[m]["output_tokens"] += c.output_tokens
        by_model[m]["cost_usd"] += c.cost_usd
        by_model[m]["cost_aud"] += c.cost_aud

        if s not in by_stage:
            by_stage[s] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_aud": 0.0}
        by_stage[s]["calls"] += 1
        by_stage[s]["input_tokens"] += c.input_tokens
        by_stage[s]["output_tokens"] += c.output_tokens
        by_stage[s]["cost_usd"] += c.cost_usd
        by_stage[s]["cost_aud"] += c.cost_aud

    return {
        "run_id": run_id,
        "total_cost_usd": round(total_usd, 4),
        "total_cost_aud": round(total_aud, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_calls": len(costs),
        "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 4), "cost_aud": round(v["cost_aud"], 4)} for k, v in by_model.items()},
        "by_stage": {k: {**v, "cost_usd": round(v["cost_usd"], 4), "cost_aud": round(v["cost_aud"], 4)} for k, v in by_stage.items()},
        "line_items": [
            {
                "stage": c.stage,
                "model": c.model,
                "task_type": c.task_type,
                "file_path": c.file_path,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cost_usd": round(c.cost_usd, 5),
                "cost_aud": round(c.cost_aud, 5),
                "created_at": c.created_at.isoformat(),
            }
            for c in costs
        ],
    }


@router.get("/{run_id}/versions")
async def get_run_versions(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Get all version tags for the agent built in this run.
    Returns version history so any version can be identified for rollback.
    """
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    agent_slug = (run.spec_json or {}).get("agent_slug") if run.spec_json else None

    query = select(BuildVersion).order_by(desc(BuildVersion.created_at))
    if agent_slug:
        query = query.where(BuildVersion.agent_slug == agent_slug)
    else:
        query = query.where(BuildVersion.run_id == run_id)

    result = await session.execute(query.limit(50))
    versions = result.scalars().all()

    return [
        {
            "id": v.id,
            "run_id": v.run_id,
            "version_tag": v.version_tag,
            "is_latest": v.is_latest,
            "agent_slug": v.agent_slug,
            "github_repo_url": v.github_repo_url,
            "commit_sha": v.commit_sha,
            "notes": v.notes,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.get("/queue/status")
async def get_queue_status(session: AsyncSession = Depends(get_db)) -> dict:
    """
    Build queue dashboard — shows queued, in-progress, and recent builds.
    Used by the Build Queue Dashboard in the Overview tab.
    """
    from datetime import datetime, timedelta, timezone

    from memory.models import RunStatus

    # Queued
    queued_result = await session.execute(
        select(ForgeRun)
        .where(ForgeRun.status == RunStatus.QUEUED.value)
        .order_by(ForgeRun.created_at.asc())
    )
    queued = queued_result.scalars().all()

    # In-progress (any non-terminal, non-queued, non-confirming status)
    in_progress_result = await session.execute(
        select(ForgeRun).where(
            ForgeRun.status.in_([
                RunStatus.VALIDATING.value,
                RunStatus.PARSING.value,
                RunStatus.ARCHITECTING.value,
                RunStatus.GENERATING.value,
                RunStatus.PACKAGING.value,
            ])
        ).order_by(ForgeRun.updated_at.desc())
    )
    in_progress = in_progress_result.scalars().all()

    # Recent (last 24 hours, terminal status)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await session.execute(
        select(ForgeRun)
        .where(
            ForgeRun.status.in_([RunStatus.COMPLETE.value, RunStatus.FAILED.value]),
            ForgeRun.updated_at >= since,
        )
        .order_by(ForgeRun.updated_at.desc())
        .limit(10)
    )
    recent = recent_result.scalars().all()

    # Estimated wait time: 20 min avg per build
    avg_build_minutes = 20
    queue_count = len(queued)

    return {
        "queued": [
            {
                "run_id": r.run_id,
                "title": r.title,
                "queued_at": r.created_at.isoformat(),
                "position": i + 1,
                "estimated_wait_minutes": (i + 1) * avg_build_minutes,
            }
            for i, r in enumerate(queued)
        ],
        "in_progress": [
            {
                "run_id": r.run_id,
                "title": r.title,
                "status": r.status,
                "files_complete": r.files_complete,
                "file_count": r.file_count,
                "started_at": r.created_at.isoformat(),
                "elapsed_minutes": round(
                    (datetime.now(timezone.utc) - r.created_at).total_seconds() / 60, 1
                ),
            }
            for r in in_progress
        ],
        "recently_completed": [
            {
                "run_id": r.run_id,
                "title": r.title,
                "status": r.status,
                "files_complete": r.files_complete,
                "completed_at": r.updated_at.isoformat(),
            }
            for r in recent
        ],
        "queue_depth": queue_count,
        "active_builds": len(in_progress),
        "estimated_wait_minutes": queue_count * avg_build_minutes,
    }
