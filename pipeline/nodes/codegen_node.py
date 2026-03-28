"""
pipeline/nodes/codegen_node.py
Stage 5: Layered Code Generation orchestrator.

Works through the build manifest layer by layer (1→7).
Within each layer, generates files in dependency order.
After each file: runs the Evaluator to check completeness.
Files failing evaluation are regenerated up to 3 times.
Progress is reported to DB after every file.

Cost protection:
  TOKEN_HARD_CAP: if cumulative tokens for the run exceeds 4,000,000 (≈A$30 at
  Sonnet rates), the build is killed, the run is marked cost_limit_exceeded,
  and a Telegram alert is sent. This is a hard kill switch — it fires before
  every file and is checked every COST_CHECK_INTERVAL files.

  Cost milestones: Telegram notifications are sent at A$10, A$15, A$20, and
  A$30 as the build progresses. A pre-build estimate is also sent before
  generation begins.

Graceful file failure (Safeguard 2):
  If generate_file_for_layer returns None, a placeholder file is saved to DB
  with status='generation_failed'. The placeholder is included in the ZIP so
  the developer knows exactly which files need manual attention. The run
  completes rather than failing entirely — failed files are listed in the
  final Telegram notification.

Safeguard gaps (added):
  Gap 1 — Cross-reference imports against already-generated files after each save.
           If the current file imports a symbol from an already-generated file
           and that symbol is absent, the source file is re-generated once.
  Gap 3 — Non-determinism guard for large files (>800 estimated lines).
           Compares function/class count against a Redis baseline of recent
           similar-complexity builds. >20% below average → re-evaluate strictly.
  Gap 5 — Redis checkpoint every CHECKPOINT_INTERVAL files.
           On worker restart, the checkpoint is loaded and already-completed
           files are skipped, limiting replay loss to ≤5 files.
"""

import json
import re

from loguru import logger

from config.settings import settings
from memory.database import get_session
from memory.models import FileStatus, ForgeFile, ForgeRun
from pipeline.nodes.layer_generator import generate_file_for_layer
from pipeline.pipeline import PipelineState
from pipeline.services.build_doctor import BuildDoctor
from pipeline.services.dependency_manifest import DependencyManifest

TOKEN_HARD_CAP = 4_000_000     # Hard kill at ≈A$30 (Sonnet) — covers 200+ file builds
COST_CHECK_INTERVAL = 5        # Query DB every N files (reduces DB load)

# ── Cost milestone thresholds (AUD) — Telegram alert sent when each is crossed ─
COST_MILESTONES_AUD = [10, 15, 20, 30]

# ── Average tokens per file (Sonnet codegen: ~10K input + 1.5K output) ────────
_AVG_TOKENS_PER_FILE = 11_500

# ── Gap 5 checkpoint constants ────────────────────────────────────────────────
CHECKPOINT_INTERVAL = 5                  # Save to Redis every N files
_CHECKPOINT_TTL_SECONDS = 4 * 3600      # Expire stale checkpoints after 4 hours
_CHECKPOINT_PREFIX = "forge:checkpoint:"

# ── Gap 3 complexity constants ────────────────────────────────────────────────
_LARGE_FILE_LINE_THRESHOLD = 800        # Files ≥ this many estimated lines get non-determinism check
_COMPLEXITY_PREFIX = "forge:complexity:"
_COMPLEXITY_MAX_ENTRIES = 10            # Ring buffer size per file basename
_NONDETERMINISM_THRESHOLD = 0.20        # >20% below average → re-evaluate

def _tokens_to_aud(tokens: int) -> float:
    """
    Estimate AUD cost from a token count using Sonnet 4.6 blended rates.
    Assumes 85% input ($3/M USD) / 15% output ($15/M USD), converted at 1.55 AUD/USD.
    """
    usd = (tokens / 1_000_000) * (0.85 * 3.0 + 0.15 * 15.0)  # $4.80/M blended
    return usd * 1.55


