"""
app/api/main.py
FastAPI application entry point for The Forge API server.

Startup: validates critical secrets, initializes DB, seeds templates, connects to Redis.
Routes: /forge (blueprint submission), /runs (status/files), /templates, /health.
Body limit: 10MB (supports large blueprints with attached code files).
Rate limiting: 60 req/min per IP, 10 build submissions per hour.
"""

import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from redis import Redis
from rq import Queue
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.middleware.auth import AuthMiddleware
from app.api.ratelimit import limiter
from app.api.routes import forge, runs, templates
from app.api.routes.chat import router as chat_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.incremental import router as incremental_router
from app.api.routes.office import router as office_router
from app.api.routes.settings import router as settings_router
from app.api.routes.system import router as system_router
from config.settings import settings
from memory.database import close_db, init_db
from memory.seed import run_seed

# ── Sentry ───────────────────────────────────────────────────────────────────

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=0.1,
    )


# ── Body size limit middleware ─────────────────────────────────────────────────


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies larger than 10MB to protect against abuse."""

    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body too large. Maximum is {self.MAX_BODY_SIZE // 1024 // 1024}MB."
                },
            )
        return await call_next(request)


# ── Redis / RQ ───────────────────────────────────────────────────────────────

redis_conn = Redis.from_url(settings.redis_url)
build_queue = Queue("forge-builds", connection=redis_conn)


# ── Startup secret validation ──────────────────────────────────────────────────


def _validate_critical_secrets() -> None:
    """
    Verify all critical secrets are set before accepting traffic.
    Logs warnings for optional secrets and raises on critical missing ones.
    """
    critical = {
        "API_SECRET_KEY": settings.api_secret_key,
        "DATABASE_URL": settings.database_url,
        "REDIS_URL": settings.redis_url,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
    }
    optional = {
        "GITHUB_TOKEN": settings.github_token,
        "FLY_API_TOKEN": settings.fly_api_token,
        "TAVILY_API_KEY": settings.tavily_api_key,
        "SENTRY_DSN": settings.sentry_dsn,
    }

    missing_critical = [k for k, v in critical.items() if not v]
    if missing_critical:
        msg = f"CRITICAL: Missing required secrets: {', '.join(missing_critical)}. Startup aborted."
        logger.error(msg)

        # Try to send Telegram alert even though we're about to crash
        try:
            import asyncio
            import httpx
            bot_token = settings.telegram_bot_token
            chat_id = settings.telegram_chat_id
            if bot_token and chat_id:
                asyncio.run(
                    httpx.AsyncClient().post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": f"🚨 The Forge API startup FAILED\n\n{msg}"},
                        timeout=5,
                    )
                )
        except Exception:
            pass
        raise RuntimeError(msg)

    missing_optional = [k for k, v in optional.items() if not v]
    if missing_optional:
        logger.warning(
            f"Optional secrets not set (some features disabled): {', '.join(missing_optional)}"
        )

    logger.info("All critical secrets validated ✓")


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"The Forge API starting — env={settings.app_env}")
    _validate_critical_secrets()
    await init_db()
    await run_seed()
    yield
    await close_db()
    logger.info("The Forge API shutdown complete")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="The Forge — AI Build Engine",
    description="Blueprint document → complete deployable codebase in 15–25 minutes.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware (order matters: outermost first) ───────────────────────────────

app.add_middleware(MaxBodySizeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [
        "https://the-forge-dashboard.fly.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)
app.add_middleware(SlowAPIMiddleware)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(forge.router, prefix="/forge", tags=["forge"])
app.include_router(runs.router, prefix="/forge/runs", tags=["runs"])
app.include_router(templates.router, prefix="/templates", tags=["templates"])
app.include_router(office_router, prefix="/forge", tags=["office"])
app.include_router(chat_router, prefix="/forge", tags=["chat"])
app.include_router(system_router, prefix="/system", tags=["system"])
app.include_router(settings_router, prefix="/settings", tags=["settings"])
app.include_router(feedback_router, prefix="/forge", tags=["feedback"])
app.include_router(incremental_router, prefix="/forge/incremental", tags=["incremental"])


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Health check endpoint. Verifies Redis connectivity."""
    try:
        redis_conn.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "status": "healthy" if redis_ok else "degraded",
        "service": "the-forge-api",
        "env": settings.app_env,
        "redis": "ok" if redis_ok else "unreachable",
    }


# ── Expose queue for routes ───────────────────────────────────────────────────

def get_build_queue() -> Queue:
    return build_queue
