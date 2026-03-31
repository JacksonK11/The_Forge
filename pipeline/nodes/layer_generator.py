"""
pipeline/nodes/layer_generator.py
Individual file code generator with evaluator loop.

For each file:
  1. Detect complexity — complex files go directly to split generation
  2. Assemble context: meta-rules + knowledge base + previous files
  3. Call Claude to generate the file
  4. On TruncatedOutputError: fall back to split generation (2 sequential calls)
  5. Run Evaluator on the output (Haiku)
  6. If evaluation fails, regenerate up to MAX_ATTEMPTS total
  7. On total failure: return None (codegen_node saves a placeholder)

Split generation (for complex files and truncation fallbacks):
  - Part 1: all imports + first half of functions, max_tokens=SPLIT_MAX_TOKENS
  - Part 2: last 50 lines of Part 1 as context + continuation, max_tokens=SPLIT_MAX_TOKENS
  - Duplicate imports stripped from Part 2 before concatenation

Model routing:
  Code generation → settings.claude_model  (Sonnet/Opus per env config)
  Evaluation      → settings.claude_fast_model  (Haiku — cheap, fast)
"""

import ast
import asyncio
import json
import re

import anthropic
from loguru import logger

from app.api.services.retry import TruncatedOutputError, retry_async
from config.model_config import router as model_router
from config.settings import settings
from memory.models import FileStatus, ForgeFile
from intelligence.evaluator import _run_static_checks
from pipeline.prompts.prompts import (
    CODEGEN_SYSTEM,
    EVALUATOR_SYSTEM,
    build_codegen_prompt,
    build_evaluator_prompt,
)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MAX_ATTEMPTS = 3
MAX_TOKENS = 16000
SPLIT_MAX_TOKENS = 16000  # Per-part token limit for split generation (~640 lines each)
_AUTOFIX_MODEL = settings.claude_model  # Use configured Sonnet — updates automatically

# Purpose/path keywords that indicate a file will be too large for one call
_COMPLEX_KEYWORDS = frozenset([
    "execution",
    "pipeline",
    "assembler",
    "orchestrat",
    "engine",
    "coordinator",
    "dispatcher",
])

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


# ── Public entry point ────────────────────────────────────────────────────────


