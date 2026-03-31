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

import json

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
        blocking_count = len(verifier_result.blocking_issues)
        logger.warning(
            f"[{state.run_id}] Verifier found {blocking_count} blocking issues — "
            f"packaging with issues in build report"
        )
        # Inject verifier blocking issues into failed_files_report so they appear
        # prominently in the build summary, Telegram notification, and dashboard UI
        verifier_issues_text = "\n\n=== VERIFIER BLOCKING ISSUES (fix before deploying) ===\n"
        for issue in verifier_result.blocking_issues:
            verifier_issues_text += (
                f"\n[{issue.category.upper()}] {issue.file}\n"
                f"  Problem: {issue.issue}\n"
                f"  Fix:     {issue.fix}\n"
            )
        state.failed_files_report = (state.failed_files_report or "") + verifier_issues_text

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
    feedback_reporter_content = _generate_feedback_reporter(state.run_id)

    # ── Register agent version ────────────────────────────────────────────────
    await _register_agent_version(state)

    # ── Assemble ZIP ─────────────────────────────────────────────────────────
    package_bytes = await assemble_package(
        run=await _load_run(state.run_id),
        files=forge_files,
        readme_content=readme_content,
        fly_secrets_content=fly_secrets_content,
        connection_test_content=connection_test_content,
        security_report_content=full_security_report,
        failed_files_report_content=state.failed_files_report or None,
        feedback_reporter_content=feedback_reporter_content,
    )

    # ── Save ZIP to disk ─────────────────────────────────────────────────────
    package_path = f"/tmp/{state.run_id}.zip"
    with open(package_path, "wb") as f:
        f.write(package_bytes)

    logger.info(
        f"[{state.run_id}] Package saved: {package_path} ({len(package_bytes):,} bytes)"
    )

    # ── Update run record — store bytes in DB so any API machine can serve it ──
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeRun)
            .where(ForgeRun.run_id == state.run_id)
            .values(package_path=package_path, package_data=package_bytes)
        )

    # ── Store build outcome in knowledge base ─────────────────────────────────
    await _store_kb_record(state, len(forge_files), len(state.failed_files))

    state.current_stage = "complete"
    return state


def _generate_feedback_reporter(run_id: str) -> str:
    """Generate a standalone feedback_reporter.py script with run_id hardcoded."""
    return f'''#!/usr/bin/env python3
"""
feedback_reporter.py — Post-deployment feedback for The Forge
Run after deploying your agent: python feedback_reporter.py

This script sends deployment feedback to The Forge so it can learn from
real-world outcomes and improve future builds.

No dependencies beyond Python stdlib.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

RUN_ID = "{run_id}"
DEFAULT_FORGE_URL = "https://the-forge-api.fly.dev"


def post_json(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {{"error": f"HTTP {{e.code}}: {{e.reason}}"}}
    except Exception as e:
        return {{"error": str(e)}}


def ask(prompt: str, default: str = "") -> str:
    try:
        answer = input(prompt).strip()
        return answer if answer else default
    except (EOFError, KeyboardInterrupt):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit deployment feedback to The Forge")
    parser.add_argument("--forge-url", default=DEFAULT_FORGE_URL, help="The Forge API URL")
    parser.add_argument("--run-id", default=RUN_ID, help="Build run ID")
    args = parser.parse_args()

    print("\\n=== The Forge — Deployment Feedback ===")
    print(f"Run ID: {{args.run_id}}")
    print("Your feedback helps The Forge generate better code in future builds.\\n")

    deployed = ask("Did the agent deploy successfully on first try? (y/n): ").lower() == "y"

    files_modified = []
    if not deployed or ask("Did you modify any generated files before deploying? (y/n): ").lower() == "y":
        paths_input = ask("Which files did you need to modify? (comma-separated paths, or Enter to skip): ")
        if paths_input:
            for path in [p.strip() for p in paths_input.split(",") if p.strip()]:
                change = ask(f"  What was wrong with {{path}}? ")
                files_modified.append({{"path": path, "change_description": change, "error_message": ""}})

    deployment_errors = []
    errors_input = ask("Any deployment errors? (paste error or press Enter to skip): ")
    if errors_input:
        deployment_errors.append(errors_input[:2000])

    notes = ask("Any other notes? (optional, press Enter to skip): ")

    payload = {{
        "run_id": args.run_id,
        "deployed_successfully": deployed,
        "files_modified": files_modified,
        "deployment_errors": deployment_errors,
        "notes": notes,
    }}

    print("\\nSubmitting feedback...")
    result = post_json(f"{{args.forge_url}}/forge/feedback", payload)

    if "error" in result:
        print(f"\\nFeedback submission failed: {{result['error']}}")
        print("(You can retry later — the data is not lost)")
        sys.exit(1)
    else:
        print("\\nFeedback submitted. The Forge will learn from this. Thank you!")


if __name__ == "__main__":
    main()
'''


async def _register_agent_version(state: PipelineState) -> None:
    """Register this build in forge_agent_versions for incremental build tracking."""
    try:
        from sqlalchemy import text
        spec = state.spec or {}
        agent_name = spec.get("agent_name", state.title)
        file_manifest = {
            path: {"layer": 0, "chars": len(content)}
            for path, content in state.generated_files.items()
        }
        async with get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO forge_agent_versions
                        (run_id, agent_name, spec_json, file_manifest, version, parent_run_id, created_at)
                    VALUES
                        (:run_id, :agent_name, :spec_json::jsonb, :file_manifest::jsonb, 1, NULL, NOW())
                    ON CONFLICT DO NOTHING
                """),
                {
                    "run_id": state.run_id,
                    "agent_name": agent_name,
                    "spec_json": json.dumps(spec),
                    "file_manifest": json.dumps(file_manifest),
                },
            )
        logger.debug(f"[{state.run_id}] Agent version registered: {agent_name} v1")
    except Exception as exc:
        logger.warning(f"[{state.run_id}] Agent version registration failed (non-blocking): {exc}")


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
