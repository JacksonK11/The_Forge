"""
pipeline/nodes/build_qa_node.py
Post-generation Build QA loop.

Position in pipeline: after recovery_node, before package_node.

Runs the full BuildQAScorer + BuildQAFixer loop until the generated codebase
scores >= 95/100 or MAX_QA_ITERATIONS (3) is reached.

Each iteration:
  1. Score all files across 5 categories (100 pts total, static analysis only)
  2. Log the score breakdown to build_logs — visible on the Pipeline tab
  3. If failed: run BuildQAFixer on every critical issue grouped by file
  4. Repeat

The final QAResult is written to ForgeRun.metadata_json["build_qa"] and stored
on state.qa_result for the Telegram notification and Results tab.

Score bands:
  95-100  → PASS    — package and deliver
  85-94   → GOOD    — log note, package and deliver (3 iterations exhausted)
  70-84   → WARNING — log warning, package and deliver
  <70     → POOR    — log critical warning, package anyway (never blocks delivery)

The QA loop never blocks a build from completing — it improves quality on every
iteration and documents what it found, even if it can't reach 100/100.
"""

import time
from typing import Optional

from loguru import logger

from pipeline.pipeline import PipelineState
from pipeline.services.build_qa import (
    MAX_QA_ITERATIONS,
    PASS_THRESHOLD,
    BuildQAFixer,
    BuildQAScorer,
    QAResult,
)


async def build_qa_node(state: PipelineState) -> PipelineState:
    """
    Score → fix → re-score loop. Updates state.generated_files with repairs.
    Stores final QAResult on state.qa_result and persists to metadata_json.
    Never raises — all errors are logged and the build continues.
    """
    if not state.generated_files:
        logger.warning(f"[{state.run_id}] build_qa_node: no files to assess, skipping")
        return state

    spec = state.spec or {}
    scorer = BuildQAScorer()
    fixer = BuildQAFixer()
    score_history: list[int] = []
    qa_result: Optional[QAResult] = None

    await _log(state.run_id,
               f"Build QA starting — assessing {len(state.generated_files)} files across 5 categories")

    for iteration in range(1, MAX_QA_ITERATIONS + 1):
        t0 = time.time()

        try:
            qa_result = await scorer.score(
                files=state.generated_files,
                spec=spec,
                iteration=iteration,
                score_history=score_history,
            )
        except Exception as exc:
            logger.error(f"[{state.run_id}] build_qa_node scorer failed (iteration {iteration}): {exc}")
            break

        score_history.append(qa_result.total_score)
        elapsed = time.time() - t0

        # ── Log the full breakdown ────────────────────────────────────────────
        cats = qa_result.categories
        await _log(
            state.run_id,
            f"QA [{iteration}/{MAX_QA_ITERATIONS}] Score: {qa_result.total_score}/100 "
            f"(API {cats.get('api', 0)}/25 · "
            f"Wiring {cats.get('wiring', 0)}/25 · "
            f"Intelligence {cats.get('intelligence', 0)}/25 · "
            f"Infrastructure {cats.get('infrastructure', 0)}/15 · "
            f"Quality {cats.get('code_quality', 0)}/10) · "
            f"{len([i for i in qa_result.issues if i.severity == 'critical'])} critical issues · "
            f"{elapsed:.1f}s",
        )

        if qa_result.passed:
            await _log(state.run_id,
                       f"QA PASSED — {qa_result.total_score}/100. Build meets global quality standard.")
            break

        # ── Fix and iterate ───────────────────────────────────────────────────
        if iteration < MAX_QA_ITERATIONS:
            critical_count = sum(1 for i in qa_result.issues if i.severity == "critical")
            await _log(state.run_id,
                       f"QA fixing {critical_count} critical issue(s) — "
                       f"running iteration {iteration + 1}")
            try:
                state.generated_files = await fixer.fix(
                    files=state.generated_files,
                    qa_result=qa_result,
                    spec=spec,
                    run_id=state.run_id,
                )
            except Exception as exc:
                logger.error(
                    f"[{state.run_id}] build_qa_node fixer failed (iteration {iteration}): {exc}"
                )
                break
        else:
            # Final iteration, no more fixes
            band = _score_band(qa_result.total_score)
            await _log(
                state.run_id,
                f"QA complete after {MAX_QA_ITERATIONS} iterations. "
                f"Final: {qa_result.total_score}/100 [{band}]. "
                f"Score progression: {' → '.join(str(s) for s in score_history)}",
                level=("WARNING" if qa_result.total_score < 85 else "INFO"),
            )

    # ── Persist to state and DB ───────────────────────────────────────────────
    if qa_result:
        state.qa_result = qa_result  # type: ignore[attr-defined]
        await _persist_qa_result(state.run_id, qa_result)

    return state


# ── Helpers ───────────────────────────────────────────────────────────────────


def _score_band(score: int) -> str:
    if score >= 95:
        return "PASS"
    if score >= 85:
        return "GOOD"
    if score >= 70:
        return "WARNING"
    return "POOR"


async def _log(run_id: str, message: str, level: str = "INFO") -> None:
    """Write to loguru and build_logs table."""
    if level == "WARNING":
        logger.warning(f"[{run_id}] [build_qa] {message}")
    else:
        logger.info(f"[{run_id}] [build_qa] {message}")
    try:
        from pipeline.pipeline import _build_log
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_build_log(run_id, "build_qa", message, level))
    except Exception:
        pass


async def _persist_qa_result(run_id: str, qa_result: QAResult) -> None:
    """Merge QA result into ForgeRun.metadata_json."""
    try:
        from sqlalchemy import select
        from sqlalchemy import update as _update
        from memory.database import get_session
        from memory.models import ForgeRun

        async with get_session() as session:
            row = await session.execute(
                select(ForgeRun.metadata_json).where(ForgeRun.run_id == run_id)
            )
            existing = row.scalar_one_or_none() or {}
            if not isinstance(existing, dict):
                try:
                    import json
                    existing = json.loads(existing) if existing else {}
                except Exception:
                    existing = {}
            existing["build_qa"] = qa_result.to_dict()
            await session.execute(
                _update(ForgeRun)
                .where(ForgeRun.run_id == run_id)
                .values(metadata_json=existing)
            )
    except Exception as exc:
        logger.warning(f"[{run_id}] QA result persist failed (non-blocking): {exc}")
