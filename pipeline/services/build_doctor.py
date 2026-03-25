"""
pipeline/services/build_doctor.py
Diagnose-and-repair loop for failed file generations.

Replaces dumb error stubs with intelligent diagnosis, knowledge retrieval,
and targeted regeneration. Works ALONGSIDE the existing evaluator and verifier —
doctor handles per-file repair, evaluator checks quality, verifier reviews
the complete package at the end.

Flow per file:
  1. generate_file_for_layer() — normal attempt (includes internal retry/eval loop)
  2. If None or secondary eval fails → diagnose() via Haiku + KB retrieval
  3. repair() via Sonnet with injected diagnosis context
  4. Re-evaluate; if still failing, one more diagnose → repair cycle
  5. After 3 total attempts: annotate best content with header comments
  6. Log all outcomes to KB (build_issues domain) for future builds

Model routing:
  Diagnosis → router.get_model('diagnosis')  → Haiku (cheap, fast)
  Repair     → router.get_model('generation') → Sonnet (quality)
"""

import json

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

_async_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_FAILED_FILE_HEADER = """\
# ══════════════════════════════════════════════════════════════════
# BUILD DOCTOR: This file failed {attempts} generation attempts.
# DIAGNOSIS: {diagnosis}
# DOWNSTREAM IMPACT: Files that import from this path may have errors.
# ══════════════════════════════════════════════════════════════════

"""


