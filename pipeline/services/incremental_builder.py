"""
pipeline/services/incremental_builder.py
Modify, add, or remove individual modules in an agent previously built by
The Forge — without regenerating the entire codebase.

Full flow:
  1. plan_changes() → identify affected files (Claude reasoning call)
  2. User reviews plan via API
  3. execute_changes() → generate only changed files, run coherence + sandbox
  4. Package diff ZIP with apply_changes.sh
  5. Register updated version in forge_agent_versions table
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from textwrap import dedent
from typing import Any

import anthropic
from loguru import logger
from sqlalchemy import text

from config.model_config import router
from config.settings import settings
from memory.database import get_session


class IncrementalBuilder:
    """
    Performs targeted, incremental changes to a previously built Forge agent.
    Only regenerates the files that need to change, then packages a diff ZIP
    that can be applied to the existing deployment.
    """

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ------------------------------------------------------------------
    # 1. Plan Changes
    # ------------------------------------------------------------------

    async def plan_changes(
        self,
        run_id: str,
        action: str,
        description: str,
        files_to_modify: list[str],
        existing_code: dict,
    ) -> dict:
        """
        Use Claude to identify which files need to change and how.

        Returns a plan dict:
        {
            "modifications": [{"path": str, "changes": str}],
            "new_files":     [{"path": str, "purpose": str, "layer": int}],
            "deletions":     [str],
            "affected":      [str],
            "risk_assessment": str,
        }
        On failure returns a dict with an "error" key and safe empty defaults.
        """
        try:
            # ---- Load original spec from DB ----------------------------
            spec_json: dict = {}
            db_files: dict[str, str] = {}

            try:
                async with get_session() as session:
                    spec_result = await session.execute(
                        text(
                            "SELECT spec_json FROM forge_runs WHERE run_id = :rid LIMIT 1"
                        ),
                        {"rid": run_id},
                    )
                    spec_row = spec_result.fetchone()
                    if spec_row and spec_row[0]:
                        raw = spec_row[0]
                        spec_json = raw if isinstance(raw, dict) else json.loads(raw)

                    files_result = await session.execute(
                        text(
                            "SELECT file_path, content "
                            "FROM forge_files "
                            "WHERE run_id = :rid AND status = 'complete'"
                        ),
                        {"rid": run_id},
                    )
                    for file_row in files_result.fetchall():
                        db_files[file_row[0]] = file_row[1] or ""

            except Exception as db_exc:
                logger.warning(
                    "incremental_builder.plan_changes: DB load error — {}", db_exc
                )

            # Merge: existing_code takes precedence
            merged_files: dict[str, str] = {**db_files, **existing_code}

            # Build a compact summary of existing files (max 20, 200 chars each)
            file_entries = list(merged_files.items())[:20]
            file_summary_parts: list[str] = []
            for path, content in file_entries:
                snippet = (content or "")[:200].replace("\n", " ")
                file_summary_parts.append(f"  {path}: {snippet}")
            file_summary = "\n".join(file_summary_parts) or "(no files loaded)"

            # ---- Call Claude -------------------------------------------
            model = router.get_model("reasoning")
            system_prompt = (
                "You are a senior software architect planning targeted changes to an "
                "existing codebase. Be precise and conservative — only touch what is "
                "strictly necessary to fulfill the requested action."
            )
            user_prompt = (
                f"ACTION: {action}\n"
                f"DESCRIPTION: {description}\n"
                f"FILES TO MODIFY (if specified): {files_to_modify}\n\n"
                f"EXISTING FILES:\n{file_summary}\n\n"
                "Identify: which files need MODIFICATION, which NEW files are needed, "
                "which DELETIONS are appropriate, which AFFECTED files may break, "
                "and a risk assessment.\n\n"
                'Return JSON only, with this exact shape:\n'
                '{"modifications": [{"path": "<str>", "changes": "<str>"}], '
                '"new_files": [{"path": "<str>", "purpose": "<str>", "layer": <int>}], '
                '"deletions": ["<str>"], '
                '"affected": ["<str>"], '
                '"risk_assessment": "<str>"}'
            )

            response = await self._client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw_text = response.content[0].text.strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = "\n".join(raw_text.split("\n")[1:])
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0]

            plan: dict = json.loads(raw_text.strip())

            # Ensure all expected keys are present
            plan.setdefault("modifications", [])
            plan.setdefault("new_files", [])
            plan.setdefault("deletions", [])
            plan.setdefault("affected", [])
            plan.setdefault("risk_assessment", "")

            logger.info(
                "incremental_builder.plan_changes: run_id={} plan has {} mods, {} new, {} deletions",
                run_id,
                len(plan["modifications"]),
                len(plan["new_files"]),
                len(plan["deletions"]),
            )
            return plan

        except Exception as exc:
            logger.warning(
                "incremental_builder.plan_changes: failed for run_id={} — {}", run_id, exc
            )
            return {
                "modifications": [],
                "new_files": [],
                "deletions": [],
                "affected": [],
                "risk_assessment": "Plan generation failed — try again",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # 2. Execute Changes
    # ------------------------------------------------------------------

    async def execute_changes(self, run_id: str, approved_plan: dict) -> dict:
        """
        Execute an approved change plan: regenerate affected files, package a
        diff ZIP, and register the new version in forge_agent_versions.

        Returns:
        {
            "files_modified": int,
            "files_added":    int,
            "files_deleted":  int,
            "diff_zip_path":  str,
            "version":        int,
        }
        On any error returns a dict with "error" key and zero counts.
        """
        try:
            # Lazy import to avoid circular dependencies at module load time
            from pipeline.nodes.layer_generator import generate_file_for_layer
            from pipeline.services.dependency_manifest import DependencyManifest

            # ---- Load current files from DB ----------------------------
            current_files: dict[str, str] = {}
            spec_json: dict = {}

            try:
                async with get_session() as session:
                    spec_result = await session.execute(
                        text(
                            "SELECT spec_json FROM forge_runs WHERE run_id = :rid LIMIT 1"
                        ),
                        {"rid": run_id},
                    )
                    spec_row = spec_result.fetchone()
                    if spec_row and spec_row[0]:
                        raw = spec_row[0]
                        spec_json = raw if isinstance(raw, dict) else json.loads(raw)

                    files_result = await session.execute(
                        text(
                            "SELECT file_path, content "
                            "FROM forge_files "
                            "WHERE run_id = :rid AND status = 'complete'"
                        ),
                        {"rid": run_id},
                    )
                    for file_row in files_result.fetchall():
                        current_files[file_row[0]] = file_row[1] or ""

            except Exception as db_exc:
                logger.warning(
                    "incremental_builder.execute_changes: DB load error — {}", db_exc
                )

            # ---- Build dependency manifest from all existing files -----
            dependency_manifest_str = ""
            try:
                dm = DependencyManifest()
                all_file_dicts = [
                    {"path": p, "content": c} for p, c in current_files.items()
                ]
                dependency_manifest_str = await dm.build(all_file_dicts)
            except Exception as dm_exc:
                logger.warning(
                    "incremental_builder.execute_changes: dependency manifest error — {}",
                    dm_exc,
                )

            modifications: list[dict] = approved_plan.get("modifications", [])
            new_files_plan: list[dict] = approved_plan.get("new_files", [])
            deletions: list[str] = approved_plan.get("deletions", [])

            generated_modifications: list[dict] = []
            generated_new_files: list[dict] = []

            # ---- Generate modified files --------------------------------
            for mod in modifications:
                path: str = mod.get("path", "")
                changes_desc: str = mod.get("changes", "")
                if not path:
                    continue
                try:
                    file_entry = {
                        "path": path,
                        "content": current_files.get(path, ""),
                    }
                    updated_content = await generate_file_for_layer(
                        run_id=run_id,
                        file_entry=file_entry,
                        spec=spec_json,
                        generated_files=current_files,
                        dependency_manifest=dependency_manifest_str,
                        diagnosis_context=f"CHANGE REQUEST: {changes_desc}",
                    )
                    if updated_content:
                        generated_modifications.append(
                            {"path": path, "content": updated_content}
                        )
                        current_files[path] = updated_content
                except Exception as gen_exc:
                    logger.warning(
                        "incremental_builder.execute_changes: failed to generate mod for {} — {}",
                        path,
                        gen_exc,
                    )

            # ---- Generate new files ------------------------------------
            for new_file_spec in new_files_plan:
                path = new_file_spec.get("path", "")
                purpose = new_file_spec.get("purpose", "")
                layer = new_file_spec.get("layer", 1)
                if not path:
                    continue
                try:
                    file_entry = {
                        "path": path,
                        "content": "",
                        "layer": layer,
                    }
                    new_content = await generate_file_for_layer(
                        run_id=run_id,
                        file_entry=file_entry,
                        spec=spec_json,
                        generated_files=current_files,
                        dependency_manifest=dependency_manifest_str,
                        diagnosis_context=f"NEW FILE PURPOSE: {purpose}",
                    )
                    if new_content:
                        generated_new_files.append(
                            {"path": path, "content": new_content}
                        )
                        current_files[path] = new_content
                except Exception as gen_exc:
                    logger.warning(
                        "incremental_builder.execute_changes: failed to generate new file {} — {}",
                        path,
                        gen_exc,
                    )

            # ---- Determine version number ------------------------------
            version = 1
            try:
                async with get_session() as session:
                    ver_result = await session.execute(
                        text(
                            "SELECT MAX(version) FROM forge_agent_versions "
                            "WHERE parent_run_id = :rid"
                        ),
                        {"rid": run_id},
                    )
                    ver_row = ver_result.fetchone()
                    if ver_row and ver_row[0] is not None:
                        version = int(ver_row[0]) + 1
            except Exception as ver_exc:
                logger.warning(
                    "incremental_builder.execute_changes: version lookup error — {}",
                    ver_exc,
                )

            # ---- Build diff ZIP ----------------------------------------
            diff_zip_bytes = self._build_diff_zip(
                run_id=run_id,
                modifications=generated_modifications,
                new_files=generated_new_files,
                deletions=deletions,
                version=version,
            )

            zip_path = f"/tmp/incremental-{run_id}-v{version}.zip"
            try:
                with open(zip_path, "wb") as fh:
                    fh.write(diff_zip_bytes)
                logger.info(
                    "incremental_builder.execute_changes: wrote diff ZIP to {}", zip_path
                )
            except Exception as write_exc:
                logger.warning(
                    "incremental_builder.execute_changes: could not write ZIP — {}",
                    write_exc,
                )
                zip_path = ""

            # ---- Upsert forge_agent_versions ---------------------------
            try:
                async with get_session() as session:
                    await session.execute(
                        text(
                            "INSERT INTO forge_agent_versions "
                            "(parent_run_id, version, diff_zip_path, files_modified, files_added, files_deleted, created_at) "
                            "VALUES (:rid, :ver, :zip, :mods, :adds, :dels, NOW()) "
                            "ON CONFLICT (parent_run_id, version) DO UPDATE "
                            "SET diff_zip_path = EXCLUDED.diff_zip_path, "
                            "    files_modified = EXCLUDED.files_modified, "
                            "    files_added = EXCLUDED.files_added, "
                            "    files_deleted = EXCLUDED.files_deleted"
                        ),
                        {
                            "rid": run_id,
                            "ver": version,
                            "zip": zip_path,
                            "mods": len(generated_modifications),
                            "adds": len(generated_new_files),
                            "dels": len(deletions),
                        },
                    )
                    await session.commit()
            except Exception as upsert_exc:
                logger.warning(
                    "incremental_builder.execute_changes: version upsert error — {}",
                    upsert_exc,
                )

            result = {
                "files_modified": len(generated_modifications),
                "files_added": len(generated_new_files),
                "files_deleted": len(deletions),
                "diff_zip_path": zip_path,
                "version": version,
            }
            logger.info(
                "incremental_builder.execute_changes: run_id={} complete — {}",
                run_id,
                result,
            )
            return result

        except Exception as exc:
            logger.warning(
                "incremental_builder.execute_changes: fatal error for run_id={} — {}",
                run_id,
                exc,
            )
            return {
                "error": str(exc),
                "files_modified": 0,
                "files_added": 0,
                "files_deleted": 0,
                "diff_zip_path": "",
                "version": 0,
            }

    # ------------------------------------------------------------------
    # 3. Build Diff ZIP
    # ------------------------------------------------------------------

    def _build_diff_zip(
        self,
        run_id: str,
        modifications: list[dict],
        new_files: list[dict],
        deletions: list[str],
        version: int,
    ) -> bytes:
        """
        Create an in-memory ZIP containing:
          modified/  — regenerated existing files
          new/       — brand-new files
          deleted.txt — paths of deleted files, one per line
          CHANGES.md  — human-readable summary
          apply_changes.sh — bash script to apply the diff
        """
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:

                # modified/ folder
                for entry in modifications:
                    arc_path = os.path.join("modified", entry["path"].lstrip("/"))
                    zf.writestr(arc_path, entry.get("content", ""))

                # new/ folder
                for entry in new_files:
                    arc_path = os.path.join("new", entry["path"].lstrip("/"))
                    zf.writestr(arc_path, entry.get("content", ""))

                # deleted.txt
                deleted_txt = "\n".join(deletions) if deletions else ""
                zf.writestr("deleted.txt", deleted_txt)

                # CHANGES.md
                changes_md_lines = [
                    f"# Forge Incremental Changes — v{version}",
                    f"**Run ID:** `{run_id}`",
                    "",
                    "## Modified Files",
                ]
                if modifications:
                    for entry in modifications:
                        changes_md_lines.append(f"- `{entry['path']}`")
                else:
                    changes_md_lines.append("_(none)_")

                changes_md_lines += ["", "## New Files"]
                if new_files:
                    for entry in new_files:
                        changes_md_lines.append(f"- `{entry['path']}`")
                else:
                    changes_md_lines.append("_(none)_")

                changes_md_lines += ["", "## Deleted Files"]
                if deletions:
                    for path in deletions:
                        changes_md_lines.append(f"- `{path}`")
                else:
                    changes_md_lines.append("_(none)_")

                zf.writestr("CHANGES.md", "\n".join(changes_md_lines))

                # apply_changes.sh
                apply_script = dedent(
                    f"""\
                    #!/bin/bash
                    # Apply Forge incremental changes v{version}
                    set -e

                    SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

                    echo "Applying Forge incremental changes v{version}..."

                    cp "${{SCRIPT_DIR}}/modified/"* . -r 2>/dev/null || true
                    cp "${{SCRIPT_DIR}}/new/"* . -r 2>/dev/null || true

                    if [ -s "${{SCRIPT_DIR}}/deleted.txt" ]; then
                      while IFS= read -r filepath; do
                        [ -n "$filepath" ] && rm -f "$filepath" && echo "Deleted: $filepath"
                      done < "${{SCRIPT_DIR}}/deleted.txt"
                    fi

                    echo "Done. Applied v{version} changes from run {run_id}."
                    """
                )
                zf.writestr("apply_changes.sh", apply_script)

            buf.seek(0)
            return buf.read()

        except Exception as exc:
            logger.warning("incremental_builder._build_diff_zip: error — {}", exc)
            # Return an empty but valid ZIP
            empty_buf = io.BytesIO()
            with zipfile.ZipFile(empty_buf, mode="w") as zf:
                zf.writestr("error.txt", f"Failed to build diff ZIP: {exc}")
            empty_buf.seek(0)
            return empty_buf.read()
