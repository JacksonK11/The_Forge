"""
pipeline/update_pipeline.py
The Forge update pipeline orchestrator.

Handles targeted codebase updates to existing GitHub repositories.

UpdatePipelineState — the central data object passed through every stage.
run_update_pipeline() — async orchestrator.
run_update_pipeline_sync() — RQ-compatible sync wrapper.

Update stages:
  1. Clone     — git clone the target repo, read all source files
  2. Plan      — Claude Sonnet analyses codebase + change description, produces change plan
  3. Apply     — Claude Sonnet generates new content for each file to create/modify
  4. Commit    — write changes to working tree, git commit + push to main
  5. Notify    — Telegram alert + optional callback POST
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from sqlalchemy import select, update

from memory.database import get_session
from memory.models import ForgeUpdate


@dataclass
class UpdatePipelineState:
    """Central state object flowing through all update pipeline stages."""

    update_id: str
    repo_url: str
    change_description: str

    # Title for display / notifications
    title: str = ""

    # Set by clone_repo_node: {relative_path: content}
    existing_files: dict[str, str] = field(default_factory=dict)

    # Set by clone_repo_node: path to the cloned working tree on disk
    clone_dir: str = ""

    # Set by change_spec_node: {"create": [...], "modify": [...], "delete": [...], "reasoning": str}
    change_plan: Optional[dict] = None

    # Set by apply_changes_node: {file_path: new_content | DELETE_SENTINEL}
    changed_files: dict[str, str] = field(default_factory=dict)

    # Callback URL for The Office or other callers
    callback_url: Optional[str] = None

    # Non-fatal errors collected during apply stage
    errors: list[str] = field(default_factory=list)

    # Timing
    started_at: float = field(default_factory=time.time)


async def run_update_pipeline(update_id: str) -> None:
    """
    Main async update pipeline orchestrator.
    Loads the ForgeUpdate from DB, executes all stages, handles errors.

    Args:
        update_id: UUID of the ForgeUpdate to process.
    """
    from pipeline.nodes.apply_changes_node import apply_changes_node
    from pipeline.nodes.change_spec_node import change_spec_node
    from pipeline.nodes.clone_repo_node import clone_repo_node
    from pipeline.nodes.commit_push_node import commit_push_node

    # ── Load update record from DB ────────────────────────────────────────────
    async with get_session() as session:
        result = await session.execute(
            select(ForgeUpdate).where(ForgeUpdate.update_id == update_id)
        )
        forge_update = result.scalar_one_or_none()
        if not forge_update:
            logger.error(f"ForgeUpdate {update_id} not found in database")
            return

        state = UpdatePipelineState(
            update_id=update_id,
            repo_url=forge_update.repo_url,
            change_description=forge_update.change_description,
            title=forge_update.title or f"Update {update_id[:8]}",
            callback_url=forge_update.callback_url,
        )

    logger.info(
        f"Update pipeline started: update_id={update_id} "
        f"repo={state.repo_url}"
    )

    # ── Stage 1: Clone ────────────────────────────────────────────────────────
    state = await _run_update_stage(update_id, "cloning", clone_repo_node, state)
    if _is_failed(state):
        return

    # ── Stage 2: Plan ─────────────────────────────────────────────────────────
    state = await _run_update_stage(update_id, "planning", change_spec_node, state)
    if _is_failed(state):
        return

    # ── Stage 3: Apply ────────────────────────────────────────────────────────
    state = await _run_update_stage(update_id, "applying", apply_changes_node, state)
    if _is_failed(state):
        return

    # ── Stage 4: Commit + Push ────────────────────────────────────────────────
    state = await _run_update_stage(update_id, "pushing", commit_push_node, state)
    if _is_failed(state):
        return

    duration = time.time() - state.started_at
    logger.info(
        f"Update pipeline complete: update_id={update_id} "
        f"duration={duration:.0f}s "
        f"files_changed={len(state.changed_files)}"
    )

    # ── Stage 5: Deploy verification and auto-fix (optional) ─────────────────
    try:
        from pipeline.nodes.deploy_verify_fix_node import deploy_verify_fix_update_node
        # Derive agent slug from repo URL (e.g. github.com/user/buildright-ai-agent → buildright-ai-agent)
        repo_slug = state.repo_url.rstrip("/").split("/")[-1]
        await deploy_verify_fix_update_node(
            update_id=update_id,
            repo_url=state.repo_url,
            agent_slug=repo_slug,
            title=state.title,
        )
    except Exception as verify_exc:
        logger.error(
            f"[{update_id}] Deploy verify stage failed (non-blocking): {verify_exc}"
        )

    # ── Stage 6: Notify ───────────────────────────────────────────────────────
    try:
        await _notify_update_complete(state, duration)
    except Exception as notify_exc:
        logger.error(f"[{update_id}] Notification failed (non-blocking): {notify_exc}")


async def _run_update_stage(
    update_id: str,
    stage_name: str,
    node_fn,
    state: UpdatePipelineState,
) -> UpdatePipelineState:
    """Execute a single update pipeline stage with error handling and DB status update."""
    await _set_update_status(update_id, stage_name)
    try:
        state = await node_fn(state)
        return state
    except Exception as exc:
        error_msg = f"Update stage '{stage_name}' failed: {exc}"
        logger.error(f"[{update_id}] {error_msg}")
        state.errors.append(error_msg)

        await _set_update_status(update_id, "failed", error_message=str(exc))

        try:
            await _notify_update_failed(state, stage_name, str(exc))
        except Exception:
            pass

        # Use a sentinel value in update_id field to signal failure to caller
        state.update_id = f"FAILED:{update_id}"
        return state


def _is_failed(state: UpdatePipelineState) -> bool:
    """Check if pipeline was marked as failed by _run_update_stage."""
    return state.update_id.startswith("FAILED:")


async def _set_update_status(
    update_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update the ForgeUpdate status in the database."""
    try:
        async with get_session() as session:
            values: dict = {"status": status}
            if error_message:
                values["error_message"] = error_message
            await session.execute(
                update(ForgeUpdate)
                .where(ForgeUpdate.update_id == update_id)
                .values(**values)
            )
    except Exception as db_exc:
        logger.error(
            f"[{update_id}] Failed to set update status to '{status}': {db_exc}"
        )


