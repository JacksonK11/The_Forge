"""
tests/conftest.py
Sets required environment variables before any module imports,
so pure-function tests work without a live database or Redis.
"""
import os

# Must be set before any app module is imported — database.py reads these at module level
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "999999")
