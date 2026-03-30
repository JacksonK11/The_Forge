"""
pipeline/nodes/parse_node.py
Stage 2: Blueprint Validation + Parsing.

PREPROCESSING: Every blueprint is cleaned before any Claude call — removes
decorative characters, collapses blank lines, deduplicates paragraphs,
strips meta-text. Logs original vs compressed size.

QUALITY SCORING: Uses a representative sample (~12K chars) for large blueprints
so a detailed 200K char spec scores 75+ instead of 45.

PARSING STRATEGY (chosen automatically by input size after preprocessing):
  ≤60K chars  — single Sonnet call, max_tokens=64000
  >60K chars  — 3-stage progressive parse:
    Stage A: SKELETON — full blueprint → only names/structure (~4K tokens output)
    Stage B: DETAIL   — one Sonnet call per section, up to 4 concurrent
    Stage C: MERGE    — pure Python deep merge of partial specs

JSON TRUNCATION RECOVERY (applied to any Claude parse response):
  Attempt 1: close all open brackets/braces programmatically
  Attempt 2: find last complete top-level object boundary
  Attempt 3: send truncated JSON to Haiku to complete it

TOKEN LIMITS:
  parse/section calls: max_tokens=64000
  skeleton call:       max_tokens=4000
  per-section detail:  max_tokens=16000
"""

import asyncio
import json
import re
import time

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

# Blueprint quality score threshold
_SUGGEST_IMPROVEMENTS_SCORE = 40

# Threshold above which staged parsing is used (chars, after preprocessing)
_LARGE_BLUEPRINT_THRESHOLD = 60_000

# Max tokens per call type
_PARSE_MAX_TOKENS = 32_000      # Single-call parse — 32K covers complex multi-service specs
_SKELETON_MAX_TOKENS = 4_000
_SECTION_MAX_TOKENS = 64_000


# ── Main node ─────────────────────────────────────────────────────────────────


