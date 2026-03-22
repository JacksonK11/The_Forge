"""
pipeline/nodes/commit_push_node.py
Update pipeline stage 4: commit and push all changes.

Uses gitpython to apply file creates/modifies/deletes to the cloned working
tree, creates a single descriptive commit, and pushes to the main branch.

The commit message is derived from the change description, trimmed to a
single concise line. If there are many files changed, the count is included.

ForgeUpdate DB record is updated with file counts and final status.
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import update

from config.settings import settings
from memory.database import get_session
from memory.models import ForgeUpdate
from pipeline.nodes.apply_changes_node import DELETE_SENTINEL

if TYPE_CHECKING:
    from pipeline.update_pipeline import UpdatePipelineState


async def commit_push_node(state: "UpdatePipelineState") -> "UpdatePipelineState":
    """
    Write changed files to the cloned working tree, commit, and push to main.

    Args:
        state: UpdatePipelineState with changed_files and clone_dir set.

    Returns:
        state (unchanged, results persisted to DB).

    Raises:
        RuntimeError: if commit or push fails.
    """
    if not state.changed_files:
        logger.warning(
            f"[{state.update_id}] No changed files to commit — skipping commit_push"
        )
        await _update_db_record(
            state.update_id,
            status="complete",
            files_created=0,
            files_modified=0,
            files_deleted=0,
            changed_files_json={},
        )
        return state

    clone_dir = getattr(state, "clone_dir", None)
    if not clone_dir or not os.path.isdir(clone_dir):
        raise RuntimeError(
            f"Clone directory not found: {clone_dir!r}. "
            "Ensure clone_repo_node ran successfully before commit_push_node."
        )

    logger.info(
        f"[{state.update_id}] Committing changes — "
        f"files={len(state.changed_files)} dir={clone_dir}"
    )

    loop = asyncio.get_event_loop()

    files_created = 0
    files_modified = 0
    files_deleted = 0

    # Apply file changes to the working tree
    for file_path, content in state.changed_files.items():
        full_path = Path(clone_dir) / file_path
        try:
            if content == DELETE_SENTINEL:
                if full_path.exists():
                    full_path.unlink()
                    logger.debug(f"[{state.update_id}] Deleted: {file_path}")
                    files_deleted += 1
                else:
                    logger.warning(
                        f"[{state.update_id}] Delete requested but file not found: {file_path}"
                    )
            else:
                is_new = not full_path.exists()
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                if is_new:
                    files_created += 1
                    logger.debug(f"[{state.update_id}] Created: {file_path}")
                else:
                    files_modified += 1
                    logger.debug(f"[{state.update_id}] Modified: {file_path}")
        except Exception as write_exc:
            logger.error(
                f"[{state.update_id}] Failed to write {file_path}: {write_exc}"
            )
            raise RuntimeError(f"Failed to write file {file_path}: {write_exc}") from write_exc

    commit_message = _build_commit_message(
        change_description=state.change_description,
        files_created=files_created,
        files_modified=files_modified,
        files_deleted=files_deleted,
    )

    logger.info(
        f"[{state.update_id}] Committing: '{commit_message}' — "
        f"created={files_created} modified={files_modified} deleted={files_deleted}"
    )

    try:
        await loop.run_in_executor(
            None,
            lambda: _commit_and_push_sync(
                clone_dir=clone_dir,
                changed_files=state.changed_files,
                commit_message=commit_message,
                github_token=settings.github_token or "",
            ),
        )
    except Exception as git_exc:
        logger.error(
            f"[{state.update_id}] git commit/push failed: {git_exc}"
        )
        await _update_db_record(
            update_id=state.update_id,
            status="failed",
            files_created=files_created,
            files_modified=files_modified,
            files_deleted=files_deleted,
            changed_files_json=_summarise_changed_files(state.changed_files),
            error_message=str(git_exc),
        )
        raise RuntimeError(f"git commit/push failed: {git_exc}") from git_exc

    logger.info(f"[{state.update_id}] Push complete — repo={state.repo_url}")

    # Persist results to DB
    await _update_db_record(
        update_id=state.update_id,
        status="complete",
        files_created=files_created,
        files_modified=files_modified,
        files_deleted=files_deleted,
        changed_files_json=_summarise_changed_files(state.changed_files),
    )

    # Clean up tmp clone dir to free disk space
    try:
        shutil.rmtree(clone_dir, ignore_errors=True)
        logger.debug(f"[{state.update_id}] Cleaned up clone dir: {clone_dir}")
    except Exception:
        pass  # Non-blocking cleanup failure

    return state


def _commit_and_push_sync(
    clone_dir: str,
    changed_files: dict[str, str],
    commit_message: str,
    github_token: str,
) -> None:
    """
    Synchronous gitpython commit and push. Must be called in executor.
    Stages all changed files, commits, then pushes to origin main.
    """
    from git import Repo

    repo = Repo(clone_dir)

    # Stage all changes (add modified/created, remove deleted)
    paths_to_add = []
    paths_to_remove = []

    for file_path, content in changed_files.items():
        if content == DELETE_SENTINEL:
            paths_to_remove.append(file_path)
        else:
            paths_to_add.append(file_path)

    if paths_to_add:
        repo.index.add(paths_to_add)

    if paths_to_remove:
        # Only stage removals for files that existed in the index
        existing_in_index = {item.a_path for item in repo.index.entries.values()} if hasattr(repo.index, 'entries') else set()
        for p in paths_to_remove:
            try:
                repo.index.remove([p])
            except Exception:
                pass  # File may not have been tracked

    # Commit
    repo.index.commit(commit_message)

    # Push to origin main — set remote URL with token for auth
    origin = repo.remote("origin")
    current_url: str = list(origin.urls)[0]

    if github_token and "github.com" in current_url:
        # Ensure token is embedded for push auth
        if "@github.com" not in current_url:
            auth_url = current_url.replace(
                "https://github.com", f"https://{github_token}@github.com"
            )
            origin.set_url(auth_url)

    origin.push(refspec="HEAD:main")


def _build_commit_message(
    change_description: str,
    files_created: int,
    files_modified: int,
    files_deleted: int,
) -> str:
    """Build a concise, informative git commit message."""
    # Take first sentence/line of the change description as the commit title
    first_line = change_description.split("\n")[0].strip()
    if len(first_line) > 72:
        first_line = first_line[:69] + "..."

    parts = []
    if files_created:
        parts.append(f"+{files_created}")
    if files_modified:
        parts.append(f"~{files_modified}")
    if files_deleted:
        parts.append(f"-{files_deleted}")

    if parts:
        return f"{first_line} [{', '.join(parts)} files]"
    return first_line


def _summarise_changed_files(changed_files: dict[str, str]) -> dict:
    """Build a JSON-serialisable summary of what changed."""
    summary: dict[str, list[str]] = {
        "created": [],
        "modified": [],
        "deleted": [],
    }
    for path, content in changed_files.items():
        if content == DELETE_SENTINEL:
            summary["deleted"].append(path)
        else:
            summary["modified"].append(path)
    return summary


async def _update_db_record(
    update_id: str,
    status: str,
    files_created: int,
    files_modified: int,
    files_deleted: int,
    changed_files_json: dict,
    error_message: str | None = None,
) -> None:
    """Persist final update stats to the forge_updates table."""
    try:
        async with get_session() as session:
            values: dict = {
                "status": status,
                "files_created": files_created,
                "files_modified": files_modified,
                "files_deleted": files_deleted,
                "changed_files_json": changed_files_json,
            }
            if error_message:
                values["error_message"] = error_message
            await session.execute(
                update(ForgeUpdate)
                .where(ForgeUpdate.update_id == update_id)
                .values(**values)
            )
    except Exception as db_exc:
        logger.error(
            f"[{update_id}] Failed to update ForgeUpdate record in DB: {db_exc}"
        )
