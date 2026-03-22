"""
memory/database.py
Async database engine, session management, and initialization for The Forge.

Uses asyncpg with connection pooling. Enables pgvector extension on first init.
All database operations across the application use the session factory from here.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from memory.models import Base

# ── Engine ───────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]

# Fly.io internal Postgres (flycast) uses an unverified TLS connection.
# asyncpg requires ssl=False for internal Fly.io connections; it does not
# accept libpq-style sslmode=disable query params.
_connect_args: dict = {}
if "flycast" in DATABASE_URL or "internal" in DATABASE_URL:
    _connect_args["ssl"] = False

# Strip any legacy sslmode=disable param that asyncpg can't parse
if "sslmode=" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

# NullPool: no persistent connection pool. Required because the RQ worker
# calls asyncio.run() per job (each creating a new event loop). A pooled
# engine attaches connections to the first event loop; subsequent asyncio.run()
# calls get a different loop and asyncpg raises "Future attached to a different
# loop". NullPool creates a fresh connection per operation, avoiding the issue.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args=_connect_args,
)

# ── Session factory ──────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions with automatic commit/rollback.
    Use this in pipeline nodes and background workers.

    Usage:
        async with get_session() as session:
            session.add(record)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(f"Database session error: {exc}")
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency injection for database sessions.
    Inject with: session: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Initialization ───────────────────────────────────────────────────────────


async def init_db() -> None:
    """
    Initialize database on startup.
    - Enables pgvector extension (required for Vector columns)
    - Creates all tables defined in models.py
    Safe to call multiple times — CREATE IF NOT EXISTS semantics.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("pgvector extension enabled")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All database tables created")
            # Idempotent column additions for schema migrations
            await conn.execute(text(
                "ALTER TABLE forge_runs ADD COLUMN IF NOT EXISTS package_data BYTEA"
            ))
        logger.info("Database initialization complete")
    except Exception as exc:
        logger.error(f"Database initialization failed: {exc}")
        raise


async def close_db() -> None:
    """Dispose of the connection pool. Call on application shutdown."""
    await engine.dispose()
    logger.info("Database connections closed")
