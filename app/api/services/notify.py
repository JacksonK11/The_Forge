"""
app/api/services/notify.py
Telegram notification service for The Forge.

Sends build completion, failure, and degradation alerts directly to Jackson's
personal Telegram account via a dedicated Forge bot.

Also handles callback_url POSTing for The Office integration — when a build or
update completes and the originating request included a callback_url, a JSON
summary is POSTed to that URL so The Office can update its state in real time.

All notifications are fire-and-forget with full error handling — a notification
failure never propagates to the calling pipeline node.
"""

import asyncio
from typing import Optional

import httpx
from loguru import logger

from config.settings import settings

TELEGRAM_API = "https://api.telegram.org"


async def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via the Telegram Bot API. Returns True on success."""
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.error(f"Telegram notification failed: {exc}")
        return False


async def notify_build_complete(
    run_id: str,
    title: str,
    file_count: int,
    files_failed: int,
    duration_seconds: float,
    callback_url: Optional[str] = None,
    github_repo_url: Optional[str] = None,
) -> None:
    """Notify when a build completes successfully."""
    status_icon = "✅" if files_failed == 0 else "⚠️"
    text = (
        f"{status_icon} <b>The Forge — Build Complete</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"Files generated: <b>{file_count - files_failed}/{file_count}</b>\n"
        f"Duration: <b>{duration_seconds:.0f}s</b>\n"
    )
    if files_failed > 0:
        text += f"⚠️ {files_failed} file(s) failed — check run detail\n"
    if github_repo_url:
        text += f"\nGitHub: <a href='{github_repo_url}'>{github_repo_url}</a>\n"
    text += f"\n<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>View Build →</a>"
    await _send(text)

    # POST callback to The Office or other caller
    if callback_url:
        summary = {
            "run_id": run_id,
            "status": "complete",
            "title": title,
            "file_count": file_count,
            "files_failed": files_failed,
            "duration_seconds": round(duration_seconds, 1),
            "github_repo_url": github_repo_url,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(callback_url, json=summary)
                resp.raise_for_status()
                logger.info(f"Build complete callback posted to {callback_url}")
        except Exception as exc:
            logger.error(f"Build complete callback POST failed (non-blocking): {exc}")


async def notify_build_failed(
    run_id: str,
    title: str,
    stage: str,
    error: str,
) -> None:
    """Notify when a build pipeline fails."""
    text = (
        f"❌ <b>The Forge — Build Failed</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n"
        f"Failed at stage: <b>{stage}</b>\n\n"
        f"Error:\n<code>{error[:400]}</code>\n\n"
        f"<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>View Run →</a>"
    )
    await _send(text)


async def notify_build_started(run_id: str, title: str) -> None:
    """Notify when a build is queued and starting."""
    text = (
        f"🔨 <b>The Forge — Build Started</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>Track Progress →</a>"
    )
    await _send(text)


async def notify_performance_degradation(
    metric_name: str,
    current_value: float,
    baseline_value: float,
    degradation_pct: float,
) -> None:
    """Alert when a KPI degrades more than 15% from baseline."""
    text = (
        f"🚨 <b>The Forge — Performance Degradation</b>\n\n"
        f"Metric: <b>{metric_name}</b>\n"
        f"Current: <b>{current_value:.2f}</b>\n"
        f"Baseline: <b>{baseline_value:.2f}</b>\n"
        f"Degradation: <b>{degradation_pct:.1f}%</b>\n\n"
        f"Investigate at: the-forge-dashboard.fly.dev"
    )
    await _send(text)


async def notify_spec_ready(run_id: str, title: str, file_count: int, service_count: int) -> None:
    """Notify when spec is parsed and waiting for approval."""
    text = (
        f"📋 <b>The Forge — Spec Ready for Approval</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"Files planned: <b>{file_count}</b>\n"
        f"Fly services: <b>{service_count}</b>\n\n"
        f"<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>Review & Approve →</a>"
    )
    await _send(text)
