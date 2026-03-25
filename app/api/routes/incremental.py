"""
app/api/routes/incremental.py
Incremental build API — modify, add, or remove individual modules in an
agent previously built by The Forge without regenerating the entire codebase.

POST /forge/incremental/plan              — plan changes (returns plan for review)
POST /forge/incremental/execute           — execute an approved change plan
GET  /forge/incremental/registry          — list all agents in forge_agent_versions
GET  /forge/incremental/registry/{run_id} — get version history for a run
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text

from app.api.ratelimit import limiter
from memory.database import get_session

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────


class IncrementalRequest(BaseModel):
    run_id: str
    action: Literal["modify", "add", "remove"] = "modify"
    description: str
    files_to_modify: list[str] = []
    existing_code: dict[str, str] = {}  # {path: content}


class ExecuteRequest(BaseModel):
    run_id: str
    approved_plan: dict  # the plan returned by /plan


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/plan")
@limiter.limit("10/minute")
async def plan_incremental_changes(
    request: Request,
    body: IncrementalRequest,
) -> dict:
    """
    Plan incremental changes to a previously built agent.

    Calls IncrementalBuilder.plan_changes() which analyses the existing code,
    determines the minimal set of file operations required, and returns a
    structured plan for user review before any changes are committed.

    The returned plan should be passed unmodified to POST /incremental/execute
    once approved.
    """
    try:
        from pipeline.services.incremental_builder import IncrementalBuilder

        builder = IncrementalBuilder()
        plan = await builder.plan_changes(
            run_id=body.run_id,
            action=body.action,
            description=body.description,
            files_to_modify=body.files_to_modify,
            existing_code=body.existing_code,
        )

        logger.info(
            f"[incremental/plan] Plan generated for run={body.run_id} "
            f"action={body.action} files={len(body.files_to_modify)}"
        )
        return {
            "run_id": body.run_id,
            "plan": plan,
        }

    except Exception as exc:
        logger.error(
            f"[incremental/plan] Failed to plan changes for run={body.run_id}: {exc}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate incremental plan: {exc}",
        )


@router.post("/execute")
@limiter.limit("5/minute")
async def execute_incremental_changes(
    request: Request,
    body: ExecuteRequest,
) -> dict:
    """
    Execute an approved incremental change plan.

    Takes the plan returned by POST /incremental/plan and executes it,
    applying only the minimal file changes needed. The approved_plan must
    be the unmodified plan object returned by the /plan endpoint.

    Rate limited to 5/minute — each execution triggers real code generation
    and may write to the agent registry.
    """
    try:
        from pipeline.services.incremental_builder import IncrementalBuilder

        builder = IncrementalBuilder()
        result = await builder.execute_changes(
            run_id=body.run_id,
            approved_plan=body.approved_plan,
        )

        logger.info(
            f"[incremental/execute] Changes executed for run={body.run_id}"
        )
        return {
            "run_id": body.run_id,
            "result": result,
        }

    except Exception as exc:
        logger.error(
            f"[incremental/execute] Failed to execute changes for run={body.run_id}: {exc}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute incremental changes: {exc}",
        )


@router.get("/registry")
@limiter.limit("60/minute")
async def list_agent_registry(
    request: Request,
) -> dict:
    """
    List all agents tracked in the forge_agent_versions table.

    Returns up to 50 entries ordered by creation date descending — the most
    recently built or modified agents appear first. Includes all versions of
    every agent so the full build lineage is visible.

    Returns an empty list with an error flag if the DB is unavailable.
    The registry is read-only and non-critical — never 500s.
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id,
                        run_id,
                        agent_name,
                        version,
                        parent_run_id,
                        created_at
                    FROM forge_agent_versions
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
            )
            rows = result.mappings().all()

        agents = [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "agent_name": row["agent_name"],
                "version": row["version"],
                "parent_run_id": row["parent_run_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]

        logger.info(f"[incremental/registry] Returned {len(agents)} agent versions")
        return {"agents": agents}

    except Exception as exc:
        logger.error(f"[incremental/registry] DB query failed: {exc}")
        return {
            "agents": [],
            "error": "Registry unavailable",
        }


@router.get("/registry/{run_id}")
@limiter.limit("60/minute")
async def get_agent_version_history(
    request: Request,
    run_id: str,
) -> dict:
    """
    Get the full version history for a specific agent run.

    Returns all forge_agent_versions rows where run_id matches the
    given run_id OR where parent_run_id points back to it, ordered
    by version ascending so the build lineage reads chronologically.

    This covers both the original build (run_id = :run_id) and all
    incremental builds that derived from it (parent_run_id = :run_id).
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id,
                        run_id,
                        agent_name,
                        version,
                        parent_run_id,
                        created_at
                    FROM forge_agent_versions
                    WHERE run_id = :run_id
                       OR parent_run_id = :run_id
                    ORDER BY version ASC
                """),
                {"run_id": run_id},
            )
            rows = result.mappings().all()

        versions = [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "agent_name": row["agent_name"],
                "version": row["version"],
                "parent_run_id": row["parent_run_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in rows
        ]

        logger.info(
            f"[incremental/registry/{run_id}] Returned {len(versions)} versions"
        )
        return {
            "run_id": run_id,
            "versions": versions,
        }

    except Exception as exc:
        logger.error(
            f"[incremental/registry/{run_id}] DB query failed: {exc}"
        )
        return {
            "run_id": run_id,
            "versions": [],
        }
