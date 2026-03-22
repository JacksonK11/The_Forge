# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## THE OFFICE — AI Agent Portfolio

**Owner:** Jackson Khoury · Sydney, Australia
**Current build:** The Forge (Agent 1 of 5)
**Folder:** `~/the-office/agents/the-forge`

This is a portfolio of 5 elite AI agents operating 24/7 across multiple businesses and investment systems. These agents handle real money, real leads, real clients, and real business decisions. Every file must be complete, production-ready, with full error handling and full logging. If a file is not ready to deploy, it is not finished.

---

## CODE QUALITY — NON-NEGOTIABLE

- Full async/await everywhere — no blocking calls
- Every external API call wrapped in try/except with loguru error logging
- Every database operation uses asyncpg with connection pooling
- No hardcoded values — everything from environment variables
- No placeholder comments, no TODO stubs, no "implement this later"
- Type hints on every function signature
- Pydantic models for every API request and response

---

## ARCHITECTURE STANDARD — ALL AGENTS

**Backend:** FastAPI (Python 3.12), async throughout
**Database:** SQLAlchemy 2.0 + asyncpg + pgvector
**Background jobs:** RQ (Redis Queue)
**Scheduling:** APScheduler
**Logging:** Loguru — structured, consistent, searchable
**Frontend:** React + Vite + Tailwind (PWA-capable)
**Deployment:** Fly.io — API in `syd` or `lhr` region
**CI/CD:** GitHub Actions — auto-deploy on push to main, never deploy manually
**Models:** `claude-opus-4-6` (reasoning), `claude-sonnet-4-6` (research/synthesis), `claude-haiku-4-5-20251001` (classification/scoring)
**Embeddings:** OpenAI `text-embedding-3-small`
**Web search:** Tavily
**Notifications:** Telegram bot per agent → Jackson's personal account

---

## INTELLIGENCE LAYER — REQUIRED IN EVERY AGENT (all 7 files)

| File | Purpose |
|------|---------|
| `config/model_config.py` | Routes Claude calls: Sonnet/Opus for reasoning, Haiku for classification. Reduces API cost 35-40% |
| `intelligence/knowledge_base.py` | Stores outcomes from every operation, retrieves via pgvector similarity. Agent improves with every run |
| `intelligence/meta_rules.py` | Weekly job extracts operational rules from real outcomes, auto-updates prompts. Agent self-improves without code changes |
| `intelligence/context_assembler.py` | Assembles optimal context before every major Claude call: KB records + meta-rules + system state |
| `intelligence/evaluator.py` | Scores every significant output against domain rubric before delivery. Substandard outputs regenerated |
| `intelligence/verifier.py` | Independent second Claude instance adversarially reviews high-stakes outputs |
| `monitoring/performance_monitor.py` | Tracks 5 KPIs every 6 hours, detects 15%+ degradation, auto-diagnoses, alerts via Telegram |

---

## KNOWLEDGE ENGINE — REQUIRED IN EVERY AGENT (all 5 files)

| File | Purpose |
|------|---------|
| `config/knowledge_config.py` | Research domains, search queries, YouTube queries, RSS feeds, refresh schedules |
| `knowledge/collector.py` | Scheduled sweeps via Tavily + RSS + YouTube. Claude summarises each article. Deduplicates by content hash |
| `knowledge/embedder.py` | Splits articles into 400-token overlapping chunks, OpenAI embeddings, stores in pgvector |
| `knowledge/retriever.py` | Semantic similarity search, returns top 8 relevant chunks before every Claude call |
| `knowledge/live_search.py` | Real-time Tavily search when question contains recency signals or KB is stale |

---

## DEPLOYMENT STANDARD — EVERY BUILD GENERATES

