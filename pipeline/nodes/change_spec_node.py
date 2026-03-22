"""
pipeline/nodes/change_spec_node.py
Update pipeline stage 2: plan the changes required.

Sends the existing codebase file listing and the change description to
Claude Sonnet. Claude returns a structured JSON plan identifying exactly
which files to CREATE, MODIFY, or DELETE, plus reasoning.

The file listing sent to Claude is a compact format:
  path/to/file.py (N lines): <first 3 lines of content>

This keeps token usage manageable while giving Claude enough context to
make accurate decisions about which files are affected by the change.
"""

import json
import re
from typing import TYPE_CHECKING

import anthropic
from loguru import logger

from config.settings import settings

if TYPE_CHECKING:
    from pipeline.update_pipeline import UpdatePipelineState

_MAX_LISTING_CHARS = 80_000  # ~20k tokens — stay well within context window

_SYSTEM_PROMPT = """You are The Forge's update specialist. You analyze an existing codebase and a
change description, then return a precise JSON plan identifying exactly which files need to be
created, modified, or deleted.

Rules:
- Only include files that are directly affected by the change.
- Do not include files that need no changes.
- Be conservative: if unsure whether a file needs changing, include it rather than omit it.
- For each file in "modify" or "create", write a brief instruction string describing what change
  is needed in that specific file.
- "delete" entries are just file paths (strings).
- Return ONLY valid JSON — no markdown, no explanation outside the JSON object.

Response format:
{
  "create": [
    {"path": "path/to/new_file.py", "instruction": "Create X that does Y"}
  ],
  "modify": [
    {"path": "path/to/existing_file.py", "instruction": "Add Z, update W"}
  ],
  "delete": ["path/to/obsolete_file.py"],
  "reasoning": "One paragraph explaining the overall approach and why these files were selected."
}"""


async def change_spec_node(state: "UpdatePipelineState") -> "UpdatePipelineState":
    """
    Use Claude Sonnet to plan which files to create, modify, or delete.

    Args:
        state: UpdatePipelineState with existing_files and change_description set.

    Returns:
        state with change_plan populated.

    Raises:
        RuntimeError: if Claude call fails or response cannot be parsed.
    """
    logger.info(
        f"[{state.update_id}] Planning changes — "
        f"files_in_repo={len(state.existing_files)} "
        f"description_len={len(state.change_description)}"
    )

    file_listing = _build_file_listing(state.existing_files)

    user_message = (
        f"CHANGE REQUEST:\n{state.change_description}\n\n"
        f"EXISTING FILES IN REPOSITORY:\n{file_listing}\n\n"
        "Return a JSON change plan as described in your instructions."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.error(f"[{state.update_id}] Claude API call failed in change_spec_node: {exc}")
        raise RuntimeError(f"Claude API error during change planning: {exc}") from exc

    raw_text = response.content[0].text if response.content else ""
    logger.debug(f"[{state.update_id}] change_spec raw response ({len(raw_text)} chars)")

    try:
        change_plan = _parse_change_plan(raw_text)
    except Exception as parse_exc:
        logger.error(
            f"[{state.update_id}] Failed to parse change plan JSON: {parse_exc}\n"
            f"Raw response: {raw_text[:500]}"
        )
        raise RuntimeError(
            f"Could not parse change plan from Claude response: {parse_exc}"
        ) from parse_exc

    creates = len(change_plan.get("create", []))
    modifies = len(change_plan.get("modify", []))
    deletes = len(change_plan.get("delete", []))

    logger.info(
        f"[{state.update_id}] Change plan ready — "
        f"create={creates} modify={modifies} delete={deletes}"
    )
    logger.debug(
        f"[{state.update_id}] Change plan reasoning: "
        f"{change_plan.get('reasoning', '')[:300]}"
    )

    state.change_plan = change_plan
    return state


def _build_file_listing(existing_files: dict[str, str]) -> str:
    """
    Build a compact text representation of the repo for Claude.
    Shows file path, line count, and first 3 non-empty lines.
    Truncates at _MAX_LISTING_CHARS to stay within context limits.
    """
    lines: list[str] = []
    total_chars = 0

    for path, content in sorted(existing_files.items()):
        file_lines = content.splitlines()
        line_count = len(file_lines)
        preview_lines = [ln.strip() for ln in file_lines if ln.strip()][:3]
        preview = " | ".join(preview_lines)
        entry = f"{path} ({line_count} lines): {preview[:120]}"
        lines.append(entry)
        total_chars += len(entry)
        if total_chars >= _MAX_LISTING_CHARS:
            lines.append(f"... (truncated — {len(existing_files) - len(lines)} more files)")
            break

    return "\n".join(lines)


def _parse_change_plan(raw_text: str) -> dict:
    """
    Extract and parse the JSON change plan from Claude's response.
    Handles cases where Claude wraps JSON in markdown code fences.
    """
    # Strip markdown code fences if present
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the outermost JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        raise ValueError("No JSON object found in response")

    json_str = text[brace_start : brace_end + 1]
    plan = json.loads(json_str)

    # Validate required keys
    for key in ("create", "modify", "delete"):
        if key not in plan:
            plan[key] = []

    if "reasoning" not in plan:
        plan["reasoning"] = ""

    # Normalise: ensure create/modify are lists of dicts, delete is list of strings
    if not isinstance(plan["create"], list):
        plan["create"] = []
    if not isinstance(plan["modify"], list):
        plan["modify"] = []
    if not isinstance(plan["delete"], list):
        plan["delete"] = []

    # Each create/modify entry must have path and instruction
    for entry in plan["create"] + plan["modify"]:
        if not isinstance(entry, dict):
            raise ValueError(f"create/modify entries must be objects, got: {entry!r}")
        if "path" not in entry:
            raise ValueError(f"create/modify entry missing 'path': {entry!r}")
        if "instruction" not in entry:
            entry["instruction"] = "Update as needed per the change description."

    return plan
