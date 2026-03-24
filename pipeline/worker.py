"""
pipeline/worker.py
RQ worker entry point for The Forge build pipeline.

Listens on the "forge-builds" queue and processes blueprint build jobs.
Run with: python pipeline/worker.py

The scheduler (APScheduler) runs as a background thread within this process
so we need only one worker app instead of a separate scheduler app.

Orphan detection runs every 60 seconds — if a build has been in "generating"
status for more than 30 minutes with no file count change, it is re-queued
automatically with all context (spec_json, manifest_json, completed files)
preserved so generation resumes without losing progress.
"""

import os
import sys
import threading
import asyncio
import time

from loguru import logger
from redis import Redis
from rq import Queue, Worker
from rq.timeouts import JobTimeoutException

from config.settings import settings
from memory.database import init_db

# ── Logging ───────────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    level="INFO",
    colorize=False,  # No ANSI codes in Fly.io logs
)

# ── Sentry (if configured) ────────────────────────────────────────────────────

if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
    )


# ── Scheduler background thread ───────────────────────────────────────────────


def _run_scheduler_in_thread() -> None:
    """
    Run APScheduler in a dedicated background thread with its own event loop.
    Called once on worker startup — replaces the separate scheduler Fly.io app.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _scheduler_main() -> None:
        logger.info("Scheduler thread: initialising database connection")
        try:
            from memory.database import init_db
            await init_db()
        except Exception as exc:
            logger.warning(f"Scheduler thread: DB init skipped (may already be running): {exc}")

        from monitoring.scheduler import start_scheduler
        scheduler = start_scheduler()
        logger.info("Scheduler thread: running (merged into worker process)")

        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            scheduler.shutdown(wait=False)

    try:
        loop.run_until_complete(_scheduler_main())
    except Exception as exc:
        logger.error(f"Scheduler thread crashed: {exc}")
    finally:
        loop.close()


def _start_scheduler_thread() -> threading.Thread:
    """Start the scheduler as a daemon thread so it dies with the worker process."""
    t = threading.Thread(
        target=_run_scheduler_in_thread,
        name="forge-scheduler",
        daemon=True,
    )
    t.start()
    logger.info(f"Scheduler background thread started: {t.name}")
    return t


# ── Orphan build detector ─────────────────────────────────────────────────────


def _run_orphan_detector_in_thread(redis_conn: Redis) -> None:
    """
    Detect and re-queue stuck builds in a background thread.
    A build is orphaned if it has been in 'generating' or 'architecting' status
    for more than 30 minutes with no file count change since the last check.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _orphan_main() -> None:
        # Give the worker time to start before first check
        await asyncio.sleep(90)
        logger.info("Orphan detector: starting (checks every 60s)")

        # Track last-seen file counts per run_id to detect no-progress
        last_file_counts: dict[str, tuple[int, float]] = {}  # run_id → (count, timestamp)

        while True:
            try:
                await _detect_and_requeue_orphans(redis_conn, last_file_counts)
            except Exception as exc:
                logger.error(f"Orphan detector error (non-blocking): {exc}")
            await asyncio.sleep(60)

    try:
        loop.run_until_complete(_orphan_main())
    except Exception as exc:
        logger.error(f"Orphan detector thread crashed: {exc}")
    finally:
        loop.close()


async def _detect_and_requeue_orphans(
    redis_conn: Redis,
    last_file_counts: dict[str, tuple[int, float]],
) -> None:
    """Check for stuck builds and re-queue them with full context preserved."""
    from datetime import datetime, timedelta, timezone
    from memory.database import get_session
    from memory.models import ForgeRun, RunStatus
    from pipeline.pipeline import run_pipeline_sync
    from sqlalchemy import select

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    stuck_statuses = (RunStatus.GENERATING.value, RunStatus.ARCHITECTING.value)

    async with get_session() as session:
        result = await session.execute(
            select(ForgeRun).where(
                ForgeRun.status.in_(stuck_statuses),
                ForgeRun.updated_at < cutoff,
            )
        )
        stuck_runs = result.scalars().all()

    if not stuck_runs:
        return

    queue = Queue("forge-builds", connection=redis_conn)

    for run in stuck_runs:
        run_id = run.run_id
        current_count = run.files_complete

        prev_count, prev_time = last_file_counts.get(run_id, (None, None))

        if prev_count is None:
            # First time we're seeing this stuck run — record current state
            last_file_counts[run_id] = (current_count, time.time())
            logger.warning(
                f"[{run_id}] Orphan candidate: status={run.status} "
                f"files_complete={current_count} updated_at={run.updated_at.isoformat()}"
            )
            continue

        # If file count hasn't changed since last check AND it's been 30+ min — orphaned
        if current_count == prev_count:
            # Check if this job is already queued (don't double-queue)
            job_id = f"build-{run_id}-resume"
            existing_job_ids = [j.id for j in queue.jobs]
            if job_id in existing_job_ids:
                logger.debug(f"[{run_id}] Already queued for resume — skipping")
                continue

            resume_from = "generating" if run.manifest_json else "resume_from_architecture"
            if run.status == RunStatus.ARCHITECTING.value:
                resume_from = "resume_from_architecture"

            queue.enqueue(
                run_pipeline_sync,
                run_id,
                resume_from,
                job_id=job_id,
                job_timeout=7200,
            )
            logger.warning(
                f"[{run_id}] Orphaned build re-queued: "
                f"resume_from={resume_from} files_complete={current_count}"
            )

            # Send Telegram notification
            try:
                from app.api.services.notify import _send
                await _send(
                    f"<b>The Forge — Orphan Build Recovered</b>\n\n"
                    f"<b>{run.title}</b>\n"
                    f"Run ID: <code>{run_id}</code>\n\n"
                    f"Build was stuck in '{run.status}' for 30+ minutes.\n"
                    f"Automatically re-queued from '{resume_from}'.\n"
                    f"Files completed before crash: <b>{current_count}</b>"
                )
            except Exception as notify_exc:
                logger.error(f"[{run_id}] Orphan notification failed: {notify_exc}")

            # Clear from tracking — it's been re-queued
            last_file_counts.pop(run_id, None)
        else:
            # Progress is being made — update tracking
            last_file_counts[run_id] = (current_count, time.time())


