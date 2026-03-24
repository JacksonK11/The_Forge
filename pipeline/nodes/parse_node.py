"""
pipeline/nodes/parse_node.py
Stage 2: Blueprint Validation + Parsing.

Step 1 — Haiku validates blueprint completeness (cheap, fast).
  If incomplete, marks run as FAILED with specific questions for user.

Step 2 — Sonnet extracts full spec JSON from blueprint.
  Retrieves active meta-rules and relevant knowledge base context first.
  Stores spec JSON in the run record and in PipelineState.

CRITICAL: blueprint_text is ALWAYS treated as a raw string passed directly to
Claude. It is NEVER passed through str.format() or json.loads(). Blueprints can
contain Python code, f-strings, curly braces, backslashes, quotes — any character.
The VALIDATION_USER prompt injects the blueprint via string concatenation only.
"""

import json

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.settings import settings
from memory.database import get_session
from memory.models import ForgeRun, MetaRule, RunStatus
from pipeline.pipeline import PipelineState
from pipeline.prompts.prompts import (
    PARSE_SYSTEM,
    VALIDATION_SYSTEM,
    build_parse_prompt,
    build_validation_prompt,
)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Blueprint quality score threshold: auto-proceed if ≥70, suggest improvements if <40
_AUTO_PROCEED_SCORE = 70
_SUGGEST_IMPROVEMENTS_SCORE = 40


async def parse_node(state: PipelineState) -> PipelineState:
    """
    Execute blueprint validation, quality scoring, and parsing.
    Returns updated state with spec populated, or marks state as failed.
    """
    logger.info(f"[{state.run_id}] Parse node started")

    # ── Step 0: Blueprint quality score (Haiku, cheap) ───────────────────────
    quality_score = await _score_blueprint_quality(state)
    logger.info(f"[{state.run_id}] Blueprint quality score: {quality_score}/100")

    # Store score in DB for dashboard display
    try:
        from sqlalchemy import update
        async with get_session() as session:
            await session.execute(
                update(ForgeRun)
                .where(ForgeRun.run_id == state.run_id)
                .values(
                    spec_json={"blueprint_quality_score": quality_score}
                    if quality_score < _SUGGEST_IMPROVEMENTS_SCORE
                    else None
                )
            )
    except Exception:
        pass  # non-blocking

    if quality_score < _SUGGEST_IMPROVEMENTS_SCORE:
        error_msg = (
            f"Blueprint quality score: {quality_score}/100 (minimum 40 required). "
            "Add more detail: specify database tables, API endpoints, and the full tech stack."
        )
        logger.warning(f"[{state.run_id}] Blueprint quality too low: {quality_score}/100")
        async with get_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ForgeRun)
                .where(ForgeRun.run_id == state.run_id)
                .values(status=RunStatus.FAILED.value, error_message=error_msg)
            )
        state.errors.append(error_msg)
        state.current_stage = "failed"
        return state

    # ── Step 1: Validate blueprint with Haiku ────────────────────────────────
    validation_result = await _validate_blueprint(state)
    if not validation_result.get("is_valid", False):
        missing = validation_result.get("missing_elements", [])
        questions = validation_result.get("questions", [])
        error_msg = (
            f"Blueprint is incomplete. Missing: {', '.join(missing)}. "
            f"Please address: {' | '.join(questions)}"
        )
        logger.warning(f"[{state.run_id}] Blueprint validation failed: {error_msg}")

        async with get_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ForgeRun)
                .where(ForgeRun.run_id == state.run_id)
                .values(
                    status=RunStatus.FAILED.value,
                    error_message=error_msg,
                )
            )

        state.errors.append(error_msg)
        state.current_stage = "failed"
        return state

    logger.info(f"[{state.run_id}] Blueprint validation passed (score={quality_score}/100)")

    # ── Step 2: Retrieve meta-rules and knowledge context ────────────────────
    meta_rules = await _get_active_meta_rules()
    knowledge_context = await _get_knowledge_context(state.blueprint_text)

    # ── Step 3: Parse blueprint with Sonnet ──────────────────────────────────
    spec = await retry_async(
        _parse_blueprint,
        state.blueprint_text,
        meta_rules,
        knowledge_context,
        max_attempts=3,
        label=f"parse_blueprint:{state.run_id}",
    )

    if not spec:
        state.errors.append("Failed to parse blueprint into spec after 3 attempts")
        state.current_stage = "failed"
        return state

    # Store spec in DB
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeRun)
            .where(ForgeRun.run_id == state.run_id)
            .values(
                spec_json=spec,
                file_count=len(spec.get("file_list", [])),
            )
        )

    state.spec = spec
    state.current_stage = "confirming"

    # Notify spec is ready for approval
    try:
        from app.api.services.notify import notify_spec_ready
        await notify_spec_ready(
            run_id=state.run_id,
            title=state.title,
            file_count=len(spec.get("file_list", [])),
            service_count=len(spec.get("fly_services", [])),
        )
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Spec notification failed (non-blocking): {exc}")

    logger.info(
        f"[{state.run_id}] Parse complete: "
        f"agent='{spec.get('agent_name')}' "
        f"files={len(spec.get('file_list', []))} "
        f"services={len(spec.get('fly_services', []))}"
    )
    return state


