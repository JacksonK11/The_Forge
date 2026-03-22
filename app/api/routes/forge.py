"""
app/api/routes/forge.py
Blueprint submission and build management routes.

POST /forge/submit          — submit blueprint text or file upload, queue build
POST /forge/runs/{id}/approve — approve parsed spec, start code generation
POST /forge/runs/{id}/regenerate/{file_path} — regenerate single file
GET  /forge/runs/{id}/package — download completed ZIP
"""

import io
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory.database import get_db
from memory.models import FileStatus, ForgeFile, ForgeRun, RunStatus
from pipeline.pipeline import run_pipeline_sync

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class SubmitBlueprintRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    blueprint_text: str = Field(..., min_length=50)


class SubmitBlueprintResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ApproveSpecResponse(BaseModel):
    run_id: str
    status: str
    message: str


class RegenerateFileResponse(BaseModel):
    run_id: str
    file_path: str
    status: str
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/submit", response_model=SubmitBlueprintResponse)
async def submit_blueprint(
    request: SubmitBlueprintRequest,
    session: AsyncSession = Depends(get_db),
) -> SubmitBlueprintResponse:
    """
    Submit a blueprint for processing.
    Creates a ForgeRun record and queues the pipeline job.
    Returns the run_id for tracking.
    """
    from app.api.main import get_build_queue

    run_id = str(uuid.uuid4())
    run = ForgeRun(
        run_id=run_id,
        title=request.title,
        blueprint_text=request.blueprint_text,
        status=RunStatus.QUEUED.value,
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
        logger.info(f"Build queued: run_id={run_id} title='{request.title}'")
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        run.error_message = f"Failed to queue build: {exc}"
        await session.commit()
        logger.error(f"Failed to queue build {run_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to queue build: {exc}")

    return SubmitBlueprintResponse(
        run_id=run_id,
        status=RunStatus.QUEUED.value,
        message="Blueprint accepted. Build queued.",
    )


@router.post("/submit-file", response_model=SubmitBlueprintResponse)
async def submit_blueprint_file(
    title: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> SubmitBlueprintResponse:
    """
    Submit a .docx or .pdf blueprint file for processing.
    Extracts text from the file, creates ForgeRun, queues build.
    """
    from app.api.main import get_build_queue

    content_type = file.content_type or ""
    filename = file.filename or ""

    try:
        file_bytes = await file.read()
        blueprint_text = _extract_text_from_file(file_bytes, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}")

    if len(blueprint_text.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail="Extracted blueprint text is too short. Check the file content.",
        )

    run_id = str(uuid.uuid4())
    run = ForgeRun(
        run_id=run_id,
        title=title,
        blueprint_text=blueprint_text,
        blueprint_file_path=filename,
        status=RunStatus.QUEUED.value,
    )
    session.add(run)
    await session.commit()

    queue = get_build_queue()
    queue.enqueue(
        run_pipeline_sync,
        run_id,
        job_id=f"build-{run_id}",
        job_timeout=3600,
    )

    logger.info(f"File build queued: run_id={run_id} file='{filename}'")
    return SubmitBlueprintResponse(
        run_id=run_id,
        status=RunStatus.QUEUED.value,
        message="Blueprint file accepted. Build queued.",
    )


@router.post("/runs/{run_id}/approve", response_model=ApproveSpecResponse)
async def approve_spec(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> ApproveSpecResponse:
    """
    Approve the parsed spec and continue with code generation.
    Called from the dashboard Spec Confirmation screen (Stage 3).
    Run must be in CONFIRMING status.
    """
    from app.api.main import get_build_queue

    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunStatus.CONFIRMING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in status '{run.status}', not 'confirming'. Cannot approve.",
        )

    run.status = RunStatus.ARCHITECTING.value
    await session.commit()

    queue = get_build_queue()
    queue.enqueue(
        run_pipeline_sync,
        run_id,
        "resume_from_architecture",
        job_id=f"build-{run_id}-arch",
        job_timeout=3600,
    )

    logger.info(f"Spec approved, resuming pipeline: run_id={run_id}")
    return ApproveSpecResponse(
        run_id=run_id,
        status=RunStatus.ARCHITECTING.value,
        message="Spec approved. Generating architecture and starting code generation.",
    )


@router.post("/runs/{run_id}/regenerate/{file_path:path}", response_model=RegenerateFileResponse)
async def regenerate_file(
    run_id: str,
    file_path: str,
    session: AsyncSession = Depends(get_db),
) -> RegenerateFileResponse:
    """
    Regenerate a single file from a completed or failed run.
    Useful for iterating on a specific file without rebuilding the entire agent.
    Cost: ~£0.02–0.04 per file.
    """
    from app.api.main import get_build_queue
    from pipeline.pipeline import regenerate_file_sync

    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in (RunStatus.COMPLETE.value, RunStatus.FAILED.value):
        raise HTTPException(
            status_code=400,
            detail="Can only regenerate files from completed or failed runs",
        )

    file_result = await session.execute(
        select(ForgeFile).where(
            ForgeFile.run_id == run_id, ForgeFile.file_path == file_path
        )
    )
    forge_file = file_result.scalar_one_or_none()
    if not forge_file:
        raise HTTPException(status_code=404, detail="File not found in this run")

    queue = get_build_queue()
    queue.enqueue(
        regenerate_file_sync,
        run_id,
        file_path,
        job_id=f"regen-{run_id}-{file_path[:30]}",
        job_timeout=300,
    )

    logger.info(f"File regeneration queued: run_id={run_id} file={file_path}")
    return RegenerateFileResponse(
        run_id=run_id,
        file_path=file_path,
        status="queued",
        message="File regeneration queued.",
    )


@router.get("/runs/{run_id}/package")
async def download_package(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Download the completed ZIP package for a build.
    Run must be in COMPLETE status and package_path must be set.
    """
    result = await session.execute(
        select(ForgeRun).where(ForgeRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400, detail=f"Run is not complete (status: {run.status})"
        )
    if not run.package_data and not run.package_path:
        raise HTTPException(status_code=404, detail="Package not found for this run")

    if run.package_data:
        package_bytes = run.package_data
    else:
        try:
            with open(run.package_path, "rb") as f:
                package_bytes = f.read()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Package file missing from disk")

    agent_slug = run.spec_json.get("agent_slug", "agent") if run.spec_json else "agent"
    filename = f"{agent_slug}-forge-package.zip"

    return StreamingResponse(
        io.BytesIO(package_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from .docx or .pdf file bytes."""
    if filename.endswith(".docx"):
        import docx
        import io as _io

        doc = docx.Document(_io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if filename.endswith(".pdf"):
        import io as _io

        from pypdf import PdfReader

        reader = PdfReader(_io.BytesIO(file_bytes))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )

    raise ValueError(f"Unsupported file type: {filename}. Use .docx or .pdf")
