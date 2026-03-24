"""
pipeline/nodes/codegen_node.py
Stage 5: Layered Code Generation orchestrator.

Works through the build manifest layer by layer (1→7).
Within each layer, generates files in dependency order.
After each file: runs the Evaluator to check completeness.
Files failing evaluation are regenerated up to 3 times.
Progress is reported to DB after every file.

Cost protection:
  TOKEN_HARD_CAP: if cumulative tokens for the run exceeds 500,000 (≈A$15 at
  Sonnet rates), the build is killed, the run is marked cost_limit_exceeded,
  and a Telegram alert is sent. This is a hard kill switch — it fires before
  every file and is checked every COST_CHECK_INTERVAL files.

Graceful file failure (Safeguard 2):
  If generate_file_for_layer returns None, a placeholder file is saved to DB
  with status='generation_failed'. The placeholder is included in the ZIP so
  the developer knows exactly which files need manual attention. The run
  completes rather than failing entirely — failed files are listed in the
  final Telegram notification.
"""

from loguru import logger

from memory.database import get_session
from memory.models import FileStatus, ForgeFile, ForgeRun
from pipeline.nodes.layer_generator import generate_file_for_layer
from pipeline.pipeline import PipelineState

TOKEN_HARD_CAP = 500_000       # Hard kill at ≈A$15 (Sonnet) / ≈A$75 (Opus)
COST_CHECK_INTERVAL = 5        # Query DB every N files (reduces DB load)

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

    for layer_num in sorted(layers.keys()):
        layer_files = layers[layer_num]
        logger.info(
            f"[{state.run_id}] Generating layer {layer_num}: {len(layer_files)} files"
        )
        state.current_layer = layer_num

        for file_entry in layer_files:
            file_path = file_entry["path"]
            state.current_file = file_path

            # ── Token hard cap check (every COST_CHECK_INTERVAL files) ────────
            if processed % COST_CHECK_INTERVAL == 0 and processed > 0:
                total_tokens = await _get_run_total_tokens(state.run_id)
                if total_tokens >= TOKEN_HARD_CAP:
                    logger.critical(
                        f"[{state.run_id}] TOKEN HARD CAP EXCEEDED: "
                        f"{total_tokens:,} >= {TOKEN_HARD_CAP:,}. "
                        f"Killing build at {processed}/{total_files} files."
                    )
                    await _mark_run_cost_limit_exceeded(state.run_id, total_tokens)
                    try:
                        from app.api.services.notify import notify_cost_limit_exceeded
                        cost_aud_estimate = (total_tokens / 1_000_000) * 15.0 * 1.58
                        await notify_cost_limit_exceeded(
                            run_id=state.run_id,
                            title=state.title,
                            total_tokens=total_tokens,
                            total_cost_aud=cost_aud_estimate,
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

            # ── Generate file ─────────────────────────────────────────────────
            try:
                content = await generate_file_for_layer(
                    run_id=state.run_id,
                    file_entry=file_entry,
                    spec=state.spec,
                    generated_files=state.generated_files,
                )
            except Exception as exc:
                logger.error(f"[{state.run_id}] EXCEPTION generating {file_path}: {exc}")
                content = None

            if content is not None:
                state.generated_files[file_path] = content
                await _mark_file_complete(state.run_id, file_path, content)
            else:
                # Safeguard 2: save placeholder, track warning, continue build
                purpose = file_entry.get("description", f"File at {file_path}")
                placeholder = _PLACEHOLDER_TEMPLATE.format(
                    file_path=file_path,
                    purpose=purpose,
                )
                state.generated_files[file_path] = placeholder
                state.generation_failed_files.append(file_path)
                await _save_generation_failed_file(state.run_id, file_path, placeholder)
                logger.warning(
                    f"[{state.run_id}] {file_path} saved as generation_failed placeholder"
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

    logger.info(
        f"[{state.run_id}] Code generation complete: "
        f"{len(state.generated_files) - len(state.generation_failed_files)} generated, "
        f"{len(state.generation_failed_files)} failed (placeholders saved)"
    )
    state.current_stage = "packaging"
    return state


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
