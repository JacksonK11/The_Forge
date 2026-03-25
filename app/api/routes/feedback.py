"""
app/api/routes/feedback.py
Deployment feedback loop — after deploying an agent, users report what
worked and what didn't. Feedback is stored in the knowledge base so
The Forge learns from real-world deployment outcomes.

POST /forge/feedback          — submit feedback for a build run
GET  /forge/feedback/{run_id} — retrieve all feedback for a run
"""

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text

from app.api.ratelimit import limiter
from intelligence.knowledge_base import store_record
from memory.database import get_session

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────


class FileModification(BaseModel):
    path: str
    change_description: str = ""
    error_message: str = ""


class FeedbackRequest(BaseModel):
    run_id: str
    deployed_successfully: bool
    files_modified: list[FileModification] = []
    deployment_errors: list[str] = []
    fly_logs: str = ""  # first 5000 chars
    notes: str = ""


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/feedback")
@limiter.limit("30/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
) -> dict:
    """
    Submit deployment feedback for a completed build run.

    Records what worked and what required manual fixes after deployment.
    All feedback is stored in the knowledge base so The Forge improves
    with every real-world deployment cycle.

    DB insert is the primary action. Knowledge base storage is best-effort
    and never blocks the response on failure.
    """
    # ── Primary DB insert ────────────────────────────────────────────────────
    try:
        async with get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO deployment_feedback (run_id, deployed_successfully, payload, created_at)
                    VALUES (:run_id, :deployed, :payload::jsonb, NOW())
                """),
                {
                    "run_id": body.run_id,
                    "deployed": body.deployed_successfully,
                    "payload": json.dumps(body.dict()),
                },
            )
        logger.info(
            f"[feedback] Stored deployment feedback for run={body.run_id} "
            f"deployed={body.deployed_successfully} "
            f"files_modified={len(body.files_modified)} "
            f"errors={len(body.deployment_errors)}"
        )
    except Exception as exc:
        logger.error(f"[feedback] DB insert failed for run={body.run_id}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Failed to store feedback. Please try again.",
        )

    # ── Knowledge base storage (best-effort, non-blocking) ───────────────────

    # Per-file modifications — each one is a discrete learning record
    for mod in body.files_modified:
        try:
            await store_record(
                record_type="deployment_feedback",
                content=(
                    f"File {mod.path} needed manual fix: {mod.change_description}. "
                    f"Error: {mod.error_message}"
                ),
                outcome="deployment_fix_required",
                run_id=body.run_id,
                metadata={
                    "file_path": mod.path,
                    "change_description": mod.change_description,
                },
            )
        except Exception as exc:
            logger.warning(
                f"[feedback] KB store failed for file_modification "
                f"run={body.run_id} path={mod.path}: {exc}"
            )

    # Per-error records — outcome varies based on whether deployment succeeded
    outcome = "deployment_failed" if not body.deployed_successfully else "deployment_warning"
    for error in body.deployment_errors:
        try:
            await store_record(
                record_type="deployment_error",
                content=f"Build {body.run_id} deployment error: {error}",
                outcome=outcome,
                run_id=body.run_id,
            )
        except Exception as exc:
            logger.warning(
                f"[feedback] KB store failed for deployment_error "
                f"run={body.run_id}: {exc}"
            )

    # Perfect deployment record — zero modifications needed, fully clean
    if body.deployed_successfully and len(body.files_modified) == 0:
        try:
            await store_record(
                record_type="clean_deployment",
                content=(
                    f"Build {body.run_id} deployed cleanly with zero modifications"
                ),
                outcome="perfect_deployment",
                run_id=body.run_id,
            )
            logger.info(f"[feedback] Perfect deployment recorded for run={body.run_id}")
        except Exception as exc:
            logger.warning(
                f"[feedback] KB store failed for clean_deployment "
                f"run={body.run_id}: {exc}"
            )

    return {
        "status": "accepted",
        "run_id": body.run_id,
        "message": "Feedback recorded. The Forge will learn from this.",
    }


@router.get("/feedback/{run_id}")
@limiter.limit("60/minute")
async def get_feedback(
    request: Request,
    run_id: str,
) -> dict:
    """
    Retrieve all deployment feedback submitted for a build run.

    Returns every feedback record stored for the given run_id, ordered
    newest first. Returns an empty result on DB error rather than 500 —
    feedback retrieval is non-critical and should never surface as an error
    to the dashboard.
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id,
                        run_id,
                        deployed_successfully,
                        payload,
                        created_at
                    FROM deployment_feedback
                    WHERE run_id = :run_id
                    ORDER BY created_at DESC
                """),
                {"run_id": run_id},
            )
            rows = result.mappings().all()

        items = [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "deployed_successfully": row["deployed_successfully"],
                "payload": row["payload"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]

        logger.info(
            f"[feedback] Retrieved {len(items)} feedback records for run={run_id}"
        )
        return {
            "run_id": run_id,
            "feedback_count": len(items),
            "items": items,
        }

    except Exception as exc:
        logger.error(
            f"[feedback] DB query failed for run={run_id}: {exc}"
        )
        return {
            "run_id": run_id,
            "feedback_count": 0,
            "items": [],
        }
