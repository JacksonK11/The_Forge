"""
connection_test.py
Pre-deployment connection verification for The Forge.

Run this before deploying to confirm all external services are reachable
and API keys are valid. Exits with code 0 on success, 1 on any failure.

Usage:
    python connection_test.py

Or with a .env file:
    python connection_test.py  # auto-loads .env via pydantic-settings
"""

import asyncio
import os
import sys


def _check_env():
    """Verify all required environment variables are set."""
    required = [
        "DATABASE_URL",
        "REDIS_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "TAVILY_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "API_SECRET_KEY",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"  FAIL — Missing env vars: {', '.join(missing)}")
        return False
    print(f"  OK   — All {len(required)} required env vars present")
    return True


async def _check_postgres():
    """Verify PostgreSQL connection and pgvector extension."""
    try:
        import asyncpg

        db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(db_url, timeout=10)
        version = await conn.fetchval("SELECT version()")
        has_vector = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
        )
        await conn.close()
        vector_status = "pgvector ✓" if has_vector else "pgvector NOT INSTALLED"
        print(f"  OK   — PostgreSQL connected. {version.split(',')[0]}. {vector_status}")
        return has_vector > 0
    except Exception as exc:
        print(f"  FAIL — PostgreSQL: {exc}")
        return False


async def _check_redis():
    """Verify Redis connection."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=5)
        await client.ping()
        info = await client.info("server")
        await client.aclose()
        print(f"  OK   — Redis connected. Version: {info['redis_version']}")
        return True
    except Exception as exc:
        print(f"  FAIL — Redis: {exc}")
        return False


async def _check_anthropic():
    """Verify Anthropic API key with a minimal request."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with just: OK"}],
        )
        text = response.content[0].text.strip()
        await client.close()
        print(f"  OK   — Anthropic API key valid. Model responded: '{text}'")
        return True
    except Exception as exc:
        print(f"  FAIL — Anthropic: {exc}")
        return False


async def _check_openai():
    """Verify OpenAI API key by generating a test embedding."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input="connection test",
        )
        dims = len(response.data[0].embedding)
        await client.close()
        print(f"  OK   — OpenAI API key valid. Embedding dims: {dims}")
        return True
    except Exception as exc:
        print(f"  FAIL — OpenAI: {exc}")
        return False


async def _check_tavily():
    """Verify Tavily API key with a minimal search."""
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        # Use a loop to run sync client in async context
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: client.search("python fastapi", max_results=1)
        )
        hits = len(result.get("results", []))
        print(f"  OK   — Tavily API key valid. Test search returned {hits} result(s)")
        return True
    except Exception as exc:
        print(f"  FAIL — Tavily: {exc}")
        return False


async def _check_telegram():
    """Verify Telegram bot token by calling getMe."""
    try:
        import httpx

        token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            r.raise_for_status()
            bot = r.json()["result"]
        print(
            f"  OK   — Telegram bot valid. Bot: @{bot.get('username')} — "
            f"Chat ID configured: {chat_id}"
        )
        return True
    except Exception as exc:
        print(f"  FAIL — Telegram: {exc}")
        return False


async def main():
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # python-dotenv optional — env vars may already be set

    print("\n╔══════════════════════════════════════════════════╗")
    print("║       THE FORGE — Connection Test                ║")
    print("╚══════════════════════════════════════════════════╝\n")

    results = {}

    print("[ Environment ]")
    results["env"] = _check_env()

    print("\n[ Infrastructure ]")
    results["postgres"] = await _check_postgres()
    results["redis"] = await _check_redis()

    print("\n[ AI Services ]")
    results["anthropic"] = await _check_anthropic()
    results["openai"] = await _check_openai()

    print("\n[ External APIs ]")
    results["tavily"] = await _check_tavily()
    results["telegram"] = await _check_telegram()

    # Summary
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n{'═' * 52}")
    print(f"  Result: {passed}/{total} checks passed")

    failed_checks = [k for k, v in results.items() if not v]
    if failed_checks:
        print(f"  Failed: {', '.join(failed_checks)}")
        print("\n  ✗ The Forge is NOT ready for deployment.")
        print("    Fix the above issues before running fly deploy.\n")
        sys.exit(1)
    else:
        print("\n  ✓ The Forge is ready for deployment.")
        print("    Run: fly deploy --config fly.api.toml\n")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