async def generate_file_for_layer(
    run_id: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    dependency_manifest: str = "",
    diagnosis_context: str = "",
) -> str | None:
    """
    Generate a single file. Returns content string on success, None on total failure.

    Complex files (large/orchestration-heavy) bypass the attempt loop and go
    straight to split generation. Normal files use the attempt loop with an
    automatic split fallback on TruncatedOutputError.

    Args:
        dependency_manifest: Optional formatted manifest of prior-layer exports.
                             Injected before file instructions so Claude knows
                             exactly which names and paths already exist.
        diagnosis_context:   Optional build-doctor repair instructions injected
                             at the top of the prompt for targeted regeneration.

    Returns None if all strategies fail — codegen_node will save a placeholder.
    """
    file_path = file_entry["path"]
    layer = file_entry.get("layer", 1)
    purpose = file_entry.get("description", f"File at {file_path}")
    estimated_lines = file_entry.get("estimated_lines", 0)

    # ── Trivial files ────────────────────────────────────────────────────────
    basename = file_path.split("/")[-1]
    if basename in TRIVIAL_FILES:
        return TRIVIAL_FILES[basename]

    # ── Template library lookup — use proven template as starting point ───────
    if not diagnosis_context:  # Don't override repair instructions with templates
        try:
            from pipeline.services.template_library import TemplateLibrary, _classify_file_type
            file_type = _classify_file_type(file_path)
            if file_type:
                tl = TemplateLibrary()
                template = await tl.get_template(file_type, spec)
                if template:
                    diagnosis_context = await tl.enhance_generation(file_entry, spec, template)
                    logger.debug(f"[{run_id}] Template library: using '{file_type}' template for {file_path}")
        except Exception as tl_exc:
            logger.debug(f"[{run_id}] Template library lookup failed (non-blocking): {tl_exc}")

    # ── Shared context (same for all attempts) ────────────────────────────────
    # Use full context assembler: KB patterns + meta-rules + knowledge chunks + live search
    assembled = await _assemble_generation_context(file_path, purpose)
    meta_rules = assembled["meta_rules"]
    knowledge_context = assembled["knowledge_context"]

    # ── Complex files: skip retry loop, go straight to split generation ───────
    if _is_complex_file(file_path, purpose, estimated_lines):
        logger.info(f"[{run_id}] Complex file detected — using split generation: {file_path}")
        content = await _generate_file_split(
            run_id=run_id,
            file_path=file_path,
            file_entry=file_entry,
            spec=spec,
            generated_files=generated_files,
            meta_rules=meta_rules,
            knowledge_context=knowledge_context,
            dependency_manifest=dependency_manifest,
            diagnosis_context=diagnosis_context,
        )
        if content:
            evaluation = await _evaluate_file(file_path, purpose, content, run_id)
            if not evaluation.get("passed", True):
                issues = len(evaluation.get("issues", []))
                logger.warning(
                    f"[{run_id}] Split-generated {file_path} has {issues} evaluation issues "
                    f"— using content anyway (re-splitting would double cost)"
                )
            return content
        logger.error(f"[{run_id}] Split generation failed for {file_path} — returning None for placeholder")
        return None

    # ── Normal generation loop (up to MAX_ATTEMPTS) ───────────────────────────
    last_evaluation: dict | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            extra_context = ""

            # Build-doctor diagnosis context takes priority at the top
            if diagnosis_context:
                extra_context = f"CRITICAL BUILD DOCTOR INSTRUCTIONS:\n{diagnosis_context}\n\n"

            if last_evaluation and last_evaluation.get("issues"):
                issues_text = "\n".join(
                    f"- [{i['severity'].upper()}] {i['issue']} → Fix: {i['fix']}"
                    for i in last_evaluation["issues"]
                )
                extra_context += (
                    f"\nPREVIOUS ATTEMPT FAILED EVALUATION. Fix these issues:\n{issues_text}\n"
                )

            # Dependency manifest prepended before file instructions
            manifest_prefix = (
                f"{dependency_manifest}\n\nNow generate the following file...\n\n"
                if dependency_manifest
                else ""
            )

            prompt = build_codegen_prompt(
                spec=spec,
                file_path=file_path,
                layer=layer,
                purpose=manifest_prefix + purpose + extra_context,
                previous_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
            )

            try:
                content = await retry_async(
                    _generate_file_content,
                    prompt,
                    file_path=file_path,
                    run_id=run_id,
                    purpose=purpose,
                    spec=spec,
                    max_attempts=3,
                    base_delay=5.0,
                    max_delay=60.0,
                    label=f"generate:{file_path}",
                    no_retry_on=(TruncatedOutputError,),
                )
            except TruncatedOutputError:
                # Truncation: same prompt will truncate again. Use split generation instead.
                logger.warning(
                    f"[{run_id}] Truncation on {file_path} attempt {attempt} "
                    f"— falling back to split generation"
                )
                split_content = await _generate_file_split(
                    run_id=run_id,
                    file_path=file_path,
                    file_entry=file_entry,
                    spec=spec,
                    generated_files=generated_files,
                    meta_rules=meta_rules,
                    knowledge_context=knowledge_context,
                )
                if split_content:
                    return split_content
                logger.error(f"[{run_id}] Split fallback failed for {file_path} — returning None")
                return None
            except Exception as gen_exc:
                logger.error(
                    f"[{run_id}] Generation exception for {file_path} "
                    f"attempt {attempt}: {gen_exc}"
                )
                if attempt == MAX_ATTEMPTS:
                    return None
                continue

            if not content or len(content.strip()) < 50:
                logger.warning(f"[{run_id}] Minimal content for {file_path} attempt {attempt}")
                continue

            # ── Evaluator ─────────────────────────────────────────────────────
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
                return content

        except Exception as exc:
            logger.error(f"[{run_id}] Outer generation error for {file_path} attempt {attempt}: {exc}")
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

    async with get_session() as session:
        result = await session.execute(
            select(ForgeFile).where(
                ForgeFile.run_id == run_id,
                ForgeFile.status == FileStatus.COMPLETE.value,
            )
        )
        existing_files = {f.file_path: f.content for f in result.scalars().all() if f.content}

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


# ── Split generation ──────────────────────────────────────────────────────────