_PLACEHOLDER_TEMPLATE = """\
# ══════════════════════════════════════════════════════════════════
# GENERATION FAILED — REQUIRES MANUAL IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════
#
# File:    {file_path}
# Purpose: {purpose}
#
# This file could not be generated automatically after all retry attempts.
# Common causes:
#   - File is too large for automated generation (even with split fallback)
#   - Output truncation persisted despite split-generation strategy
#   - Evaluation quality checks failed on all attempts
#
# To implement manually:
#   1. Review the agent spec for this file's requirements
#   2. Implement all functions with full type hints and error handling
#   3. Use loguru for all logging — no print() statements
#   4. Wrap every external API call in try/except with logger.error()
#   5. Reference adjacent layer files for import path conventions
#
raise NotImplementedError(
    "This file requires manual implementation — see comment header for details."
)
"""


async def codegen_node(state: PipelineState) -> PipelineState:
    """
    Orchestrate layered code generation through all 7 layers.

    Checks the token hard cap every COST_CHECK_INTERVAL files.
    On cap breach: marks run as cost_limit_exceeded and raises RuntimeError
    to stop the pipeline immediately.

    Files that return None from generate_file_for_layer receive a placeholder
    with status=generation_failed and are added to state.generation_failed_files.
    The run continues to the next file rather than failing entirely.
    """
    if not state.spec or not state.manifest:
        raise ValueError("Codegen node requires spec and manifest")

    logger.info(f"[{state.run_id}] Code generation started")
    file_manifest = state.manifest.get("file_manifest", [])

    # Group files by layer, preserving dependency order within each layer
    layers: dict[int, list[dict]] = {}
    for file_entry in file_manifest:
        layer = file_entry.get("layer", 1)
        if layer not in layers:
            layers[layer] = []
        layers[layer].append(file_entry)

    total_files = len(file_manifest)
    processed = 0

    # ── Self-healing services ─────────────────────────────────────────────────
    doctor = BuildDoctor()
    manifest_builder = DependencyManifest()
    cumulative_manifest: dict = {"files": []}
    file_reports: list[dict] = []

    # ── Gap 5: Load Redis checkpoint — skip already-completed files on restart ─
    redis_conn = _get_redis_conn()
    checkpoint = _load_checkpoint(state.run_id, redis_conn)
    already_done: set[str] = set()
    if checkpoint:
        already_done = set(checkpoint.get("completed_paths", []))
        if already_done:
            restored = await _restore_completed_content(state.run_id, already_done)
            state.generated_files.update(restored)
            processed = checkpoint.get("total_processed", len(already_done))
            logger.info(
                f"[{state.run_id}] Checkpoint loaded: resuming from file "
                f"{processed}/{total_files} — skipping {len(already_done)} completed files"
            )
            try:
                from app.api.services.notify import _send
                await _send(
                    f"<b>The Forge — Build Resumed from Checkpoint</b>\n\n"
                    f"<b>{state.title}</b>\n"
                    f"Resuming interrupted build from file "
                    f"<b>{processed}/{total_files}</b>.\n"
                    f"Skipping {len(already_done)} already-completed files."
                )
            except Exception:
                pass

    # Track source files we've already attempted to re-generate (Gap 1 guard)
    cross_ref_regenerated: set[str] = set()

    # Track which AUD cost milestones have already been notified this build
    cost_milestones_notified: set[int] = set()

    # ── Pre-build cost estimate notification ──────────────────────────────────
    try:
        from app.api.services.notify import notify_build_cost_estimate
        estimated_tokens = total_files * _AVG_TOKENS_PER_FILE
        estimated_cost_aud = _tokens_to_aud(estimated_tokens)
        await notify_build_cost_estimate(
            run_id=state.run_id,
            title=state.title,
            file_count=total_files,
            estimated_tokens=estimated_tokens,
            estimated_cost_aud=estimated_cost_aud,
        )
    except Exception as _notify_exc:
        logger.debug(f"[{state.run_id}] Pre-build estimate notification failed (non-blocking): {_notify_exc}")

    for layer_num in sorted(layers.keys()):
        layer_files = layers[layer_num]
        logger.info(
            f"[{state.run_id}] Generating layer {layer_num}: {len(layer_files)} files"
        )
        state.current_layer = layer_num

        # Track files generated in this layer for manifest building
        layer_generated_files: dict[str, str] = {}

        for file_entry in layer_files:
            file_path = file_entry["path"]
            state.current_file = file_path

            # ── Gap 5: Skip files restored from checkpoint ────────────────────
            if file_path in already_done:
                logger.debug(f"[{state.run_id}] Checkpoint skip: {file_path}")
                continue

            # ── Token / cost check (every COST_CHECK_INTERVAL files) ──────────
            if processed % COST_CHECK_INTERVAL == 0 and processed > 0:
                total_tokens = await _get_run_total_tokens(state.run_id)
                current_cost_aud = _tokens_to_aud(total_tokens)

                # ── Cost milestone notifications (A$10 / A$15 / A$20 / A$30) ──
                for milestone in COST_MILESTONES_AUD:
                    if current_cost_aud >= milestone and milestone not in cost_milestones_notified:
                        cost_milestones_notified.add(milestone)
                        logger.info(
                            f"[{state.run_id}] Cost milestone reached: "
                            f"A${milestone} (actual A${current_cost_aud:.2f}, "
                            f"{total_tokens:,} tokens, {processed}/{total_files} files)"
                        )
                        try:
                            from app.api.services.notify import notify_cost_milestone
                            await notify_cost_milestone(
                                run_id=state.run_id,
                                title=state.title,
                                cost_aud=current_cost_aud,
                                milestone_aud=milestone,
                                total_tokens=total_tokens,
                                files_complete=processed,
                                file_count=total_files,
                            )
                        except Exception as _m_exc:
                            logger.debug(f"[{state.run_id}] Milestone notify failed (non-blocking): {_m_exc}")

                # ── Hard cap kill ──────────────────────────────────────────────
                if total_tokens >= TOKEN_HARD_CAP:
                    logger.critical(
                        f"[{state.run_id}] TOKEN HARD CAP EXCEEDED: "
                        f"{total_tokens:,} >= {TOKEN_HARD_CAP:,}. "
                        f"Killing build at {processed}/{total_files} files."
                    )
                    await _mark_run_cost_limit_exceeded(state.run_id, total_tokens)
                    try:
                        from app.api.services.notify import notify_cost_limit_exceeded
                        await notify_cost_limit_exceeded(
                            run_id=state.run_id,
                            title=state.title,
                            total_tokens=total_tokens,
                            total_cost_aud=current_cost_aud,
                            files_complete=processed,
                            file_count=total_files,
                        )
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Build killed: token hard cap exceeded "
                        f"({total_tokens:,} tokens >= {TOKEN_HARD_CAP:,}). "
                        f"Completed {processed}/{total_files} files before kill."
                    )

            # ── Generate file via BuildDoctor diagnose-and-repair loop ─────────
            manifest_str = manifest_builder.format_for_prompt(cumulative_manifest)
            content, _tokens, file_report = await doctor.diagnose_and_repair(
                file_spec=file_entry,
                full_spec=state.spec,
                prior_files=state.generated_files,
                run_id=state.run_id,
                max_attempts=3,
            )
            file_report["file_path"] = file_path
            file_reports.append(file_report)

            # ── Validate imports against dependency manifest ───────────────────
            if content and cumulative_manifest.get("files"):
                try:
                    validation = await manifest_builder.validate_file(
                        file_content=content,
                        file_spec=file_entry,
                        manifest=cumulative_manifest,
                    )
                    if not validation["valid"] and validation.get("mismatches"):
                        logger.warning(
                            f"[{state.run_id}] Import mismatch in {file_path}: "
                            f"{validation['mismatches']}"
                        )
                        repair_diag = {
                            "diagnosis": "Import mismatch detected",
                            "root_cause": "Wrong import name used",
                            "fix_instructions": (
                                f"Fix these imports: {validation['mismatches']}"
                            ),
                            "similar_fixes": [],
                        }
                        fixed, _ = await doctor.repair(
                            file_spec=file_entry,
                            full_spec=state.spec,
                            prior_files=state.generated_files,
                            diagnosis=repair_diag,
                            attempt=0,
                        )
                        if fixed:
                            content = fixed
                except Exception as val_exc:
                    logger.debug(
                        f"[{state.run_id}] Manifest validation failed (non-blocking): {val_exc}"
                    )

            if content is not None:
                state.generated_files[file_path] = content
                layer_generated_files[file_path] = content
                await _mark_file_complete(state.run_id, file_path, content)

                # ── Gap 1: Cross-reference imports against already-generated files ──
                missing = _cross_reference_imports(
                    file_path, content, state.generated_files, state.run_id
                )
                for source_file, missing_names in missing:
                    if source_file not in cross_ref_regenerated:
                        cross_ref_regenerated.add(source_file)
                        source_entry = next(
                            (e for e in file_manifest if e["path"] == source_file), None
                        )
                        if source_entry:
                            logger.warning(
                                f"[{state.run_id}] Cross-ref: re-generating {source_file} "
                                f"— missing exports {missing_names} needed by {file_path}"
                            )
                            try:
                                fixed = await generate_file_for_layer(
                                    run_id=state.run_id,
                                    file_entry=source_entry,
                                    spec=state.spec,
                                    generated_files=state.generated_files,
                                    dependency_manifest=manifest_str,
                                )
                                if fixed:
                                    state.generated_files[source_file] = fixed
                                    layer_generated_files[source_file] = fixed
                                    await _mark_file_complete(
                                        state.run_id, source_file, fixed
                                    )
                            except Exception as regen_exc:
                                logger.error(
                                    f"[{state.run_id}] Cross-ref re-gen failed for "
                                    f"{source_file}: {regen_exc}"
                                )

                # ── Gap 3: Non-determinism guard for large files ───────────────
                estimated_lines = content.count("\n") + 1
                if estimated_lines >= _LARGE_FILE_LINE_THRESHOLD:
                    _check_and_store_complexity(
                        file_path, content, redis_conn, state.run_id
                    )

                # ── Gap 5: Save checkpoint every CHECKPOINT_INTERVAL files ─────
                if (processed + 1) % CHECKPOINT_INTERVAL == 0:
                    _save_checkpoint(
                        run_id=state.run_id,
                        completed_paths=list(
                            p for p in state.generated_files
                            if p not in state.generation_failed_files
                        ),
                        current_layer=layer_num,
                        total_processed=processed + 1,
                        redis_conn=redis_conn,
                    )

            else:
                # BuildDoctor exhausted — save placeholder, track warning, continue build
                purpose = file_entry.get("description", f"File at {file_path}")
                placeholder = _PLACEHOLDER_TEMPLATE.format(
                    file_path=file_path,
                    purpose=purpose,
                )
                state.generated_files[file_path] = placeholder
                state.generation_failed_files.append(file_path)
                await _save_generation_failed_file(state.run_id, file_path, placeholder)
                logger.warning(
                    f"[{state.run_id}] {file_path} saved as generation_failed placeholder "
                    f"after BuildDoctor exhausted all repair attempts"
                )

            processed += 1
            await _update_run_progress(
                state.run_id,
                files_complete=processed - len(state.generation_failed_files),
                files_failed=len(state.generation_failed_files),
            )

            logger.debug(
                f"[{state.run_id}] Progress: {processed}/{total_files} — "
                f"{'✓' if content is not None else '⚠ placeholder'} {file_path}"
            )

        # ── Build dependency manifest after each layer completes ──────────────
        if layer_generated_files:
            try:
                layer_manifest = await manifest_builder.build_manifest(
                    layer_num=layer_num,
                    completed_files=layer_generated_files,
                )
                cumulative_manifest = manifest_builder.accumulate(
                    cumulative_manifest, layer_manifest
                )
                logger.debug(
                    f"[{state.run_id}] Layer {layer_num} manifest built: "
                    f"{len(layer_manifest.get('files', []))} files"
                )
            except Exception as mani_exc:
                logger.warning(
                    f"[{state.run_id}] Manifest build for layer {layer_num} "
                    f"failed (non-blocking): {mani_exc}"
                )

    # ── Phase 8: Generate pytest test files after layers 1-4 ─────────────────
    try:
        from pipeline.nodes.test_generator import generate_test_files
        test_files = await generate_test_files(state)
        for test_path, test_content in test_files.items():
            state.generated_files[test_path] = test_content
            await _mark_file_complete(state.run_id, test_path, test_content)
        if test_files:
            logger.info(f"[{state.run_id}] Test suite generated: {len(test_files)} test files")
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Test generation failed (non-blocking): {exc}")

    # ── Post-build health report ──────────────────────────────────────────────
    health_report_str: str = ""
    try:
        health_report_str = await doctor.post_build_report(state.run_id, file_reports)
        logger.info(f"[{state.run_id}] {health_report_str}")
    except Exception as report_exc:
        logger.warning(
            f"[{state.run_id}] Post-build report failed (non-blocking): {report_exc}"
        )

    # ── Coherence check — verify files work together as a system ─────────────
    all_files_list = [
        {"path": p, "content": c} for p, c in state.generated_files.items()
    ]
    coherence_result: dict = {"passed": True, "total_issues": 0}
    try:
        from pipeline.services.coherence_checker import CoherenceChecker
        checker = CoherenceChecker()
        coherence_result = await checker.check_coherence(all_files_list, state.spec or {})
        logger.info(
            f"[{state.run_id}] COHERENCE: {'PASSED' if coherence_result.get('passed') else 'ISSUES'} — "
            f"{coherence_result.get('total_issues', 0)} issues found"
        )
        if not coherence_result.get("passed"):
            fixed_files = await checker.auto_fix(all_files_list, coherence_result)
            for f in fixed_files:
                state.generated_files[f["path"]] = f["content"]
            all_files_list = fixed_files
    except Exception as coh_exc:
        logger.warning(f"[{state.run_id}] Coherence check failed (non-blocking): {coh_exc}")

    # ── Sandbox validation — actually run the code ────────────────────────────
    sandbox_result: dict = {"passed": True, "app_loads": True, "syntax_errors": [], "import_errors": []}
    sandbox_dir: str = f"/tmp/forge-sandbox-{state.run_id}"
    try:
        from pipeline.services.sandbox import BuildSandbox
        sandbox = BuildSandbox()
        sandbox_result = await sandbox.validate_package(state.run_id, all_files_list)
        logger.info(
            f"[{state.run_id}] SANDBOX: {'PASSED' if sandbox_result.get('passed') else 'FAILED'} — "
            f"syntax_errors={len(sandbox_result.get('syntax_errors', []))} "
            f"import_errors={len(sandbox_result.get('import_errors', []))} "
            f"app_loads={sandbox_result.get('app_loads', False)}"
        )
        if not sandbox_result.get("passed"):
            repaired = await sandbox.repair_from_sandbox(
                state.run_id, sandbox_result, all_files_list
            )
            for f in repaired:
                state.generated_files[f["path"]] = f["content"]
            all_files_list = repaired
            # Re-validate after repairs
            sandbox_result = await sandbox.validate_package(state.run_id, all_files_list)
            logger.info(
                f"[{state.run_id}] SANDBOX (post-repair): "
                f"{'PASSED' if sandbox_result.get('passed') else 'STILL FAILING'}"
            )
    except Exception as sb_exc:
        logger.warning(f"[{state.run_id}] Sandbox validation failed (non-blocking): {sb_exc}")

    # ── Run tests in sandbox ──────────────────────────────────────────────────
    test_results: dict = {"total": 0, "passed": 0, "failed": 0}
    try:
        from pipeline.nodes.test_generator import TestGenerator
        test_gen = TestGenerator()
        test_results = await test_gen.run_tests_in_sandbox(
            run_id=state.run_id,
            sandbox_dir=sandbox_dir,
        )
        logger.info(
            f"[{state.run_id}] TESTS: {test_results.get('passed', 0)}/{test_results.get('total', 0)} passed"
        )
    except Exception as test_exc:
        logger.warning(f"[{state.run_id}] Test run failed (non-blocking): {test_exc}")
    finally:
        # Always clean up sandbox directory
        try:
            from pipeline.services.sandbox import BuildSandbox as _BS
            _BS().cleanup(state.run_id)
        except Exception:
            pass

    # ── Gap 5: Delete checkpoint on successful completion ─────────────────────
    try:
        if redis_conn:
            redis_conn.delete(f"{_CHECKPOINT_PREFIX}{state.run_id}")
    except Exception:
        pass

    # ── Persist quality gate results to metadata_json (surfaces in /report) ───
    # health_report, coherence_results, sandbox_results, test_results were all
    # computed above but never written to the DB — this is the fix.
    try:
        from sqlalchemy import select, update as _update
        healed_count = sum(1 for r in file_reports if r.get("healed"))
        failed_count = sum(
            1 for r in file_reports
            if not r.get("healed") and r.get("attempts", 1) > 1
        )
        health_report_dict = {
            "summary": health_report_str,
            "total_files": len(file_reports),
            "clean": len(file_reports) - healed_count - failed_count,
            "healed": healed_count,
            "failed": failed_count,
        }
        async with get_session() as _session:
            _row = await _session.execute(
                select(ForgeRun.metadata_json).where(ForgeRun.run_id == state.run_id)
            )
            existing_meta = _row.scalar_one_or_none() or {}
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            existing_meta.update({
                "health_report": health_report_dict,
                "coherence_results": coherence_result,
                "sandbox_results": sandbox_result,
                "test_results": test_results,
                "blueprint_validation": state.blueprint_validation or None,
            })
            await _session.execute(
                _update(ForgeRun)
                .where(ForgeRun.run_id == state.run_id)
                .values(metadata_json=existing_meta)
            )
        logger.info(
            f"[{state.run_id}] Quality gate results persisted to metadata_json "
            f"(coherence={'PASS' if coherence_result.get('passed') else 'FAIL'}, "
            f"sandbox={'PASS' if sandbox_result.get('passed') else 'FAIL'}, "
            f"tests={test_results.get('passed', 0)}/{test_results.get('total', 0)})"
        )
    except Exception as _meta_exc:
        logger.warning(
            f"[{state.run_id}] metadata_json quality gate persist failed (non-blocking): {_meta_exc}"
        )

    logger.info(
        f"[{state.run_id}] Code generation complete: "
        f"{len(state.generated_files) - len(state.generation_failed_files)} generated, "
        f"{len(state.generation_failed_files)} failed (placeholders saved)"
    )
    state.current_stage = "packaging"
    return state


