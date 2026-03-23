"""
app/api/routes/runs.py
Run status and file retrieval routes.

GET /forge/runs           — list all runs (paginated)
GET /forge/runs/{id}      — run detail with status and progress
GET /forge/runs/{id}/files — all generated files for a run
GET /forge/runs/{id}/spec  — parsed spec JSON
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memory.database import get_db
from memory.models import ForgeFile, ForgeRun

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
