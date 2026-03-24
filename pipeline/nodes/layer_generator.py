"""
pipeline/nodes/layer_generator.py
Individual file code generator with evaluator loop.

For each file:
  1. Assemble context: meta-rules + knowledge base + previous files
  2. Call Claude Sonnet to generate the file (max_tokens=64000)
  3. Detect truncation — if file ends mid-function or has unclosed braces, regenerate
  4. Run Evaluator on the output
  5. If evaluation fails, regenerate (up to 3 attempts total)
  6. Return final content or None if all attempts fail

Also handles special files (requirements.txt, __init__.py, etc.) that have
deterministic content and don't need LLM generation.

Model routing (Part E):
  Code generation → claude-sonnet-4-6 (settings.claude_model)
  Evaluation → claude-haiku-4-5-20251001 (settings.claude_fast_model)
  All calls logged via config.model_config.router for cost tracking.
"""

import json
import re

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.model_config import router as model_router
from config.settings import settings
from memory.models import FileStatus, ForgeFile
from pipeline.prompts.prompts import (
    CODEGEN_SYSTEM,
    EVALUATOR_SYSTEM,
    build_codegen_prompt,
    build_evaluator_prompt,
)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MAX_ATTEMPTS = 3
MAX_TOKENS = 64000

# Files that are deterministic — skip LLM generation
TRIVIAL_FILES = {
    "__init__.py": "",
    ".gitkeep": "",
}

# Layer 2 files that use template generation instead of LLM
TEMPLATE_FILES = frozenset([
    "requirements.txt",
    "docker-compose.yml",
    ".env.example",
    ".gitignore",
])


async def generate_file_for_layer(
    run_id: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
) -> str | None:
    """
    Generate a single file. Returns content string on success, None on failure.
    Runs evaluator after generation and regenerates if evaluation fails.
    Detects truncation and regenerates with explicit continuation instruction.
    """
    file_path = file_entry["path"]
    layer = file_entry.get("layer", 1)
    purpose = file_entry.get("description", f"File at {file_path}")

    # ── Trivial files ────────────────────────────────────────────────────────
    basename = file_path.split("/")[-1]
    if basename in TRIVIAL_FILES:
        return TRIVIAL_FILES[basename]

    # ── Retrieve context for generation ──────────────────────────────────────
    meta_rules = await _get_meta_rules()
    knowledge_context = await _get_knowledge_context(file_path, purpose)

    # ── Generation loop (up to MAX_ATTEMPTS) ─────────────────────────────────
    last_evaluation: dict | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # Build prompt — inject evaluation feedback on retry
            extra_context = ""
            if last_evaluation and last_evaluation.get("issues"):
                issues_text = "\n".join(
                    f"- [{i['severity'].upper()}] {i['issue']} → Fix: {i['fix']}"
                    for i in last_evaluation["issues"]
                )
                extra_context = (
                    f"\nPREVIOUS ATTEMPT FAILED EVALUATION. Fix these issues:\n{issues_text}\n"
                )

            prompt = build_codegen_prompt(
                spec=spec,
                file_path=file_path,
                layer=layer,
                purpose=purpose + extra_context,
                previous_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
            )

            content, was_truncated = await retry_async(
                _generate_file_content,
                prompt,
                file_path=file_path,
                run_id=run_id,
                max_attempts=3,
                base_delay=5.0,
                max_delay=60.0,
                label=f"generate:{file_path}",
            )

            if not content or len(content.strip()) < 10:
                logger.warning(f"[{run_id}] Empty content for {file_path} attempt {attempt}")
                continue

            # ── Truncation detection ─────────────────────────────────────────
            if was_truncated:
                logger.warning(
                    f"[{run_id}] Truncation detected for {file_path} attempt {attempt} — regenerating"
                )
                extra_context += (
                    "\n\nPREVIOUS ATTEMPT WAS TRUNCATED — the output ended before the file was complete. "
                    "Generate the COMPLETE file from the beginning. Do not truncate. "
                    "If the file is very large, prioritise completeness over comments.\n"
                )
                if attempt < MAX_ATTEMPTS:
                    last_evaluation = None
                    continue
                # On last attempt use the truncated content rather than returning None
                logger.error(
                    f"[{run_id}] {file_path} still truncated after {attempt} attempts — using partial content"
                )
                return content

            # ── Evaluator check ───────────────────────────────────────────────
            evaluation = await _evaluate_file(file_path, purpose, content, run_id)
            if evaluation.get("passed", True):
                logger.debug(f"[{run_id}] Generated and evaluated: {file_path} (attempt {attempt})")
                return content

            last_evaluation = evaluation
            issues_count = len(evaluation.get("issues", []))
            logger.warning(
                f"[{run_id}] Evaluation failed for {file_path} attempt {attempt}: "
                f"{issues_count} issues — {evaluation.get('summary', '')}"
            )

            if attempt == MAX_ATTEMPTS:
                logger.error(
                    f"[{run_id}] {file_path} failed evaluation after {MAX_ATTEMPTS} attempts. "
                    f"Using last attempt content."
                )
                # Use last attempt rather than returning None — partial is better than missing
                return content

        except Exception as exc:
            logger.error(f"[{run_id}] Generation error for {file_path} attempt {attempt}: {exc}")
            if attempt == MAX_ATTEMPTS:
                return None

    return None