- `FLY_SECRETS.txt` — every `flyctl secrets set` command ready to run
- `README.md` — complete setup and deployment guide
- `connection_test.py` — verifies all API keys before deploying
- `.env.example` — template with all required variables
- `.github/workflows/deploy.yml` — GitHub Actions auto-deploy
- `docker-compose.yml` — local dev
- Dockerfile per service
- `fly.toml` per service

**Fly.io services per agent:**
- API: `performance-cpu-4x`, 2GB RAM (~A$37/mo)
- Worker: `performance-cpu-4x`, 4GB RAM (~A$73/mo)
- Dashboard: `performance-cpu-2x`, 512MB (~A$9/mo)
- Scheduler: `performance-cpu-2x`, 512MB (~A$9/mo)
- Postgres HA: managed, 2GB (~A$63/mo)
- Redis: managed, 256MB (~A$30/mo)

---

## THE 5 AGENTS

### Agent 1: The Forge — AI Build Engine (CURRENT BUILD)
Blueprint document → complete deployable codebase in 15-25 minutes.

**Services:** `the-forge-api` (512MB), `the-forge-worker` (1GB), `the-forge-dashboard` (256MB), `the-forge-db`, `the-forge-redis`

**7-stage pipeline:** Parse → Spec Confirmation → Architecture → Code Generation → Secrets → README → Package

**6 code generation layers (dependency order):**
1. Database schema — imported by everything, generated first
2. Infrastructure — requirements.txt, docker-compose, .env.example, Dockerfiles
3. Backend API — FastAPI routes, services, middleware, auth
4. Worker/agent logic — RQ workers, pipeline nodes, background processors
5. Web dashboard — React JSX, Tailwind styling, API client
6. Deployment — fly.toml files, GitHub Actions deploy.yml

**Evaluator checks every generated file:** no placeholders, correct imports, complete error handling, no hardcoded URLs, no exposed secrets.
**Verifier reviews complete output package:** "What would prevent this from deploying on first try?"

Every generated ZIP must contain all source code, FLY_SECRETS.txt, README.md, deploy.yml, connection_test.py, .env.example, docker-compose.yml, all Dockerfiles, all fly.toml files. Nothing missing. Nothing incomplete.

---

### Agent 2: BuildRight AI Agent — Sydney Construction Lead Machine
Most sophisticated AI lead generation, qualification, and conversion system for a Sydney construction business.

**Stack:** Next.js 14, TypeScript, Prisma, Vercel + Python FastAPI on Fly.io
**Market:** Sydney, NSW — all prices AUD including GST 10%
**AI Model:** Claude Opus 4.6 for all conversation

**22 modules across two tracks:**
- **Inbound:** 60-second SMS/WhatsApp response 24/7, lead scoring 0-100, 6-touch follow-up (Day 0/1/3/5/8/14), booking detection, Google Calendar invite, pre-quote intelligence (3-tier Low/Mid/High), job lifecycle tracking, GST-compliant invoice drafting, review requests, suburb performance tracking, material price monitoring (12 prices weekly)
- **Outbound:** DA Application Monitor (NSW Planning Portal every 6h), Property Sales Monitor (Domain + realestate.com.au daily), Competitor Review Miner (weekly Google Maps scan top 20 competitors), Neighbour Referral Engine (8 nearest neighbours within 24h of job completion)
- **Learning engines:** Internal Transcript Analyser (Sunday 11pm), World Sales Intelligence (Wednesday 6am), Performance + Suburb Engine (Sunday midnight)

**Hardcoded rules:** Never mention dollar figures in automated messages. Every conversation goal is booking a call/site visit — never close via SMS. Commercial/strata always requires onsite quote. External door: 1 day. Complex external: up to 2 days. Whole house: 3-4 days.

---

### Agent 3: AI Trading Operating System
Fully autonomous trading research, strategy development, validation, optimisation, and live execution pipeline for prop firm accounts.

