"""
pipeline/worker.py
RQ worker entry point for The Forge build pipeline.

Listens on the "forge-builds" queue and processes blueprint build jobs.
Run with: python pipeline/worker.py

One worker processes one build at a time. Scale by running multiple worker
instances: `flyctl scale count 2 --app the-forge-worker`
"""

import os
import sys

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


def main() -> None:
    """Initialize database and start the RQ worker."""
    import asyncio

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

    # Start worker
    queue = Queue("forge-builds", connection=redis_conn)
    worker = Worker(
        queues=[queue],
        connection=redis_conn,
        name=f"forge-worker-{os.getpid()}",
        exception_handlers=[_handle_job_exception],
    )

    logger.info(f"Worker '{worker.name}' listening on queue 'forge-builds'")
    worker.work(with_scheduler=True)


def _handle_job_exception(job, exc_type, exc_value, traceback):
    """
    RQ exception handler. Logs failed jobs and sends Telegram alert.
    Called when a job raises an unhandled exception after all retries.
    """
    import asyncio
    from app.api.services.notify import notify_build_failed

    run_id = job.args[0] if job.args else "unknown"
    error_msg = str(exc_value)

    logger.error(
        f"Job failed permanently: job_id={job.id} run_id={run_id} "
        f"exc={exc_type.__name__}: {error_msg}"
    )

    if exc_type == JobTimeoutException:
        error_msg = "Build exceeded 60-minute timeout. Blueprint may be too complex."

    try:
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
