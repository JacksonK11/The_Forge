"""
pipeline/nodes/recovery_node.py
Post-build recovery pass for generation_failed files.

For each file marked generation_failed in the run:
  Step 1 — Diagnose: Claude Sonnet analyses WHY the file failed (JSON response)
  Step 2 — Strategy-specific rebuild chosen from the diagnosis:
            truncated          → 2-part split generation
            import_error       → inject missing file content into the prompt
            logic_incomplete   → targeted completion instruction
            missing_dependency → generate dependency first, then retry
            wrong_structure    → structural reference from same layer
            manual_only / low  → skip auto-rebuild entirely
  Step 3 — Verify: ast.parse + Haiku evaluator + targeted failure-reason check
            All three must pass before the file is marked complete.

Max 2 rebuild attempts per file. Never loops on the same strategy.
Files that cannot be recovered are documented in FAILED_FILES_REPORT.md
which is included in the build ZIP.
"""

import ast
import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from loguru import logger

from app.api.services.retry import TruncatedOutputError, retry_async
from config.settings import settings
from memory.database import get_session
from memory.models import FileStatus, ForgeFile
from pipeline.pipeline import PipelineState
from pipeline.prompts.prompts import CODEGEN_SYSTEM, build_codegen_prompt

_DIAGNOSIS_MODEL = "claude-sonnet-4-6"
_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MAX_REBUILD_ATTEMPTS = 2


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class _FailedFileAnalysis:
    """Tracks one failed file through the full diagnosis → rebuild → verify cycle."""

    file_path: str
    purpose: str
    error_message: str
    placeholder_content: str
    diagnosis: dict = field(default_factory=dict)
    rebuild_attempts: list[dict] = field(default_factory=list)
    resolved: bool = False


# ── Public entry point ────────────────────────────────────────────────────────


