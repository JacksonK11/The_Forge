"""
memory/seed.py
Seeds the database with starter data for The Forge.

Seeded on first startup via app/api/main.py lifespan.
Idempotent — safe to run multiple times.

Data seeded:
  - 5 ForgeTemplate records (blueprint starter library)
"""

import asyncio

from loguru import logger
from sqlalchemy import select

from memory.database import get_session
from memory.models import ForgeTemplate

# ── Template definitions ─────────────────────────────────────────────────────

TEMPLATES: list[dict] = [
    {
        "name": "Research Agent",
        "category": "research_agent",
        "description": "AI agent that continuously monitors configurable research domains and surfaces actionable intelligence.",
        "blueprint_text": """# Research Agent Blueprint

## Overview
An AI research agent that continuously scans multiple intelligence domains and delivers structured reports.

## Services Required
- API server (performance-cpu-4x, 2GB RAM)
- Worker (performance-cpu-4x, 4GB RAM)
- Scheduler (performance-cpu-2x, 512MB)

## Database Tables
- research_runs: id, query, status, report_json, created_at
- research_domains: id, name, search_queries, rss_feeds, refresh_hours
- research_findings: id, run_id, domain, title, summary, priority, url, created_at

## API Routes
- POST /research/submit — submit research query
- GET /research/runs/{run_id} — get run status and report
- GET /research/domains — list configured domains
- PUT /research/domains/{domain_id} — update domain config
- GET /health — health check

## Dashboard Screens
- Home: Submit research query, domain configuration
- Report: Structured research report with findings by domain
- History: Past research runs

## External APIs
- Anthropic Claude (claude-sonnet-4-6 for synthesis, claude-haiku-4-5-20251001 for classification)
- Tavily (web search per domain)
- OpenAI (text-embedding-3-small for knowledge base)
- Telegram (findings notifications)

## Environment Variables
- ANTHROPIC_API_KEY
- TAVILY_API_KEY
- OPENAI_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- DATABASE_URL
- REDIS_URL
- API_SECRET_KEY
""",
    },
    {
        "name": "Trading Bot",
        "category": "trading_bot",
        "description": "Autonomous trading strategy development, backtesting, and live signal routing pipeline.",
        "blueprint_text": """# Trading Bot Blueprint

## Overview
Autonomous trading pipeline: research → strategy development → validation → live signal routing.

## Services Required
- API server (performance-cpu-4x, 2GB RAM)
- Worker (performance-cpu-8x, 8GB RAM — for backtesting)
- Scheduler (performance-cpu-2x, 512MB)

## Database Tables
- strategies: id, name, entry_rules, exit_rules, status, calmar_ratio, win_rate, max_drawdown, created_at
- backtest_runs: id, strategy_id, start_date, end_date, metrics_json, status, created_at
- signals: id, strategy_id, symbol, direction, entry_price, stop_loss, take_profit, status, created_at
- market_data: id, symbol, timeframe, ohlcv_json, recorded_at

## API Routes
- POST /strategies/research — start research and strategy development
- GET /strategies/{id} — get strategy details and metrics
- POST /strategies/{id}/backtest — run backtest
- GET /strategies/{id}/signals — get live signals
- POST /signals/webhook — TradingView webhook receiver
- GET /health

## Dashboard Screens
- Home: Active strategies overview, live P&L
- Strategy Builder: Research input, generated strategy review
- Backtest Results: Metrics, equity curve, trade list
- Signals: Live routing status

## External APIs
- Anthropic Claude
- Alpaca Markets (OHLCV data)
- Telegram (signal notifications)
- OpenAI (embeddings)

## Environment Variables
- ANTHROPIC_API_KEY
- ALPACA_API_KEY
- ALPACA_SECRET_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- DATABASE_URL
- REDIS_URL
- API_SECRET_KEY
""",
    },
    {
        "name": "Customer Service Agent",
        "category": "customer_service",
        "description": "AI agent that handles inbound customer messages 24/7 with intelligent routing and escalation.",
        "blueprint_text": """# Customer Service Agent Blueprint

## Overview
AI-powered customer service handling inbound messages across SMS, WhatsApp, and email.

## Services Required
- API server (performance-cpu-4x, 2GB RAM)
- Worker (performance-cpu-4x, 4GB RAM)

## Database Tables
- conversations: id, customer_phone, customer_email, channel, status, last_message_at, created_at
- messages: id, conversation_id, direction, content, channel, sentiment_score, created_at
- customers: id, phone, email, name, tags, notes, created_at
- escalations: id, conversation_id, reason, assigned_to, resolved_at, created_at

## API Routes
- POST /webhooks/sms — inbound SMS webhook
- POST /webhooks/whatsapp — inbound WhatsApp webhook
- POST /webhooks/email — inbound email webhook
- GET /conversations — list conversations
- GET /conversations/{id} — conversation detail
- POST /conversations/{id}/reply — manual reply
- POST /conversations/{id}/escalate — escalate to human
- GET /health

## Dashboard Screens
- Inbox: All active conversations, sorted by urgency
- Conversation: Full message thread, AI suggestions
- Customers: Customer profiles and history
- Analytics: Response time, sentiment, resolution rate

## External APIs
- Anthropic Claude (claude-opus-4-6 for conversations)
- Twilio (SMS/WhatsApp)
- SendGrid (email)
- Telegram (escalation alerts)

## Environment Variables
- ANTHROPIC_API_KEY
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- SENDGRID_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- DATABASE_URL
- REDIS_URL
- API_SECRET_KEY
""",
    },
    {
        "name": "Data Pipeline Agent",
        "category": "data_pipeline",
        "description": "Scheduled data collection, transformation, and reporting agent with configurable sources.",
        "blueprint_text": """# Data Pipeline Agent Blueprint

## Overview
Scheduled data collection from configurable sources, AI-powered transformation and insight extraction.

## Services Required
- API server (performance-cpu-4x, 2GB RAM)
- Worker (performance-cpu-4x, 4GB RAM)
- Scheduler (performance-cpu-2x, 512MB)

## Database Tables
- pipeline_runs: id, pipeline_name, status, records_processed, error_message, started_at, completed_at
- data_sources: id, name, source_type, config_json, last_run_at, is_active
- records: id, source_id, run_id, raw_json, transformed_json, created_at
- reports: id, pipeline_name, report_json, period_start, period_end, created_at

## API Routes
- POST /pipelines/trigger/{name} — manually trigger pipeline
- GET /pipelines/runs — list recent runs
- GET /pipelines/runs/{id} — run detail
- GET /sources — list data sources
- PUT /sources/{id} — update source config
- GET /reports/latest/{pipeline_name} — latest report
- GET /health

## Dashboard Screens
- Home: Pipeline status overview, recent runs
- Run Detail: Records processed, errors, duration
- Sources: Configure data sources
- Reports: View latest reports per pipeline

## External APIs
- Anthropic Claude (insight extraction)
- Tavily (web data sources)
- Telegram (run completion/failure alerts)
- OpenAI (embeddings)

## Environment Variables
- ANTHROPIC_API_KEY
- TAVILY_API_KEY
- OPENAI_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- DATABASE_URL
- REDIS_URL
- API_SECRET_KEY
""",
    },
    {
        "name": "Monitoring Agent",
        "category": "monitoring_agent",
        "description": "Infrastructure and application monitoring agent with anomaly detection and automated alerting.",
        "blueprint_text": """# Monitoring Agent Blueprint

## Overview
Continuous monitoring of services, APIs, and metrics with AI-powered anomaly detection and Telegram alerting.

## Services Required
- API server (performance-cpu-4x, 2GB RAM)
- Scheduler (performance-cpu-2x, 512MB)

## Database Tables
- monitors: id, name, check_type, target_url, check_interval_seconds, is_active, created_at
- check_results: id, monitor_id, status, response_time_ms, status_code, error_message, checked_at
- alerts: id, monitor_id, alert_type, message, resolved_at, created_at
- baselines: id, monitor_id, metric_name, baseline_value, threshold_percent, updated_at

## API Routes
- POST /monitors — create monitor
- GET /monitors — list monitors
- PUT /monitors/{id} — update monitor
- DELETE /monitors/{id} — delete monitor
- GET /monitors/{id}/history — check history
- GET /alerts — list active alerts
- POST /alerts/{id}/resolve — resolve alert
- GET /health

## Dashboard Screens
- Home: All monitors status, uptime percentages, active alerts
- Monitor Detail: Response time chart, check history, alert history
- Alerts: Active and resolved alerts

## External APIs
- Anthropic Claude (anomaly diagnosis)
- Telegram (instant alerts)

## Environment Variables
- ANTHROPIC_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- DATABASE_URL
- REDIS_URL
- API_SECRET_KEY
""",
    },
]


# ── Seed functions ────────────────────────────────────────────────────────────


async def seed_templates() -> None:
    """Insert starter blueprint templates. Skips existing records by name."""
    async with get_session() as session:
        inserted = 0
        for data in TEMPLATES:
            result = await session.execute(
                select(ForgeTemplate).where(ForgeTemplate.name == data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(ForgeTemplate(**data))
                inserted += 1
        logger.info(f"Templates seeded: {inserted} new, {len(TEMPLATES) - inserted} already existed")


async def run_seed() -> None:
    """Run all seed operations. Called on application startup."""
    logger.info("Running database seed...")
    await seed_templates()
    logger.info("Database seed complete")


if __name__ == "__main__":
    asyncio.run(run_seed())