async def _notify_update_complete(
    state: UpdatePipelineState,
    duration: float,
) -> None:
    """Send Telegram notification and POST to callback_url on successful update."""
    import httpx
    from app.api.services.notify import _send

    change_plan = state.change_plan or {}
    creates = len(change_plan.get("create", []))
    modifies = len(change_plan.get("modify", []))
    deletes = len(change_plan.get("delete", []))

    telegram_text = (
        f"<b>The Forge — Update Complete</b>\n\n"
        f"<b>{state.title}</b>\n"
        f"Update ID: <code>{state.update_id}</code>\n"
        f"Repo: {state.repo_url}\n\n"
        f"Files created: <b>{creates}</b>\n"
        f"Files modified: <b>{modifies}</b>\n"
        f"Files deleted: <b>{deletes}</b>\n"
        f"Duration: <b>{duration:.0f}s</b>"
    )
    await _send(telegram_text)

    if state.callback_url:
        summary = {
            "update_id": state.update_id,
            "status": "complete",
            "repo_url": state.repo_url,
            "title": state.title,
            "duration_seconds": round(duration, 1),
            "files_created": creates,
            "files_modified": modifies,
            "files_deleted": deletes,
            "changed_files": list(state.changed_files.keys()),
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(state.callback_url, json=summary)
                resp.raise_for_status()
                logger.info(
                    f"[{state.update_id}] Callback posted to {state.callback_url}"
                )
        except Exception as cb_exc:
            logger.error(
                f"[{state.update_id}] Callback POST failed (non-blocking): {cb_exc}"
            )


async def _notify_update_failed(
    state: UpdatePipelineState,
    stage: str,
    error: str,
) -> None:
    """Send Telegram notification on update pipeline failure."""
    from app.api.services.notify import _send

    await _send(
        f"<b>The Forge — Update Failed</b>\n\n"
        f"<b>{state.title}</b>\n"
        f"Update ID: <code>{state.update_id}</code>\n"
        f"Repo: {state.repo_url}\n\n"
        f"Failed at stage: <b>{stage}</b>\n"
        f"Error:\n<code>{error[:400]}</code>"
    )

    if state.callback_url:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    state.callback_url,
                    json={
                        "update_id": state.update_id,
                        "status": "failed",
                        "stage": stage,
                        "error": error,
                    },
                )
        except Exception:
            pass


# ── RQ-compatible sync wrapper ────────────────────────────────────────────────


def run_update_pipeline_sync(update_id: str) -> None:
    """Sync wrapper for RQ. Runs the async update pipeline in a new event loop."""
    asyncio.run(run_update_pipeline(update_id))