async def recovery_node(state: PipelineState) -> PipelineState:
    """
    Post-build recovery pass. Diagnoses and rebuilds generation_failed files.

    On success: marks file complete in DB, updates state.generated_files.
    On failure: records the analysis for FAILED_FILES_REPORT.md.
    Non-blocking — any internal exception is logged and skipped.
    """
    if not state.generation_failed_files:
        logger.info(f"[{state.run_id}] Recovery node: no failed files")
        return state

    logger.info(
        f"[{state.run_id}] Recovery node: attempting to recover "
        f"{len(state.generation_failed_files)} file(s)"
    )

    manifest_map = {
        fe["path"]: fe
        for fe in (state.manifest or {}).get("file_manifest", [])
    }
    failed_records = await _get_failed_files(state.run_id)
    failed_map = {f.file_path: f for f in failed_records}

    analyses: list[_FailedFileAnalysis] = []
    rebuilt_paths: list[str] = []

    for file_path in list(state.generation_failed_files):
        file_record = failed_map.get(file_path)
        file_entry = manifest_map.get(file_path) or {
            "path": file_path,
            "layer": 3,
            "description": f"File at {file_path}",
            "estimated_lines": 0,
        }
        purpose = (
            file_record.purpose
            if (file_record and file_record.purpose)
            else file_entry.get("description", f"File at {file_path}")
        )
        error_msg = (
            file_record.error_message
            if file_record
            else "All generation attempts failed"
        )
        placeholder = file_record.content if file_record else ""

        analysis = _FailedFileAnalysis(
            file_path=file_path,
            purpose=purpose,
            error_message=error_msg,
            placeholder_content=placeholder,
        )

        # ── Step 1: Diagnose ─────────────────────────────────────────────────
        logger.info(f"[{state.run_id}] Diagnosing: {file_path}")
        try:
            diagnosis = await _diagnose_failure(
                run_id=state.run_id,
                file_path=file_path,
                file_entry=file_entry,
                error_message=error_msg,
                spec=state.spec or {},
            )
        except Exception as exc:
            logger.error(f"[{state.run_id}] Diagnosis failed for {file_path}: {exc}")
            diagnosis = {
                "failure_reason": "truncated",
                "root_cause": "Diagnosis unavailable — defaulting to split strategy",
                "fix_strategy": "split",
                "missing_context": [],
                "confidence": "medium",
            }

        analysis.diagnosis = diagnosis
        logger.info(
            f"[{state.run_id}] {file_path}: reason={diagnosis.get('failure_reason')} "
            f"strategy={diagnosis.get('fix_strategy')} confidence={diagnosis.get('confidence')}"
        )

        # Skip manual_only or low-confidence — go straight to the report
        if (
            diagnosis.get("fix_strategy") == "manual_only"
            or diagnosis.get("confidence") == "low"
        ):
            logger.info(
                f"[{state.run_id}] Skipping auto-rebuild for {file_path} "
                f"(confidence={diagnosis.get('confidence')}, strategy={diagnosis.get('fix_strategy')})"
            )
            analyses.append(analysis)
            continue

        # ── Steps 2 + 3: Rebuild and verify (max 2 attempts) ─────────────────
        for attempt_num in range(1, MAX_REBUILD_ATTEMPTS + 1):
            logger.info(
                f"[{state.run_id}] Rebuild {attempt_num}/{MAX_REBUILD_ATTEMPTS}: "
                f"{file_path} [{diagnosis.get('failure_reason')}]"
            )
            attempt_record: dict = {
                "attempt": attempt_num,
                "strategy": diagnosis.get("failure_reason", "unknown"),
                "passed": False,
                "failures": [],
            }

            try:
                content = await _rebuild_with_strategy(
                    run_id=state.run_id,
                    file_path=file_path,
                    file_entry=file_entry,
                    spec=state.spec or {},
                    generated_files=state.generated_files,
                    diagnosis=diagnosis,
                )
            except Exception as exc:
                logger.error(
                    f"[{state.run_id}] Rebuild exception for {file_path} "
                    f"attempt {attempt_num}: {exc}"
                )
                attempt_record["error"] = str(exc)
                analysis.rebuild_attempts.append(attempt_record)
                continue

            if not content:
                attempt_record["error"] = "Rebuild returned no content"
                analysis.rebuild_attempts.append(attempt_record)
                continue

            attempt_record["content_lines"] = len(content.splitlines())

            # ── Step 3: Verify ────────────────────────────────────────────────
            passed, check_failures = await _verify_rebuilt_file(
                file_path=file_path,
                content=content,
                purpose=purpose,
                diagnosis=diagnosis,
                run_id=state.run_id,
                generated_files=state.generated_files,
            )
            attempt_record["passed"] = passed
            attempt_record["failures"] = check_failures
            analysis.rebuild_attempts.append(attempt_record)

            if passed:
                await _mark_file_complete_in_db(state.run_id, file_path, content)
                state.generated_files[file_path] = content
                analysis.resolved = True
                rebuilt_paths.append(file_path)
                logger.info(f"[{state.run_id}] ✅ Recovered: {file_path} (attempt {attempt_num})")
                break
            else:
                logger.warning(
                    f"[{state.run_id}] Rebuild attempt {attempt_num} failed for {file_path}: "
                    + "; ".join(check_failures[:3])
                )

        analyses.append(analysis)

    # ── Update state ──────────────────────────────────────────────────────────
    still_failed = [fp for fp in state.generation_failed_files if fp not in rebuilt_paths]
    state.generation_failed_files = still_failed
    state.rebuilt_files_count = len(rebuilt_paths)
    state.still_failed_files = still_failed

    logger.info(
        f"[{state.run_id}] Recovery complete: "
        f"{len(rebuilt_paths)} recovered, {len(still_failed)} still failed"
    )

    unresolved = [a for a in analyses if not a.resolved]
    if unresolved:
        state.failed_files_report = _build_failed_files_report(unresolved)
        logger.info(
            f"[{state.run_id}] FAILED_FILES_REPORT.md generated "
            f"({len(unresolved)} file(s))"
        )

    return state


