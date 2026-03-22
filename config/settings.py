"""
config/settings.py
Central application settings loaded from environment variables.
Used by all services: API, worker, pipeline nodes, intelligence layer.
"""

import os
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    app_env: str = "development"
    app_port: int = 8000

    # ── Security ─────────────────────────────────────────────────────────────
    api_secret_key: str

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str

    # ── Claude AI ────────────────────────────────────────────────────────────
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"
    claude_fast_model: str = "claude-haiku-4-5-20251001"

    # ── OpenAI (embeddings only) ─────────────────────────────────────────────
    openai_api_key: str

    # ── Tavily (web search) ──────────────────────────────────────────────────
    tavily_api_key: str

    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_chat_id: str

    # ── Sentry (optional) ────────────────────────────────────────────────────
    sentry_dsn: str = ""

    # ── GitHub (optional — enables auto-push of generated codebases) ─────────
    github_token: Optional[str] = None

    # ── The Office (optional — set when Agent 5 is deployed) ─────────────────
    office_webhook_url: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


# Singleton — import this everywhere
settings = Settings()
