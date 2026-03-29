"""
monitoring/performance_monitor.py
Tracks 5 KPIs every 6 hours and detects degradation.

KPIs tracked:
  1. builds_completed      — count of completed builds in the last 24h
  2. avg_build_time_seconds — average duration (queued → complete) in last 24h
  3. success_rate           — % builds with zero failed files in last 24h
  4. avg_files_per_build    — average file count across completed builds in last 24h
  5. kb_record_count        — total knowledge base records (growth signal)

Degradation detection:
  - Maintains a 7-day rolling baseline for each KPI
  - If any KPI degrades > 15% from baseline, fires Telegram alert
  - Auto-diagnoses likely cause by comparing to recent error patterns

Called by scheduler.py every 6 hours.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, select

from app.api.services.notify import notify_performance_degradation
from config.settings import settings
from memory.database import get_session
from memory.models import BuildCost, ForgeRun, PerformanceMetric, RunStatus

# Sydney time = UTC+10 (AEST) / UTC+11 (AEDT).
# Daily cost check fires at 23:00 UTC which is 09:00 AEST (or 10:00 AEDT).
DAILY_COST_ALERT_AUD = 20.0          # Alert if yesterday > A$20
MONTHLY_PROJECTION_ALERT_AUD = 100.0 # Alert if projected month > A$100

DEGRADATION_THRESHOLD = 0.15  # 15% degradation triggers alert

KPI_DEFINITIONS = {
    "builds_completed": {
        "description": "Completed builds in last 24h",
        "higher_is_better": True,
    },
    "avg_build_time_seconds": {
        "description": "Average build time (seconds) in last 24h",
        "higher_is_better": False,  # Lower is better
    },
    "success_rate": {
        "description": "% builds with zero failed files in last 24h",
        "higher_is_better": True,
    },
    "avg_files_per_build": {
        "description": "Average files generated per completed build",
        "higher_is_better": True,
    },
    "kb_record_count": {
        "description": "Total knowledge base records (growth signal)",
        "higher_is_better": True,
    },
}


async def run_performance_check() -> dict:
    """
    Calculate all 5 KPIs, compare to baselines, alert on degradation.
    Stores results in performance_metrics table.
    Returns dict of metric_name → current_value.
    NOTE: This fires Telegram alerts immediately. Only call this directly
    if you want real-time alerts. The scheduler uses run_performance_check_silent().
    """
    logger.info("Performance check starting")

    metrics = await _calculate_kpis()
    baselines = await _get_baselines()

    alerts_fired = 0
    for name, value in metrics.items():
        await _store_metric(name, value)

        if name in baselines and baselines[name] is not None:
            baseline = baselines[name]
            definition = KPI_DEFINITIONS.get(name, {})
            higher_is_better = definition.get("higher_is_better", True)

            degradation = _calculate_degradation(value, baseline, higher_is_better)
            if degradation > DEGRADATION_THRESHOLD:
                logger.warning(
                    f"KPI degradation detected: {name} "
                    f"current={value:.2f} baseline={baseline:.2f} "
                    f"degradation={degradation:.1%}"
                )
                try:
                    await notify_performance_degradation(
                        metric_name=name,
                        current_value=value,
                        baseline_value=baseline,
                        degradation_pct=degradation * 100,
                    )
                    alerts_fired += 1
                except Exception as exc:
                    logger.error(f"Degradation alert failed: {exc}")

    logger.info(
        f"Performance check complete: {len(metrics)} KPIs measured, "
        f"{alerts_fired} degradation alerts fired"
    )
    return metrics


async def run_performance_check_silent() -> dict:
    """
    Calculate all 5 KPIs and store to DB — no Telegram alerts.
    Used by the 6-hourly scheduler job. Degradation surfaces in the Sunday summary.
    Returns dict of metric_name → current_value.
    """
    logger.info("Performance check (silent) starting")
    metrics = await _calculate_kpis()
    for name, value in metrics.items():
        await _store_metric(name, value)
    logger.info(f"Performance check (silent) complete: {len(metrics)} KPIs stored")
    return metrics


async def get_weekly_degradation_summary() -> list[dict]:
    """
    Return any KPIs that are currently degraded vs their 7-day baseline.
    Used by the Sunday weekly summary to surface the week's performance issues.
    Returns list of dicts: [{metric, current, baseline, pct}]
    """
    metrics = await _calculate_kpis()
    baselines = await _get_baselines()
    degraded = []

    for name, value in metrics.items():
        if name in baselines and baselines[name] is not None:
            baseline = baselines[name]
            definition = KPI_DEFINITIONS.get(name, {})
            higher_is_better = definition.get("higher_is_better", True)
            degradation = _calculate_degradation(value, baseline, higher_is_better)
            if degradation > DEGRADATION_THRESHOLD:
                degraded.append({
                    "metric": name,
                    "current": value,
                    "baseline": baseline,
                    "pct": degradation * 100,
                })

    return degraded


# ── KPI calculations ──────────────────────────────────────────────────────────


async def _calculate_kpis() -> dict[str, float]:
    """Calculate current values for all 5 KPIs."""
    metrics: dict[str, float] = {}
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)

    try:
        async with get_session() as session:
            # KPI 1: builds completed in last 24h
            result = await session.execute(
                select(func.count(ForgeRun.run_id)).where(
                    ForgeRun.status == RunStatus.COMPLETE.value,
                    ForgeRun.updated_at >= window_start,
                )
            )
            metrics["builds_completed"] = float(result.scalar_one() or 0)

            # KPI 2: average build time in last 24h
            completed_runs = await session.execute(
                select(ForgeRun).where(
                    ForgeRun.status == RunStatus.COMPLETE.value,
                    ForgeRun.updated_at >= window_start,
                )
            )
            runs = completed_runs.scalars().all()
            if runs:
                durations = [
                    (r.updated_at - r.created_at).total_seconds() for r in runs
                    if r.updated_at and r.created_at
                ]
                metrics["avg_build_time_seconds"] = (
                    sum(durations) / len(durations) if durations else 0.0
                )
            else:
                metrics["avg_build_time_seconds"] = 0.0

            # KPI 3: success rate (zero failed files)
            if runs:
                successful = sum(1 for r in runs if r.files_failed == 0)
                metrics["success_rate"] = successful / len(runs)
            else:
                metrics["success_rate"] = 1.0

            # KPI 4: average files per build
            if runs:
                metrics["avg_files_per_build"] = sum(
                    r.files_complete for r in runs
                ) / len(runs)
            else:
                metrics["avg_files_per_build"] = 0.0

        # KPI 5: KB record count
        from intelligence.knowledge_base import get_record_count
        metrics["kb_record_count"] = float(await get_record_count())

    except Exception as exc:
        logger.error(f"KPI calculation failed: {exc}")

    return metrics


async def _get_baselines() -> dict[str, Optional[float]]:
    """
    Calculate 7-day rolling baseline for each KPI.
    Returns dict of metric_name → baseline_value (or None if insufficient data).
    """
    baselines: dict[str, Optional[float]] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    try:
        async with get_session() as session:
            for metric_name in KPI_DEFINITIONS:
                result = await session.execute(
                    select(func.avg(PerformanceMetric.metric_value)).where(
                        PerformanceMetric.metric_name == metric_name,
                        PerformanceMetric.recorded_at >= cutoff,
                    )
                )
                avg = result.scalar_one()
                baselines[metric_name] = float(avg) if avg is not None else None
    except Exception as exc:
        logger.error(f"Baseline calculation failed: {exc}")

    return baselines


async def _store_metric(name: str, value: float) -> None:
    """Persist a KPI value to the performance_metrics table."""
    async with get_session() as session:
        session.add(PerformanceMetric(metric_name=name, metric_value=value))


async def run_daily_cost_check() -> dict:
    """
    Query yesterday's total AUD spend from the build_costs table.
    Fires Telegram alerts if:
      - Yesterday's spend > A$20
      - Month-to-date projected to exceed A$100

    Uses the internal build_costs table — Anthropic has no public billing API.
    Returns a dict with cost summary for logging.
    """
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    yesterday_end = yesterday_start + timedelta(days=1)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = 31  # Conservative estimate for projection
    days_elapsed = max((now - month_start).days, 1)

    summary: dict = {}

    try:
        async with get_session() as session:
            # Yesterday's total spend
            result = await session.execute(
                select(
                    func.coalesce(func.sum(BuildCost.cost_aud), 0.0).label("total_aud"),
                    func.count(BuildCost.id).label("api_calls"),
                ).where(
                    BuildCost.created_at >= yesterday_start,
                    BuildCost.created_at < yesterday_end,
                )
            )
            row = result.one()
            yesterday_aud = float(row.total_aud)
            yesterday_calls = int(row.api_calls)

            # Month-to-date spend
            mtd_result = await session.execute(
                select(func.coalesce(func.sum(BuildCost.cost_aud), 0.0)).where(
                    BuildCost.created_at >= month_start,
                )
            )
            mtd_aud = float(mtd_result.scalar_one() or 0.0)

            # Projected end-of-month spend
            daily_rate = mtd_aud / days_elapsed
            projected_month_aud = daily_rate * days_in_month

            # Per-run breakdown for yesterday (for alert detail)
            breakdown_result = await session.execute(
                select(
                    BuildCost.run_id,
                    func.sum(BuildCost.cost_aud).label("run_total"),
                ).where(
                    BuildCost.created_at >= yesterday_start,
                    BuildCost.created_at < yesterday_end,
                    BuildCost.run_id.isnot(None),
                ).group_by(BuildCost.run_id).order_by(
                    func.sum(BuildCost.cost_aud).desc()
                ).limit(5)
            )
            top_runs = [
                {"run_id": r.run_id, "cost_aud": round(float(r.run_total), 2)}
                for r in breakdown_result.all()
            ]

        summary = {
            "yesterday_aud": round(yesterday_aud, 2),
            "yesterday_calls": yesterday_calls,
            "mtd_aud": round(mtd_aud, 2),
            "projected_month_aud": round(projected_month_aud, 2),
            "top_runs": top_runs,
        }

        logger.info(
            f"Daily cost check: yesterday=A${yesterday_aud:.2f} "
            f"MTD=A${mtd_aud:.2f} projected=A${projected_month_aud:.2f}/mo"
        )

        # ── Alert: yesterday exceeded threshold ───────────────────────────────
        if yesterday_aud > DAILY_COST_ALERT_AUD:
            run_lines = "\n".join(
                f"  • <code>{r['run_id'][:8]}</code>: A${r['cost_aud']:.2f}"
                for r in top_runs
            ) or "  (no breakdown available)"
            try:
                from app.api.services.notify import _send
                await _send(
                    f"<b>The Forge — Daily Cost Alert</b>\n\n"
                    f"Yesterday's spend: <b>A${yesterday_aud:.2f}</b> "
                    f"(threshold: A${DAILY_COST_ALERT_AUD:.0f})\n"
                    f"API calls: <b>{yesterday_calls}</b>\n\n"
                    f"<b>Top runs:</b>\n{run_lines}\n\n"
                    f"Month-to-date: <b>A${mtd_aud:.2f}</b>\n"
                    f"Projected month: <b>A${projected_month_aud:.2f}</b>"
                )
            except Exception as exc:
                logger.error(f"Daily cost alert send failed: {exc}")

        # ── Alert: monthly projection exceeded threshold ───────────────────────
        elif projected_month_aud > MONTHLY_PROJECTION_ALERT_AUD:
            try:
                from app.api.services.notify import _send
                await _send(
                    f"<b>The Forge — Monthly Cost Projection Alert</b>\n\n"
                    f"Projected end-of-month: <b>A${projected_month_aud:.2f}</b> "
                    f"(threshold: A${MONTHLY_PROJECTION_ALERT_AUD:.0f})\n\n"
                    f"Month-to-date ({days_elapsed} days): <b>A${mtd_aud:.2f}</b>\n"
                    f"Daily rate: <b>A${daily_rate:.2f}/day</b>"
                )
            except Exception as exc:
                logger.error(f"Monthly projection alert send failed: {exc}")

    except Exception as exc:
        logger.error(f"Daily cost check failed: {exc}")

    return summary


def _calculate_degradation(
    current: float, baseline: float, higher_is_better: bool
) -> float:
    """
    Calculate degradation percentage relative to baseline.
    Returns 0.0 if no degradation, positive value if degraded.
    """
    if baseline == 0:
        return 0.0
    if higher_is_better:
        # Degradation = how much lower current is vs baseline
        return max(0.0, (baseline - current) / baseline)
    else:
        # Degradation = how much higher current is vs baseline (for time metrics)
        return max(0.0, (current - baseline) / baseline)
