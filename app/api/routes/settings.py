"""
app/api/routes/settings.py
GET /settings        — return all settings as {key: value} dict
PUT /settings        — update one or more settings, body: {key: value, ...}
POST /settings/reset — reset all settings to defaults
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from memory.database import get_db
from memory.models import SystemSetting

router = APIRouter()

DEFAULTS: dict[str, str] = {
    "claude_model": "claude-sonnet-4-6",
    "claude_fast_model": "claude-haiku-4-5-20251001",
    "parse_max_tokens": "8000",
    "architecture_max_tokens": "16000",
    "codegen_max_tokens": "16000",
    "large_blueprint_threshold": "60000",
    "max_retries": "3",
    "orphan_timeout_minutes": "20",
    "quality_score_minimum": "65",
    "cost_alert_threshold_aud": "10.0",
    "telegram_notify_on_complete": "true",
    "telegram_notify_on_failure": "true",
    "telegram_notify_on_stall": "true",
    # Dashboard settings form keys
    "push_to_github": "false",
    "push_to_github_default": "false",
    "default_region": "syd",
    "notification_email": "",
    "telegram_chat_id": "",
    "auto_approve_low_risk": "false",
    "max_parallel_builds": "2",
}


@router.get("", response_model=dict[str, str])
async def get_settings(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Return all settings as a flat {key: value} dict, falling back to defaults for missing keys."""
    result = await session.execute(select(SystemSetting))
    rows = result.scalars().all()
    db_settings = {row.key: row.value for row in rows}

    # Merge: DB values take priority, DEFAULTS fill in missing keys
    merged = {**DEFAULTS, **db_settings}
    return merged


@router.put("", response_model=dict[str, str])
async def update_settings(
    body: dict[str, str],
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Accept {key: value, ...}, validate keys exist in DEFAULTS, upsert in DB, return updated dict."""
    unknown_keys = [k for k in body if k not in DEFAULTS]
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown setting keys: {', '.join(unknown_keys)}. Valid keys: {list(DEFAULTS.keys())}",
        )

    if not body:
        raise HTTPException(status_code=422, detail="No settings provided to update")

    for key, value in body.items():
        stmt = (
            insert(SystemSetting)
            .values(key=key, value=value)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": value},
            )
        )
        await session.execute(stmt)

    await session.commit()
    logger.info(f"Settings updated: {list(body.keys())}")

    # Return full merged state
    result = await session.execute(select(SystemSetting))
    rows = result.scalars().all()
    db_settings = {row.key: row.value for row in rows}
    return {**DEFAULTS, **db_settings}


@router.post("/reset", response_model=dict[str, str])
async def reset_settings(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Delete all settings from DB, returning DEFAULTS."""
    await session.execute(delete(SystemSetting))
    await session.commit()
    logger.info("Settings reset to defaults")
    return DEFAULTS