async def parse_node(state: PipelineState) -> PipelineState:
    """
    Execute blueprint preprocessing, quality scoring, validation, and parsing.
    Returns updated state with spec populated, or marks state as failed.
    """
    logger.info(f"[{state.run_id}] Parse node started")

    # ── Step 0: Preprocess blueprint ─────────────────────────────────────────
    original_len = len(state.blueprint_text)
    preprocessed = _preprocess_blueprint(state.blueprint_text, state.run_id)
    is_large = len(preprocessed) > _LARGE_BLUEPRINT_THRESHOLD
    logger.info(
        f"[{state.run_id}] Blueprint: {original_len:,} → {len(preprocessed):,} chars "
        f"(~{len(preprocessed)//4:,} tokens) | mode: {'staged' if is_large else 'single'}"
    )
    state.blueprint_text = preprocessed

    # Telegram alert for very large blueprints
    if len(preprocessed) > 200_000:
        try:
            from app.api.services.notify import _send as send_telegram
            chunks_est = max(1, len(preprocessed) // 40_000)
            await send_telegram(
                f"🔨 Large blueprint detected ({len(preprocessed):,} chars) — "
                f"using staged parsing (~{chunks_est} sections)"
            )
        except Exception:
            pass

    # ── Step 1: Quality score (Haiku, cheap) ─────────────────────────────────
    quality_score = await _score_blueprint_quality(state)
    logger.info(f"[{state.run_id}] Blueprint quality score: {quality_score}/100")

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
        pass

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

    # ── Step 1b: Blueprint deep validation + auto-resolve (40-70 range) ───────
    try:
        from pipeline.services.blueprint_validator import BlueprintValidator
        bv = BlueprintValidator()
        bv_result = await bv.validate(state.blueprint_text)
        bv_score = bv_result.get("score", quality_score)
        bv_summary = bv.format_for_spec_review(bv_result)
        logger.info(f"[{state.run_id}] Blueprint validator: {bv_score}/100")

        # Auto-resolve ambiguities for mid-range blueprints
        if 40 <= bv_score <= 70 and bv_result.get("ambiguities"):
            state.blueprint_text = await bv.auto_resolve(state.blueprint_text, bv_result)
            logger.info(
                f"[{state.run_id}] Blueprint auto-resolved: "
                f"{len([a for a in bv_result.get('ambiguities', []) if a.get('auto_resolvable')])} ambiguities"
            )

        # Store validation summary for spec review screen
        state.blueprint_validation = bv_summary
    except Exception as bv_exc:
        logger.warning(f"[{state.run_id}] Blueprint validator failed (non-blocking): {bv_exc}")

    # ── Step 2: Validate with Haiku ──────────────────────────────────────────
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
                .values(status=RunStatus.FAILED.value, error_message=error_msg)
            )
        state.errors.append(error_msg)
        state.current_stage = "failed"
        return state

    logger.info(f"[{state.run_id}] Blueprint validation passed (score={quality_score}/100)")

    # ── Step 3: Meta-rules and knowledge context ──────────────────────────────
    meta_rules = await _get_active_meta_rules()
    knowledge_context = await _get_knowledge_context(state.blueprint_text)

    # ── Step 4: Parse blueprint → spec JSON ──────────────────────────────────
    t0 = time.monotonic()
    if is_large:
        logger.info(
            f"[{state.run_id}] Large blueprint — using staged parse (A→B→C)"
        )
        spec = await _parse_blueprint_staged(
            state.blueprint_text, meta_rules, knowledge_context, state.run_id
        )
    else:
        spec = await retry_async(
            _parse_blueprint_single,
            state.blueprint_text,
            meta_rules,
            knowledge_context,
            state.run_id,
            max_attempts=3,
            base_delay=2.0,
            label=f"parse_blueprint:{state.run_id}",
        )

    parse_duration = time.monotonic() - t0

    if not spec:
        state.errors.append("Failed to parse blueprint into spec after all attempts")
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

    try:
        from app.api.services.notify import notify_spec_ready
        _file_count = len(spec.get("file_list", []))
        # Estimate cost: ~11,500 tokens/file at Sonnet blended rate ($4.80/M USD × 1.55 AUD/USD)
        _estimated_cost_aud = (_file_count * 11_500 / 1_000_000) * 4.80 * 1.55
        _cost_warning = _estimated_cost_aud >= 22.0  # XL build — flag for review
        await notify_spec_ready(
            run_id=state.run_id,
            title=state.title,
            file_count=_file_count,
            service_count=len(spec.get("fly_services", [])),
            estimated_cost_aud=_estimated_cost_aud,
            cost_warning=_cost_warning,
        )
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Spec notification failed (non-blocking): {exc}")

    logger.info(
        f"[{state.run_id}] Parse complete in {parse_duration:.1f}s: "
        f"agent='{spec.get('agent_name')}' "
        f"files={len(spec.get('file_list', []))} "
        f"tables={len(spec.get('database_tables', []))} "
        f"services={len(spec.get('fly_services', []))}"
    )
    return state


# ── Preprocessing ─────────────────────────────────────────────────────────────


def _preprocess_blueprint(text: str, run_id: str = "") -> str:
    """
    Clean blueprint text before any Claude call.
    Reduces token usage while preserving all meaningful content.
    """
    original_len = len(text)

    # Strip "PASTE INTO CLAUDE CODE" meta-instructions
    text = re.sub(r'#\s*PASTE INTO CLAUDE CODE[^\n]*\n?', '', text, flags=re.IGNORECASE)

    # Remove decorative box-drawing and line characters
    text = re.sub(r'[═─━┌┐└┘├┤┬┴┼│║╔╗╚╝╠╣╦╩╬▀▄█▌▐░▒▓]+', ' ', text)

    # Remove repetitive decorative patterns (====, ------, ******, ~~~~~~)
    text = re.sub(r'^[=\-*~^]{4,}\s*$', '', text, flags=re.MULTILINE)

    # Collapse multiple blank lines → single blank line
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Compress excessive spaces within lines (preserve indentation)
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        content = re.sub(r'  +', ' ', stripped)
        lines.append(indent + content)
    text = '\n'.join(lines)

    # Deduplicate substantial paragraphs (common in multi-doc blueprints)
    seen: set[str] = set()
    result_paras = []
    for para in text.split('\n\n'):
        normalized = re.sub(r'\s+', ' ', para.strip()).lower()
        if len(normalized) > 80:
            if normalized in seen:
                continue
            seen.add(normalized)
        result_paras.append(para)
    text = '\n\n'.join(result_paras).strip()

    if run_id and original_len > 0:
        reduction = 100 - int(len(text) / original_len * 100)
        logger.debug(
            f"[{run_id}] Preprocess: {original_len:,} → {len(text):,} chars "
            f"({reduction}% reduction)"
        )
    return text


