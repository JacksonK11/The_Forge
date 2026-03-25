"""
pipeline/services/template_library.py
After each successful build with positive deployment feedback, extracts proven
file patterns and stores them as reusable templates. Future builds start from
templates instead of generating from scratch, dramatically reducing errors.

Only stores templates from builds that passed sandbox validation AND received
positive deployment feedback (deployed_successfully=True, zero files_modified).
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from sqlalchemy import text

from memory.database import get_session


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _classify_file_type(file_path: str) -> str | None:
    """Map file path to a reusable template type."""
    p = file_path.lower()
    if p.endswith("app/api/main.py"):
        return "fastapi_main"
    if "models.py" in p and "memory" in p:
        return "sqlalchemy_models"
    if "dockerfile.api" in p or p == "dockerfile.api":
        return "dockerfile_api"
    if "dockerfile.worker" in p:
        return "dockerfile_worker"
    if p.startswith("fly.") and p.endswith(".toml"):
        return "fly_toml"
    if "worker.py" in p or "pipeline/worker" in p:
        return "rq_worker"
    if "pipeline_node" in p or "/nodes/" in p:
        return "pipeline_node"
    if p.endswith(".jsx") and "dashboard" in p:
        return "react_dashboard"
    if p.endswith("requirements.txt"):
        return "requirements_txt"
    if "docker-compose" in p:
        return "docker_compose"
    return None


def _generalise_content(content: str, spec: dict) -> str:
    """Replace agent-specific names with placeholders."""
    agent_name = spec.get("agent_name", "")
    agent_slug = spec.get("agent_slug", "")
    result = content
    if agent_name:
        result = result.replace(agent_name, "{AGENT_NAME}")
    if agent_slug:
        result = result.replace(agent_slug, "{AGENT_SLUG}")
    # Replace specific Fly app names (pattern: xxx-yyy-zzz)
    result = re.sub(
        r'app\s*=\s*"[a-z][a-z0-9-]+-(?:api|worker|dashboard)"',
        'app = "{AGENT_SLUG}-api"',
        result,
    )
    return result


# ---------------------------------------------------------------------------
# TemplateLibrary
# ---------------------------------------------------------------------------


class TemplateLibrary:
    """
    Extracts proven file patterns from successful builds and stores them as
    reusable templates so future builds can start from a validated baseline.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_templates(
        self,
        run_id: str,
        all_files: list[dict],
        sandbox_passed: bool,
        feedback: dict | None,
    ) -> int:
        """
        Extract templates from a successful build.

        Only stores templates when:
          - sandbox_passed is True
          - feedback is None  OR  (deployed_successfully=True AND no files_modified)

        Returns the number of templates stored/updated; 0 on any error.
        """
        # --- Guard: only extract from high-quality builds ---------------
        if not sandbox_passed:
            logger.debug(
                "template_library.extract_templates: sandbox did not pass — skipping"
            )
            return 0

        if feedback is not None:
            deployed_ok = bool(feedback.get("deployed_successfully", False))
            files_modified = feedback.get("files_modified", [])
            if not deployed_ok or len(files_modified) != 0:
                logger.debug(
                    "template_library.extract_templates: feedback indicates imperfect "
                    "deployment — skipping (deployed_successfully={}, files_modified={})",
                    deployed_ok,
                    len(files_modified),
                )
                return 0

        stored = 0

        for file_entry in all_files:
            try:
                file_path: str = file_entry.get("path", "")
                content: str = file_entry.get("content", "")

                if not file_path or not content:
                    continue

                file_type = _classify_file_type(file_path)
                if file_type is None:
                    continue

                generalised = _generalise_content(content, spec={})

                async with get_session() as session:
                    # Check whether a row already exists
                    result = await session.execute(
                        text(
                            "SELECT id, successful_deployments "
                            "FROM build_templates "
                            "WHERE file_type = :ft"
                        ),
                        {"ft": file_type},
                    )
                    row = result.fetchone()

                    if row is not None:
                        existing_id = row[0]
                        existing_deployments: int = row[1] or 0
                        new_deployments = max(existing_deployments, existing_deployments + 1)

                        await session.execute(
                            text(
                                "UPDATE build_templates "
                                "SET template_content = :content, "
                                "    successful_deployments = :deps, "
                                "    updated_at = NOW() "
                                "WHERE id = :id"
                            ),
                            {
                                "content": generalised,
                                "deps": new_deployments,
                                "id": existing_id,
                            },
                        )
                        logger.debug(
                            "template_library: updated template file_type={} (deployments={})",
                            file_type,
                            new_deployments,
                        )
                    else:
                        await session.execute(
                            text(
                                "INSERT INTO build_templates "
                                "(file_type, template_content, successful_deployments, source_run_id, created_at, updated_at) "
                                "VALUES (:ft, :content, 1, :run_id, NOW(), NOW())"
                            ),
                            {
                                "ft": file_type,
                                "content": generalised,
                                "run_id": run_id,
                            },
                        )
                        logger.debug(
                            "template_library: inserted new template file_type={}",
                            file_type,
                        )

                    await session.commit()
                    stored += 1

            except Exception as exc:
                logger.warning(
                    "template_library.extract_templates: DB error for path={} — {}",
                    file_entry.get("path", "unknown"),
                    exc,
                )
                # Continue to next file rather than aborting entirely

        logger.info(
            "template_library.extract_templates: run_id={} stored/updated {} templates",
            run_id,
            stored,
        )
        return stored

    async def get_template(self, file_type: str, spec: dict) -> str | None:
        """
        Retrieve a stored template for file_type and fill spec placeholders.

        Returns the filled template string, or None if not found / on error.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT template_content, successful_deployments "
                        "FROM build_templates "
                        "WHERE file_type = :ft"
                    ),
                    {"ft": file_type},
                )
                row = result.fetchone()

            if row is None:
                logger.debug(
                    "template_library.get_template: no template found for file_type={}",
                    file_type,
                )
                return None

            template_content: str = row[0] or ""
            if not template_content:
                return None

            # Fill placeholders
            agent_name = spec.get("agent_name", "Agent")
            agent_slug = spec.get("agent_slug", "agent")

            tables: list[dict] = spec.get("database_tables", [{}])
            first_table_name = tables[0].get("name", "records") if tables else "records"

            filled = (
                template_content
                .replace("{AGENT_NAME}", agent_name)
                .replace("{AGENT_SLUG}", agent_slug)
                .replace("{TABLE_NAME}", first_table_name)
            )

            logger.debug(
                "template_library.get_template: returning template for file_type={}",
                file_type,
            )
            return filled

        except Exception as exc:
            logger.debug(
                "template_library.get_template: error fetching file_type={} — {}",
                file_type,
                exc,
            )
            return None

    async def enhance_generation(
        self,
        file_spec: dict,
        spec: dict,
        template: str,
    ) -> str:
        """
        Build a prompt string that injects template context for use as
        diagnosis_context in generate_file_for_layer.

        Returns a string; never raises.
        """
        try:
            snippet = template[:3000]
            prompt = (
                "PROVEN TEMPLATE — Use this as your starting point and customise for the current spec.\n"
                "This template has been validated through successful deployments.\n"
                "\n"
                "TEMPLATE:\n"
                f"{snippet}\n"
                "\n"
                "Now adapt this template for the current requirements below."
            )
            return prompt
        except Exception as exc:
            logger.warning(
                "template_library.enhance_generation: failed to build prompt — {}",
                exc,
            )
            return ""
