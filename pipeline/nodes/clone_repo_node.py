"""
pipeline/nodes/clone_repo_node.py
Update pipeline stage 1: clone the target repository.

Clones the GitHub repo to /tmp/{update_id}/ using gitpython (sync),
wrapped in asyncio executor. Reads all non-binary source files and
stores them in state.existing_files as {relative_path: content}.

Skips: .git/, node_modules/, __pycache__/, *.pyc, *.png, *.jpg, *.ico,
       *.woff, *.woff2, *.ttf, *.eot, *.zip, *.gz, *.tar, *.bin
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from config.settings import settings

if TYPE_CHECKING:
    from pipeline.update_pipeline import UpdatePipelineState

# File extensions treated as binary — skip reading content
_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".gz", ".tar", ".tgz", ".rar",
    ".bin", ".exe", ".dll", ".so", ".dylib",
    ".pdf", ".docx", ".xlsx",
    ".pyc", ".pyo",
    ".db", ".sqlite", ".sqlite3",
    ".lock",  # package-lock.json is text but often huge — include as text anyway
}

# Directory names to skip entirely
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
}


async def clone_repo_node(state: "UpdatePipelineState") -> "UpdatePipelineState":
    """
    Clone the target repo and read all source files into state.existing_files.

    Args:
        state: UpdatePipelineState with repo_url and update_id set.

    Returns:
        state with existing_files populated.

    Raises:
        RuntimeError: if clone or file reading fails (caller marks update as failed).
    """
    if not settings.github_token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set — cannot clone private repositories. "
            "Set GITHUB_TOKEN with repo read/write scope."
        )

    tmp_dir = f"/tmp/forge-update-{state.update_id}"

    # Clean up any previous attempt
    if os.path.exists(tmp_dir):
        logger.info(f"[{state.update_id}] Removing existing tmp dir: {tmp_dir}")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Insert token into HTTPS clone URL
    clone_url = _inject_token(state.repo_url, settings.github_token)
    logger.info(
        f"[{state.update_id}] Cloning repo: {state.repo_url} → {tmp_dir}"
    )

    loop = asyncio.get_event_loop()

    try:
        await loop.run_in_executor(None, lambda: _clone_sync(clone_url, tmp_dir))
    except Exception as exc:
        logger.error(
            f"[{state.update_id}] git clone failed for {state.repo_url}: {exc}"
        )
        raise RuntimeError(f"Failed to clone repository: {exc}") from exc

    logger.info(f"[{state.update_id}] Clone complete — reading source files")

    try:
        existing_files = await loop.run_in_executor(
            None, lambda: _read_files_sync(tmp_dir)
        )
    except Exception as exc:
        logger.error(
            f"[{state.update_id}] Failed to read cloned files: {exc}"
        )
        raise RuntimeError(f"Failed to read repository files: {exc}") from exc

    state.existing_files = existing_files
    state.clone_dir = tmp_dir

    logger.info(
        f"[{state.update_id}] Repository loaded — "
        f"files={len(existing_files)} dir={tmp_dir}"
    )
    return state


def _inject_token(repo_url: str, token: str) -> str:
    """
    Insert GitHub personal access token into an HTTPS clone URL.

    https://github.com/user/repo.git
    → https://<token>@github.com/user/repo.git
    """
    if repo_url.startswith("https://"):
        return repo_url.replace("https://", f"https://{token}@", 1)
    # SSH URLs (git@github.com:...) are already handled by SSH keys;
    # convert to HTTPS with token for consistency.
    if repo_url.startswith("git@github.com:"):
        path = repo_url[len("git@github.com:"):]
        return f"https://{token}@github.com/{path}"
    return repo_url


def _clone_sync(clone_url: str, tmp_dir: str) -> None:
    """Synchronous gitpython clone — must be called in executor."""
    from git import Repo

    Repo.clone_from(clone_url, tmp_dir, depth=1)


def _read_files_sync(root_dir: str) -> dict[str, str]:
    """
    Walk the cloned directory and read all non-binary source files.
    Returns {relative_path: content} with POSIX-style relative paths.
    """
    files: dict[str, str] = {}
    root = Path(root_dir)

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # Skip if any parent directory is in the skip list
        relative = path.relative_to(root)
        parts = relative.parts
        if any(part in _SKIP_DIRS for part in parts):
            continue

        # Skip binary extensions
        if path.suffix.lower() in _BINARY_EXTENSIONS:
            continue

        # Skip very large files (> 500 KB) — likely generated/bundled assets
        try:
            if path.stat().st_size > 512_000:
                continue
        except OSError:
            continue

        # Read as UTF-8, skip files with decoding errors
        try:
            content = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        relative_posix = relative.as_posix()
        files[relative_posix] = content

    return files
