"""
app/api/routes/system.py
System management: deploy-lock, active-build check, detailed health.

GET  /system/active-builds   — public; returns count + safe_to_deploy flag (used by CI)
GET  /system/deploy-lock     — check lock status
POST /system/deploy-lock     — set lock (prevents worker from being deployed)
DELETE /system/deploy-lock   — clear lock
"""

from fastapi import APIRouter
from loguru import logger
from redis import Redis

from config.settings import settings

router = APIRouter()

_redis = Redis.from_url(settings.redis_url)

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
