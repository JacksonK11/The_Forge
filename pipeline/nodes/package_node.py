"""
pipeline/nodes/package_node.py
Stage 6: Package assembly.

Runs the verifier on the complete generated codebase first.
If blocking issues are found, logs them (but does not block packaging —
the build summary includes any verifier warnings).

Then assembles the ZIP:
  - All generated source files
  - README.md
  - FLY_SECRETS.txt
  - connection_test.py
  - SECURITY_REPORT.txt (pip-audit + detect-secrets + verifier results)

Saves ZIP to /tmp/{run_id}.zip and stores path in ForgeRun.package_path.
Stores build outcome in knowledge base for future improvement.
"""

from loguru import logger

from app.api.services.packager import assemble_package, generate_connection_test
from intelligence.verifier import format_verification_report, verify_package
from memory.database import get_session
from memory.models import ForgeFile, ForgeRun, KbRecord
from pipeline.nodes.readme_node import generate_readme_content
from pipeline.nodes.secrets_node import generate_secrets_content
from pipeline.pipeline import PipelineState
from pipeline.quality.linter import format_all_files
from pipeline.quality.security_scanner import run_security_scan


async def package_node(state: PipelineState) -> PipelineState:
    """
    Assemble the final ZIP package.
    Returns updated state with package_path set.
    """
    logger.info(f"[{state.run_id}] Package node started")

    # ── Load all file records from DB ────────────────────────────────────────
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ForgeFile).where(ForgeFile.run_id == state.run_id)
        )
        forge_files = result.scalars().all()

    # ── Format generated files with Black + isort ─────────────────────────────
    formatted_files, format_report = await format_all_files(state.generated_files)
    state.generated_files = formatted_files
    if format_report:
        logger.debug(f"[{state.run_id}] Linter report: {str(format_report)[:200]}")

    # ── Run verifier on complete package ─────────────────────────────────────
    spec = state.spec or {}
    verifier_result = await verify_package(
        agent_name=spec.get("agent_name", "Unknown"),
        fly_services=[s["name"] for s in spec.get("fly_services", [])],
        file_manifest=state.manifest.get("file_manifest", []) if state.manifest else [],
        generated_files=state.generated_files,
    )
    if not verifier_result.deployment_ready:
        logger.warning(
            f"[{state.run_id}] Verifier found {len(verifier_result.blocking_issues)} blocking issues — "
            f"packaging anyway with warnings in build report"
        )

    # ── Run security scan (pip-audit + detect-secrets + anti-patterns) ────────
    security_scan_content = await run_security_scan(state.generated_files)
    full_security_report = (
        security_scan_content
        + "\n\n"
        + format_verification_report(verifier_result)
    )

    # ── Generate supporting documents ─────────────────────────────────────────
    readme_content = await generate_readme_content(state)
    fly_secrets_content = await generate_secrets_content(state)
    connection_test_content = generate_connection_test(spec)

    # ── Assemble ZIP ─────────────────────────────────────────────────────────
    package_bytes = await assemble_package(
        run=await _load_run(state.run_id),
        files=forge_files,
        readme_content=readme_content,
        fly_secrets_content=fly_secrets_content,
        connection_test_content=connection_test_content,
        security_report_content=full_security_report,
    )

    # ── Save ZIP to disk ─────────────────────────────────────────────────────
    package_path = f"/tmp/{state.run_id}.zip"
    with open(package_path, "wb") as f:
        f.write(package_bytes)

    logger.info(
        f"[{state.run_id}] Package saved: {package_path} ({len(package_bytes):,} bytes)"
    )

    # ── Update run record ────────────────────────────────────────────────────
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeRun)
            .where(ForgeRun.run_id == state.run_id)
            .values(package_path=package_path)
        )

    # ── Store build outcome in knowledge base ─────────────────────────────────
    await _store_kb_record(state, len(forge_files), len(state.failed_files))

    state.current_stage = "complete"
    return state


async def _load_run(run_id: str) -> ForgeRun:
    """Load ForgeRun from DB."""
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ForgeRun).where(ForgeRun.run_id == run_id)
        )
        return result.scalar_one()


async def _store_kb_record(
    state: PipelineState,
    total_files: int,
    failed_files: int,
) -> None:
    """Store build outcome in knowledge base for future pattern retrieval."""
    try:
        spec = state.spec or {}
        outcome = "success" if failed_files == 0 else "partial"
        content = (
            f"Build pattern for {spec.get('agent_name', 'unknown agent')}. "
            f"Stack: {', '.join(spec.get('external_apis', []))}. "
            f"Services: {len(spec.get('fly_services', []))}. "
            f"Tables: {len(spec.get('database_tables', []))}. "
            f"Files: {total_files} generated, {failed_files} failed. "
            f"Result: {outcome}."
        )
        async with get_session() as session:
            record = KbRecord(
                run_id=state.run_id,
                record_type="build_pattern",
                content=content,
                outcome=outcome,
                metadata_json={
                    "agent_slug": spec.get("agent_slug"),
                    "total_files": total_files,
                    "failed_files": failed_files,
                    "services": [s["name"] for s in spec.get("fly_services", [])],
                },
            )
            session.add(record)
        logger.debug(f"[{state.run_id}] Build outcome stored in knowledge base")
    except Exception as exc:
        logger.warning(f"[{state.run_id}] KB record storage failed (non-blocking): {exc}")
