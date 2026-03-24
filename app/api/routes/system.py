"""
app/api/routes/system.py
System management: deploy-lock, active-build check, detailed health.

GET  /system/active-builds      — public; returns count + safe_to_deploy flag (used by CI)
GET  /system/deploy-lock        — check lock status
POST /system/deploy-lock        — set lock (prevents worker from being deployed)
DELETE /system/deploy-lock      — clear lock
GET  /system/logs/recent        — recent worker logs from Redis list
GET  /system/health/detailed    — detailed component health
"""

import time

from fastapi import APIRouter, Query
from loguru import logger
from redis import Redis

from config.settings import settings

router = APIRouter()

_redis = Redis.from_url(settings.redis_url)

_START_TIME = time.time()

DEPLOY_LOCK_KEY = "forge:deploy-lock"
DEPLOY_LOCK_TTL = 3600  # 1 hour auto-expire


# ── Active builds ─────────────────────────────────────────────────────────────


@router.get("/active-builds")
async def get_active_builds() -> dict:
    """
    Returns count of in-progress builds and whether it is safe to deploy the worker.
    Public endpoint — no auth required (used by GitHub Actions CI).
    """
    from memory.database import get_session
    from memory.models import ForgeRun, RunStatus
    from sqlalchemy import func, select

    active_statuses = [
        RunStatus.QUEUED.value,
        RunStatus.VALIDATING.value,
        RunStatus.PARSING.value,
        RunStatus.CONFIRMING.value,
        RunStatus.ARCHITECTING.value,
        RunStatus.GENERATING.value,
        RunStatus.PACKAGING.value,
    ]

    try:
        async with get_session() as session:
            result = await session.execute(
                select(func.count()).select_from(ForgeRun).where(
                    ForgeRun.status.in_(active_statuses)
                )
            )
            count = result.scalar() or 0
    except Exception as exc:
        logger.warning(f"active-builds check failed: {exc}")
        count = 0

    deploy_locked = bool(_redis.exists(DEPLOY_LOCK_KEY))

    return {
        "active_builds": count,
        "safe_to_deploy": count == 0 and not deploy_locked,
        "deploy_locked": deploy_locked,
    }


# ── Deploy lock ───────────────────────────────────────────────────────────────


@router.get("/deploy-lock")
async def get_deploy_lock() -> dict:
    """Check whether the deploy lock is active."""
    raw = _redis.get(DEPLOY_LOCK_KEY)
    if raw:
        ttl = _redis.ttl(DEPLOY_LOCK_KEY)
        return {"locked": True, "reason": raw.decode(), "ttl_seconds": ttl}
    return {"locked": False, "reason": None, "ttl_seconds": 0}


@router.post("/deploy-lock")
async def set_deploy_lock(reason: str = "Manual lock") -> dict:
    """
    Engage the deploy lock. Worker deploys will wait until the lock is cleared
    or the TTL expires (1 hour). Use to protect long-running builds from interruption.
    """
    _redis.setex(DEPLOY_LOCK_KEY, DEPLOY_LOCK_TTL, reason)
    logger.info(f"Deploy lock engaged: {reason}")
    return {"locked": True, "reason": reason, "ttl_seconds": DEPLOY_LOCK_TTL}


@router.delete("/deploy-lock")
async def clear_deploy_lock() -> dict:
    """Clear the deploy lock, allowing worker deploys to proceed immediately."""
    _redis.delete(DEPLOY_LOCK_KEY)
    logger.info("Deploy lock cleared")
    return {"locked": False, "reason": None, "ttl_seconds": 0}


# ── Recent worker logs ────────────────────────────────────────────────────────


@router.get("/logs/recent")
async def get_recent_logs(
    limit: int = Query(default=100, ge=1, le=500),
    level: str = Query(default=""),
    module: str = Query(default=""),
    run_id: str = Query(default=""),
) -> dict:
    """
    Returns recent worker log entries from the Redis 'forge-worker-logs' list.
    Supports optional filtering by level (case-insensitive), module (substring),
    and run_id (exact match).
    """
    import json

    raw_entries = _redis.lrange("forge-worker-logs", 0, 999)
    total_read = len(raw_entries)

    logs = []
    for raw in raw_entries:
        try:
            entry = json.loads(raw)
        except Exception:
            continue

        if level and entry.get("level", "").upper() != level.upper():
            continue
        if module and module.lower() not in (entry.get("module") or "").lower():
            continue
        if run_id and entry.get("run_id") != run_id:
            continue

        logs.append(entry)
        if len(logs) >= limit:
            break

    return {"logs": logs, "total_read": total_read}


