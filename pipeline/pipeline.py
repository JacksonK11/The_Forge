"""
pipeline/pipeline.py
The Forge build pipeline orchestrator.

Defines PipelineState — the central data object passed through every node.
Defines run_pipeline() — async orchestrator that executes all stages in order.
Defines run_pipeline_sync() and regenerate_file_sync() — RQ-compatible sync wrappers.

Pipeline stages:
  1. Validate    — lightweight Haiku check blueprint is complete enough
  2. Parse       — Sonnet extracts full spec JSON from blueprint
  3. Confirm     — pause and wait for user approval via API
  4. Architecture — map spec to build manifest with dependency order
  5. Generate    — layer-by-layer code generation (layers 1-7)
  6. Package     — assemble ZIP with README, FLY_SECRETS, connection_test
  7. Notify      — Telegram alert with results
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from memory.database import get_session
from memory.models import ForgeRun, RunStatus


@dataclass
class PipelineState:
    """Central state object flowing through all pipeline nodes."""

    run_id: str
    title: str
    blueprint_text: str

    # Extracted spec JSON (after parse node)
    spec: Optional[dict] = None

    # Build manifest (after architecture node)
    manifest: Optional[dict] = None

    # Generated file contents: {file_path: content}
    generated_files: dict[str, str] = field(default_factory=dict)

    # Files that failed after all retries
    failed_files: list[str] = field(default_factory=list)

    # Pipeline errors by stage
    errors: list[str] = field(default_factory=list)

    # Current progress
    current_stage: str = "validating"
    current_layer: int = 0
    current_file: str = ""

    # GitHub auto-push
    repo_name: Optional[str] = None
    push_to_github: bool = False
    github_repo_url: Optional[str] = None

    # Timing
    started_at: float = field(default_factory=time.time)


async def run_pipeline(run_id: str, resume_from: Optional[str] = None) -> None:
    """
    Main async pipeline orchestrator.
    Loads the run from DB, executes all nodes, handles errors at each stage.

    Args:
        run_id:      UUID of the ForgeRun to process.
        resume_from: If set, skip to this stage (used after spec approval).
    """
    from pipeline.nodes.architecture_node import architecture_node
    from pipeline.nodes.codegen_node import codegen_node
    from pipeline.nodes.package_node import package_node
    from pipeline.nodes.parse_node import parse_node

    # ── Load run from DB ─────────────────────────────────────────────────────
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ForgeRun).where(ForgeRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            logger.error(f"Run {run_id} not found in database")
            return

        state = PipelineState(
            run_id=run_id,
            title=run.title,
            blueprint_text=run.blueprint_text or "",
            repo_name=run.repo_name,
            push_to_github=run.push_to_github or False,
        )

        # Restore spec/manifest if resuming after spec approval
        if resume_from == "resume_from_architecture" and run.spec_json:
            state.spec = run.spec_json
            state.current_stage = "architecting"

        # Restore spec + manifest when resuming mid-generation (killed job)
        if resume_from == "generating":
            if run.spec_json:
                state.spec = run.spec_json
            if run.manifest_json:
                state.manifest = run.manifest_json
            state.current_stage = "generating"

    logger.info(f"Pipeline started: run_id={run_id} resume_from={resume_from}")

    # ── Stage 1 & 2: Validate + Parse (skip if resuming) ────────────────────
    if not resume_from:
        state = await _run_stage(run_id, "parsing", parse_node, state)
        if state.current_stage == "failed":
            return

        # Pause for spec confirmation — API will call resume_from_architecture
        await _update_run_status(run_id, RunStatus.CONFIRMING.value, spec=state.spec)
        logger.info(f"Run {run_id} paused for spec confirmation")
        return

    # ── Stage 3: Architecture (skip if resuming mid-generation) ─────────────
    if resume_from != "generating":
        state = await _run_stage(run_id, "architecting", architecture_node, state)
        if state.current_stage == "failed":
            return

    # ── Stage 4: Code generation ─────────────────────────────────────────────
    state = await _run_stage(run_id, "generating", codegen_node, state)
    if state.current_stage == "failed":
        return

    # ── Stage 5: Package ─────────────────────────────────────────────────────
    state = await _run_stage(run_id, "packaging", package_node, state)
    if state.current_stage == "failed":
        return

    # ── Stage 6: GitHub push (optional, never blocks completion) ─────────────
    from pipeline.nodes.github_push_node import github_push_node
    state = await github_push_node(state)

    # ── Stage 7: Deploy verification and auto-fix (optional) ─────────────────
    from pipeline.nodes.deploy_verify_fix_node import deploy_verify_fix_node
    state = await deploy_verify_fix_node(state)

    # ── Stage 8: Complete ─────────────────────────────────────────────────────
    duration = time.time() - state.started_at
    await _update_run_status(run_id, RunStatus.COMPLETE.value)
    logger.info(
        f"Pipeline complete: run_id={run_id} "
        f"files={len(state.generated_files)} "
        f"failed={len(state.failed_files)} "
        f"duration={duration:.0f}s"
    )

    # ── Stage 8: Notify ───────────────────────────────────────────────────────
    try:
        from app.api.services.notify import notify_build_complete
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ForgeRun).where(ForgeRun.run_id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                await notify_build_complete(
                    run_id=run_id,
                    title=state.title,
                    file_count=run.file_count,
                    files_failed=run.files_failed,
                    duration_seconds=duration,
                    callback_url=run.callback_url,
                    github_repo_url=run.github_repo_url,
                )
    except Exception as exc:
        logger.error(f"Notification failed (non-blocking): {exc}")


async def regenerate_file(run_id: str, file_path: str) -> None:
    """Regenerate a single file from a completed run."""
    from pipeline.nodes.layer_generator import generate_single_file

    logger.info(f"Regenerating file: run_id={run_id} file={file_path}")

    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ForgeRun).where(ForgeRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run or not run.spec_json or not run.manifest_json:
            logger.error(f"Cannot regenerate: run {run_id} missing spec or manifest")
            return

    await generate_single_file(run_id, file_path)
    logger.info(f"File regeneration complete: {file_path}")


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _run_stage(
    run_id: str,
    stage_name: str,
    node_fn,
    state: PipelineState,
) -> PipelineState:
    """Execute a single pipeline stage with error handling and DB status update."""
    await _update_run_status(run_id, stage_name)
    try:
        state = await node_fn(state)
        return state
    except Exception as exc:
        error_msg = f"Stage '{stage_name}' failed: {exc}"
        logger.error(f"[{run_id}] {error_msg}")
        state.errors.append(error_msg)
        state.current_stage = "failed"
        await _update_run_status(run_id, RunStatus.FAILED.value, error=error_msg)

        try:
            from app.api.services.notify import notify_build_failed
            await notify_build_failed(
                run_id=run_id,
                title=state.title,
                stage=stage_name,
                error=str(exc),
            )
        except Exception:
            pass

        return state


async def _update_run_status(
    run_id: str,
    status: str,
    error: Optional[str] = None,
    spec: Optional[dict] = None,
) -> None:
    """Update run status in the database."""
    async with get_session() as session:
        from sqlalchemy import select, update
        values: dict = {"status": status}
        if error:
            values["error_message"] = error
        if spec:
            values["spec_json"] = spec
        await session.execute(
            update(ForgeRun).where(ForgeRun.run_id == run_id).values(**values)
        )


# ── RQ-compatible sync wrappers ───────────────────────────────────────────────


def run_pipeline_sync(run_id: str, resume_from: Optional[str] = None) -> None:
    """Sync wrapper for RQ. Runs the async pipeline in a new event loop."""
    asyncio.run(run_pipeline(run_id, resume_from))


def regenerate_file_sync(run_id: str, file_path: str) -> None:
    """Sync wrapper for RQ. Regenerates a single file."""
    asyncio.run(regenerate_file(run_id, file_path))