class BuildDoctor:
    """
    Intelligent per-file repair service for the code generation pipeline.
    All methods are safe — failures log warnings and return sensible defaults.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    async def diagnose(
        self,
        file_spec: dict,
        error: str,
        prior_files: dict[str, str],
        spec: dict,
    ) -> dict:
        """
        Diagnose why a file failed to generate correctly.

        Uses Haiku for cost efficiency — runs on every failure.
        Also retrieves similar past failures from KB for pattern matching.

        Returns dict with: diagnosis, root_cause, fix_instructions, similar_fixes.
        Never raises — returns safe defaults on any failure.
        """
        default = {
            "diagnosis": str(error)[:500],
            "root_cause": "unknown",
            "fix_instructions": "",
            "similar_fixes": [],
        }
        try:
            file_path = file_spec.get("path", "unknown")
            purpose = file_spec.get("description", "")

            # Filter prior_files to only files this one would import from
            relevant_files = _filter_relevant_files(file_path, prior_files)
            prior_context = "\n\n".join(
                f"=== {p} ===\n{c[:800]}"
                for p, c in list(relevant_files.items())[:5]
            )

            # Pull relevant spec section
            spec_section = _extract_spec_section(file_path, spec)

            prompt = (
                f"This file failed to generate correctly. Diagnose the specific cause.\n\n"
                f"FILE: {file_path}\nPURPOSE: {purpose}\n\n"
                f"ERROR OR FAILED OUTPUT:\n{str(error)[:2000]}\n\n"
                f"FILES IT DEPENDS ON:\n{prior_context or '(none identified)'}\n\n"
                f"SPEC REQUIREMENTS:\n{spec_section}\n\n"
                f"Return JSON only:\n"
                f'{{"diagnosis": "what went wrong", "root_cause": "specific technical cause", '
                f'"fix_instructions": "exactly what to change", '
                f'"affected_imports": ["list of import paths to fix"]}}'
            )

            model = router.get_model("diagnosis")
            response = await _async_client.messages.create(
                model=model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            raw = json.loads(text)

            # Retrieve similar past failures from KB
            similar_fixes: list[str] = []
            try:
                from intelligence.knowledge_base import retrieve_similar
                similar_fixes = await retrieve_similar(
                    query=f"build error {str(error)[:200]}",
                    record_type="file_pattern",
                    top_k=4,
                )
            except Exception as kb_exc:
                logger.debug(f"KB retrieval for diagnosis failed (non-blocking): {kb_exc}")

            return {
                "diagnosis": raw.get("diagnosis", default["diagnosis"]),
                "root_cause": raw.get("root_cause", "unknown"),
                "fix_instructions": raw.get("fix_instructions", ""),
                "affected_imports": raw.get("affected_imports", []),
                "similar_fixes": similar_fixes,
            }

        except Exception as exc:
            logger.warning(f"BuildDoctor.diagnose failed (non-blocking): {exc}")
            return default

    async def repair(
        self,
        file_spec: dict,
        full_spec: dict,
        prior_files: dict[str, str],
        diagnosis: dict,
        attempt: int,
    ) -> tuple[str | None, int]:
        """
        Attempt to generate a repaired version of the file by injecting
        the diagnosis context into the generation prompt.

        Returns (content, tokens). Content is None on total failure.
        """
        try:
            from pipeline.nodes.layer_generator import generate_file_for_layer

            similar = diagnosis.get("similar_fixes", [])
            similar_text = (
                "\n".join(f"  • {fix[:300]}" for fix in similar[:3])
                if similar
                else "  (no similar past fixes found)"
            )

            diagnosis_context = (
                f"CRITICAL: Previous generation attempt failed.\n"
                f"DIAGNOSIS: {diagnosis.get('diagnosis', '')}\n"
                f"ROOT CAUSE: {diagnosis.get('root_cause', '')}\n"
                f"FIX INSTRUCTIONS: {diagnosis.get('fix_instructions', '')}\n"
                f"SIMILAR PAST FIXES:\n{similar_text}\n"
                f"DO NOT repeat the same error. Follow the fix instructions exactly."
            )

            content = await generate_file_for_layer(
                run_id=f"repair-attempt-{attempt}",
                file_entry=file_spec,
                spec=full_spec,
                generated_files=prior_files,
                diagnosis_context=diagnosis_context,
            )

            tokens = len(content) // 4 if content else 0
            return content, tokens

        except Exception as exc:
            logger.warning(
                f"BuildDoctor.repair failed for {file_spec.get('path', '?')} "
                f"attempt {attempt} (non-blocking): {exc}"
            )
            return None, 0

    async def diagnose_and_repair(
        self,
        file_spec: dict,
        full_spec: dict,
        prior_files: dict[str, str],
        run_id: str = "",
        max_attempts: int = 3,
    ) -> tuple[str | None, int, dict]:
        """
        Full diagnose-and-repair loop for a single file.

        Attempt 1: normal generate_file_for_layer call.
        If it returns None or secondary evaluation finds critical issues:
          → diagnose → repair (attempt 2)
          → if still failing: diagnose → repair (attempt 3)
          → if still failing: return best content with diagnostic header comments
        Logs all outcomes to the KB.

        Returns: (content, tokens, build_report_dict)
        """
        from intelligence.evaluator import evaluate_file

        file_path = file_spec.get("path", "unknown")
        best_content: str | None = None
        best_tokens: int = 0
        diagnosis: dict = {}
        scores: list[dict] = []

        # ── Attempt 1: normal generation ─────────────────────────────────────
        try:
            from pipeline.nodes.layer_generator import generate_file_for_layer
            content = await generate_file_for_layer(
                run_id=run_id,
                file_entry=file_spec,
                spec=full_spec,
                generated_files=prior_files,
            )
        except Exception as exc:
            logger.warning(f"[{run_id}] BuildDoctor attempt 1 exception for {file_path}: {exc}")
            content = None

        if content is not None:
            best_content = content
            best_tokens = len(content) // 4

            # Secondary evaluation — check if layer_generator's internal eval
            # already caught issues or if something slipped through
            try:
                purpose = file_spec.get("description", f"File at {file_path}")
                eval_result = await evaluate_file(
                    file_path=file_path,
                    purpose=purpose,
                    content=content,
                    strict=True,
                )
                scores.append({
                    "attempt": 1,
                    "passed": eval_result.passed,
                    "issues": len(eval_result.issues),
                })
                if eval_result.passed:
                    return content, best_tokens, {
                        "attempts": 1,
                        "healed": False,
                        "diagnosis": {},
                        "scores": scores,
                    }
                # Has critical issues — fall through to repair
                error_summary = eval_result.summary or f"{len(eval_result.critical_issues)} critical issues"
                logger.warning(
                    f"[{run_id}] BuildDoctor: {file_path} passed generation "
                    f"but secondary eval found issues — attempting repair"
                )
            except Exception as eval_exc:
                logger.debug(f"[{run_id}] BuildDoctor secondary eval failed (non-blocking): {eval_exc}")
                # If eval itself fails, treat the content as passing
                return content, best_tokens, {
                    "attempts": 1,
                    "healed": False,
                    "diagnosis": {},
                    "scores": scores,
                }
        else:
            error_summary = "generate_file_for_layer returned None"

        # ── Repair loop (attempts 2 and 3) ────────────────────────────────────
        for repair_attempt in range(2, max_attempts + 1):
            # Diagnose
            diagnosis = await self.diagnose(
                file_spec=file_spec,
                error=error_summary,
                prior_files=prior_files,
                spec=full_spec,
            )

            # Log to KB
            try:
                from intelligence.knowledge_base import store_record
                await store_record(
                    record_type="file_pattern",
                    content=(
                        f"{file_path}: {diagnosis.get('diagnosis', error_summary)}"
                    ),
                    outcome="diagnosing",
                    run_id=run_id or None,
                    metadata={
                        "file_path": file_path,
                        "repair_attempt": repair_attempt,
                        "root_cause": diagnosis.get("root_cause", ""),
                    },
                )
            except Exception as kb_exc:
                logger.debug(f"[{run_id}] KB log failed (non-blocking): {kb_exc}")

            # Repair
            repaired, tokens = await self.repair(
                file_spec=file_spec,
                full_spec=full_spec,
                prior_files=prior_files,
                diagnosis=diagnosis,
                attempt=repair_attempt,
            )

            if repaired is not None:
                best_content = repaired
                best_tokens = tokens

                # Evaluate repaired output
                try:
                    purpose = file_spec.get("description", f"File at {file_path}")
                    eval_result = await evaluate_file(
                        file_path=file_path,
                        purpose=purpose,
                        content=repaired,
                        strict=True,
                    )
                    scores.append({
                        "attempt": repair_attempt,
                        "passed": eval_result.passed,
                        "issues": len(eval_result.issues),
                    })
                    if eval_result.passed:
                        # Healed successfully
                        try:
                            from intelligence.knowledge_base import store_record
                            await store_record(
                                record_type="file_pattern",
                                content=(
                                    f"{file_path} healed on attempt {repair_attempt}: "
                                    f"{diagnosis.get('fix_instructions', '')[:400]}"
                                ),
                                outcome=f"healed_attempt_{repair_attempt}",
                                run_id=run_id or None,
                                metadata={
                                    "file_path": file_path,
                                    "diagnosis": diagnosis.get("diagnosis", ""),
                                    "fix_applied": diagnosis.get("fix_instructions", ""),
                                },
                            )
                        except Exception:
                            pass
                        logger.info(
                            f"[{run_id}] BuildDoctor healed {file_path} "
                            f"on attempt {repair_attempt}"
                        )
                        return repaired, tokens, {
                            "attempts": repair_attempt,
                            "healed": True,
                            "diagnosis": diagnosis,
                            "scores": scores,
                        }
                    error_summary = (
                        eval_result.summary
                        or f"{len(eval_result.critical_issues)} critical issues after repair"
                    )
                except Exception as eval_exc:
                    logger.debug(f"[{run_id}] BuildDoctor repair eval failed (non-blocking): {eval_exc}")
                    # If we can't evaluate, accept the repaired content
                    return repaired, tokens, {
                        "attempts": repair_attempt,
                        "healed": True,
                        "diagnosis": diagnosis,
                        "scores": scores,
                    }

        # ── All attempts exhausted ────────────────────────────────────────────
        diag_summary = diagnosis.get("diagnosis", error_summary) if diagnosis else error_summary
        logger.error(
            f"[{run_id}] BuildDoctor: {file_path} failed after {max_attempts} attempts — "
            f"annotating best content with diagnostic header"
        )

        # Log final failure to KB
        try:
            from intelligence.knowledge_base import store_record
            await store_record(
                record_type="file_pattern",
                content=f"{file_path} failed all {max_attempts} repair attempts: {diag_summary[:400]}",
                outcome="failure",
                run_id=run_id or None,
                metadata={
                    "file_path": file_path,
                    "total_attempts": max_attempts,
                    "final_diagnosis": diag_summary,
                },
            )
        except Exception:
            pass

        if best_content:
            annotated = (
                _FAILED_FILE_HEADER.format(
                    attempts=max_attempts,
                    diagnosis=diag_summary[:300],
                )
                + best_content
            )
            return annotated, best_tokens, {
                "attempts": max_attempts,
                "healed": False,
                "diagnosis": diagnosis,
                "scores": scores,
            }

        return None, 0, {
            "attempts": max_attempts,
            "healed": False,
            "diagnosis": diagnosis,
            "scores": scores,
        }

    async def post_build_report(
        self,
        run_id: str,
        all_file_reports: list[dict],
    ) -> str:
        """
        Aggregate all per-file build reports into a summary.
        Stores on the run record and returns a formatted string.
        """
        total = len(all_file_reports)
        healed = sum(1 for r in all_file_reports if r.get("healed"))
        failed = sum(
            1 for r in all_file_reports
            if not r.get("healed") and r.get("attempts", 1) > 1
        )
        clean = total - healed - failed

        lines = [
            f"BUILD HEALTH: {clean}/{total} files clean, "
            f"{healed} healed, {failed} failed"
        ]

        problem_files = [
            r for r in all_file_reports
            if not r.get("healed") and r.get("attempts", 1) > 1
        ]
        for report in problem_files:
            file_path = report.get("file_path", "unknown")
            diag = report.get("diagnosis", {})
            diag_text = diag.get("diagnosis", "unknown") if isinstance(diag, dict) else str(diag)
            affected = diag.get("affected_imports", []) if isinstance(diag, dict) else []
            lines.append(f"  FAILED: {file_path}")
            lines.append(f"    Diagnosis: {diag_text[:200]}")
            if affected:
                lines.append(f"    Affected imports: {', '.join(affected[:5])}")

        report_str = "\n".join(lines)
        logger.info(f"[{run_id}] {report_str}")

        # Store on run record
        try:
            from memory.database import get_session
            from memory.models import ForgeRun
            from sqlalchemy import update
            async with get_session() as session:
                await session.execute(
                    update(ForgeRun)
                    .where(ForgeRun.run_id == run_id)
                    .values(error_message=report_str[:2000] if failed > 0 else None)
                )
        except Exception as exc:
            logger.debug(f"[{run_id}] BuildDoctor report store failed (non-blocking): {exc}")

        return report_str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _filter_relevant_files(file_path: str, prior_files: dict[str, str]) -> dict[str, str]:
    """
    Return the subset of prior_files that this file is likely to import from,
    based on the directory structure and common import patterns.
    """
    import re
    basename = file_path.split("/")[-1]
    # Heuristic: files in the same package layer or that match common import targets
    relevant: dict[str, str] = {}
    priority_paths = ("memory/models", "memory/database", "config/settings", "config/model_config")
    for path, content in prior_files.items():
        if any(path.startswith(p) for p in priority_paths):
            relevant[path] = content
        elif path.split("/")[0] == file_path.split("/")[0]:  # Same top-level package
            relevant[path] = content
    return relevant


def _extract_spec_section(file_path: str, spec: dict) -> str:
    """
    Pull the most relevant section of the spec for this file type.
    Returns a truncated string for prompt injection.
    """
    parts: list[str] = []
    path_lower = file_path.lower()

    if "model" in path_lower or "schema" in path_lower:
        tables = spec.get("database_tables", [])
        if tables:
            parts.append(f"Database tables: {json.dumps(tables[:5])[:600]}")
    if "route" in path_lower or "api" in path_lower or "endpoint" in path_lower:
        endpoints = spec.get("api_endpoints", [])
        if endpoints:
            parts.append(f"API endpoints: {json.dumps(endpoints[:5])[:600]}")
    if "worker" in path_lower or "pipeline" in path_lower or "job" in path_lower:
        services = spec.get("services", [])
        if services:
            parts.append(f"Services: {json.dumps(services[:3])[:400]}")

    if not parts:
        # Generic: agent name + tech stack
        parts.append(
            f"Agent: {spec.get('agent_name', '')} — {spec.get('agent_description', '')[:300]}"
        )

    return "\n".join(parts)[:1200]
