"""
app/api/main.py
FastAPI application entry point for The Forge API server.

Startup: initializes DB, seeds templates, connects to Redis.
Routes: /forge (blueprint submission), /runs (status/files), /templates, /health.
"""

import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from redis import Redis
from rq import Queue

from app.api.middleware.auth import AuthMiddleware
from app.api.routes import forge, runs, templates
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


# ── Redis / RQ ───────────────────────────────────────────────────────────────

redis_conn = Redis.from_url(settings.redis_url)
build_queue = Queue("forge-builds", connection=redis_conn)


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"The Forge API starting — env={settings.app_env}")
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

# ── Middleware ────────────────────────────────────────────────────────────────

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

# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(forge.router, prefix="/forge", tags=["forge"])
app.include_router(runs.router, prefix="/forge/runs", tags=["runs"])
app.include_router(templates.router, prefix="/templates", tags=["templates"])


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