async def _validate_blueprint(state: PipelineState) -> dict:
    """
    Use Haiku to check blueprint completeness. Returns validation result dict.

    blueprint_text is injected via build_validation_prompt() using string
    concatenation — never str.format() — so curly braces and special characters
    in the blueprint are never misinterpreted as format placeholders.
    """
    try:
        user_content = build_validation_prompt(state.blueprint_text[:8000])
        response = client.messages.create(
            model=settings.claude_fast_model,
            max_tokens=512,
            system=VALIDATION_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[{state.run_id}] Validation response not valid JSON: {exc}")
        return {"is_valid": True}  # Default to valid if validation parsing fails
    except Exception as exc:
        logger.error(f"[{state.run_id}] Blueprint validation error: {exc}")
        return {"is_valid": True}  # Fail open — don't block valid blueprints


async def _score_blueprint_quality(state: PipelineState) -> int:
    """
    Score blueprint quality 1-100 using Haiku. Fast and cheap.
    Returns integer score. Fails open at 80 on any error.
    """
    try:
        prompt = (
            "Score this blueprint document 1-100 on completeness for AI code generation.\n\n"
            "Scoring criteria:\n"
            "- 80-100: All sections clear (purpose, DB tables, endpoints, stack, env vars)\n"
            "- 60-79: Most sections present, minor gaps\n"
            "- 40-59: Core purpose clear but missing details (tables or endpoints vague)\n"
            "- 20-39: Very vague — only describes purpose, no technical detail\n"
            "- 1-19: Too short or meaningless\n\n"
            "BLUEPRINT:\n"
            + state.blueprint_text[:6000]
            + "\n\nRespond with ONLY a JSON object: {\"score\": <integer 1-100>, \"reason\": \"one sentence\"}"
        )
        response = client.messages.create(
            model=settings.claude_fast_model,
            max_tokens=100,
            system="You are a blueprint quality scorer. Respond with JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        result = json.loads(text)
        score = int(result.get("score", 80))
        logger.info(
            f"[{state.run_id}] Blueprint score: {score}/100 — {result.get('reason', '')}"
        )
        return max(1, min(100, score))
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Blueprint scoring failed (fail-open at 80): {exc}")
        return 80  # Fail open


async def _parse_blueprint(
    blueprint_text: str,
    meta_rules: list[str],
    knowledge_context: str,
) -> dict | None:
    """Use Sonnet to extract full spec JSON from blueprint."""
    prompt = build_parse_prompt(blueprint_text, meta_rules, knowledge_context)
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=32000,
            system=PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Strip markdown fences
        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                if block.startswith("{"):
                    text = block
                    break

        # If Claude added prose before the JSON, find the first {
        if not text.startswith("{"):
            start = text.find("{")
            if start != -1:
                text = text[start:]

        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Parse response not valid JSON: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Blueprint parse error: {exc}")
        raise


async def _get_active_meta_rules() -> list[str]:
    """Retrieve active meta-rules from DB for prompt injection."""
    try:
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(MetaRule)
                .where(MetaRule.is_active == True)
                .order_by(MetaRule.confidence.desc())
                .limit(15)
            )
            rules = result.scalars().all()
            return [r.rule_text for r in rules]
    except Exception as exc:
        logger.warning(f"Failed to retrieve meta-rules: {exc}")
        return []


async def _get_knowledge_context(blueprint_text: str) -> str:
    """Retrieve relevant knowledge base context for the blueprint."""
    try:
        from knowledge.retriever import retrieve_relevant_chunks
        chunks = await retrieve_relevant_chunks(blueprint_text, top_k=6)
        if not chunks:
            return ""
        return "\n\n".join(chunks)
    except Exception as exc:
        logger.warning(f"Knowledge context retrieval failed (non-blocking): {exc}")
        return ""