async def generate_single_file(run_id: str, file_path: str) -> None:
    """
    Regenerate a single file from a completed run.
    Used by the POST /forge/runs/{id}/regenerate/{file_path} endpoint.
    """
    from memory.database import get_session
    from memory.models import ForgeRun
    from sqlalchemy import select, update

    async with get_session() as session:
        result = await session.execute(
            select(ForgeRun).where(ForgeRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run or not run.spec_json or not run.manifest_json:
            logger.error(f"Cannot regenerate: run {run_id} missing spec or manifest")
            return

        spec = run.spec_json
        manifest = run.manifest_json

    # Load all existing generated files for context
    async with get_session() as session:
        result = await session.execute(
            select(ForgeFile).where(
                ForgeFile.run_id == run_id,
                ForgeFile.status == FileStatus.COMPLETE.value,
            )
        )
        existing_files = {f.file_path: f.content for f in result.scalars().all() if f.content}

    # Find file entry in manifest
    file_entry = next(
        (f for f in manifest.get("file_manifest", []) if f["path"] == file_path),
        {"path": file_path, "layer": 3, "description": f"Regenerated file: {file_path}"},
    )

    content = await generate_file_for_layer(
        run_id=run_id,
        file_entry=file_entry,
        spec=spec,
        generated_files=existing_files,
    )

    if content:
        async with get_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ForgeFile)
                .where(ForgeFile.run_id == run_id, ForgeFile.file_path == file_path)
                .values(status=FileStatus.COMPLETE.value, content=content)
            )
        logger.info(f"[{run_id}] Regenerated: {file_path}")
    else:
        logger.error(f"[{run_id}] Regeneration failed: {file_path}")


async def _generate_file_content(
    prompt: str,
    *,
    file_path: str = "",
    run_id: str = "",
) -> tuple[str, bool]:
    """
    Call Claude Sonnet to generate file content.
    Returns (content, was_truncated).
    Logs model + token usage via model_router for cost tracking.
    Handles context-too-long errors by trimming previous_files context.
    """
    model = settings.claude_model
    logger.debug(f"[{run_id}] Calling {model} for {file_path or 'file generation'}")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=CODEGEN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.BadRequestError as exc:
        # Context too long — trim prompt to just spec + file entry (no previous files)
        if "context_length_exceeded" in str(exc) or "too long" in str(exc).lower():
            logger.warning(
                f"[{run_id}] Context too long for {file_path} — retrying with trimmed prompt"
            )
            trimmed_prompt = _trim_prompt_to_fit(prompt)
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=CODEGEN_SYSTEM,
                messages=[{"role": "user", "content": trimmed_prompt}],
            )
        else:
            raise

    # Record usage for cost tracking — persist to DB
    if hasattr(response, "usage"):
        cost_usd = await model_router.persist_cost(
            run_id=run_id,
            stage="generating",
            model=model,
            task_type="generation",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            file_path=file_path or None,
        )
        logger.debug(
            f"[{run_id}] {model} generation: "
            f"in={response.usage.input_tokens} out={response.usage.output_tokens} "
            f"cost_usd={cost_usd:.4f}"
        )

    was_truncated = response.stop_reason == "max_tokens"
    if was_truncated:
        logger.warning(
            f"[{run_id}] Generation hit max_tokens ({MAX_TOKENS}) for {file_path} — truncation detected"
        )

    content = response.content[0].text.strip()

    # Strip markdown fences if model adds them despite instructions
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    # Additional truncation heuristics — check for obviously incomplete code
    if not was_truncated:
        was_truncated = _detect_truncation(content, file_path)

    return content, was_truncated


