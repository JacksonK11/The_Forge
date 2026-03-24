"""
pipeline/nodes/apply_changes_node.py
Update pipeline stage 3: generate new/modified file content.

For each file in change_plan.create and change_plan.modify, calls Claude
Sonnet to produce the complete new file content. Passes relevant existing
files as context so Claude can maintain consistency with the rest of the
codebase (imports, naming conventions, patterns, etc.).

Files in change_plan.delete are recorded in state.changed_files with a
sentinel value so commit_push_node can handle the deletion.

Context selection strategy:
  - Always include the file being modified (if it exists).
  - Include files explicitly referenced in the instruction string.
  - Include files with the same parent directory.
  - Include core config/model files if they exist.
  - Cap total context at ~60 KB to stay within token budget.
"""

import asyncio
from typing import TYPE_CHECKING

import anthropic
from loguru import logger

from config.settings import settings

if TYPE_CHECKING:
    from pipeline.update_pipeline import UpdatePipelineState

# Sentinel value stored in changed_files to mark a file for deletion
DELETE_SENTINEL = "__FORGE_DELETE__"

# Core files always included as context if they exist in the repo
_CORE_CONTEXT_FILES = {
    "requirements.txt",
    "package.json",
    "config/settings.py",
    "memory/models.py",
    "memory/database.py",
    ".env.example",
}

_MAX_CONTEXT_CHARS = 60_000
_MAX_RETRIES = 2

_SYSTEM_PROMPT = """You are The Forge's code modification specialist. You receive:
1. The instruction describing exactly what change is needed in this specific file.
2. The current content of the file (if it exists).
3. Relevant context files from the same codebase for consistency.

Your task: produce the complete new content of the file.

Rules:
- Return ONLY the complete file content — no markdown fences, no explanation, no commentary.
- Preserve all existing functionality unless the instruction explicitly says to change it.
- Match the coding style, import patterns, and conventions of the surrounding codebase.
- Full async/await throughout. Full error handling with loguru. Type hints on all functions.
- No placeholder comments, no TODO stubs, no "implement this later".
- Production-ready code only."""


async def apply_changes_node(state: "UpdatePipelineState") -> "UpdatePipelineState":
    """
    Generate content for all files in the change plan.

    Args:
        state: UpdatePipelineState with existing_files and change_plan set.

    Returns:
        state with changed_files populated:
          {file_path: new_content} for creates/modifies
          {file_path: DELETE_SENTINEL} for deletes
    """
    change_plan = state.change_plan or {}
    creates = change_plan.get("create", [])
    modifies = change_plan.get("modify", [])
    deletes = change_plan.get("delete", [])

    logger.info(
        f"[{state.update_id}] Applying changes — "
        f"create={len(creates)} modify={len(modifies)} delete={len(deletes)}"
    )

    # Mark files for deletion
    for file_path in deletes:
        if isinstance(file_path, str):
            state.changed_files[file_path] = DELETE_SENTINEL
            logger.debug(f"[{state.update_id}] Marked for deletion: {file_path}")

    # Process creates and modifies concurrently (up to 4 at once)
    semaphore = asyncio.Semaphore(4)
    all_file_entries = creates + modifies

    async def _process(entry: dict) -> None:
        async with semaphore:
            file_path = entry.get("path", "")
            instruction = entry.get("instruction", "")
            if not file_path:
                logger.warning(
                    f"[{state.update_id}] Skipping entry with empty path: {entry!r}"
                )
                return

            try:
                content = await _generate_file(
                    update_id=state.update_id,
                    file_path=file_path,
                    instruction=instruction,
                    change_description=state.change_description,
                    existing_files=state.existing_files,
                )
                state.changed_files[file_path] = content
                logger.info(
                    f"[{state.update_id}] Generated: {file_path} "
                    f"({len(content)} chars)"
                )
            except Exception as exc:
                error_msg = f"Failed to generate {file_path}: {exc}"
                logger.error(f"[{state.update_id}] {error_msg}")
                state.errors.append(error_msg)

    await asyncio.gather(*[_process(entry) for entry in all_file_entries])

    successful = len([v for v in state.changed_files.values() if v != DELETE_SENTINEL])
    total_creates_modifies = len(creates) + len(modifies)
    logger.info(
        f"[{state.update_id}] apply_changes complete — "
        f"generated={successful}/{total_creates_modifies} "
        f"deletes={len(deletes)} "
        f"errors={len(state.errors)}"
    )

    return state


async def _generate_file(
    update_id: str,
    file_path: str,
    instruction: str,
    change_description: str,
    existing_files: dict[str, str],
) -> str:
    """
    Generate complete file content for a single create/modify entry.
    Retries up to _MAX_RETRIES times on API errors.
    """
    context = _build_context(file_path, instruction, existing_files)
    current_content = existing_files.get(file_path, "")

    user_message_parts = [
        f"OVERALL CHANGE DESCRIPTION:\n{change_description}\n",
        f"FILE TO GENERATE: {file_path}",
        f"SPECIFIC INSTRUCTION: {instruction}\n",
    ]

    if current_content:
        user_message_parts.append(
            f"CURRENT FILE CONTENT:\n```\n{current_content}\n```\n"
        )
    else:
        user_message_parts.append("(This is a new file — no existing content)\n")

    if context:
        user_message_parts.append(f"CONTEXT FILES FOR CONSISTENCY:\n{context}")

    user_message_parts.append(
        "\nReturn the complete new content of the file only. No markdown fences."
    )
    user_message = "\n".join(user_message_parts)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=16000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            content = response.content[0].text if response.content else ""
            if not content.strip():
                raise ValueError("Claude returned empty content")
            return content
        except Exception as exc:
            last_error = exc
            if attempt <= _MAX_RETRIES:
                logger.warning(
                    f"[{update_id}] Attempt {attempt} failed for {file_path}: {exc} — retrying"
                )
            else:
                logger.error(
                    f"[{update_id}] All {_MAX_RETRIES + 1} attempts failed for {file_path}: {exc}"
                )

    raise RuntimeError(
        f"File generation failed after {_MAX_RETRIES + 1} attempts: {last_error}"
    )


def _build_context(
    target_path: str,
    instruction: str,
    existing_files: dict[str, str],
) -> str:
    """
    Assemble relevant context files to include alongside the generation request.
    Returns a formatted string of file contents, capped at _MAX_CONTEXT_CHARS.
    """
    import os

    context_paths: list[str] = []
    target_dir = os.path.dirname(target_path)

    # Always include core config files if present
    for core_path in _CORE_CONTEXT_FILES:
        if core_path in existing_files and core_path != target_path:
            context_paths.append(core_path)

    # Include files in the same directory
    for path in existing_files:
        if path == target_path:
            continue
        if os.path.dirname(path) == target_dir and path not in context_paths:
            context_paths.append(path)

    # Include files mentioned by name in the instruction
    instruction_lower = instruction.lower()
    for path in existing_files:
        if path == target_path or path in context_paths:
            continue
        filename = os.path.basename(path)
        if filename.lower() in instruction_lower or path.lower() in instruction_lower:
            context_paths.append(path)

    # Build the context string up to the character limit
    context_parts: list[str] = []
    total_chars = 0

    for path in context_paths:
        content = existing_files.get(path, "")
        entry = f"=== {path} ===\n{content}\n"
        if total_chars + len(entry) > _MAX_CONTEXT_CHARS:
            break
        context_parts.append(entry)
        total_chars += len(entry)

    return "\n".join(context_parts)
