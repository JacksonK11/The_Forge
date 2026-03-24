"""
monitoring/scheduler.py
APScheduler configuration for all scheduled background tasks.

Registered jobs:
  Every 6 hours:  Performance KPI check
  Daily at 02:00: Knowledge collection sweep (all 6 domains)
  Daily at 03:00: Knowledge embedding sweep (after collection)
  Sunday 00:00:   Meta-rules extraction from build outcomes
  Sunday 07:00:   Weekly Telegram summary

Run as a standalone process:
  python monitoring/scheduler.py

Or import and start within the worker:
  from monitoring.scheduler import start_scheduler
  scheduler = start_scheduler()
"""

import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from config.settings import settings
from memory.database import close_db, init_db


def start_scheduler() -> AsyncIOScheduler:
    """
    Create, configure, and start the APScheduler instance.
    Returns the running scheduler so it can be stopped on shutdown.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    # ── Performance monitoring: every 6 hours ─────────────────────────────────
    scheduler.add_job(
        _run_performance_check,
        trigger=IntervalTrigger(hours=6),
        id="performance_check",
        name="Performance KPI Check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── Knowledge collection: daily at 02:00 UTC ──────────────────────────────
    scheduler.add_job(
        _run_knowledge_collection,
        trigger=CronTrigger(hour=2, minute=0),
        id="knowledge_collection",
        name="Knowledge Collection Sweep",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # ── Knowledge embedding: daily at 03:00 UTC (after collection) ────────────
    scheduler.add_job(
        _run_knowledge_embedding,
        trigger=CronTrigger(hour=3, minute=0),
        id="knowledge_embedding",
        name="Knowledge Embedding Sweep",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # ── Meta-rules extraction: Sunday at 00:00 UTC ────────────────────────────
    scheduler.add_job(
        _run_meta_rules_extraction,
        trigger=CronTrigger(day_of_week="sun", hour=0, minute=0),
        id="meta_rules_extraction",
        name="Meta-Rules Extraction",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Weekly summary: Sunday at 07:00 UTC ───────────────────────────────────
    scheduler.add_job(
        _send_weekly_summary,
        trigger=CronTrigger(day_of_week="sun", hour=7, minute=0),
        id="weekly_summary",
        name="Weekly Telegram Summary",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Agent health polling: every 60 seconds ────────────────────────────────
    scheduler.add_job(
        poll_agent_health,
        trigger=IntervalTrigger(seconds=60),
        id="agent_health_poll",
        name="Agent Health Poll",
        replace_existing=True,
        misfire_grace_time=30,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started with {len(scheduler.get_jobs())} jobs: "
        + ", ".join(job.name for job in scheduler.get_jobs())
    )
    return scheduler


# ── Job implementations ───────────────────────────────────────────────────────


async def _run_performance_check() -> None:
    """Run the 6-hourly performance KPI check."""
    logger.info("Scheduled job: performance_check")
    try:
        from monitoring.performance_monitor import run_performance_check
        metrics = await run_performance_check()
        logger.info(f"Performance check complete: {metrics}")
    except Exception as exc:
        logger.error(f"Performance check job failed: {exc}")


async def _run_knowledge_collection() -> None:
    """Run the daily knowledge collection sweep across all domains."""
    logger.info("Scheduled job: knowledge_collection")
    try:
        from knowledge.collector import run_collection_sweep
        results = await run_collection_sweep()
        total = sum(results.values())
        logger.info(f"Knowledge collection: {total} new articles across {len(results)} domains")
    except Exception as exc:
        logger.error(f"Knowledge collection job failed: {exc}")


async def _run_knowledge_embedding() -> None:
    """Run the daily embedding sweep on unembedded articles."""
    logger.info("Scheduled job: knowledge_embedding")
    try:
        from knowledge.embedder import run_embedding_sweep
        result = await run_embedding_sweep()
        logger.info(
            f"Knowledge embedding: {result['articles_processed']} articles, "
            f"{result['chunks_created']} chunks"
        )
    except Exception as exc:
        logger.error(f"Knowledge embedding job failed: {exc}")


async def _run_meta_rules_extraction() -> None:
    """Run the weekly meta-rules extraction from build outcomes."""
    logger.info("Scheduled job: meta_rules_extraction")
    try:
        from intelligence.meta_rules import extract_and_update_rules
        result = await extract_and_update_rules()
        logger.info(
            f"Meta-rules extraction: {result.get('new_rules', 0)} new, "
            f"{result.get('retired_rules', 0)} retired"
        )
    except Exception as exc:
        logger.error(f"Meta-rules extraction job failed: {exc}")


async def _send_weekly_summary() -> None:
    """Send a weekly Telegram summary of Forge activity including costs and health."""
    logger.info("Scheduled job: weekly_summary")
    try:
        from app.api.services.notify import _send
        from memory.database import get_session
        from memory.models import BuildCost, BuildLog, ForgeRun, RunStatus
        from sqlalchemy import func, select
        from datetime import datetime, timedelta, timezone

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        async with get_session() as session:
            total_result = await session.execute(
                select(func.count(ForgeRun.run_id)).where(
                    ForgeRun.created_at >= week_ago
                )
            )
            complete_result = await session.execute(
                select(func.count(ForgeRun.run_id)).where(
                    ForgeRun.status == RunStatus.COMPLETE.value,
                    ForgeRun.created_at >= week_ago,
                )
            )
            failed_result = await session.execute(
                select(func.count(ForgeRun.run_id)).where(
                    ForgeRun.status == RunStatus.FAILED.value,
                    ForgeRun.created_at >= week_ago,
                )
            )
            total = total_result.scalar_one()
            complete = complete_result.scalar_one()
            failed = failed_result.scalar_one()

            # Weekly cost
            cost_usd_result = await session.execute(
                select(func.sum(BuildCost.cost_usd)).where(
                    BuildCost.created_at >= week_ago
                )
            )
            cost_aud_result = await session.execute(
                select(func.sum(BuildCost.cost_aud)).where(
                    BuildCost.created_at >= week_ago
                )
            )
            week_cost_usd = float(cost_usd_result.scalar_one() or 0.0)
            week_cost_aud = float(cost_aud_result.scalar_one() or 0.0)

        try:
            from knowledge.retriever import get_knowledge_stats
            kb_stats = await get_knowledge_stats()
        except Exception:
            kb_stats = {}

        success_pct = f"{(complete/total*100):.0f}%" if total > 0 else "—"

        text = (
            f"📊 <b>The Forge — Weekly Summary</b>\n\n"
            f"<b>Builds (last 7 days):</b>\n"
            f"  Total: <b>{total}</b>\n"
            f"  Completed: <b>{complete}</b>\n"
            f"  Failed: <b>{failed}</b>\n"
            f"  Success rate: <b>{success_pct}</b>\n\n"
            f"<b>Cost (last 7 days):</b>\n"
            f"  USD: <b>${week_cost_usd:.2f}</b>\n"
            f"  AUD: <b>A${week_cost_aud:.2f}</b>\n\n"
            f"<b>Knowledge Base:</b>\n"
            f"  Total chunks: <b>{kb_stats.get('total_chunks', 0):,}</b>\n"
        )
        await _send(text)
    except Exception as exc:
        logger.error(f"Weekly summary job failed: {exc}")


async def poll_agent_health() -> None:
    """
    Poll /health for every registered agent with a non-null api_url.
    Updates health_status and last_health_check in agents_registry.
    Sends Telegram alerts on status transitions (healthy ↔ unhealthy).
    All errors are non-fatal and logged.
    """
    logger.info("Scheduled job: poll_agent_health")
    try:
        from datetime import datetime, timezone

        import httpx
        from sqlalchemy import select, update as sa_update

        from app.api.services.notify import _send
        from memory.database import get_session
        from memory.models import AgentRegistry

        async with get_session() as session:
            result = await session.execute(
                select(AgentRegistry).where(AgentRegistry.api_url.isnot(None))
            )
            agents = result.scalars().all()

        for agent in agents:
            previous_status = agent.health_status
            new_status: str

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{agent.api_url}/health")
                    new_status = "healthy" if resp.status_code == 200 else "unhealthy"
            except Exception as exc:
                new_status = "unhealthy"
                logger.debug(
                    f"[health_poll] {agent.agent_name} ({agent.api_url}): {exc}"
                )

            now = datetime.now(timezone.utc)

            try:
                async with get_session() as session:
                    await session.execute(
                        sa_update(AgentRegistry)
                        .where(AgentRegistry.agent_id == agent.agent_id)
                        .values(health_status=new_status, last_health_check=now)
                    )
                    await session.commit()
            except Exception as db_exc:
                logger.error(
                    f"[health_poll] Failed to persist health status for "
                    f"{agent.agent_name}: {db_exc}"
                )

            # Alert on status transitions
            if previous_status == "healthy" and new_status == "unhealthy":
                try:
                    await _send(
                        f"🔴 <b>Agent Down</b>: <b>{agent.agent_name}</b> is unhealthy\n"
                        f"URL: {agent.api_url}"
                    )
                except Exception as alert_exc:
                    logger.error(
                        f"[health_poll] Failed to send down alert for "
                        f"{agent.agent_name}: {alert_exc}"
                    )
            elif previous_status == "unhealthy" and new_status == "healthy":
                try:
                    await _send(
                        f"🟢 <b>Agent Recovered</b>: <b>{agent.agent_name}</b> is back up\n"
                        f"URL: {agent.api_url}"
                    )
                except Exception as alert_exc:
                    logger.error(
                        f"[health_poll] Failed to send recovery alert for "
                        f"{agent.agent_name}: {alert_exc}"
                    )

        logger.info(f"[health_poll] Checked {len(agents)} agent(s)")
    except Exception as exc:
        logger.error(f"Agent health poll job failed: {exc}")


# ── Standalone entry point ────────────────────────────────────────────────────


async def main() -> None:
    """Run the scheduler as a standalone process."""
    logger.remove()
    logger.add(
        sys.stdout,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
        level="INFO",
        colorize=False,
    )

    logger.info("The Forge Scheduler starting")
    await init_db()

    scheduler = start_scheduler()

    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down")
        scheduler.shutdown()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
