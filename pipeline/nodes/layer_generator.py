"""
pipeline/nodes/layer_generator.py
Individual file code generator with evaluator loop.

For each file:
  1. Assemble context: meta-rules + knowledge base + previous files
  2. Call Claude Sonnet to generate the file
  3. Run Evaluator on the output
  4. If evaluation fails, regenerate (up to 3 attempts total)
  5. Return final content or None if all attempts fail

Also handles special files (requirements.txt, __init__.py, etc.) that have
deterministic content and don't need LLM generation.
"""

import json
import re

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.settings import settings
from memory.models import FileStatus, ForgeFile
from pipeline.prompts.prompts import (
    CODEGEN_SYSTEM,
    EVALUATOR_SYSTEM,
    EVALUATOR_USER,
    build_codegen_prompt,
)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MAX_ATTEMPTS = 3

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

            content = await retry_async(
                _generate_file_content,
                prompt,
                max_attempts=2,
                label=f"generate:{file_path}",
            )

            if not content or len(content.strip()) < 10:
                logger.warning(f"[{run_id}] Empty content for {file_path} attempt {attempt}")
                continue

            # ── Evaluator check ───────────────────────────────────────────────
            evaluation = await _evaluate_file(file_path, purpose, content)
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
        from sqlalchemy import select
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


async def _generate_file_content(prompt: str) -> str:
    """Call Claude Sonnet to generate file content."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=64000,
        system=CODEGEN_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "max_tokens":
        logger.warning(
            f"Generation hit max_tokens limit — file may be truncated. "
            f"Consider splitting into smaller modules."
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
    return content


async def _evaluate_file(file_path: str, purpose: str, content: str) -> dict:
    """
    Run the evaluator on a generated file.
    Returns evaluation dict with 'passed' bool and 'issues' list.
    """
    try:
        prompt = EVALUATOR_USER.format(
            file_path=file_path,
            purpose=purpose,
            content=content[:30000],
        )
        response = client.messages.create(
            model=settings.claude_fast_model,
            max_tokens=1024,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
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