# ── Detailed health ───────────────────────────────────────────────────────────


@router.get("/health/detailed")
async def get_detailed_health() -> dict:
    """
    Returns detailed health information for all system components:
    API, worker, database, Redis, and scheduler.
    """
    # ── API ──────────────────────────────────────────────────────────────────
    api_info = {
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
    }

    # ── Worker ───────────────────────────────────────────────────────────────
    worker_info: dict = {
        "status": "stopped",
        "current_job": None,
        "idle_since": None,
        "machine_id": None,
    }
    try:
        from rq.worker import Worker as RQWorker
        workers = RQWorker.all(connection=_redis)
        if workers:
            w = workers[0]
            current_job = w.get_current_job()
            worker_info["status"] = "running" if current_job else "idle"
            worker_info["current_job"] = current_job.id if current_job else None
            worker_info["machine_id"] = w.name
            if not current_job:
                try:
                    worker_info["idle_since"] = w.last_heartbeat.isoformat() if w.last_heartbeat else None
                except Exception:
                    pass
    except Exception as exc:
        logger.warning(f"health/detailed: worker check failed: {exc}")

    # ── Database ─────────────────────────────────────────────────────────────
    database_info: dict = {
        "connected": False,
        "active_runs": 0,
        "total_runs": 0,
    }
    try:
        from memory.database import get_session
        from memory.models import ForgeRun, RunStatus
        from sqlalchemy import func, select

        active_statuses = [
            RunStatus.QUEUED.value,
            RunStatus.VALIDATING.value,
            RunStatus.PARSING.value,
            RunStatus.CONFIRMING.value,
            RunStatus.ARCHITECTING.value,
            RunStatus.GENERATING.value,
            RunStatus.PACKAGING.value,
        ]
        async with get_session() as session:
            active_result = await session.execute(
                select(func.count()).select_from(ForgeRun).where(
                    ForgeRun.status.in_(active_statuses)
                )
            )
            total_result = await session.execute(
                select(func.count()).select_from(ForgeRun)
            )
            database_info["connected"] = True
            database_info["active_runs"] = active_result.scalar() or 0
            database_info["total_runs"] = total_result.scalar() or 0
    except Exception as exc:
        logger.warning(f"health/detailed: database check failed: {exc}")

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_info: dict = {
        "connected": False,
        "memory_used_mb": 0.0,
        "queue_depth": 0,
        "log_entries": 0,
    }
    try:
        from rq import Queue as RQQueue
        mem_info = _redis.info("memory")
        redis_info["connected"] = True
        redis_info["memory_used_mb"] = round(mem_info.get("used_memory", 0) / 1024 / 1024, 2)
        redis_info["queue_depth"] = RQQueue("forge-builds", connection=_redis).count
        redis_info["log_entries"] = _redis.llen("forge-worker-logs")
    except Exception as exc:
        logger.warning(f"health/detailed: redis check failed: {exc}")

    # ── Scheduler ────────────────────────────────────────────────────────────
    scheduler_info: dict = {"running": False, "next_jobs": []}
    try:
        from monitoring.scheduler import get_scheduler_instance
        sched = get_scheduler_instance()
        if sched is not None and sched.running:
            scheduler_info["running"] = True
            jobs = sched.get_jobs()
            scheduler_info["next_jobs"] = [
                {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
                for j in jobs[:5]
            ]
    except Exception:
        # Scheduler module may not expose get_scheduler_instance — fall back silently
        try:
            from monitoring import scheduler as _sched_mod
            scheduler_info["running"] = getattr(_sched_mod, "_scheduler_running", False)
        except Exception:
            pass

    return {
        "api": api_info,
        "worker": worker_info,
        "database": database_info,
        "redis": redis_info,
        "scheduler": scheduler_info,
    }
