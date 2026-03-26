"""
app/api/services/notify.py
Telegram notification service for The Forge.

Sends build completion, failure, cost alerts, and degradation notifications
directly to Jackson's personal Telegram account via the dedicated Forge bot.

Also handles callback_url POSTing for The Office integration.

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
    estimated_cost_aud: Optional[float] = None,
    generation_failed_files: Optional[list[str]] = None,
    rebuilt_files_count: int = 0,
    qa_result: Optional[dict] = None,
) -> None:
    """
    Notify when a build completes.

    generation_failed_files: files still needing manual attention AFTER recovery pass.
    rebuilt_files_count: files successfully recovered by the recovery pass.
    qa_result: BuildQAResult.to_dict() — includes score, categories, and issues.
    """
    files_complete = file_count - files_failed
    has_manual = bool(generation_failed_files)

    qa_score = qa_result.get("total_score") if qa_result else None
    qa_passed = qa_result.get("passed", True) if qa_result else True
    qa_issues = [i for i in (qa_result.get("issues") or []) if i.get("severity") == "critical"] if qa_result else []

    # Status icon: red X if manual files needed, orange if QA gaps, green if clean
    if has_manual:
        status_icon = "⚠️"
    elif qa_score is not None and qa_score < 100:
        status_icon = "🟡"
    else:
        status_icon = "✅"

    cost_aud = estimated_cost_aud if estimated_cost_aud is not None else files_complete * 0.002

    text = (
        f"{status_icon} <b>The Forge — Build Complete</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"Files generated: <b>{files_complete}/{file_count}</b>\n"
        f"Duration: <b>{duration_seconds:.0f}s</b>\n"
        f"Estimated cost: <b>A${cost_aud:.3f}</b>\n"
    )

    # QA score line
    if qa_score is not None:
        score_label = "✅ PASS" if qa_score >= 95 else ("🟡 GOOD" if qa_score >= 85 else "🔴 NEEDS FIXES")
        text += f"Build QA Score: <b>{qa_score}/100</b> — {score_label}\n"
        if qa_result and qa_result.get("categories"):
            cats = qa_result["categories"]
            text += (
                f"  API {cats.get('api', {}).get('score', 0)}/25 · "
                f"Wiring {cats.get('wiring', {}).get('score', 0)}/25 · "
                f"Intel {cats.get('intelligence', {}).get('score', 0)}/25 · "
                f"Infra {cats.get('infrastructure', {}).get('score', 0)}/15 · "
                f"Quality {cats.get('code_quality', {}).get('score', 0)}/10\n"
            )

    if files_failed > 0:
        text += f"⚠️ {files_failed} file(s) failed initial generation\n"

    if rebuilt_files_count > 0:
        text += f"✅ <b>{rebuilt_files_count} file(s) auto-recovered</b> by recovery pass\n"

    if generation_failed_files:
        text += f"\n🔧 <b>{len(generation_failed_files)} file(s) need manual attention:</b>\n"
        for fp in generation_failed_files[:8]:
            text += f"  • <code>{fp}</code>\n"
        if len(generation_failed_files) > 8:
            text += f"  ... and {len(generation_failed_files) - 8} more\n"

    # QA issues — what still needs fixing
    if qa_issues and qa_score is not None and qa_score < 100:
        text += f"\n🔴 <b>{len(qa_issues)} issue(s) still need fixing after QA loop:</b>\n"
        for issue in qa_issues[:8]:
            cat = issue.get("category", "").upper()
            fp = issue.get("file", "")
            desc = issue.get("description", "")
            text += f"  [{cat}] "
            if fp:
                text += f"<code>{fp}</code>: "
            text += f"{desc[:120]}\n"
        if len(qa_issues) > 8:
            text += f"  ... and {len(qa_issues) - 8} more (see Run Status page)\n"

        # Ready-to-paste fix prompt
        fix_lines = []
        for issue in qa_issues[:15]:
            cat = issue.get("category", "").upper()
            fp = issue.get("file", "")
            desc = issue.get("description", "")
            hint = issue.get("fix_hint", "")
            line = f"[{cat}]"
            if fp:
                line += f" {fp}:"
            line += f" {desc}"
            if hint:
                line += f" — {hint}"
            fix_lines.append(line)

        fix_prompt = (
            f"Fix the following QA issues in run {run_id} ({title}):\n\n"
            + "\n".join(f"{i+1}. {line}" for i, line in enumerate(fix_lines))
            + "\n\nFix all issues so the build scores 100/100."
        )
        text += f"\n💬 <b>Fix prompt (paste into Upgrade or Claude Code):</b>\n<code>{fix_prompt[:800]}</code>\n"

    if github_repo_url:
        text += f"\nGitHub: <a href='{github_repo_url}'>{github_repo_url}</a>\n"

    text += f"\n<a href='https://the-forge-dashboard-v6.fly.dev/runs/{run_id}'>View Build →</a>"
    await _send(text)

    if callback_url:
        summary = {
            "run_id": run_id,
            "status": "complete",
            "title": title,
            "file_count": file_count,
            "files_failed": files_failed,
            "duration_seconds": round(duration_seconds, 1),
            "github_repo_url": github_repo_url,
            "generation_failed_files": generation_failed_files or [],
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
    files_complete: int = 0,
    file_count: int = 0,
    estimated_cost_aud: Optional[float] = None,
) -> None:
    """Notify when a build pipeline fails at a specific stage."""
    from app.api.services.error_translator import translate_error_for_storage, translate_error
    translated = translate_error_for_storage(error)
    translated_detail = translate_error(error)
    suggested_fix = translated_detail.get("fix", "Check run logs for details.")
    cost_aud = estimated_cost_aud if estimated_cost_aud is not None else files_complete * 0.002

    text = (
        f"❌ <b>The Forge — Build Failed</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n"
        f"Failed at stage: <b>{stage}</b>\n\n"
        f"Error:\n<code>{translated[:400]}</code>\n"
    )
    if files_complete or file_count:
        text += f"Files generated before failure: <b>{files_complete}/{file_count}</b>\n"
    if cost_aud:
        text += f"Estimated cost: <b>A${cost_aud:.3f}</b>\n"
    text += (
        f"\n💡 Fix: {suggested_fix}\n\n"
        f"<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>View Run →</a>"
    )
    await _send(text)


async def notify_cost_limit_exceeded(
    run_id: str,
    title: str,
    total_tokens: int,
    total_cost_aud: float,
    files_complete: int,
    file_count: int,
) -> None:
    """
    Alert when a build hits the hard token cap and is force-stopped.
    Sent before the RuntimeError that kills the pipeline.
    """
    text = (
        f"🚨 <b>The Forge — Build KILLED: Cost Cap Exceeded</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"Tokens used: <b>{total_tokens:,}</b> (hard cap: 500,000)\n"
        f"Estimated cost: <b>A${total_cost_aud:.2f}</b>\n"
        f"Progress at kill: <b>{files_complete}/{file_count} files</b>\n\n"
        f"Build stopped to prevent runaway API costs.\n"
        f"The run is marked <code>cost_limit_exceeded</code>.\n\n"
        f"To resume with a higher cap, update TOKEN_HARD_CAP in codegen_node.py "
        f"and call <code>POST /forge/runs/{run_id}/resume</code>.\n\n"
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


async def notify_worker_restart() -> None:
    """Notify that the worker has restarted and in-progress builds will auto-resume."""
    text = "🔄 <b>The Forge Worker</b> — restarted. In-progress builds will auto-resume."
    await _send(text)


async def notify_spec_ready(
    run_id: str,
    title: str,
    file_count: int,
    service_count: int,
    estimated_cost_aud: Optional[float] = None,
    cost_warning: bool = False,
) -> None:
    """
    Notify when spec is parsed and waiting for approval.
    Includes cost estimate and warning flag if the build is projected to be expensive.
    """
    text = (
        f"📋 <b>The Forge — Spec Ready for Approval</b>\n\n"
        f"<b>{title}</b>\n"
        f"Run ID: <code>{run_id}</code>\n\n"
        f"Files planned: <b>{file_count}</b>\n"
        f"Fly services: <b>{service_count}</b>\n"
    )

    if estimated_cost_aud is not None:
        text += f"Estimated cost: <b>A${estimated_cost_aud:.2f}</b>\n"
        if cost_warning:
            text += f"⚠️ <b>High cost build</b> — confirm before approving\n"

    text += f"\n<a href='https://the-forge-dashboard.fly.dev/runs/{run_id}'>Review & Approve →</a>"
    await _send(text)