def _detect_truncation(content: str, file_path: str) -> bool:
    """
    Heuristic truncation detection for generated code files.
    Returns True if the content appears to be cut off mid-generation.
    """
    if not content or len(content) < 100:
        return False

    # Only apply heuristics to code files
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext not in ("py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "cs"):
        return False

    stripped = content.rstrip()

    # Python: ends mid-function (last non-empty line is not a closing statement)
    if ext == "py":
        lines = [l for l in stripped.splitlines() if l.strip()]
        if not lines:
            return False
        last = lines[-1].strip()
        # Ends with a colon = open block, comma = mid-dict/list, backslash = continuation
        if last.endswith(":") or last.endswith(",") or last.endswith("\\"):
            return True
        # Ends with an opening paren/bracket
        if last.endswith("(") or last.endswith("[") or last.endswith("{"):
            return True
        # Unclosed parentheses/brackets/braces
        open_count = content.count("(") - content.count(")")
        brace_count = content.count("{") - content.count("}")
        bracket_count = content.count("[") - content.count("]")
        if open_count > 2 or brace_count > 2 or bracket_count > 2:
            return True

    # JS/TS: unclosed braces suggest cut-off
    if ext in ("ts", "tsx", "js", "jsx"):
        brace_count = content.count("{") - content.count("}")
        if brace_count > 3:
            return True

    return False


def _trim_prompt_to_fit(prompt: str) -> str:
    """
    Trim a too-long prompt by removing the previous_files section.
    Keeps spec + file_path + purpose + meta_rules but drops prior file contents.
    """
    # Find and remove the PREVIOUSLY GENERATED FILES section
    previous_files_marker = "PREVIOUSLY GENERATED FILES"
    if previous_files_marker in prompt:
        idx = prompt.index(previous_files_marker)
        # Find where the next major section starts after the files block
        next_section = prompt.find("\n\nGENERATE FILE:", idx)
        if next_section == -1:
            next_section = prompt.find("\n\nNOW GENERATE:", idx)
        if next_section == -1:
            # Just cut the files section entirely
            trimmed = prompt[:idx] + "\n\n[Previous files omitted due to context length — generate this file independently]\n\n"
            # Re-append the final instruction if present
            return trimmed
        trimmed = (
            prompt[:idx]
            + "[Previous files omitted to reduce context length — generate this file independently]\n"
            + prompt[next_section:]
        )
        logger.info(
            f"Trimmed prompt from {len(prompt)} to {len(trimmed)} chars "
            f"by removing previous_files section"
        )
        return trimmed
    return prompt


async def _evaluate_file(file_path: str, purpose: str, content: str, run_id: str = "") -> dict:
    """
    Run the evaluator on a generated file.
    Returns evaluation dict with 'passed' bool and 'issues' list.
    Uses Haiku for cost efficiency.
    """
    try:
        model = settings.claude_fast_model
        prompt = build_evaluator_prompt(file_path, purpose, content)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        # Log Haiku usage — persist to DB
        if hasattr(response, "usage"):
            await model_router.persist_cost(
                run_id=run_id,
                stage="evaluating",
                model=model,
                task_type="evaluation",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                file_path=file_path or None,
            )
            logger.debug(
                f"[{run_id}] {model} evaluation for {file_path}: "
                f"in={response.usage.input_tokens} out={response.usage.output_tokens}"
            )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        return result
    except Exception as exc:
        logger.warning(f"Evaluator failed for {file_path} (non-blocking): {exc}")
        return {"passed": True, "issues": []}  # Fail open


async def _get_meta_rules() -> list[str]:
    """Retrieve active meta-rules."""
    try:
        from memory.database import get_session
        from memory.models import MetaRule
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(MetaRule)
                .where(MetaRule.is_active == True)
                .order_by(MetaRule.confidence.desc())
                .limit(10)
            )
            return [r.rule_text for r in result.scalars().all()]
    except Exception as exc:
        logger.warning(f"Meta-rules retrieval failed: {exc}")
        return []


async def _get_knowledge_context(file_path: str, purpose: str) -> str:
    """Get relevant knowledge base context for this file type."""
    try:
        from knowledge.retriever import retrieve_relevant_chunks
        query = f"{file_path} {purpose}"
        chunks = await retrieve_relevant_chunks(query, top_k=4)
        return "\n\n".join(chunks) if chunks else ""
    except Exception as exc:
        logger.warning(f"Knowledge context failed for {file_path}: {exc}")
        return ""