def _is_complex_file(file_path: str, purpose: str, estimated_lines: int = 0) -> bool:
    """
    Return True if this file warrants split generation.

    Triggers on:
      - Purpose or path contains a complexity keyword (execution, pipeline, etc.)
      - Architecture manifest estimated_lines > 200
    """
    combined = (purpose + " " + file_path).lower()
    if any(kw in combined for kw in _COMPLEX_KEYWORDS):
        return True
    if estimated_lines > 200:
        return True
    return False


async def _generate_file_split(
    *,
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    meta_rules: list[str],
    knowledge_context: str,
    dependency_manifest: str = "",
    diagnosis_context: str = "",
) -> str | None:
    """
    Generate a complex file in two sequential Claude calls.

    Part 1: all imports, constants, class definitions, and the first half
            of function implementations. Ends at a clean function boundary.
    Part 2: receives the last 50 lines of Part 1 as context and generates
            the remaining functions to complete the file.

    Duplicate import lines are stripped from Part 2 before concatenation.
    Returns the merged content string, or None if both parts fail.
    """
    layer = file_entry.get("layer", 1)
    purpose = file_entry.get("description", f"File at {file_path}")

    # Inject dependency manifest and diagnosis context into purpose
    purpose_prefix = ""
    if diagnosis_context:
        purpose_prefix += f"CRITICAL BUILD DOCTOR INSTRUCTIONS:\n{diagnosis_context}\n\n"
    if dependency_manifest:
        purpose_prefix += f"{dependency_manifest}\n\nNow generate the following file...\n\n"

    base_prompt = build_codegen_prompt(
        spec=spec,
        file_path=file_path,
        layer=layer,
        purpose=purpose_prefix + purpose,
        previous_files=generated_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    # ── Part 1: structure + first half ────────────────────────────────────────
    part1_prompt = (
        base_prompt
        + "\n\n"
        + "SPLIT GENERATION — PART 1 OF 2:\n"
        + "This is a large file generated in two sequential parts to guarantee completeness.\n"
        + "Generate Part 1: ALL imports, ALL constants, ALL class definitions, "
        + "and COMPLETE implementations for the first half of functions (by logical grouping).\n"
        + "You MUST end at a clean function boundary — never cut off mid-function.\n"
        + "CRITICAL: Do NOT close the class, do NOT add `if __name__ == '__main__'`, "
        + "and do NOT write any module-closing remarks — this file continues in Part 2.\n"
        + "Do NOT add any closing comments, module summary, or 'end of Part 1' marker. "
        + "Just end with complete, valid Python at a clean function boundary."
    )

    part1_content: str = ""
    try:
        part1_content = await retry_async(
            _generate_file_content,
            part1_prompt,
            file_path=file_path,
            run_id=run_id,
            max_tokens=SPLIT_MAX_TOKENS,
            max_attempts=2,
            base_delay=5.0,
            max_delay=30.0,
            label=f"split-part1:{file_path}",
            no_retry_on=(TruncatedOutputError,),
        )
    except TruncatedOutputError as exc:
        # Part 1 itself truncated — use partial content as context for Part 2
        logger.warning(
            f"[{run_id}] Part 1 of {file_path} was truncated — "
            f"using partial content as context for Part 2"
        )
        part1_content = exc.partial_content
    except Exception as exc:
        logger.error(f"[{run_id}] Part 1 generation failed for {file_path}: {exc}")
        return None

    if not part1_content or len(part1_content.strip()) < 50:
        logger.error(f"[{run_id}] Part 1 returned empty content for {file_path}")
        return None

    # ── Part 2: continuation using last 50 lines of Part 1 as context ─────────
    last_50_lines = "\n".join(part1_content.splitlines()[-50:])

    part2_prompt = (
        base_prompt
        + "\n\n"
        + "SPLIT GENERATION — PART 2 OF 2:\n"
        + "You are continuing a file that was started in Part 1. "
        + "You are generating the CONTINUATION ONLY — not a new file.\n\n"
        + "Part 1 ends with:\n"
        + "```python\n"
        + last_50_lines
        + "\n```\n\n"
        + "Continue IMMEDIATELY from exactly where Part 1 ended.\n"
        + "ABSOLUTE RULES for Part 2:\n"
        + "  - Do NOT repeat any imports already in Part 1 — not a single one\n"
        + "  - Do NOT repeat any class definitions, constants, or functions already written\n"
        + "  - Do NOT echo back any code shown above — start with the very next function\n"
        + "  - Generate ONLY the remaining functions needed to complete the file\n"
        + "  - Every remaining function must be fully implemented — no stubs or pass statements\n"
        + "  - The combined Part 1 + Part 2 must be a complete, syntactically valid Python file\n"
        + "  - You MAY add `if __name__ == '__main__'` only if the file genuinely needs it"
    )

    part2_content: str = ""
    try:
        part2_content = await retry_async(
            _generate_file_content,
            part2_prompt,
            file_path=file_path,
            run_id=run_id,
            max_tokens=SPLIT_MAX_TOKENS,
            max_attempts=2,
            base_delay=5.0,
            max_delay=30.0,
            label=f"split-part2:{file_path}",
            no_retry_on=(TruncatedOutputError,),
        )
    except TruncatedOutputError as exc:
        # Part 2 truncated — merge what we have; better than nothing
        logger.warning(
            f"[{run_id}] Part 2 of {file_path} was truncated — merging partial content"
        )
        part2_content = exc.partial_content
    except Exception as exc:
        logger.error(
            f"[{run_id}] Part 2 generation failed for {file_path}: {exc} — returning Part 1 only"
        )
        return part1_content if len(part1_content.strip()) > 100 else None

    if not part2_content or len(part2_content.strip()) < 20:
        logger.warning(
            f"[{run_id}] Part 2 returned minimal content for {file_path} — returning Part 1 only"
        )
        return part1_content

    merged = await _deduplicate_and_validate(part1_content, part2_content, file_path, run_id)
    if merged is None:
        logger.error(
            f"[{run_id}] Deduplication/validation failed for {file_path} — "
            f"returning Part 1 only as fallback"
        )
        return part1_content if len(part1_content.strip()) > 100 else None
    logger.info(
        f"[{run_id}] Split generation complete for {file_path}: "
        f"{len(merged.splitlines())} lines total"
    )
    return merged


async def _deduplicate_and_validate(
    part1: str,
    part2: str,
    file_path: str,
    run_id: str,
) -> str | None:
    """
    Merge Part 1 and Part 2 into a validated, deduplicated file.

    Steps:
      1. Strip duplicate import lines from Part 2 (import-level dedup)
      2. If ast.parse succeeds → also dedup duplicate function/class definitions
         keeping the longer (more complete) version
      3. Final ast.parse gate — file must be syntactically valid
      4. If ast.parse fails → one auto-fix pass via Claude Sonnet
      5. Return content only once ast.parse confirms valid Python

    For non-Python files: performs import dedup and returns without ast checks.
    Returns None if all validation attempts fail.
    """
    # Step 1: Merge with duplicate import removal
    merged = _strip_duplicate_imports(part1, part2)

    if not file_path.endswith(".py"):
        return merged  # No ast checks for non-Python files

    # Step 2: Try ast-based function/class dedup (only works on valid syntax)
    try:
        ast.parse(merged)
        deduped, warnings = _dedup_definitions_ast(merged)
        for w in warnings:
            logger.warning(f"[{run_id}] Split dedup: {w}")
        merged = deduped
    except SyntaxError:
        # Syntax errors present — skip ast dedup, go straight to auto-fix
        logger.warning(
            f"[{run_id}] Merged split has syntax errors for {file_path} — "
            f"attempting auto-fix pass"
        )
        fixed = await _auto_fix_syntax(merged, run_id, file_path)
        if not fixed:
            return None
        merged = fixed

    # Step 3: Final ast.parse gate
    try:
        ast.parse(merged)
        return merged
    except SyntaxError as exc:
        logger.error(
            f"[{run_id}] Final ast.parse failed for {file_path} after dedup: {exc}"
        )
        return None


def _strip_duplicate_imports(part1: str, part2: str) -> str:
    """
    Merge Part 1 and Part 2, stripping duplicate import lines from the
    top of Part 2 to prevent redefinition errors.
    """
    part1_imports: set[str] = set()
    for line in part1.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            part1_imports.add(stripped)

    part2_lines = part2.splitlines()
    filtered: list[str] = []
    past_header = False

    for line in part2_lines:
        stripped = line.strip()
        if not past_header:
            if not stripped:
                continue  # skip leading blank lines
            if stripped.startswith("import ") or stripped.startswith("from "):
                if stripped in part1_imports:
                    continue  # skip duplicate import
                filtered.append(line)
                continue
            past_header = True
        filtered.append(line)

    return part1.rstrip() + "\n\n\n" + "\n".join(filtered)


def _dedup_definitions_ast(content: str) -> tuple[str, list[str]]:
    """
    Remove duplicate top-level function/class definitions using ast,
    keeping the longer (more complete) version of each duplicate.

    Returns (deduplicated_content, list_of_warning_messages).
    Only called when content is already syntactically valid.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content, []

    lines = content.splitlines(keepends=True)

    # Map name → list of (start_line, end_line) — 1-indexed from ast
    defs: dict[str, list[tuple[int, int]]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            defs.setdefault(node.name, []).append((start, end))

    duplicates = {name: ranges for name, ranges in defs.items() if len(ranges) > 1}
    if not duplicates:
        return content, []

    lines_to_remove: set[int] = set()  # 0-indexed
    warnings: list[str] = []

    for name, ranges in duplicates.items():
        # Sort by length desc — keep the longest (most complete) definition
        sorted_ranges = sorted(ranges, key=lambda r: r[1] - r[0], reverse=True)
        keep_start, keep_end = sorted_ranges[0]
        for start, end in sorted_ranges[1:]:
            for idx in range(start - 1, end):  # ast is 1-indexed, list is 0-indexed
                lines_to_remove.add(idx)
            warnings.append(
                f"Duplicate '{name}': removed lines {start}–{end}, "
                f"keeping lines {keep_start}–{keep_end} (longer version)"
            )

    filtered = [line for i, line in enumerate(lines) if i not in lines_to_remove]
    return "".join(filtered), warnings


async def _auto_fix_syntax(content: str, run_id: str, file_path: str) -> str | None:
    """
    Send syntactically broken Python to Claude Sonnet with a fix-only instruction.
    Does NOT add new functionality — only repairs syntax so ast.parse passes.
    Returns fixed content if ast.parse succeeds, None otherwise.
    """
    from config.model_config import router as model_router

    logger.info(f"[{run_id}] Auto-fix pass starting for {file_path}")

    prompt = (
        "Fix the syntax errors in this Python file. "
        "Do not add new functionality, do not remove existing logic. "
        "Only fix syntax errors so the file passes ast.parse. "
        "Output the complete fixed file with no markdown fences.\n\n"
        "FILE: " + file_path + "\n\n"
        + content[:30000]
    )

    try:
        response = client.messages.create(
            model=_AUTOFIX_MODEL,
            max_tokens=SPLIT_MAX_TOKENS,
            system=CODEGEN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        if hasattr(response, "usage"):
            await model_router.persist_cost(
                run_id=run_id,
                stage="generating",
                model=_AUTOFIX_MODEL,
                task_type="generation",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                file_path=file_path,
            )
            model_router.record_usage(
                model=_AUTOFIX_MODEL,
                task_type="generation",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                run_id=run_id,
                stage="generating",
                file_path=file_path,
            )

        fixed = response.content[0].text.strip()
        if fixed.startswith("```"):
            lines = fixed.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            fixed = "\n".join(lines)

        ast.parse(fixed)
        logger.info(f"[{run_id}] Auto-fix succeeded for {file_path}")
        return fixed

    except SyntaxError:
        logger.error(f"[{run_id}] Auto-fix produced invalid Python for {file_path}")
        return None
    except Exception as exc:
        logger.error(f"[{run_id}] Auto-fix call failed for {file_path}: {exc}")
        return None


# ── Core Claude generation call ───────────────────────────────────────────────


async def _generate_file_content(
    prompt: str,
    *,
    file_path: str = "",
    run_id: str = "",
    max_tokens: int = MAX_TOKENS,
    purpose: str = "",
    spec: dict | None = None,
) -> str:
    """
    Call Claude to generate file content.

    Returns content string on success.
    Raises TruncatedOutputError if output was cut off (stop_reason==max_tokens
    or heuristic truncation detected).

    Logs model + token usage via model_router for cost tracking and the
    in-memory usage log (used by test_split_generation.py for cost reporting).
    """
    model = settings.claude_model
    logger.debug(f"[{run_id}] Calling {model} for {file_path or 'file generation'} (max_tokens={max_tokens})")

    _RATE_LIMIT_MAX_RETRIES = 3
    _rate_limit_attempt = 0
    while True:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=CODEGEN_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError as exc:
            _rate_limit_attempt += 1
            wait = getattr(exc, "retry_after", None) or 60
            if _rate_limit_attempt > _RATE_LIMIT_MAX_RETRIES:
                logger.error(
                    f"[{run_id}] Rate limit exceeded after {_RATE_LIMIT_MAX_RETRIES} retries "
                    f"for {file_path} — re-raising"
                )
                raise
            logger.warning(
                f"[{run_id}] Rate limited — waiting {wait}s before retry "
                f"{_rate_limit_attempt}/{_RATE_LIMIT_MAX_RETRIES}"
            )
            await asyncio.sleep(wait)
        except anthropic.BadRequestError as exc:
            if "context_length_exceeded" in str(exc) or "too long" in str(exc).lower():
                logger.warning(
                    f"[{run_id}] Context too long for {file_path} — retrying with trimmed prompt"
                )
                trimmed_prompt = _trim_prompt_to_fit(prompt)
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=CODEGEN_SYSTEM,
                    messages=[{"role": "user", "content": trimmed_prompt}],
                )
                break
            else:
                raise

    # Track usage for cost dashboard (DB) and in-memory reporting (tests)
    if hasattr(response, "usage"):
        await model_router.persist_cost(
            run_id=run_id,
            stage="generating",
            model=model,
            task_type="generation",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            file_path=file_path or None,
        )
        # Also update in-memory log so model_router.get_usage_summary() reflects this call
        model_router.record_usage(
            model=model,
            task_type="generation",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            run_id=run_id,
            stage="generating",
            file_path=file_path or None,
        )
        logger.debug(
            f"[{run_id}] {model} generation: "
            f"in={response.usage.input_tokens} out={response.usage.output_tokens}"
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

    # Truncation detection: stop_reason==max_tokens is definitive
    if response.stop_reason == "max_tokens":
        logger.warning(
            f"[{run_id}] Generation hit max_tokens={max_tokens} for {file_path} — truncated"
        )
        raise TruncatedOutputError(
            f"Output hit max_tokens={max_tokens} for {file_path}",
            partial_content=content,
        )

    # Heuristic truncation: catches mid-function cuts that stop before max_tokens
    if _detect_truncation(content, file_path):
        logger.warning(
            f"[{run_id}] Truncation heuristic triggered for {file_path} — raising TruncatedOutputError"
        )
        raise TruncatedOutputError(
            f"Truncation detected by heuristic for {file_path}",
            partial_content=content,
        )

    # Semantic completeness: catches model stopping early with syntactically valid stubs
    if _check_semantic_completeness(content, file_path, purpose=purpose, spec=spec):
        logger.warning(
            f"[{run_id}] Semantic incompleteness detected for {file_path} "
            f"— model closed with stubs instead of real logic — raising TruncatedOutputError"
        )
        raise TruncatedOutputError(
            f"Semantic incompleteness for {file_path}",
            partial_content=content,
        )

    return content


# ── Truncation detection ──────────────────────────────────────────────────────


def _detect_truncation(content: str, file_path: str) -> bool:
    """
    Heuristic truncation detection for generated code files.
    Returns True if the content appears to be cut off mid-generation.

    Checks:
      - Last non-empty line ends with a colon, comma, backslash, or open bracket
        (all indicate an open block that was never closed)
      - Significantly unbalanced parentheses/braces/brackets
      - Unclosed triple-quoted string literals (Python)
      - ast.parse failure for Python files (definitive syntax check)
    """
    if not content or len(content) < 100:
        return False

    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext not in ("py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "cs"):
        return False

    stripped = content.rstrip()
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1].strip()

    if ext == "py":
        # Definitive check: try ast.parse first — catches all syntax issues including
        # unterminated strings, unclosed brackets, missing dedents, etc.
        try:
            ast.parse(content)
        except SyntaxError:
            return True

        # Open block indicators (redundant but kept for speed on valid files)
        if last.endswith(":") or last.endswith(",") or last.endswith("\\"):
            return True
        if last.endswith("(") or last.endswith("[") or last.endswith("{"):
            return True
        # Significantly unbalanced delimiters (> 2 tolerance for nested structures)
        if content.count("(") - content.count(")") > 2:
            return True
        if content.count("{") - content.count("}") > 2:
            return True
        if content.count("[") - content.count("]") > 2:
            return True

    if ext in ("ts", "tsx", "js", "jsx"):
        if content.count("{") - content.count("}") > 3:
            return True

    return False


# ── Semantic completeness check ───────────────────────────────────────────────


def _check_semantic_completeness(
    content: str,
    file_path: str,
    purpose: str = "",
    spec: dict | None = None,
) -> bool:
    """
    Detect semantic incompleteness in syntactically valid Python.

    Catches the silent-truncation gap: the model ran out of generation budget
    but produced valid Python by closing every open block with pass/return None
    instead of real implementation. ast.parse passes, but the file is broken.

    Two checks:
      1. Stub-ending: last top-level definition has 0 real statements while
         earlier definitions have substantive logic (model stopped early and
         closed cleanly to avoid a SyntaxError).
      2. Model-file table coverage: for files with "model/schema/entity/table"
         in their path, every database table from the spec should appear in the
         output. Missing tables → file was cut before all models were written.

    Returns True if the file appears semantically incomplete.
    """
    if not file_path.endswith(".py") or not content:
        return False

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return True  # Syntax failure is always truncation

    top_defs = [
        n for n in tree.body
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not top_defs:
        return False

    def _real_stmt_count(body: list) -> int:
        """Count substantive statements — excludes pass, ellipsis, bare return None, docstrings."""
        count = 0
        for stmt in body:
            if isinstance(stmt, ast.Pass):
                continue
            val = getattr(stmt, "value", None)
            if isinstance(stmt, ast.Expr) and isinstance(val, (ast.Constant, ast.Ellipsis)):
                continue  # docstring or ...
            if isinstance(stmt, ast.Return) and (
                stmt.value is None
                or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
            ):
                continue  # bare return None
            count += 1
        return count

    def _def_real_stmts(node) -> int:
        if isinstance(node, ast.ClassDef):
            body_stmts = _real_stmt_count(
                [s for s in node.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
            )
            method_stmts = sum(
                _real_stmt_count(m.body)
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            return body_stmts + method_stmts
        return _real_stmt_count(node.body)

    # ── Check 1: Stub-ending detection ────────────────────────────────────────
    if len(top_defs) >= 3:
        last_stmts = _def_real_stmts(top_defs[-1])
        if last_stmts == 0:
            others_with_content = sum(
                1 for d in top_defs[:-1] if _def_real_stmts(d) >= 3
            )
            if others_with_content >= 2:
                return True  # Last def is a stub while earlier ones have real logic

    # ── Check 2: Model/schema file table coverage ──────────────────────────────
    is_model_file = any(
        kw in file_path.lower()
        for kw in ("model", "schema", "entity", "table")
    )
    if is_model_file and spec:
        db_tables = spec.get("database_tables", [])
        if len(db_tables) >= 2:
            content_lower = content.lower()
            missing = [
                t for t in db_tables
                if t.get("name") and t["name"].lower() not in content_lower
            ]
            if missing and len(missing) / len(db_tables) > 0.20:
                logger.debug(
                    f"Model file {file_path} missing {len(missing)}/{len(db_tables)} "
                    f"expected tables: {[t['name'] for t in missing[:5]]}"
                )
                return True

    return False


# ── Evaluator ─────────────────────────────────────────────────────────────────


async def _evaluate_file(file_path: str, purpose: str, content: str, run_id: str = "") -> dict:
    """
    Run the evaluator on a generated file.
    Returns dict with 'passed' bool and 'issues' list.
    Uses Haiku (settings.claude_fast_model) — never Sonnet — for cost efficiency.
    """
    # Fast static checks — zero API cost, catch known deployment-breaking patterns
    static_issues = _run_static_checks(file_path, content)
    critical_static = [i for i in static_issues if i.severity == "critical"]
    if critical_static:
        logger.warning(
            f"[{run_id}] Static check FAILED {file_path}: "
            + "; ".join(i.issue[:80] for i in critical_static)
        )
        return {
            "passed": False,
            "issues": [
                {"severity": i.severity, "line": i.line, "issue": i.issue, "fix": i.fix}
                for i in static_issues
            ],
        }

    try:
        model = settings.claude_fast_model  # Haiku — ~20x cheaper than Sonnet
        prompt = build_evaluator_prompt(file_path, purpose, content)
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

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
        return json.loads(text)
    except Exception as exc:
        logger.warning(f"Evaluator failed for {file_path} (non-blocking): {exc}")
        return {"passed": True, "issues": []}  # Fail open — don't block on evaluator errors


# ── Prompt utilities ──────────────────────────────────────────────────────────


def _trim_prompt_to_fit(prompt: str) -> str:
    """
    Trim an over-long prompt by removing the previous_files section.
    Keeps spec + file_path + purpose + meta_rules but drops prior file contents.
    """
    previous_files_marker = "PREVIOUSLY GENERATED FILES"
    if previous_files_marker in prompt:
        idx = prompt.index(previous_files_marker)
        next_section = prompt.find("\n\nGENERATE FILE:", idx)
        if next_section == -1:
            next_section = prompt.find("\n\nNOW GENERATE:", idx)
        if next_section == -1:
            trimmed = (
                prompt[:idx]
                + "\n\n[Previous files omitted due to context length — generate this file independently]\n\n"
            )
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


# ── Knowledge context helpers ─────────────────────────────────────────────────


async def _assemble_generation_context(file_path: str, purpose: str) -> dict:
    """
    Assemble the full intelligence context for a file generation call.

    Uses context_assembler to pull from all four sources concurrently:
      1. Meta-rules extracted from past build outcomes (self-improving rules)
      2. Past build KB patterns (similar files we've generated before)
      3. Domain knowledge chunks (Tavily-scraped best practices, indexed nightly)
      4. Live search results (when purpose contains recency signals like "latest", "2025")

    Returns dict with 'meta_rules' (list[str]) and 'knowledge_context' (str).
    Falls back to legacy individual fetchers if assembler fails.
    """
    try:
        from intelligence.context_assembler import assemble_context
        query = f"{file_path} {purpose}"
        ctx = await assemble_context(
            query=query,
            task_type="generation",
            include_live_search=True,
        )
        # Combine KB patterns + domain knowledge + live results into a single context string
        context_parts = []
        if ctx.kb_chunks:
            context_parts.append("PAST BUILD PATTERNS (similar files generated before):\n" + "\n\n".join(ctx.kb_chunks[:3]))
        if ctx.knowledge_chunks:
            context_parts.append("DOMAIN KNOWLEDGE (current best practices):\n" + "\n\n".join(ctx.knowledge_chunks[:4]))
        if ctx.live_results:
            context_parts.append("LIVE RESEARCH (retrieved now):\n" + "\n\n".join(ctx.live_results[:2]))

        sources = ctx.sources_used
        if sources:
            logger.debug(f"Context assembled for {file_path}: sources={sources} rules={len(ctx.meta_rules)} chunks={len(ctx.kb_chunks)+len(ctx.knowledge_chunks)}")

        return {
            "meta_rules": ctx.meta_rules,
            "knowledge_context": "\n\n".join(context_parts),
        }
    except Exception as exc:
        logger.warning(f"Context assembler failed for {file_path} — falling back to legacy fetchers: {exc}")
        # Fallback: legacy individual fetchers
        meta_rules = await _get_meta_rules_legacy()
        knowledge_context = await _get_knowledge_context_legacy(file_path, purpose)
        return {"meta_rules": meta_rules, "knowledge_context": knowledge_context}


async def _get_meta_rules_legacy() -> list[str]:
    """Legacy meta-rules retrieval — used only if context_assembler fails."""
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
        logger.warning(f"Meta-rules legacy retrieval failed: {exc}")
        return []


async def _get_knowledge_context_legacy(file_path: str, purpose: str) -> str:
    """Legacy knowledge retrieval — used only if context_assembler fails."""
    try:
        from knowledge.retriever import retrieve_relevant_chunks
        query = f"{file_path} {purpose}"
        chunks = await retrieve_relevant_chunks(query, top_k=4)
        return "\n\n".join(chunks) if chunks else ""
    except Exception as exc:
        logger.warning(f"Knowledge context legacy failed for {file_path}: {exc}")
        return ""