def _extract_quality_sample(text: str, max_chars: int = 12_000) -> str:
    """
    Extract a representative ~12K char sample from a large blueprint.
    Takes: first 5K (intro), middle section headers + first para, last 3K (deployment).
    """
    if len(text) <= max_chars:
        return text

    parts = []

    # First 5000 chars
    parts.append(text[:5000])

    # Middle: section headers + first paragraph each
    mid_start = len(text) // 4
    mid_end = (3 * len(text)) // 4
    middle = text[mid_start:mid_end]
    header_chunks = []
    lines = middle.splitlines()
    i = 0
    while i < len(lines) and len('\n'.join(header_chunks)) < 4000:
        line = lines[i]
        if re.match(r'^#{1,4}\s+\S', line) or re.match(
            r'^(PART|PHASE|SECTION|ADDITION|CHAPTER)\s+\d', line, re.IGNORECASE
        ):
            block = [line]
            i += 1
            while i < len(lines) and len(block) < 6 and lines[i].strip():
                block.append(lines[i])
                i += 1
            header_chunks.append('\n'.join(block))
        else:
            i += 1
    if header_chunks:
        parts.append('\n\n[...]\n\n' + '\n\n'.join(header_chunks))

    # Last 3000 chars
    parts.append('\n\n[...]\n\n' + text[-3000:])

    return '\n\n'.join(parts)[:max_chars]


# ── Quality scoring ───────────────────────────────────────────────────────────


async def _score_blueprint_quality(state: PipelineState) -> int:
    """
    Score blueprint quality 1-100 using Haiku.
    Uses a representative sample for large blueprints.
    Fails open at 80 on any error.
    """
    try:
        sample = _extract_quality_sample(state.blueprint_text, max_chars=12_000)
        is_sampled = len(sample) < len(state.blueprint_text)

        size_note = (
            f"NOTE: This is a SAMPLE of a large {len(state.blueprint_text):,}-char blueprint. "
            "The full document is much more detailed — score generously if core structure is visible.\n\n"
            if is_sampled
            else ""
        )

        prompt = (
            "Score this blueprint document 1-100 on completeness for AI code generation.\n\n"
            + size_note
            + "Scoring criteria:\n"
            "- 80-100: All sections clear (purpose, DB tables, endpoints, stack, env vars)\n"
            "- 60-79: Most sections present, minor gaps\n"
            "- 40-59: Core purpose clear but missing details\n"
            "- 20-39: Very vague — only describes purpose, no technical detail\n"
            "- 1-19: Too short or meaningless\n\n"
            "BLUEPRINT" + (" SAMPLE" if is_sampled else "") + ":\n"
            + sample
            + "\n\nRespond with ONLY: {\"score\": <integer 1-100>, \"reason\": \"one sentence\"}"
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
            + (f" (sampled {len(sample):,}/{len(state.blueprint_text):,} chars)" if is_sampled else "")
        )
        return max(1, min(100, score))
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Blueprint scoring failed (fail-open at 80): {exc}")
        return 80


# ── Validation ────────────────────────────────────────────────────────────────