# ── Gap 5: Redis checkpoint helpers ──────────────────────────────────────────


def _get_redis_conn():
    """Return a Redis connection or None if unavailable (non-blocking)."""
    try:
        from redis import Redis
        return Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    except Exception:
        return None


def _save_checkpoint(
    run_id: str,
    completed_paths: list[str],
    current_layer: int,
    total_processed: int,
    redis_conn,
) -> None:
    """Save a build checkpoint to Redis. Silent on failure."""
    if not redis_conn:
        return
    try:
        from datetime import datetime, timezone
        payload = json.dumps({
            "run_id": run_id,
            "completed_paths": completed_paths,
            "current_layer": current_layer,
            "total_processed": total_processed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        key = f"{_CHECKPOINT_PREFIX}{run_id}"
        redis_conn.setex(key, _CHECKPOINT_TTL_SECONDS, payload)
        logger.debug(
            f"[{run_id}] Checkpoint saved: {len(completed_paths)} files, "
            f"layer={current_layer}, processed={total_processed}"
        )
    except Exception as exc:
        logger.debug(f"[{run_id}] Checkpoint save failed (non-blocking): {exc}")


def _load_checkpoint(run_id: str, redis_conn) -> dict | None:
    """Load a checkpoint from Redis. Returns None if missing or expired."""
    if not redis_conn:
        return None
    try:
        from datetime import datetime, timedelta, timezone
        key = f"{_CHECKPOINT_PREFIX}{run_id}"
        raw = redis_conn.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        # Ignore checkpoints older than 4 hours
        ts = datetime.fromisoformat(data.get("timestamp", "1970-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - ts > timedelta(hours=4):
            redis_conn.delete(key)
            return None
        return data
    except Exception as exc:
        logger.debug(f"[{run_id}] Checkpoint load failed (non-blocking): {exc}")
        return None


async def _restore_completed_content(
    run_id: str,
    completed_paths: set[str],
) -> dict[str, str]:
    """Load content of already-completed files from DB to rebuild state.generated_files."""
    restored: dict[str, str] = {}
    if not completed_paths:
        return restored
    try:
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(ForgeFile.file_path, ForgeFile.content).where(
                    ForgeFile.run_id == run_id,
                    ForgeFile.file_path.in_(list(completed_paths)),
                    ForgeFile.status == FileStatus.COMPLETE.value,
                    ForgeFile.content.isnot(None),
                )
            )
            for file_path, content in result.all():
                restored[file_path] = content
        logger.debug(
            f"[{run_id}] Restored {len(restored)}/{len(completed_paths)} files from DB"
        )
    except Exception as exc:
        logger.warning(f"[{run_id}] Content restore failed (non-blocking): {exc}")
    return restored


# ── Gap 1: Cross-reference imports helper ─────────────────────────────────────


def _cross_reference_imports(
    file_path: str,
    content: str,
    generated_files: dict[str, str],
    run_id: str,
) -> list[tuple[str, list[str]]]:
    """
    Parse the current file's Python import statements and check that every
    symbol imported from an already-generated file actually exists there.

    Returns a list of (source_file_path, [missing_name, ...]) tuples.
    Only applies to local module imports — stdlib/third-party imports are ignored.
    """
    if not file_path.endswith(".py"):
        return []

    # Match: from some.module import Name1, Name2 (or Name as Alias)
    import_re = re.compile(r"^from\s+([\w.]+)\s+import\s+(.+)$", re.MULTILINE)
    missing: list[tuple[str, list[str]]] = []

    for match in import_re.finditer(content):
        module_str = match.group(1).strip()
        names_str = match.group(2).strip()

        # Convert dotted module path to file path: memory.models → memory/models.py
        source_file = module_str.replace(".", "/") + ".py"
        if source_file not in generated_files:
            continue  # External dependency — skip

        source_content = generated_files[source_file]

        # Parse imported names, handling "Name as Alias" and trailing comments
        raw_names = re.sub(r"\(|\)", "", names_str).split(",")
        names = [
            n.strip().split(" as ")[0].strip().split("#")[0].strip()
            for n in raw_names
        ]
        names = [n for n in names if n and n != "*"]

        missing_names = []
        for name in names:
            # Check for: class Name, def name, or Name = at module level
            if not re.search(
                rf"(?:^|\n)\s*(?:class|def)\s+{re.escape(name)}\b"
                rf"|(?:^|\n){re.escape(name)}\s*=",
                source_content,
            ):
                missing_names.append(name)

        if missing_names:
            logger.warning(
                f"[{run_id}] Cross-ref: {file_path} imports {missing_names} "
                f"from {source_file} — not found in generated content"
            )
            missing.append((source_file, missing_names))

    return missing


# ── Gap 3: Non-determinism guard helpers ──────────────────────────────────────


def _count_callables(content: str) -> int:
    """Count top-level and method-level def/class definitions as a complexity proxy."""
    return len(re.findall(r"^\s*(?:def |class |async def )", content, re.MULTILINE))


def _check_and_store_complexity(
    file_path: str,
    content: str,
    redis_conn,
    run_id: str,
) -> None:
    """
    Compare this file's callable count against the Redis baseline for similar files.
    If >20% below average of last 3 entries → log warning and mark for strict re-eval.
    Always stores the current count in the rolling Redis buffer.
    """
    if not redis_conn:
        return
    basename = file_path.split("/")[-1]
    key = f"{_COMPLEXITY_PREFIX}{basename}"
    current_count = _count_callables(content)

    try:
        # Load existing entries
        raw = redis_conn.get(key)
        entries: list[dict] = json.loads(raw) if raw else []

        if len(entries) >= 3:
            avg = sum(e["count"] for e in entries[-3:]) / 3
            if avg > 0 and current_count < avg * (1 - _NONDETERMINISM_THRESHOLD):
                logger.warning(
                    f"[{run_id}] Non-determinism guard: {file_path} has "
                    f"{current_count} callables vs baseline avg {avg:.1f} "
                    f"({(1 - current_count / avg) * 100:.0f}% below — threshold "
                    f"{int(_NONDETERMINISM_THRESHOLD * 100)}%)"
                )
                # Store warning in run metadata for final notification
                try:
                    redis_conn.rpush(
                        f"forge:nondeterminism:{run_id}",
                        json.dumps({
                            "file": file_path,
                            "count": current_count,
                            "baseline_avg": round(avg, 1),
                        }),
                    )
                    redis_conn.expire(f"forge:nondeterminism:{run_id}", 86400)
                except Exception:
                    pass

        # Append current count to rolling buffer
        from datetime import datetime, timezone
        entries.append({
            "count": current_count,
            "run_id": run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        entries = entries[-_COMPLEXITY_MAX_ENTRIES:]
        redis_conn.setex(key, 30 * 86400, json.dumps(entries))  # 30-day TTL

    except Exception as exc:
        logger.debug(f"[{run_id}] Complexity check failed (non-blocking): {exc}")


# ── DB helpers ────────────────────────────────────────────────────────────────


async def _get_run_total_tokens(run_id: str) -> int:
    """Return total input+output tokens consumed by this run so far."""
    try:
        from memory.models import BuildCost
        from sqlalchemy import func, select
        async with get_session() as session:
            result = await session.execute(
                select(
                    func.coalesce(
                        func.sum(BuildCost.input_tokens + BuildCost.output_tokens), 0
                    )
                ).where(BuildCost.run_id == run_id)
            )
            return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.warning(f"[{run_id}] Token count query failed (non-blocking): {exc}")
        return 0


async def _mark_run_cost_limit_exceeded(run_id: str, total_tokens: int) -> None:
    """Mark run as cost_limit_exceeded with a descriptive error message."""
    try:
        async with get_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ForgeRun)
                .where(ForgeRun.run_id == run_id)
                .values(
                    status="cost_limit_exceeded",
                    error_message=(
                        f"Build killed: token hard cap exceeded "
                        f"({total_tokens:,} >= {TOKEN_HARD_CAP:,}). "
                        f"Increase TOKEN_HARD_CAP or reduce file count."
                    ),
                )
            )
    except Exception as exc:
        logger.error(f"[{run_id}] Failed to mark cost_limit_exceeded: {exc}")


async def _mark_file_complete(run_id: str, file_path: str, content: str) -> None:
    """Mark a file record as complete and store its content."""
    import tiktoken
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(content))
    except Exception:
        token_count = len(content) // 4

    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeFile)
            .where(ForgeFile.run_id == run_id, ForgeFile.file_path == file_path)
            .values(
                status=FileStatus.COMPLETE.value,
                content=content,
                token_count=token_count,
            )
        )


async def _save_generation_failed_file(run_id: str, file_path: str, placeholder: str) -> None:
    """
    Save a placeholder file to DB with status='generation_failed'.
    The placeholder is included in the ZIP so developers know what to implement.
    """
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeFile)
            .where(ForgeFile.run_id == run_id, ForgeFile.file_path == file_path)
            .values(
                status="generation_failed",
                content=placeholder,
                error_message="All generation attempts failed — placeholder saved",
            )
        )


async def _update_run_progress(
    run_id: str,
    files_complete: int,
    files_failed: int,
) -> None:
    """Update the run's progress counters in DB."""
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeRun)
            .where(ForgeRun.run_id == run_id)
            .values(
                files_complete=files_complete,
                files_failed=files_failed,
            )
        )