def _start_orphan_detector(redis_conn: Redis) -> threading.Thread:
    """Start the orphan build detector as a daemon thread."""
    t = threading.Thread(
        target=_run_orphan_detector_in_thread,
        args=(redis_conn,),
        name="forge-orphan-detector",
        daemon=True,
    )
    t.start()
    logger.info(f"Orphan detector thread started: {t.name}")
    return t


# ── DB write retry queue (Redis-backed) ───────────────────────────────────────


def _run_db_retry_worker(redis_conn: Redis) -> None:
    """
    Process queued DB writes that failed due to transient Postgres outages.
    Reads from the 'forge-db-retry' Redis list and replays them.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _retry_main() -> None:
        await asyncio.sleep(30)  # Give DB time to be ready
        logger.info("DB retry worker: started")
        while True:
            try:
                raw = redis_conn.lpop("forge-db-retry")
                if raw:
                    import json
                    payload = json.loads(raw)
                    await _apply_db_retry_write(payload)
                else:
                    await asyncio.sleep(10)
            except Exception as exc:
                logger.error(f"DB retry worker error: {exc}")
                await asyncio.sleep(30)

    try:
        loop.run_until_complete(_retry_main())
    except Exception as exc:
        logger.error(f"DB retry worker crashed: {exc}")
    finally:
        loop.close()


async def _apply_db_retry_write(payload: dict) -> None:
    """Apply a single queued DB write from the retry queue."""
    from memory.database import get_session
    from memory.models import ForgeRun
    from sqlalchemy import update

    run_id = payload.get("run_id")
    values = payload.get("values", {})
    if not run_id or not values:
        return

    async with get_session() as session:
        await session.execute(
            update(ForgeRun).where(ForgeRun.run_id == run_id).values(**values)
        )
    logger.info(f"[{run_id}] DB retry write applied: {list(values.keys())}")


def _start_db_retry_worker(redis_conn: Redis) -> threading.Thread:
    """Start the DB retry worker as a daemon thread."""
    t = threading.Thread(
        target=_run_db_retry_worker,
        args=(redis_conn,),
        name="forge-db-retry",
        daemon=True,
    )
    t.start()
    logger.info(f"DB retry worker thread started: {t.name}")
    return t


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Initialize database, start background threads, and start the RQ worker."""
    logger.info("The Forge worker starting...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Redis: {settings.redis_url}")

    # Initialize DB (creates tables if they don't exist)
    asyncio.run(init_db())
    logger.info("Database initialized")

    # Connect to Redis
    try:
        redis_conn = Redis.from_url(settings.redis_url)
        redis_conn.ping()
        logger.info("Redis connection verified")
    except Exception as exc:
        logger.error(f"Redis connection failed: {exc}")
        sys.exit(1)

    # Start background threads (scheduler merged into worker process)
    _start_scheduler_thread()
    _start_orphan_detector(redis_conn)
    _start_db_retry_worker(redis_conn)

    # Start RQ worker
    queue = Queue("forge-builds", connection=redis_conn)
    worker = Worker(
        queues=[queue],
        connection=redis_conn,
        name=f"forge-worker-{os.getpid()}",
        exception_handlers=[_handle_job_exception],
    )

    logger.info(
        f"Worker '{worker.name}' listening on queue 'forge-builds' "
        f"(scheduler + orphan detector running in background threads)"
    )
    worker.work(with_scheduler=True)


def _handle_job_exception(job, exc_type, exc_value, traceback):
    """
    RQ exception handler. Logs failed jobs and sends Telegram alert.
    Called when a job raises an unhandled exception after all retries.
    """
    run_id = job.args[0] if job.args else "unknown"
    error_msg = str(exc_value)

    logger.error(
        f"Job failed permanently: job_id={job.id} run_id={run_id} "
        f"exc={exc_type.__name__}: {error_msg}"
    )

    if exc_type == JobTimeoutException:
        error_msg = "Build exceeded 60-minute timeout. Blueprint may be too complex."

    try:
        from app.api.services.notify import notify_build_failed
        asyncio.run(
            notify_build_failed(
                run_id=run_id,
                title="Unknown",
                stage="worker",
                error=error_msg,
            )
        )
    except Exception as notify_exc:
        logger.error(f"Failed to send failure notification: {notify_exc}")

    return True  # Suppress default RQ exception handling


if __name__ == "__main__":
    main()