async def _validate_blueprint(state: PipelineState) -> dict:
    """
    Use Haiku to check blueprint completeness. Fails open if parsing fails.
    Uses first 8000 chars of the (preprocessed) blueprint.
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
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[{state.run_id}] Validation response not valid JSON: {exc}")
        return {"is_valid": True}
    except Exception as exc:
        logger.error(f"[{state.run_id}] Blueprint validation error: {exc}")
        return {"is_valid": True}


# ── Single-call parse (≤60K chars) ───────────────────────────────────────────


async def _parse_blueprint_single(
    blueprint_text: str,
    meta_rules: list[str],
    knowledge_context: str,
    run_id: str = "",
) -> dict | None:
    """
    Parse blueprint with a single Sonnet call. max_tokens=64000.
    Applies truncation recovery on any JSON decode error.
    """
    prompt = build_parse_prompt(blueprint_text, meta_rules, knowledge_context)
    try:
        response = client.messages.create(
            model=settings.claude_opus_model,
            max_tokens=_PARSE_MAX_TOKENS,
            system=PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        was_truncated = response.stop_reason == "max_tokens"
        if was_truncated:
            logger.warning(f"[{run_id}] Parse hit max_tokens — attempting recovery")

        text = _extract_json_from_response(response.content[0].text.strip())

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            recovered = _recover_truncated_json(text, run_id)
            if recovered:
                return recovered
            raise

    except json.JSONDecodeError as exc:
        logger.error(f"[{run_id}] Parse response not valid JSON: {exc}")
        raise
    except Exception as exc:
        logger.error(f"[{run_id}] Blueprint parse error: {exc}")
        raise


# ── Staged parse (>60K chars): A → B → C ─────────────────────────────────────


async def _parse_blueprint_staged(
    blueprint_text: str,
    meta_rules: list[str],
    knowledge_context: str,
    run_id: str = "",
) -> dict | None:
    """
    Progressive 3-stage parse for large blueprints:
    A) SKELETON: full blueprint → names/structure only
    B) DETAIL:   one Sonnet call per section, up to 4 concurrent
    C) MERGE:    pure Python deep merge
    Falls back to chunked sequential parse if Stage A fails.
    """
    t0 = time.monotonic()

    # ── Stage A: Skeleton ─────────────────────────────────────────────────────
    logger.info(f"[{run_id}] Stage A: extracting skeleton...")
    skeleton = await _parse_skeleton(blueprint_text, run_id)

    if not skeleton:
        logger.warning(f"[{run_id}] Stage A failed — falling back to chunked parse")
        return await _parse_blueprint_chunked(
            blueprint_text, meta_rules, knowledge_context, run_id
        )

    sections = skeleton.get("sections", [])
    logger.info(
        f"[{run_id}] Stage A complete ({time.monotonic()-t0:.1f}s): "
        f"agent='{skeleton.get('agent_name')}' "
        f"sections={len(sections)} "
        f"est_files={skeleton.get('estimated_file_count', '?')}"
    )

    if not sections:
        # No sections returned — fall back to chunked
        logger.warning(f"[{run_id}] Stage A returned no sections — falling back to chunked parse")
        return await _parse_blueprint_chunked(
            blueprint_text, meta_rules, knowledge_context, run_id
        )

    # ── Stage B: Detail per section (≤4 parallel) ────────────────────────────
    section_texts = _split_blueprint_by_sections(blueprint_text, sections)
    logger.info(
        f"[{run_id}] Stage B: {len(section_texts)} sections, "
        f"sizes: {[len(t) for _, t in section_texts]}"
    )

    semaphore = asyncio.Semaphore(4)

    async def parse_one(section_name: str, section_text: str) -> dict:
        async with semaphore:
            t_s = time.monotonic()
            result = await _parse_section_detail(
                section_name, section_text, skeleton, meta_rules, run_id
            )
            logger.debug(
                f"[{run_id}] Stage B '{section_name[:35]}': "
                f"{len(section_text):,} chars → {time.monotonic()-t_s:.1f}s"
            )
            return result

    results = await asyncio.gather(
        *[parse_one(name, text) for name, text in section_texts],
        return_exceptions=True,
    )

    valid_specs = [r for r in results if isinstance(r, dict) and r]
    failed_count = sum(1 for r in results if isinstance(r, Exception))
    if failed_count:
        logger.warning(f"[{run_id}] Stage B: {failed_count} section(s) failed (non-fatal)")

    logger.info(
        f"[{run_id}] Stage B complete ({time.monotonic()-t0:.1f}s): "
        f"{len(valid_specs)}/{len(section_texts)} sections parsed"
    )

    # ── Stage C: Merge ────────────────────────────────────────────────────────
    merged = _merge_specs([skeleton] + valid_specs)
    logger.info(
        f"[{run_id}] Stage C merge ({time.monotonic()-t0:.1f}s): "
        f"files={len(merged.get('file_list', []))} "
        f"tables={len(merged.get('database_tables', []))} "
        f"endpoints={len(merged.get('api_endpoints', []))}"
    )

    return merged if merged.get("agent_name") else None


async def _parse_skeleton(blueprint_text: str, run_id: str = "") -> dict | None:
    """
    Stage A: extract structure/names from full blueprint.
    Output is small (~2-4K tokens) — always succeeds regardless of blueprint size.
    Uses first 80K chars if blueprint is massive (skeleton only needs overview).
    """
    text = blueprint_text[:80_000] if len(blueprint_text) > 80_000 else blueprint_text

    prompt = (
        "Read this blueprint and return ONLY a JSON skeleton. "
        "Be thorough listing sections — every major topic you see.\n\n"
        "Return exactly this structure (no prose, no markdown fences):\n"
        "{\n"
        '  "agent_name": "Full human name of the agent",\n'
        '  "agent_slug": "kebab-case-slug",\n'
        '  "tech_stack": {"backend": "FastAPI Python 3.12", "database": "PostgreSQL + pgvector", '
        '"frontend": "React + Vite + Tailwind", "deployment": "Fly.io"},\n'
        '  "services": ["api", "worker", "dashboard"],\n'
        '  "database_tables": [{"name": "table_name", "purpose": "one line"}],\n'
        '  "estimated_file_count": 50,\n'
        '  "sections": [\n'
        '    {"name": "exact section name from blueprint", "summary": "one line"}\n'
        "  ]\n"
        "}\n\n"
        "BLUEPRINT:\n" + text
    )
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=_SKELETON_MAX_TOKENS,
            system=PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text_resp = _extract_json_from_response(response.content[0].text.strip())
        try:
            return json.loads(text_resp)
        except json.JSONDecodeError:
            return _recover_truncated_json(text_resp, run_id)
    except Exception as exc:
        logger.error(f"[{run_id}] Stage A skeleton error: {exc}")
        return None


async def _parse_section_detail(
    section_name: str,
    section_text: str,
    skeleton: dict,
    meta_rules: list[str],
    run_id: str = "",
) -> dict:
    """
    Stage B: extract full technical spec for one blueprint section.
    Returns partial spec JSON — only fields relevant to this section.
    """
    meta_rules_text = "\n".join(f"- {r}" for r in meta_rules[:5]) if meta_rules else ""
    skeleton_ctx = json.dumps(
        {k: v for k, v in skeleton.items() if k in ("agent_name", "agent_slug", "tech_stack", "services")},
        indent=2,
    )

    prompt = (
        f"Extract ALL technical details from the '{section_name}' section of this blueprint.\n\n"
        f"AGENT CONTEXT:\n{skeleton_ctx}\n\n"
        + (f"META-RULES:\n{meta_rules_text}\n\n" if meta_rules_text else "")
        + f"SECTION CONTENT:\n{section_text}\n\n"
        + "Return a JSON object with any/all of these fields (only include fields that have "
        "content in this section — omit empty ones):\n"
        "{\n"
        '  "agent_name": "...",\n'
        '  "agent_slug": "...",\n'
        '  "file_list": [{"path": "path/file.py", "layer": 3, "description": "purpose", "dependencies": []}],\n'
        '  "database_tables": [{"name": "tbl", "columns": [{"name": "col", "type": "String(255)", "nullable": false, "description": "..."}]}],\n'
        '  "api_endpoints": [{"path": "/api/v1/x", "method": "POST", "description": "...", "request_model": "Req", "response_model": "Resp"}],\n'
        '  "rq_jobs": [{"function": "module.fn", "trigger": "event_or_schedule", "description": "..."}],\n'
        '  "env_vars": [{"name": "VAR_NAME", "description": "purpose", "example": "value"}],\n'
        '  "fly_services": [{"name": "svc-name", "type": "api|worker|dashboard", "vm_size": "performance-cpu-4x", "memory_mb": 2048}],\n'
        '  "tech_stack": {},\n'
        '  "integrations": ["external service names"]\n'
        "}\n\n"
        "Return ONLY the JSON object. No prose."
    )
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=_SECTION_MAX_TOKENS,
            system=PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_json_from_response(response.content[0].text.strip())
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return _recover_truncated_json(text, run_id) or {}
    except Exception as exc:
        logger.error(f"[{run_id}] Stage B section '{section_name}' error: {exc}")
        return {}


def _split_blueprint_by_sections(
    blueprint_text: str, sections: list[dict]
) -> list[tuple[str, str]]:
    """
    Split blueprint text into per-section chunks using section names from Stage A.
    Each section is capped at 40K chars.
    Falls back to fixed-size character chunking if no sections can be located.
    """
    MAX_SECTION = 40_000
    text_lower = blueprint_text.lower()

    # Find positions of each section in the text
    positions: list[tuple[int, str]] = []
    for section in sections:
        name = section.get("name", "")
        if not name:
            continue
        name_lower = name.lower()
        pos = text_lower.find(name_lower)
        if pos == -1:
            # Try matching first 4 words
            words = name_lower.split()[:4]
            for n_words in range(len(words), 0, -1):
                partial = ' '.join(words[:n_words])
                if len(partial) > 8:
                    pos = text_lower.find(partial)
                    if pos != -1:
                        break
        if pos != -1:
            positions.append((pos, name))

    positions.sort(key=lambda x: x[0])

    # Deduplicate very close positions (within 100 chars)
    deduped: list[tuple[int, str]] = []
    for pos, name in positions:
        if deduped and abs(pos - deduped[-1][0]) < 100:
            continue
        deduped.append((pos, name))

    if not deduped:
        # Fall back to fixed-size character chunks
        chunks = []
        for i in range(0, len(blueprint_text), MAX_SECTION):
            chunks.append((f"Chunk {len(chunks)+1}", blueprint_text[i:i+MAX_SECTION]))
        return chunks

    result = []
    for i, (pos, name) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(blueprint_text)
        section_text = blueprint_text[pos:end]
        if len(section_text) > MAX_SECTION:
            logger.debug(
                f"Section '{name}' capped: {len(section_text):,} → {MAX_SECTION:,} chars"
            )
            section_text = section_text[:MAX_SECTION]
        if section_text.strip():
            result.append((name, section_text))

    return result or [("Full Blueprint", blueprint_text[:MAX_SECTION])]


# ── Chunked sequential fallback ───────────────────────────────────────────────


async def _parse_blueprint_chunked(
    blueprint_text: str,
    meta_rules: list[str],
    knowledge_context: str,
    run_id: str = "",
) -> dict | None:
    """
    Fallback: split blueprint into ~40K char chunks by section headers.
    Chunk 1 produces the base spec; subsequent chunks augment it.
    """
    chunks = _split_by_headers(blueprint_text, target_chunk_size=40_000)
    logger.info(
        f"[{run_id}] Chunked parse: {len(chunks)} chunks, "
        f"sizes: {[f'{len(c):,}' for c in chunks]} chars"
    )

    # Parse chunk 1 as base spec
    base_spec = await retry_async(
        _parse_blueprint_single,
        chunks[0],
        meta_rules,
        knowledge_context,
        run_id,
        max_attempts=2,
        base_delay=2.0,
        label=f"parse_chunk_0:{run_id}",
    )
    if not base_spec:
        return None

    # Parse remaining chunks with base spec as context
    for i, chunk in enumerate(chunks[1:], 1):
        logger.info(f"[{run_id}] Parsing chunk {i+1}/{len(chunks)} ({len(chunk):,} chars)")
        extra_prompt = (
            f"EXISTING SPEC SO FAR:\n{json.dumps(base_spec, indent=2)[:6000]}\n\n"
            f"Extract ADDITIONAL spec elements from this continuation of the blueprint. "
            f"Return the same JSON structure with any NEW tables, endpoints, files, etc. "
            f"Do NOT repeat items already in the existing spec.\n\n"
            f"BLUEPRINT CONTINUATION:\n{chunk}"
        )
        try:
            response = client.messages.create(
                model=settings.claude_model,
                max_tokens=_SECTION_MAX_TOKENS,
                system=PARSE_SYSTEM,
                messages=[{"role": "user", "content": extra_prompt}],
            )
            text = _extract_json_from_response(response.content[0].text.strip())
            try:
                chunk_spec = json.loads(text)
            except json.JSONDecodeError:
                chunk_spec = _recover_truncated_json(text, run_id) or {}
            if chunk_spec:
                base_spec = _merge_specs([base_spec, chunk_spec])
        except Exception as exc:
            logger.warning(f"[{run_id}] Chunk {i+1} failed (non-fatal): {exc}")

    return base_spec


# ── JSON helpers ──────────────────────────────────────────────────────────────


def _extract_json_from_response(text: str) -> str:
    """Strip markdown fences and leading prose from a Claude response to isolate JSON."""
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                return block
    if not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            return text[start:]
    return text


def _recover_truncated_json(text: str, run_id: str = "") -> dict | None:
    """
    Attempt to recover a valid JSON dict from a truncated response.

    Attempt 1: Close all open brackets/braces programmatically.
    Attempt 2: Trim to last complete top-level object boundary.
    Attempt 3: Send to Haiku to complete the structure.
    """
    cleaned = _extract_json_from_response(text)
    if not cleaned.startswith("{"):
        return None

    # Attempt 1: close open brackets
    attempt1 = _close_open_brackets(cleaned)
    if attempt1:
        try:
            result = json.loads(attempt1)
            logger.info(f"[{run_id}] Truncation recovery: attempt 1 (bracket close) succeeded")
            return result
        except json.JSONDecodeError:
            pass

    # Attempt 2: trim to last complete value
    attempt2 = _trim_to_last_complete(cleaned)
    if attempt2 and attempt2 != cleaned:
        try:
            result = json.loads(attempt2)
            logger.info(f"[{run_id}] Truncation recovery: attempt 2 (trim to boundary) succeeded")
            return result
        except json.JSONDecodeError:
            pass

    # Attempt 3: ask Haiku to complete it
    try:
        sample = cleaned[:8000]
        response = client.messages.create(
            model=settings.claude_fast_model,
            max_tokens=2000,
            system="You complete truncated JSON. Return ONLY valid JSON — no prose, no fences.",
            messages=[{"role": "user", "content": (
                "This JSON was truncated mid-generation. Complete it so it is valid. "
                "Close all open arrays and objects. Preserve all existing data. "
                "Return ONLY the complete valid JSON:\n\n" + sample
            )}],
        )
        completed = _extract_json_from_response(response.content[0].text.strip())
        result = json.loads(completed)
        logger.info(f"[{run_id}] Truncation recovery: attempt 3 (Haiku completion) succeeded")
        return result
    except Exception as exc:
        logger.warning(f"[{run_id}] Truncation recovery attempt 3 failed: {exc}")

    # Attempt 4: ask Sonnet to extract structured data from the malformed response
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            system="You extract structured data from malformed JSON. Return ONLY valid JSON — no prose, no fences.",
            messages=[{"role": "user", "content": (
                "Extract all structured data from this malformed JSON response and return valid JSON. "
                "Original text:\n\n" + text[:8000]
            )}],
        )
        completed = _extract_json_from_response(response.content[0].text.strip())
        result = json.loads(completed)
        logger.info(f"[{run_id}] Truncation recovery: attempt 4 (Sonnet extraction) succeeded")
        return result
    except Exception as exc:
        logger.warning(f"[{run_id}] Truncation recovery attempt 4 failed: {exc}")
        raise

    return None


def _close_open_brackets(text: str) -> str:
    """Close all unclosed brackets, braces, and string values in a JSON string."""
    stack: list[str] = []
    in_string = False
    escape_next = False

    for char in text:
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if char in '{[':
                stack.append(char)
            elif char in '}]':
                if stack:
                    stack.pop()

    suffix = ''
    if in_string:
        suffix += '"'
    for bracket in reversed(stack):
        suffix += '}' if bracket == '{' else ']'

    return text + suffix


def _trim_to_last_complete(text: str) -> str | None:
    """Find the last position where the JSON top-level structure is balanced."""
    depth = 0
    in_string = False
    escape_next = False
    last_balanced = -1

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if char in '{[':
                depth += 1
            elif char in '}]':
                depth -= 1
                if depth == 0:
                    last_balanced = i + 1

    if last_balanced > 0:
        return text[:last_balanced]
    return None


# ── Spec merge ────────────────────────────────────────────────────────────────


def _merge_specs(specs: list[dict]) -> dict:
    """
    Deep merge partial spec dicts into one complete spec.
    Arrays: concatenated with deduplication by primary key field.
    Dicts: merged (later values win on conflict).
    Scalars: last non-empty value wins.
    """
    if not specs:
        return {}
    if len(specs) == 1:
        return dict(specs[0])

    # Array fields and their deduplication key
    ARRAY_FIELDS: dict[str, str | None] = {
        "file_list": "path",
        "database_tables": "name",
        "api_endpoints": "path",
        "rq_jobs": "function",
        "env_vars": "name",
        "fly_services": "name",
        "integrations": None,
        "sections": "name",
    }

    result: dict = {}

    for spec in specs:
        if not isinstance(spec, dict):
            continue
        for key, value in spec.items():
            if key in ARRAY_FIELDS:
                dedup_key = ARRAY_FIELDS[key]
                existing = result.get(key, [])
                if not isinstance(existing, list):
                    existing = []
                if isinstance(value, list):
                    if dedup_key:
                        existing_keys: set = {
                            item.get(dedup_key)
                            for item in existing
                            if isinstance(item, dict)
                        }
                        for item in value:
                            if isinstance(item, dict):
                                item_key = item.get(dedup_key)
                                if item_key not in existing_keys:
                                    existing.append(item)
                                    existing_keys.add(item_key)
                            elif item not in existing:
                                existing.append(item)
                    else:
                        for item in value:
                            if item not in existing:
                                existing.append(item)
                result[key] = existing
            elif isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = {**result[key], **value}
            elif value not in (None, "", [], {}):
                result[key] = value

    return result


# ── Section/chunk splitting ───────────────────────────────────────────────────


def _split_by_headers(text: str, target_chunk_size: int = 40_000) -> list[str]:
    """
    Split text into chunks of ~target_chunk_size chars, never mid-section.
    Detects common blueprint section header patterns.
    """
    header_re = re.compile(
        r'^(?:#{1,4}\s+\S|PART\s+\d|PHASE\s+\d|SECTION\s+\d|ADDITION\s+\d|CHAPTER\s+\d)',
        re.IGNORECASE | re.MULTILINE,
    )

    boundaries = [0]
    for m in header_re.finditer(text):
        if m.start() > 0:
            boundaries.append(m.start())
    boundaries.append(len(text))

    chunks: list[str] = []
    current = ""

    for i in range(len(boundaries) - 1):
        section = text[boundaries[i]:boundaries[i + 1]]
        if len(current) + len(section) > target_chunk_size and current:
            chunks.append(current)
            current = section
        else:
            current += section

    if current:
        chunks.append(current)

    return chunks or [text]


# ── DB helpers ────────────────────────────────────────────────────────────────


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
            return [r.rule_text for r in result.scalars().all()]
    except Exception as exc:
        logger.warning(f"Failed to retrieve meta-rules: {exc}")
        return []


async def _get_knowledge_context(blueprint_text: str) -> str:
    """Retrieve relevant knowledge base context for the blueprint."""
    try:
        from knowledge.retriever import retrieve_relevant_chunks
        # Use first 2000 chars of blueprint as search query
        query = blueprint_text[:2000]
        chunks = await retrieve_relevant_chunks(query, top_k=6)
        return "\n\n".join(chunks) if chunks else ""
    except Exception as exc:
        logger.warning(f"Knowledge context retrieval failed (non-blocking): {exc}")
        return ""
