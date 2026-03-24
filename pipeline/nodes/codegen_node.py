"""
pipeline/nodes/codegen_node.py
Stage 5: Layered Code Generation orchestrator.

Works through the build manifest layer by layer (1→7).
Within each layer, generates files in dependency order.
After each file: runs the Evaluator to check completeness.
Files failing evaluation are regenerated up to 3 times.
Progress is reported to DB after every file.
"""

from loguru import logger

from memory.database import get_session
from memory.models import FileStatus, ForgeFile, ForgeRun
from pipeline.nodes.layer_generator import generate_file_for_layer
from pipeline.pipeline import PipelineState


async def codegen_node(state: PipelineState) -> PipelineState:
    """
    Orchestrate layered code generation through all 7 layers.
    Updates state.generated_files, state.failed_files, and DB records.
    After layers 1-4, generates pytest test files (Phase 8).
    """
    if not state.spec or not state.manifest:
        raise ValueError("Codegen node requires spec and manifest")

    logger.info(f"[{state.run_id}] Code generation started")
    file_manifest = state.manifest.get("file_manifest", [])
    _LAYERS_BEFORE_TESTS = 4  # Generate tests after layer 4 is complete

    # Group files by layer, preserving order within each layer
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

            try:
                content = await generate_file_for_layer(
                    run_id=state.run_id,
                    file_entry=file_entry,
                    spec=state.spec,
                    generated_files=state.generated_files,
                )
            except Exception as exc:
                logger.error(f"[{state.run_id}] EXCEPTION generating {file_path}: {exc}")
                state.failed_files.append(file_path)
                await _mark_file_failed(state.run_id, file_path)
                processed += 1
                await _update_run_progress(state.run_id, processed, len(state.failed_files))
                continue

            if content is not None:
                state.generated_files[file_path] = content
                await _mark_file_complete(state.run_id, file_path, content)
            else:
                state.failed_files.append(file_path)
                await _mark_file_failed(state.run_id, file_path)

            processed += 1
            await _update_run_progress(state.run_id, processed, len(state.failed_files))

            logger.debug(
                f"[{state.run_id}] Progress: {processed}/{total_files} — "
                f"{'✓' if content else '✗'} {file_path}"
            )

    # ── Phase 8: Generate pytest test files after layers 1-4 ────────────────
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
        f"{len(state.generated_files)} generated, "
        f"{len(state.failed_files)} failed"
    )
    state.current_stage = "packaging"
    return state


async def _mark_file_complete(run_id: str, file_path: str, content: str) -> None:
    """Mark a file record as complete and store its content."""
    import tiktoken
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(content))
    except Exception:
        token_count = len(content) // 4  # Rough fallback estimate

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


async def _mark_file_failed(run_id: str, file_path: str) -> None:
    """Mark a file record as permanently failed."""
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeFile)
            .where(ForgeFile.run_id == run_id, ForgeFile.file_path == file_path)
            .values(status=FileStatus.FAILED.value)
        )


async def _update_run_progress(
    run_id: str,
    files_complete: int,
    files_failed: int,
    current_file_path: str = "",
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