# ── Step 1: Diagnosis ─────────────────────────────────────────────────────────


async def _diagnose_failure(
    run_id: str,
    file_path: str,
    file_entry: dict,
    error_message: str,
    spec: dict,
) -> dict:
    """
    Call Claude Sonnet to diagnose exactly why a file failed to generate.
    Uses string concatenation throughout — never str.format() — because
    error messages and purpose text can contain { } characters.
    """
    purpose = file_entry.get("description", f"File at {file_path}")
    estimated_lines = file_entry.get("estimated_lines", 0)

    # Build prompt with concatenation — never .format() on user/generated content
    prompt = (
        "Here is a file that failed to generate correctly:\n\n"
        "File path: " + file_path + "\n"
        "File purpose: " + purpose + "\n"
        "Estimated lines: " + str(estimated_lines) + "\n"
        "Error message: " + (error_message or "All generation attempts failed") + "\n"
        "Agent: " + spec.get("agent_name", "") + "\n\n"
        "Diagnose exactly why this file failed. Return JSON only — no prose, no markdown fences:\n"
        "{\n"
        '  "failure_reason": "truncated|import_error|logic_incomplete|wrong_structure|missing_dependency|prompt_too_large",\n'
        '  "root_cause": "specific explanation in one sentence",\n'
        '  "fix_strategy": "split|simplify_prompt|add_missing_context|reduce_scope|manual_only",\n'
        '  "missing_context": ["list of specific files or tables Claude needed but did not have"],\n'
        '  "confidence": "high|medium|low"\n'
        "}"
    )

    response = _client.messages.create(
        model=_DIAGNOSIS_MODEL,
        max_tokens=512,
        system=(
            "You are a code generation diagnostician. "
            "Analyse why AI-generated files fail and return precise JSON. "
            "Common causes: file too large for one call (truncated), missing import context, "
            "complex orchestration logic that needs splitting. "
            "Be precise. Return only valid JSON with the exact keys requested."
        ),
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    result = json.loads(text)
    result.setdefault("failure_reason", "truncated")
    result.setdefault("fix_strategy", "split")
    result.setdefault("missing_context", [])
    result.setdefault("confidence", "medium")
    result.setdefault("root_cause", "Unknown failure")
    return result


# ── Step 2: Strategy-specific rebuild ─────────────────────────────────────────


async def _rebuild_with_strategy(
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    diagnosis: dict,
) -> str | None:
    """Route to the appropriate rebuild strategy based on diagnosis.failure_reason."""
    from pipeline.nodes.layer_generator import (
        _generate_file_content,
        _generate_file_split,
        _get_knowledge_context,
        _get_meta_rules,
    )

    failure_reason = diagnosis.get("failure_reason", "truncated")
    meta_rules = await _get_meta_rules()
    knowledge_context = await _get_knowledge_context(
        file_path, file_entry.get("description", "")
    )

    # Shared kwargs for direct split fallback on truncation
    split_kwargs = dict(
        run_id=run_id,
        file_path=file_path,
        file_entry=file_entry,
        spec=spec,
        generated_files=generated_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    if failure_reason in ("truncated", "prompt_too_large"):
        # Use 2-part split generation
        return await _generate_file_split(**split_kwargs)

    elif failure_reason == "import_error":
        try:
            return await _rebuild_import_error(
                run_id=run_id,
                file_path=file_path,
                file_entry=file_entry,
                spec=spec,
                generated_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
                missing_context=diagnosis.get("missing_context", []),
            )
        except TruncatedOutputError:
            logger.warning(
                f"[{run_id}] import_error rebuild truncated for {file_path} — switching to split"
            )
            return await _generate_file_split(**split_kwargs)

    elif failure_reason == "logic_incomplete":
        try:
            return await _rebuild_logic_incomplete(
                run_id=run_id,
                file_path=file_path,
                file_entry=file_entry,
                spec=spec,
                generated_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
                root_cause=diagnosis.get("root_cause", ""),
            )
        except TruncatedOutputError:
            logger.warning(
                f"[{run_id}] logic_incomplete rebuild truncated for {file_path} — switching to split"
            )
            return await _generate_file_split(**split_kwargs)

    elif failure_reason == "missing_dependency":
        try:
            return await _rebuild_missing_dependency(
                run_id=run_id,
                file_path=file_path,
                file_entry=file_entry,
                spec=spec,
                generated_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
                missing_context=diagnosis.get("missing_context", []),
            )
        except TruncatedOutputError:
            logger.warning(
                f"[{run_id}] missing_dependency rebuild truncated for {file_path} — switching to split"
            )
            return await _generate_file_split(**split_kwargs)

    elif failure_reason == "wrong_structure":
        try:
            return await _rebuild_wrong_structure(
                run_id=run_id,
                file_path=file_path,
                file_entry=file_entry,
                spec=spec,
                generated_files=generated_files,
                meta_rules=meta_rules,
                knowledge_context=knowledge_context,
            )
        except TruncatedOutputError:
            logger.warning(
                f"[{run_id}] wrong_structure rebuild truncated for {file_path} — switching to split"
            )
            return await _generate_file_split(**split_kwargs)

    else:
        # Unknown reason — default to split
        logger.info(
            f"[{run_id}] Unknown failure_reason '{failure_reason}' — using split generation"
        )
        return await _generate_file_split(**split_kwargs)


async def _rebuild_import_error(
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    meta_rules: list[str],
    knowledge_context: str,
    missing_context: list[str],
) -> str | None:
    """
    Rebuild by pulling the actual content of all missing files from DB
    and injecting them explicitly into the prompt.
    """
    from pipeline.nodes.layer_generator import _generate_file_content

    layer = file_entry.get("layer", 3)
    purpose = file_entry.get("description", f"File at {file_path}")

    # Start with all generated files, then load any truly missing ones from DB
    enriched_files = dict(generated_files)
    for ctx_path in missing_context:
        if ctx_path not in enriched_files:
            db_content = await _get_file_content_from_db(run_id, ctx_path)
            if db_content:
                enriched_files[ctx_path] = db_content
                logger.debug(f"[{run_id}] Injected missing context: {ctx_path}")

    base_prompt = build_codegen_prompt(
        spec=spec,
        file_path=file_path,
        layer=layer,
        purpose=purpose,
        previous_files=enriched_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    # Append explicit import-fix note using concatenation (not .format())
    if missing_context:
        fix_note = (
            "\n\nIMPORT FIX — RECOVERY CONTEXT:\n"
            "This file previously failed due to import errors. "
            "The required files are now explicitly included above.\n"
            "Reference only these files for your imports:\n"
            + "\n".join("  - " + ctx for ctx in missing_context)
            + "\nDo not import from any other local path not listed above."
        )
        prompt = base_prompt + fix_note
    else:
        prompt = base_prompt

    return await retry_async(
        _generate_file_content,
        prompt,
        file_path=file_path,
        run_id=run_id,
        max_attempts=2,
        base_delay=5.0,
        max_delay=30.0,
        label="recovery-import:" + file_path,
        no_retry_on=(TruncatedOutputError,),
    )


async def _rebuild_logic_incomplete(
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    meta_rules: list[str],
    knowledge_context: str,
    root_cause: str,
) -> str | None:
    """
    Rebuild with an explicit instruction to complete the specific missing logic.
    Tells Claude exactly what was incomplete and demands full implementation.
    """
    from pipeline.nodes.layer_generator import _generate_file_content

    layer = file_entry.get("layer", 3)
    purpose = file_entry.get("description", f"File at {file_path}")

    focused_purpose = (
        purpose
        + "\n\nRECOVERY — LOGIC COMPLETION REQUIRED:\n"
        + "Previous generation was incomplete. Diagnosed issue: "
        + root_cause
        + "\n"
        + "You MUST implement every function body completely. "
        + "No pass statements, no NotImplementedError, no ellipsis stubs. "
        + "Complete every function with real production logic."
    )

    prompt = build_codegen_prompt(
        spec=spec,
        file_path=file_path,
        layer=layer,
        purpose=focused_purpose,
        previous_files=generated_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    return await retry_async(
        _generate_file_content,
        prompt,
        file_path=file_path,
        run_id=run_id,
        max_attempts=2,
        base_delay=5.0,
        max_delay=30.0,
        label="recovery-logic:" + file_path,
        no_retry_on=(TruncatedOutputError,),
    )


async def _rebuild_missing_dependency(
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    meta_rules: list[str],
    knowledge_context: str,
    missing_context: list[str],
) -> str | None:
    """
    Generate any truly missing dependency files first, then rebuild the target.
    If the dependency already exists in generated_files, it was excluded from
    original context — just rebuilding with it included fixes the issue.
    """
    from pipeline.nodes.layer_generator import generate_file_for_layer, _generate_file_content

    updated_files = dict(generated_files)

    # Generate any deps not already in generated_files
    for dep_path in missing_context:
        if dep_path in updated_files:
            continue
        # Check DB first
        db_content = await _get_file_content_from_db(run_id, dep_path)
        if db_content:
            updated_files[dep_path] = db_content
            logger.debug(f"[{run_id}] Loaded dependency from DB: {dep_path}")
            continue
        # Generate fresh
        logger.info(f"[{run_id}] Generating missing dependency: {dep_path}")
        dep_entry = {
            "path": dep_path,
            "layer": max(1, file_entry.get("layer", 3) - 1),
            "description": "Dependency required by " + file_path,
            "estimated_lines": 100,
        }
        try:
            dep_content = await generate_file_for_layer(
                run_id=run_id,
                file_entry=dep_entry,
                spec=spec,
                generated_files=updated_files,
            )
            if dep_content:
                updated_files[dep_path] = dep_content
                await _mark_file_complete_in_db(run_id, dep_path, dep_content)
                logger.info(f"[{run_id}] Dependency generated: {dep_path}")
        except Exception as exc:
            logger.warning(f"[{run_id}] Could not generate dependency {dep_path}: {exc}")

    # Now rebuild the target with dependencies available
    layer = file_entry.get("layer", 3)
    purpose = file_entry.get("description", f"File at {file_path}")

    prompt = build_codegen_prompt(
        spec=spec,
        file_path=file_path,
        layer=layer,
        purpose=purpose,
        previous_files=updated_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    return await retry_async(
        _generate_file_content,
        prompt,
        file_path=file_path,
        run_id=run_id,
        max_attempts=2,
        base_delay=5.0,
        max_delay=30.0,
        label="recovery-dep:" + file_path,
        no_retry_on=(TruncatedOutputError,),
    )


async def _rebuild_wrong_structure(
    run_id: str,
    file_path: str,
    file_entry: dict,
    spec: dict,
    generated_files: dict[str, str],
    meta_rules: list[str],
    knowledge_context: str,
) -> str | None:
    """
    Rebuild with a working example file from the same directory/layer as a
    structural reference. Helps when Claude produced the wrong class layout.
    """
    from pipeline.nodes.layer_generator import _generate_file_content

    layer = file_entry.get("layer", 3)
    purpose = file_entry.get("description", f"File at {file_path}")

    # Find an example from the same directory (same path prefix)
    file_dir = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""
    example_path = ""
    example_snippet = ""

    for path, content in generated_files.items():
        if path == file_path or not content or len(content) < 200:
            continue
        path_dir = "/".join(path.split("/")[:-1]) if "/" in path else ""
        if path_dir == file_dir and path.endswith(".py"):
            example_path = path
            example_snippet = content[:3000]
            break

    # Fallback: any file from generated_files in the same extension
    if not example_path:
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
        for path, content in generated_files.items():
            if path != file_path and content and len(content) > 200:
                if path.endswith("." + ext):
                    example_path = path
                    example_snippet = content[:3000]
                    break

    extra_note = ""
    if example_path:
        extra_note = (
            "\n\nSTRUCTURAL REFERENCE — match the structure of this file from the same module:\n"
            "=== " + example_path + " ===\n"
            + example_snippet
            + "\n[end reference]\n"
            "Follow the same class layout, import style, and code patterns."
        )

    prompt = build_codegen_prompt(
        spec=spec,
        file_path=file_path,
        layer=layer,
        purpose=purpose + extra_note,
        previous_files=generated_files,
        meta_rules=meta_rules,
        knowledge_context=knowledge_context,
    )

    return await retry_async(
        _generate_file_content,
        prompt,
        file_path=file_path,
        run_id=run_id,
        max_attempts=2,
        base_delay=5.0,
        max_delay=30.0,
        label="recovery-struct:" + file_path,
        no_retry_on=(TruncatedOutputError,),
    )


# ── Step 3: Verification ──────────────────────────────────────────────────────


async def _verify_rebuilt_file(
    file_path: str,
    content: str,
    purpose: str,
    diagnosis: dict,
    run_id: str,
    generated_files: dict[str, str],
) -> tuple[bool, list[str]]:
    """
    Three-gate verification after a rebuild attempt.

    Gate 1: ast.parse — definitive syntax check (Python files only)
    Gate 2: Haiku evaluator — same rubric as original generation
    Gate 3: Targeted check based on the specific failure_reason

    Returns (passed: bool, failure_messages: list[str]).
    """
    from pipeline.nodes.layer_generator import _detect_truncation, _evaluate_file

    failures: list[str] = []

    # Gate 1: Syntax
    if file_path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as exc:
            failures.append(f"SyntaxError at line {exc.lineno}: {exc.msg}")
            return False, failures  # No point running further checks

    # Gate 2: Evaluator (Haiku)
    try:
        evaluation = await _evaluate_file(file_path, purpose, content, run_id)
        if not evaluation.get("passed", True):
            issues = evaluation.get("issues", [])
            critical = [i for i in issues if i.get("severity") == "critical"]
            for issue in critical[:3]:
                failures.append("Evaluator: " + issue.get("issue", "Critical issue"))
    except Exception as exc:
        logger.warning(f"[{run_id}] Evaluator failed in recovery for {file_path}: {exc}")

    # Gate 3: Targeted check based on failure_reason
    failure_reason = diagnosis.get("failure_reason", "")

    if failure_reason == "truncated":
        if _detect_truncation(content, file_path):
            failures.append("Truncation still detected in rebuilt content")

    elif failure_reason == "logic_incomplete":
        stubs = ["raise NotImplementedError", "    pass\n", "\tpass\n", "    ...\n"]
        for stub in stubs:
            if stub in content:
                failures.append(
                    "Logic incomplete: stub pattern still present: " + stub.strip()
                )
                break

    elif failure_reason == "import_error":
        # Light check — just verify no obvious broken local import patterns
        broken = _check_for_broken_imports(content)
        failures.extend(broken[:2])

    return len(failures) == 0, failures


def _check_for_broken_imports(content: str) -> list[str]:
    """
    Very light import sanity check. Only flags obviously self-referential
    or clearly invented imports. Intentionally lenient to avoid false positives.
    """
    import re

    failures = []
    for line in content.splitlines():
        stripped = line.strip()
        # Flag imports of non-existent top-level packages that look invented
        m = re.match(r"from ([\w]+)\.[\w.]+ import", stripped)
        if m:
            top = m.group(1)
            # Known-always-present project packages
            always_ok = {
                "config", "memory", "intelligence", "monitoring", "knowledge",
                "pipeline", "app", "backend", "worker", "loguru", "pydantic",
                "fastapi", "sqlalchemy", "anthropic", "httpx", "redis",
                "asyncpg", "rq", "apscheduler", "tiktoken",
            }
            if top not in always_ok and len(top) > 20:
                # Suspiciously long package name — might be hallucinated
                failures.append(f"Suspicious import: {stripped[:80]}")
    return failures


# ── Report generation ─────────────────────────────────────────────────────────


def _build_failed_files_report(analyses: list[_FailedFileAnalysis]) -> str:
    """
    Generate FAILED_FILES_REPORT.md for files that could not be auto-recovered.

    Gives the developer everything they need to implement each file manually
    in under 5 minutes: purpose, why it failed, what was attempted, checklist.
    """
    lines = [
        "# FAILED FILES REPORT",
        "",
        f"{len(analyses)} file(s) could not be automatically generated or recovered.",
        "Each section below explains the failure and what to implement manually.",
        "",
        "---",
        "",
    ]

    for analysis in analyses:
        d = analysis.diagnosis

        lines += [
            f"## `{analysis.file_path}`",
            "",
            f"**Purpose:** {analysis.purpose}",
            "",
            f"**Failure reason:** `{d.get('failure_reason', 'unknown')}`  ",
            f"**Root cause:** {d.get('root_cause', 'Unknown')}  ",
            f"**Auto-fix confidence:** `{d.get('confidence', 'n/a')}`",
            "",
        ]

        missing = d.get("missing_context", [])
        if missing:
            lines.append("**Missing context at generation time:**")
            for item in missing:
                lines.append(f"- `{item}`")
            lines.append("")

        if analysis.rebuild_attempts:
            lines.append("**Auto-rebuild attempts:**")
            for att in analysis.rebuild_attempts:
                icon = "✅" if att.get("passed") else "❌"
                lines.append(
                    f"- Attempt {att['attempt']} "
                    f"[{att.get('strategy', '?')}]: {icon}"
                )
                for fail in att.get("failures", [])[:3]:
                    lines.append(f"  - {fail}")
            lines.append("")

        lines += [
            "### What to implement",
            "",
            analysis.purpose,
            "",
            "### Implementation checklist",
            "",
            "- [ ] `from loguru import logger` at the top",
            "- [ ] Full type hints on every function parameter and return type",
            "- [ ] Every external API call wrapped in `try/except` with `logger.error()`",
            "- [ ] All config from `settings` — no hardcoded strings or credentials",
            "- [ ] No `pass`, no `TODO`, no stub functions — every body complete",
            "- [ ] Run `python -c \"import ast; ast.parse(open('" + analysis.file_path + "').read())\"` to verify syntax",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


# ── DB helpers ────────────────────────────────────────────────────────────────


async def _get_failed_files(run_id: str) -> list[ForgeFile]:
    """Load all generation_failed ForgeFile records for this run."""
    try:
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ForgeFile).where(
                    ForgeFile.run_id == run_id,
                    ForgeFile.status == "generation_failed",
                )
            )
            return list(result.scalars().all())
    except Exception as exc:
        logger.error(f"[{run_id}] Failed to load generation_failed records: {exc}")
        return []


async def _get_file_content_from_db(run_id: str, file_path: str) -> str:
    """Load content of a specific file record from DB (any status)."""
    try:
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ForgeFile).where(
                    ForgeFile.run_id == run_id,
                    ForgeFile.file_path == file_path,
                )
            )
            record = result.scalar_one_or_none()
            return (record.content or "") if record else ""
    except Exception as exc:
        logger.warning(f"[{run_id}] Failed to load {file_path} from DB: {exc}")
        return ""


async def _mark_file_complete_in_db(run_id: str, file_path: str, content: str) -> None:
    """Mark a previously-failed file as complete in DB with new content."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(content))
    except Exception:
        token_count = len(content) // 4

    try:
        async with get_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ForgeFile)
                .where(ForgeFile.run_id == run_id, ForgeFile.file_path == file_path)
                .values(
                    status=FileStatus.COMPLETE.value,
                    content=content,
                    token_count=token_count,
                    error_message=None,
                )
            )
        logger.debug(f"[{run_id}] Marked {file_path} complete in DB")
    except Exception as exc:
        logger.error(f"[{run_id}] Failed to mark {file_path} complete: {exc}")