**Stack:** Python 3.12, FastAPI, LangGraph, asyncpg, RQ, Optuna, Fly.io (Sydney)
**Models:** Claude Sonnet 4.6 for research/strategy, Haiku for classification
**Target:** FTMO and similar prop firms — A$100,000 account

**Pipeline:** Research (10 intelligence layers: ForexFactory, CFTC COT, Central Bank sentiment, Guardian news, Alpaca OHLCV, TA-Lib, SMC, academic papers, seasonality, session analysis) → 4 specialist agents (Research Analyst → Strategy Architect → Self-Critique → Code Engineer → Risk Officer) → 6-gate validation (Sample Size, Walk-Forward, Holdout, Monte Carlo, Six Metrics [Calmar ≥3.0, Win Rate ≥70%, Profit Factor ≥1.8, Sharpe ≥1.5, Max DD ≤15%, Avg RR ≥1.5], Correlation) → Optuna optimisation (150 trials, 4 regime studies) → Live routing (TradingView webhooks, 5-constraint router)

**Hardcoded safety:** Weekly loss limit 2% → 3-day pause. Daily loss limit 1% → same pause. Max 3 concurrent positions. No trading within 15min of high-impact news.

---

### Agent 4: ARIA — AI Research Intelligence Agent
Continuously scans 12 intelligence domains and surfaces what matters for Jackson's portfolio.

**Stack:** Python 3.12, FastAPI, asyncpg, RQ, APScheduler, Fly.io
**Models:** Claude Sonnet 4.6 for synthesis, Haiku for classification

**12 domains:** Models & LLMs, Agent Frameworks, Memory & Context, Trading AI, Real Estate AI, Business Automation, Coding & Dev AI, Competitive Intelligence, Market Gaps, Opportunities, APIs & Connectors, Accuracy & Safety

**Outputs:** Individual research reports with production-ready integration code for Jackson's exact stack, Strategic Synthesis brief, Opportunity Radar (net-new agent ideas with revenue impact), Action Queue (persistent prioritised implementation checklist)

**Auto-scan:** Configurable 30/60/120 min intervals. WebSocket live terminal. HIGH priority findings surface immediately as dashboard alerts.

---

### Agent 5: The Office — Unified AI Command Center
Single executive dashboard above every business and agent — one view, one chat interface, one notification stream.

**Stack:** Python 3.12, FastAPI, asyncpg, React + Vite + Tailwind, Fly.io (Sydney)
**Models:** Claude Sonnet 4.6 for analysis, Haiku for classification

**Features:** Health score 0-100 per business (hourly), anomaly prediction 2-4h ahead, cross-business financial consolidation, unified chat bridge routing to any agent, automated daily brief (7am) and weekly summary (Sunday 8pm), cross-portfolio pattern recognition

**Future:** React Native iOS app with native APNs, lock screen action buttons, replaces Telegram as primary notification channel.

---

## SHARED ACCOUNTS (one account — all agents share)

- **Anthropic:** Named keys per agent (the-forge, buildright, trading-os, aria, the-office)
- **OpenAI:** One key — `text-embedding-3-small` for embeddings only
- **Tavily:** Free tier covers all agents
- **GitHub:** One org, one private repo per agent
- **Telegram:** One bot per agent → Jackson's personal account
- **Fly.io:** One account, all apps

---

## ABSOLUTE PROHIBITIONS

- Never expose API keys in code, logs, or GitHub
- Never generate placeholder code, stub functions, or TODO comments
- Never use synchronous/blocking code in async contexts
- Never skip error handling on any external API call
- Never hardcode environment-specific values (URLs, ports, credentials)
- Never cut corners on the intelligence layer — all 7 files must be complete in every agent

---

## BUILD ORDER

1. **The Forge** ← current
2. BuildRight (first agent built through The Forge)
3. Trading OS
4. ARIA
5. The Office
6. Unlimited future agents — all built through The Forge, all to this same standard

The Forge is the engine. Every agent it builds compounds the advantage of every other. Build it right the first time.
