"""
app/api/routes/dashboard_stats.py
Dashboard statistics and utility routes for The Forge UI.

GET /forge/runs/pending              — spec_ready runs awaiting approval
GET /forge/notifications             — notification counts + recent activity
GET /forge/search?q={query}          — cross-entity search
GET /forge/intelligence/stats        — KB / meta-rules / template counts
GET /forge/templates                 — list all build templates
GET /forge/templates/{template_id}   — full template content
GET /forge/registry                  — agent version registry grouped by agent_name
GET /forge/config                    — env var presence check + model config
GET /forge/runs/{runId}/report       — build health report from metadata_json
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from sqlalchemy import desc, func, select

from app.api.ratelimit import limiter
from config.settings import settings
from memory.database import get_db
from memory.models import (
    BuildTemplate,
    DeploymentFeedback,
    ForgeAgentVersion,
    ForgeRun,
    KbRecord,
    MetaRule,
)

router = APIRouter()


# ── 1. Pending runs (spec_ready) ─────────────────────────────────────────────


@router.get("/runs/pending")
@limiter.limit("60/minute")
async def get_pending_runs(request: Request) -> list[dict]:
    """
    Returns runs with status='spec_ready', ordered oldest first.
    Used by the Approval Queue tab in the dashboard.
    """
    async for session in get_db():
        result = await session.execute(
            select(ForgeRun)
            .where(ForgeRun.status == "spec_ready")
            .order_by(ForgeRun.created_at.asc())
        )
        runs = result.scalars().all()

        logger.debug(f"[pending-runs] Found {len(runs)} spec_ready runs")

        return [
            {
                "run_id": r.run_id,
                "title": r.title,
                "blueprint_text": (r.blueprint_text or "")[:500] if r.blueprint_text else None,
                "spec_json": r.spec_json,
                "blueprint_validation": (r.spec_json or {}).get("blueprint_validation") if r.spec_json else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]


# ── 2. Notifications ──────────────────────────────────────────────────────────


@router.get("/notifications")
@limiter.limit("60/minute")
async def get_notifications(request: Request) -> dict:
    """
    Dashboard notification counts and recent activity feed.
    Returns pendingApprovals, activeBuilds, failedBuilds (last 24h),
    pendingFeedback, and recentActivity (last 5 runs).
    """
    active_statuses = [
        "parsing",
        "validating",
        "confirming",
        "architecting",
        "generating",
        "packaging",
    ]
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    async for session in get_db():
        # Pending approvals — spec_ready
        pending_result = await session.execute(
            select(func.count(ForgeRun.run_id)).where(ForgeRun.status == "spec_ready")
        )
        pending_approvals: int = pending_result.scalar_one() or 0

        # Active builds — in-pipeline statuses
        active_result = await session.execute(
            select(func.count(ForgeRun.run_id)).where(
                ForgeRun.status.in_(active_statuses)
            )
        )
        active_builds: int = active_result.scalar_one() or 0

        # Failed builds in last 24 hours
        failed_result = await session.execute(
            select(func.count(ForgeRun.run_id)).where(
                ForgeRun.status == "failed",
                ForgeRun.created_at > since_24h,
            )
        )
        failed_builds: int = failed_result.scalar_one() or 0

        # Pending feedback — forge_agent_versions with no matching deployment_feedback run_id
        # Subquery: run_ids that already have feedback
        feedback_run_ids_result = await session.execute(
            select(DeploymentFeedback.run_id)
        )
        feedback_run_ids = {row[0] for row in feedback_run_ids_result.fetchall()}

        agent_versions_result = await session.execute(
            select(ForgeAgentVersion.run_id)
        )
        all_agent_run_ids = [row[0] for row in agent_versions_result.fetchall()]
        pending_feedback = sum(
            1 for rid in all_agent_run_ids if rid not in feedback_run_ids
        )

        # Recent activity — last 5 runs
        recent_result = await session.execute(
            select(ForgeRun)
            .order_by(ForgeRun.created_at.desc())
            .limit(5)
        )
        recent_runs = recent_result.scalars().all()

        # Map status to activity type
        def _activity_type(status: str) -> str:
            if status == "complete":
                return "build_complete"
            if status == "failed":
                return "build_failed"
            if status == "spec_ready":
                return "approval_needed"
            if status in active_statuses:
                return "build_active"
            return "build_queued"

        recent_activity = [
            {
                "type": _activity_type(r.status),
                "title": r.title,
                "run_id": r.run_id,
                "status": r.status,
                "timestamp": r.created_at.isoformat(),
            }
            for r in recent_runs
        ]

        logger.debug(
            f"[notifications] pending={pending_approvals} active={active_builds} "
            f"failed_24h={failed_builds} pending_feedback={pending_feedback}"
        )

        return {
            "pendingApprovals": pending_approvals,
            "activeBuilds": active_builds,
            "failedBuilds": failed_builds,
            "pendingFeedback": pending_feedback,
            "recentActivity": recent_activity,
        }


# ── 3. Search ─────────────────────────────────────────────────────────────────


@router.get("/search")
@limiter.limit("60/minute")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
) -> list[dict]:
    """
    Cross-entity search across forge_runs, forge_agent_versions, build_templates, meta_rules.
    Returns up to 8 results with type, id, title, and deep-link url.
    Case-insensitive ILIKE search.
    """
    results: list[dict] = []
    pattern = f"%{q}%"

    async for session in get_db():
        # forge_runs — search by title
        runs_result = await session.execute(
            select(ForgeRun)
            .where(ForgeRun.title.ilike(pattern))
            .order_by(ForgeRun.created_at.desc())
            .limit(4)
        )
        for run in runs_result.scalars().all():
            results.append(
                {
                    "type": "build",
                    "id": run.run_id,
                    "title": run.title,
                    "url": f"/forge/runs/{run.run_id}",
                }
            )

        # forge_agent_versions — search by agent_name
        agents_result = await session.execute(
            select(ForgeAgentVersion)
            .where(ForgeAgentVersion.agent_name.ilike(pattern))
            .order_by(ForgeAgentVersion.created_at.desc())
            .limit(4)
        )
        seen_agents: set[str] = set()
        for av in agents_result.scalars().all():
            if av.agent_name not in seen_agents:
                seen_agents.add(av.agent_name)
                results.append(
                    {
                        "type": "agent",
                        "id": str(av.id),
                        "title": av.agent_name,
                        "url": f"/forge/registry",
                    }
                )

        # build_templates — search by file_type
        templates_result = await session.execute(
            select(BuildTemplate)
            .where(BuildTemplate.file_type.ilike(pattern))
            .order_by(BuildTemplate.updated_at.desc())
            .limit(4)
        )
        for tmpl in templates_result.scalars().all():
            results.append(
                {
                    "type": "template",
                    "id": str(tmpl.id),
                    "title": tmpl.file_type,
                    "url": f"/forge/templates/{tmpl.id}",
                }
            )

        # meta_rules — search by rule_text
        rules_result = await session.execute(
            select(MetaRule)
            .where(MetaRule.rule_text.ilike(pattern))
            .order_by(MetaRule.created_at.desc())
            .limit(4)
        )
        for rule in rules_result.scalars().all():
            results.append(
                {
                    "type": "rule",
                    "id": str(rule.id),
                    "title": rule.rule_text[:120],
                    "url": f"/forge/intelligence/stats",
                }
            )

    # Deduplicate and cap at 8
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for item in results:
        key = f"{item['type']}:{item['id']}"
        if key not in seen_ids:
            seen_ids.add(key)
            deduped.append(item)
        if len(deduped) >= 8:
            break

    logger.debug(f"[search] q={q!r} → {len(deduped)} results")
    return deduped


# ── 4. Intelligence stats ─────────────────────────────────────────────────────


@router.get("/intelligence/stats")
@limiter.limit("60/minute")
async def get_intelligence_stats(request: Request) -> dict:
    """
    Counts for all intelligence / KB tables.
    Returns kb_records, meta_rules_active, build_templates, recent_builds, error_fix_pairs.
    """
    async for session in get_db():
        # kb_records total
        kb_result = await session.execute(select(func.count(KbRecord.id)))
        kb_records: int = kb_result.scalar_one() or 0

        # meta_rules active
        rules_result = await session.execute(
            select(func.count(MetaRule.id)).where(MetaRule.is_active.is_(True))
        )
        meta_rules_active: int = rules_result.scalar_one() or 0

        # build_templates total
        templates_result = await session.execute(
            select(func.count(BuildTemplate.id))
        )
        build_templates: int = templates_result.scalar_one() or 0

        # recent_builds — completed in last 7 days
        since_7d = datetime.now(timezone.utc) - timedelta(days=7)
        recent_result = await session.execute(
            select(func.count(ForgeRun.run_id)).where(
                ForgeRun.status == "complete",
                ForgeRun.created_at >= since_7d,
            )
        )
        recent_builds: int = recent_result.scalar_one() or 0

        # error_fix_pairs — kb_records of type "deployment_failure"
        fix_result = await session.execute(
            select(func.count(KbRecord.id)).where(
                KbRecord.record_type == "deployment_failure"
            )
        )
        error_fix_pairs: int = fix_result.scalar_one() or 0

        logger.debug(
            f"[intelligence-stats] kb={kb_records} rules={meta_rules_active} "
            f"templates={build_templates} recent={recent_builds} fixes={error_fix_pairs}"
        )

        return {
            "kb_records": kb_records,
            "meta_rules_active": meta_rules_active,
            "build_templates": build_templates,
            "recent_builds": recent_builds,
            "error_fix_pairs": error_fix_pairs,
        }


# ── 5. Templates list ─────────────────────────────────────────────────────────


@router.get("/templates")
@limiter.limit("60/minute")
async def list_build_templates(request: Request) -> list[dict]:
    """
    List all build templates with metadata and a 500-char preview.
    Used by the Intelligence → Templates tab.
    """
    async for session in get_db():
        result = await session.execute(
            select(BuildTemplate).order_by(
                BuildTemplate.successful_deployments.desc(),
                BuildTemplate.updated_at.desc(),
            )
        )
        templates = result.scalars().all()

        logger.debug(f"[templates] Returning {len(templates)} build templates")

        return [
            {
                "id": t.id,
                "file_type": t.file_type,
                "successful_deployments": t.successful_deployments,
                "source_run_id": t.source_run_id,
                "template_preview": (t.template_content or "")[:500],
                "updated_at": t.updated_at.isoformat(),
            }
            for t in templates
        ]


# ── 6. Template detail ────────────────────────────────────────────────────────


@router.get("/templates/{template_id}")
@limiter.limit("60/minute")
async def get_build_template(
    request: Request,
    template_id: int,
) -> dict:
    """
    Return full content of a single build template.
    """
    async for session in get_db():
        result = await session.execute(
            select(BuildTemplate).where(BuildTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        logger.debug(f"[template-detail] id={template_id} file_type={template.file_type}")

        return {
            "id": template.id,
            "file_type": template.file_type,
            "template_content": template.template_content,
            "source_run_id": template.source_run_id,
            "successful_deployments": template.successful_deployments,
            "created_at": template.created_at.isoformat(),
            "updated_at": template.updated_at.isoformat(),
        }


# ── 7. Agent registry ─────────────────────────────────────────────────────────


@router.get("/registry")
@limiter.limit("60/minute")
async def get_agent_registry(request: Request) -> list[dict]:
    """
    List all ForgeAgentVersion records grouped by agent_name.
    Returns each unique agent with its latest run_id, version count, and first-seen date.
    Used by the Registry tab in the dashboard.
    """
    async for session in get_db():
        # All versions ordered by creation, newest first
        result = await session.execute(
            select(ForgeAgentVersion).order_by(ForgeAgentVersion.created_at.desc())
        )
        all_versions = result.scalars().all()

        # Group by agent_name: track latest_run_id, count, first created_at
        agent_map: dict[str, dict[str, Any]] = {}
        for v in all_versions:
            name = v.agent_name
            if name not in agent_map:
                agent_map[name] = {
                    "agent_name": name,
                    "latest_run_id": v.run_id,
                    "version_count": 0,
                    # newest first, so this will be overwritten to earliest below
                    "created_at": v.created_at.isoformat(),
                }
            agent_map[name]["version_count"] += 1
            # Keep earliest created_at as the "registered" date
            if v.created_at.isoformat() < agent_map[name]["created_at"]:
                agent_map[name]["created_at"] = v.created_at.isoformat()

        registry = sorted(
            agent_map.values(),
            key=lambda x: x["created_at"],
            reverse=True,
        )

        logger.debug(f"[registry] {len(registry)} unique agents")

        return registry


# ── 8. Config / env status ────────────────────────────────────────────────────


@router.get("/config")
@limiter.limit("60/minute")
async def get_forge_config(request: Request) -> dict:
    """
    Returns which environment variables are configured (True/False, never values).
    Also returns current model config and basic scheduler status.
    """
    required_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "FLY_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    ]
    optional_vars = ["SENTRY_DSN"]

    env_status = {var: bool(os.environ.get(var, "").strip()) for var in required_vars + optional_vars}
    env_status["_optional"] = optional_vars  # type: ignore[assignment]

    model_config = {
        "reasoning_model": settings.claude_opus_model,
        "synthesis_model": settings.claude_model,
        "classification_model": settings.claude_fast_model,
        "embedding_model": "text-embedding-3-small",
    }

    # Basic scheduler status — attempt to connect to Redis and check queue depth
    scheduler_status: dict[str, Any] = {"status": "unknown", "queue_depth": None}
    try:
        from redis import Redis
        from rq import Queue

        r = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        q = Queue("forge-builds", connection=r)
        scheduler_status = {
            "status": "connected",
            "queue_depth": len(q),
        }
    except Exception as exc:
        logger.warning(f"[config] Redis check failed: {exc}")
        scheduler_status = {"status": "unreachable", "queue_depth": None}

    logger.debug(f"[config] env_status={env_status}")

    return {
        "env_vars": env_status,
        "model_config": model_config,
        "scheduler": scheduler_status,
    }


# ── 9. Run health report ──────────────────────────────────────────────────────


@router.get("/runs/{run_id}/report")
@limiter.limit("60/minute")
async def get_run_report(
    request: Request,
    run_id: str,
) -> dict:
    """
    Returns build health report data extracted from the run's metadata_json field.
    Surfaces health_report, sandbox_results, coherence_results, test_results,
    and blueprint_validation for the Results tab.
    """
    import json as _json

    async for session in get_db():
        result = await session.execute(
            select(ForgeRun).where(ForgeRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        try:
            metadata: dict = {}
            if run.metadata_json:
                if isinstance(run.metadata_json, dict):
                    metadata = run.metadata_json
                elif isinstance(run.metadata_json, str):
                    metadata = _json.loads(run.metadata_json)

            spec: dict = {}
            if run.spec_json:
                if isinstance(run.spec_json, dict):
                    spec = run.spec_json
                elif isinstance(run.spec_json, str):
                    spec = _json.loads(run.spec_json)

            logger.debug(f"[run-report] run_id={run_id} metadata_keys={list(metadata.keys())}")

            return {
                "run_id": run_id,
                "title": run.title,
                "status": run.status,
                "health_report": metadata.get("health_report"),
                "sandbox_results": metadata.get("sandbox_results"),
                "coherence_results": metadata.get("coherence_results"),
                "test_results": metadata.get("test_results"),
                "blueprint_validation": metadata.get("blueprint_validation")
                or spec.get("blueprint_validation"),
            }
        except Exception as exc:
            logger.error(f"[run-report] Failed to build report for {run_id}: {exc}")
            return {
                "run_id": run_id,
                "title": run.title,
                "status": run.status,
                "health_report": None,
                "sandbox_results": None,
                "coherence_results": None,
                "test_results": None,
                "blueprint_validation": None,
            }
