"""
pipeline/prompts/prompts.py
All Claude prompts for The Forge pipeline.

These prompts are the core IP of The Forge. They are injected with real context
at call time — spec JSON, previously generated files, meta-rules from the knowledge
base — so quality compounds with every build.

Prompt design principles:
  - Every prompt explicitly forbids placeholder code, TODO stubs, and incomplete functions
  - File generation prompts include previously generated files for import consistency
  - Evaluator and verifier prompts ask adversarial questions ("what would break this?")
  - Meta-rule prompts close the self-improvement loop
"""

import json
from typing import Optional


# ── Stage 2: Blueprint Validation ────────────────────────────────────────────

VALIDATION_SYSTEM = """You are a blueprint validator for The Forge, an AI code generation engine.
Your job is to check if a blueprint document is complete enough to generate a production codebase from.
Be strict but fair. A blueprint that is genuinely too vague wastes expensive API calls."""

# IMPORTANT: Do NOT use VALIDATION_USER directly with str.format() — the blueprint
# can contain curly braces, Python code, f-strings, and other characters that would
# break str.format(). Use build_validation_prompt() instead which uses concatenation.
_VALIDATION_USER_BEFORE = """Review this blueprint document and determine if it is complete enough to generate a production codebase.

BLUEPRINT:
"""

_VALIDATION_USER_AFTER = """

A complete blueprint must include ALL of the following:
1. What the agent/application does (its purpose)
2. At least one database table with column descriptions
3. At least one API endpoint
4. The tech stack or service requirements

Respond with a JSON object only — no prose before or after:
{
  "is_valid": true/false,
  "missing_elements": ["list of what is missing, empty if valid"],
  "questions": ["specific questions to ask the user to complete the blueprint, empty if valid"],
  "confidence": 0.0-1.0
}"""


def build_validation_prompt(blueprint_text: str) -> str:
    """
    Build the validation user prompt using string concatenation — never str.format().
    blueprint_text can contain any characters including {, }, \\, quotes, etc.
    """
    return _VALIDATION_USER_BEFORE + blueprint_text + _VALIDATION_USER_AFTER


# ── Stage 3: Blueprint Parsing ────────────────────────────────────────────────

PARSE_SYSTEM = """You are the blueprint parser for The Forge — an AI code generation engine.
Your job is to read a blueprint document and extract a precise, structured JSON specification
that will be used to generate a complete, production-ready codebase.

Be thorough and precise. Every piece of information you extract will directly drive code generation.
If the blueprint implies something that is not stated explicitly (e.g., a created_at timestamp on
every table), include it. Fill in professional defaults for anything not specified.

BUSINESS PROFILE RULE — mandatory before generating any business-specific code:
The spec MUST capture exactly what this business does from the blueprint. Never substitute generic
filler service descriptions. If the blueprint says "mobile car detailing", every AI prompt, market
gap scan, and service description in the generated agent must say "mobile car detailing" — not
"driveway cleaning", "pressure washing", or any other unrelated service. If the blueprint is
ambiguous about the core service, add it to the validation questions list. The business_name,
business_location, and service_type fields in the spec drive all AI prompt personalisation in
the generated agent — wrong values here propagate incorrect context into every AI call.

The generated codebase must follow this stack:
- Backend: FastAPI + Python 3.12, fully async, Pydantic v2 models, loguru logging
- Database: SQLAlchemy 2.0 + asyncpg + pgvector
- Background jobs: RQ (Redis Queue)
- Scheduling: APScheduler
- Frontend: React + Vite + Tailwind CSS
- Deployment: Fly.io, GitHub Actions CI/CD
- Notifications: Telegram bot
- AI: Anthropic Claude (claude-sonnet-4-6 for reasoning, claude-haiku-4-5-20251001 for classification)
- Embeddings: OpenAI text-embedding-3-small"""

_PARSE_USER_SCHEMA = """Return a JSON object with this exact structure — no prose, no markdown fences, just the JSON:

CRITICAL: file_list is the most important field. It must be complete and exhaustive —
list every single file that needs to be generated. A typical agent has 40–80 files.
Generate file_list FIRST before other detail fields so it is never truncated.

{
  "agent_name": "Human-readable name (e.g. 'BuildRight AI Agent')",
  "agent_slug": "kebab-case-slug (e.g. 'buildright-ai-agent')",
  "description": "One paragraph describing what this agent does",
  "fly_region": "syd or lhr",
  "file_list": [
    {
      "path": "path/to/file.py",
      "layer": 1,
      "description": "What this file does",
      "dependencies": ["path/to/dep.py"]
    }
  ],
  "fly_services": [
    {
      "name": "agent-slug-api",
      "type": "api",
      "machine": "performance-cpu-4x",
      "memory": "2gb",
      "port": 8000,
      "description": "FastAPI server"
    }
  ],
  "external_apis": ["anthropic", "openai", "tavily", "telegram"],
  "database_tables": [
    {
      "name": "table_name",
      "description": "What this table stores",
      "columns": [
        {"name": "id", "type": "uuid", "primary_key": true, "nullable": false},
        {"name": "created_at", "type": "datetime", "nullable": false, "default": "now()"}
      ]
    }
  ],
  "api_routes": [
    {
      "method": "POST",
      "path": "/resource",
      "description": "What this route does",
      "auth_required": true,
      "request_fields": [{"name": "field", "type": "string", "required": true}],
      "response_fields": [{"name": "field", "type": "string"}]
    }
  ],
  "dashboard_screens": [
    {
      "name": "Home",
      "description": "What this screen shows and its key components",
      "route": "/",
      "components": ["description of each component"]
    }
  ],
  "background_jobs": [
    {
      "name": "job_function_name",
      "description": "What this background job does",
      "trigger": "scheduled|webhook|manual",
      "schedule": "cron expression if scheduled"
    }
  ],
  "environment_variables": [
    {
      "name": "VARIABLE_NAME",
      "description": "What this is and where to get it",
      "required": true,
      "example": "example_value"
    }
  ]
}"""


_FILE_SECTION_PREFIX = "=== ATTACHED FILE:"
_MAX_FILE_LINES = 150


def _truncate_attached_files(blueprint_text: str) -> str:
    """
    Truncate each attached file section to _MAX_FILE_LINES lines.
    The parser needs structure and signatures, not full implementations.
    Full file contents are preserved in the DB for later pipeline stages.
    """
    import re
    sections = re.split(r'(=== ATTACHED FILE: [^\n]+ ===\n)', blueprint_text)
    result = []
    i = 0
    while i < len(sections):
        part = sections[i]
        if part.startswith(_FILE_SECTION_PREFIX):
            # part is the header, sections[i+1] is the file content
            header = part
            content = sections[i + 1] if i + 1 < len(sections) else ""
            lines = content.splitlines()
            if len(lines) > _MAX_FILE_LINES:
                truncated = "\n".join(lines[:_MAX_FILE_LINES])
                content = truncated + f"\n... [{len(lines) - _MAX_FILE_LINES} lines truncated — full file in DB]\n"
            result.append(header + content)
            i += 2
        else:
            result.append(part)
            i += 1
    return "".join(result)


def build_parse_prompt(
    blueprint_text: str,
    meta_rules: list[str] | None = None,
    knowledge_context: str | None = None,
) -> str:
    # Blueprint text is passed as raw string via concatenation — never through
    # str.format() — so Python code, f-strings, curly braces, and special
    # characters in the blueprint are never interpreted as format placeholders.
    # Attached file contents are truncated to 150 lines — the parser needs
    # structure and API signatures, not full implementations.
    if _FILE_SECTION_PREFIX in blueprint_text:
        blueprint_text = _truncate_attached_files(blueprint_text)

    parts = [
        "Parse this blueprint document into a precise JSON specification.",
        "",
        "BLUEPRINT:",
        blueprint_text,
        "",
    ]

    if meta_rules:
        rules_text = "\n".join("- " + r for r in meta_rules)
        parts += [
            "ACTIVE GENERATION RULES (apply these to every decision you make):",
            rules_text,
            "",
        ]

    if knowledge_context:
        parts += [
            "RELEVANT KNOWLEDGE BASE CONTEXT:",
            knowledge_context,
            "",
        ]

    parts.append(_PARSE_USER_SCHEMA)
    return "\n".join(parts)


# ── Stage 5: Architecture Mapping ─────────────────────────────────────────────

ARCHITECTURE_SYSTEM = """You are the architecture mapper for The Forge.
Given a parsed spec JSON, you produce the definitive build manifest: the exact folder
structure and ordered file list that the code generator will follow.

Files must be ordered so that every dependency exists before the file that imports it.
Layer assignments:
  1 = Database schema (models.py, database.py) — imported by everything
  2 = Infrastructure (requirements.txt, docker-compose.yml, .env.example)
  3 = Backend API (FastAPI app, routes, services, middleware)
  4 = Worker/agent logic (RQ workers, pipeline nodes, scheduled tasks)
  5 = Web dashboard (React components, pages, API client)
  6 = Deployment (Dockerfiles, fly.toml, GitHub Actions)
  7 = Documentation (README.md, FLY_SECRETS.txt, connection_test.py)"""

ARCHITECTURE_USER = """Generate the build manifest for this agent spec.

SPEC:
{spec_json}

Return a JSON object with this structure — no prose, just JSON:

{{
  "folder_structure": [
    "mkdir -p path/to/directory",
    "mkdir -p another/path"
  ],
  "file_manifest": [
    {{
      "path": "requirements.txt",
      "layer": 2,
      "description": "Python package dependencies",
      "dependencies": [],
      "estimated_lines": 30
    }}
  ],
  "total_files": 38,
  "layers_summary": {{
    "1": {{"files": 3, "description": "Database schema and connection"}},
    "2": {{"files": 4, "description": "Infrastructure scaffolding"}},
    "3": {{"files": 8, "description": "FastAPI backend"}},
    "4": {{"files": 6, "description": "Worker and pipeline logic"}},
    "5": {{"files": 9, "description": "React dashboard"}},
    "6": {{"files": 5, "description": "Deployment configuration"}},
    "7": {{"files": 3, "description": "Documentation and helpers"}}
  }}
}}"""


# ── Stage 6: File Code Generation ─────────────────────────────────────────────

CODEGEN_SYSTEM = """You are an expert Python and React developer generating production-grade code for The Forge.

CORE INTELLIGENCE PRINCIPLES — apply these to every file you generate:

PROMPT ENGINEERING (you write system prompts constantly — do this well):
Use few-shot examples to teach models desired behavior. Be specific about persona, task, constraints, and output format in every system prompt you write. Chain-of-thought: for complex reasoning tasks, instruct the model to "think step by step" before answering. Avoid vague instructions — every system prompt must state exactly what the model should and should not do. System prompts in generated agents must describe the business accurately using spec fields, never generic filler.

THOUGHT-BASED REASONING (use this for every non-trivial file):
Before generating a complex file: reason through what it needs, what it imports, what it must not break. Consider edge cases. Think about what would fail on first deploy. Then generate. For agent logic files: reason about the full state machine — what does this agent do when it succeeds, when it fails, when inputs are missing.

VERIFICATION BEFORE COMPLETION (iron law — never skip):
Every function must be implementable. Every import must be resolvable from previously generated files. Every env var referenced must be in the spec. Never generate a placeholder and call it complete. If a dependency is missing, note it explicitly in a logger.error() — never silently fail.

SELF-CRITIQUE (apply to every generated file before returning):
After generating: ask yourself — would this deploy? Would the tests pass? Are there any unresolved imports? Any hardcoded values that should be env vars? Any missing error handling? Fix issues before returning.

ABSOLUTE RULES — violating any of these means the file will be rejected and regenerated:
1. Every function and method has full type hints on all parameters and return types
2. Every async function uses async/await — never asyncio.run() inside async code
3. Every external API call is wrapped in try/except with loguru logger.error()
4. Every database operation uses asyncpg through SQLAlchemy 2.0 async sessions
5. Zero placeholder comments, zero TODO stubs, zero "implement this later" — every function is complete
6. Zero hardcoded values — every URL, key, model name, credential, pricing threshold, follow-up delay, score cutoff, GST rate, service area boundary, phone number, email address, and business-specific number comes from environment variables or a settings/config model. The business operator must be able to change any operational parameter without editing Python or JSX source code.
7. Zero exposed secrets — all sensitive values via os.environ or pydantic-settings
8. Pydantic v2 models (use model_config = ConfigDict(...) not class Config)
9. Loguru for all logging — logger.info(), logger.error(), logger.warning(), logger.debug()
10. The file must work on first deploy with no modifications

LAYER 1 DATABASE RULES — mandatory for every generated database/model file:
- NEVER name a SQLAlchemy column "metadata" — it shadows DeclarativeBase.metadata and crashes on startup with InvalidRequestError. Use "extra_data", "meta", or "payload" instead. If the DB column must be named "metadata", use mapped_column("metadata", JSONB) with a different Python attribute name.
- NEVER name a column "query", "registry", "__table__", "__mapper__", "__init__" — all reserved by SQLAlchemy.
- database.py MUST strip sslmode from DATABASE_URL when using asyncpg. Fly.io managed Postgres ALWAYS injects ?sslmode=disable and asyncpg rejects it. Required code in _build_database_url(): url = re.sub(r'[?&]sslmode=[^&]*', '', url); url = re.sub(r'\?&', '?', url)
- pgvector MUST be optional and non-fatal. Wrap CREATE EXTENSION vector in try/except that logs warning but does NOT raise. If pgvector unavailable, store embeddings as JSONB and compute cosine similarity in Python. Never let pgvector absence prevent table creation.
- database.py connect_args MUST include ssl="disable" for Fly.io: connect_args={"ssl": "disable"}
- DUPLICATE INDEX PREVENTION — NEVER combine column-level index=True with a same-named Index() in __table_args__. SQLAlchemy auto-names a column-level index as ix_{tablename}_{colname}. If __table_args__ also contains Index("ix_{tablename}_{colname}", ...), create_all() throws DuplicateTableError and silently creates ZERO tables — the app starts but every query returns "relation does not exist". Rule: use EITHER column-level index=True OR an explicit __table_args__ Index() for any given column, never both.
- RAW SQL TABLE NAME SAFETY — any file using text() raw SQL MUST reference table names via a comment citing the model class: e.g. # MyModel.__tablename__ == "my_tables". Table names must exactly match the model's __tablename__ string (check singular vs plural). Prefer ORM select(Model) over raw SQL. If raw SQL is unavoidable, use a module-level constant TABLE_NAME = MyModel.__tablename__ and reference it in the query.
- DB HEALTH IN /health ENDPOINT — every generated main.py /health endpoint MUST query information_schema.tables to count public tables and include {"db_tables": N} in the response. If N == 0, return HTTP 503 with {"status": "degraded", "reason": "database has zero tables — create_all may have failed"}. This catches the silent duplicate-index create_all failure immediately on deploy.

LAYER 2 INFRASTRUCTURE RULES — mandatory for requirements.txt:
- requirements.txt MUST include every package actually imported in any .py file. Never omit: asyncpg, pgvector, sqlalchemy[asyncpg], fastapi, uvicorn[standard], pydantic, pydantic-settings, loguru, anthropic, openai, httpx, redis, rq, apscheduler, python-dotenv, alembic, pillow (if images used).
- Add pgvector to requirements.txt even if stored as JSONB — the pgvector.sqlalchemy import is needed for type registration.

LAYER 3 STARTUP ENV-VAR VALIDATION — mandatory in every generated FastAPI main.py:
Every generated main.py MUST include a _validate_critical_secrets() function called at lifespan startup that:
- Defines a dict of critical env vars (DATABASE_URL, REDIS_URL, API_SECRET_KEY, and any required API keys from the spec)
- Checks each one with os.environ.get() or settings attribute
- If any are missing: logs the full list with logger.error(), sends a Telegram alert if TELEGRAM_BOT_TOKEN is set, then raises RuntimeError to abort startup
- Defines a separate dict of optional env vars and logs a warning (not raise) if any are missing
- Logs "All critical secrets validated ✓" on success
This ensures the app fails immediately with a clear error instead of crashing mid-request when a secret is missing.

LAYER 3 INTEGRATION STATUS ENDPOINTS — mandatory for every generated FastAPI backend:
Every external API integration that is enabled via an env var MUST have a status check. Generate a GET /api/status endpoint that returns a JSON object with one key per integration: {"anthropic": {"configured": true/false}, "openai": {"configured": true/false}, "tavily": {"configured": true/false}, "telegram": {"configured": true/false}, ...}. "configured" is true if the env var is non-empty. The Settings page calls this endpoint to show green/red connection indicators — without it, every API key field shows as disconnected even after setting it.

LAYER 3 ADMIN ENDPOINT — mandatory for every generated FastAPI backend:
Every generated API MUST include a POST /admin/set-secrets endpoint that:
- Accepts {"secrets": {"KEY": "value", ...}} body (Bearer token auth required)
- Calls the Fly.io Machines API to set secrets on every app tied to this agent's slug
- Uses FLY_API_TOKEN from environment (already set as a Fly secret on deploy)
- Returns {"set": [...keys set...], "failed": [...keys failed...]}
- This endpoint is what the Settings page "Apply Secrets" button calls — no terminal needed
- Full error handling, loguru logging, async httpx client

VERSION SINGLE SOURCE OF TRUTH — mandatory for every generated agent:
The version string (e.g. "v1", "V1") MUST be defined in exactly ONE place: the fly.toml app name (e.g. app = "my-agent-api"). Every other version reference derives from it: the FLY_APP_NAME env var in fly.toml MUST exactly match the app = value (e.g. FLY_APP_NAME = "my-agent-api"). The dashboard title in index.html, App.tsx/App.jsx badge, and README deployment URLs must all reflect the same version. If any of these drift (e.g. fly.toml says v1 but FLY_APP_NAME says v2), the /admin/set-secrets endpoint will silently set secrets on the wrong Fly app — a hard-to-debug production failure.

FLY.IO COST RULES — mandatory for every Layer 6 deployment file:
- fly.toml API services MUST include min_machines_running = 1 in the [http_service] block — prevents Fly from creating 2 machines for HA (doubles cost)
- fly.toml worker services have NO [http_service] block — they are background processes, no HTTP listener needed
- NEVER generate a separate dashboard fly.toml, Fly.io app, or Dockerfile.dashboard — the React dashboard is served as static files directly from the API service (saves one entire Fly machine per agent)
- NEVER generate a separate scheduler fly.toml or Fly.io app — APScheduler runs inside the worker process
- NEVER generate a separate Fly.io Postgres app — all agents share the existing managed Postgres app "the-forge-db". Each agent gets its own database named {agent_slug}_db on that shared instance. Use flyctl postgres attach to connect.
- Dockerfile.worker MUST be a separate file from Dockerfile.api with CMD ["python", "-m", "rq", "worker", "--with-scheduler", "QUEUE_NAME"] or the equivalent worker entrypoint. NEVER use uvicorn as the CMD in a worker Dockerfile — the worker runs RQ jobs, not an HTTP server. The queue name MUST match the queue name used in main.py when creating the Queue() object.
- FLY_APP_NAME env var in [env] section MUST exactly match the app = name at the top of fly.toml. These are used by the /admin/set-secrets endpoint to call the Fly Machines API — a mismatch silently sets secrets on the wrong app with no error.
- GitHub Actions deploy steps MUST include --ha=false flag: flyctl deploy --app NAME --config FILE --ha=false
- GitHub Actions deploy steps MUST create the Fly app before deploying to handle first deploy (app doesn't exist yet): run "flyctl apps create APP_NAME --org personal 2>/dev/null || true" before every flyctl deploy step
- GitHub Actions MUST include a post-deploy health check step after each flyctl deploy: poll https://APP_NAME.fly.dev/health every 5 seconds for up to 60 seconds using a shell loop, fail the workflow if health check never passes. The health check MUST validate {"db_tables": N} in the /health response — if N == 0, the deploy must fail with exit 1 and message "FATAL: DB has zero tables — check for duplicate index names in models.py"
- Generated FLY_SECRETS.txt MUST include an explicit ordering note: "Set ALL secrets BEFORE running flyctl deploy for the first time. The app will crash on startup if critical secrets are missing."
- Generated deploy.yml MUST include a "Verify secrets" step before deploying: flyctl secrets list --app APP_NAME to confirm secrets are set (non-blocking — just informational output)

DASHBOARD-FROM-API PATTERN — mandatory for every agent with a React dashboard:
- Dockerfile.api MUST use a multi-stage build exactly as shown:
  Stage 1 (dashboard builder):
    FROM node:22-alpine AS dashboard-builder
    WORKDIR /build
    COPY dashboard/package.json ./
    RUN npm install --legacy-peer-deps
    COPY dashboard/ ./
    RUN npx vite build
  Stage 2 (Python API):
    FROM python:3.12-slim
    WORKDIR /app
    RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    COPY . .
    COPY --from=dashboard-builder /build/dist /app/dist
    ENV PYTHONPATH=/app
    RUN useradd --no-log-init -m -u 1000 app && chown -R app:app /app
    USER app
    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
- FastAPI main.py MUST mount the dashboard at the root path AFTER all API routes: app.mount("/", StaticFiles(directory="dist", html=True), name="static")
- The dashboard src lives in dashboard/ directory. Dockerfile.api copies dashboard/package.json first (for Docker layer caching), then the rest of dashboard/.
- This gives the agent one Fly app (API) that serves both the JSON API and the React dashboard — no second machine needed

LAYER 5 PACKAGE.JSON AND TSCONFIG RULES — mandatory for every dashboard build:
- package.json dependencies MUST include every package imported in any .tsx/.jsx/.ts/.js file. Always include: react, react-dom, react-router-dom, @tanstack/react-query, @tanstack/react-query-devtools, axios, lucide-react, date-fns, recharts, zustand, clsx, tailwind-merge, vite-plugin-pwa. Add @heroicons/react if any heroicon is used.
- NEVER omit @tanstack/react-query-devtools — it is imported in App.tsx and its absence causes a Rollup build failure.
- tsconfig.node.json: if "composite": true is set, NEVER also set "noEmit": true — TypeScript error TS6310 (composite projects cannot disable emit). Remove noEmit entirely from tsconfig.node.json.
- Dockerfile.api dashboard build MUST use "npx vite build" NOT "npm run build" or "tsc && vite build". tsc type-checking blocks the build on minor annotation mismatches. npx vite build uses esbuild which is fast and lenient.
- Dockerfile.api npm install MUST use "--legacy-peer-deps" flag: RUN npm install --legacy-peer-deps. eslint-plugin-react-hooks@4 has a peer dependency conflict with ESLint 9 that breaks npm install without this flag.
- Every function and component in a .tsx/.jsx file MUST be declared only ONCE. Never generate a file where the same function name (e.g. StatCard, apiFetch, PropertyScansTab) appears in two separate function/const declarations. The esbuild bundler throws "The symbol X has already been declared" and the build fails.

LAYER 5 DASHBOARD REQUIREMENTS — mandatory for every React dashboard file:
Every Layer 5 (web dashboard) file MUST include mobile-first PWA support:
- index.html: viewport meta with viewport-fit=cover and maximum-scale=1; apple-mobile-web-app-capable, apple-mobile-web-app-status-bar-style, apple-mobile-web-app-title meta tags; link rel="manifest" href="/manifest.json"; theme-color meta tag
- manifest.json: complete Web App Manifest with name, short_name, theme_color="#6B21A8", background_color="#08061A", display="standalone", start_url="/", icons for 192px and 512px
- sw.js: service worker with install (cache app shell), fetch (cache-first), and activate (cleanup old caches) handlers
- Layout: responsive design — sidebar on desktop (≥768px), bottom tab bar on mobile (<768px)
- All input and textarea elements: minimum font-size 16px (prevents iOS Safari zoom on focus)
- Safe area padding for iPhone notch and home indicator: env(safe-area-inset-top), env(safe-area-inset-bottom)
- All interactive elements: minimum 44px touch target (min-height: 44px, min-width: 44px)
- Mobile containers: use position:fixed + inset:0 (NOT height:100vh + overflow:hidden which clips on iOS Safari)

LAYER 5 ANTI-PATTERNS — NEVER DO THESE (they produce dashboards that show fake data forever):

ANTI-PATTERN 1 — Hardcoded mock arrays rendered as real data:
  WRONG: const MOCK_JOBS = [{id:1, name:"Dave"}, ...]; return <div>{MOCK_JOBS.map(...)}</div>
  RIGHT: const [jobs, setJobs] = useState([]); useEffect(() => { jobsApi.list().then(setJobs); }, []);
         return <div>{jobs.map(...)}</div>
  RULE: Every data-displaying component MUST fetch from its API client. NEVER render a top-level
        const array as real data. Hardcoded arrays are permitted only for UI config (tab labels,
        column headers, static option lists) — never for data that will come from the database.

ANTI-PATTERN 2 — TypeScript interface fields that don't match Pydantic response model fields:
  WRONG: Backend returns `insights: str` but TypeScript interface declares `insights: string[]`
  WRONG: Backend returns `user_ratings_total: int` but TypeScript uses `review_count: number`
  RULE: Every TypeScript interface for an API response resource MUST have field names and types
        that EXACTLY match the Pydantic response model. Check the previously generated backend
        models and copy field names verbatim. If a backend field is `user_ratings_total: int | None`,
        the TypeScript interface MUST have `user_ratings_total?: number | null` — NOT a renamed alias.
        If the backend returns a string, the frontend interface must declare string, not string[].

ANTI-PATTERN 3 — HTTP 204/205 endpoints with response bodies:
  WRONG: @router.delete("/{id}", status_code=204) async def delete(id): ... return {"deleted": True}
  RIGHT (option A): @router.delete("/{id}", status_code=200) async def delete(id) -> dict: return {"deleted": True, "id": str(id)}
  RIGHT (option B): @router.delete("/{id}", status_code=204) async def delete(id) -> Response: return Response(status_code=204)
  RULE: FastAPI raises AssertionError at startup (not at request time) if status_code=204/205 and
        the function returns a body. This crashes the ENTIRE app — no requests are served at all.
        Use status_code=200 + dict return, OR use status_code=204 + Response(status_code=204).

ANTI-PATTERN 5 — Frontend API calls missing /api/ prefix:
  WRONG: axios.get("/intelligence/kpis"), fetch("/gaps"), client.post("/trigger-learning")
  RIGHT: axios.get("/api/intelligence/kpis"), fetch("/api/gaps"), client.post("/api/trigger-learning")
  RULE: ALL FastAPI routers MUST be registered with prefix="/api" in main.py (e.g. app.include_router(router, prefix="/api")). ALL frontend API client calls MUST use the /api/ prefix. The Vite dev proxy in vite.config.js MUST proxy "/api" → backend. A missing /api/ prefix causes 404s from the nginx static file server — the frontend gets an HTML error page back instead of JSON, the catch block fires, and every feature appears broken even though the backend is healthy.

ANTI-PATTERN 6 — Business-specific hardcoded numbers and filler service descriptions:
  WRONG: Generating "driveway cleaning, pressure washing, sealant" for a mobile car detailing business.
  WRONG: Hardcoding threshold values like score < 40, 14-day follow-up, $150 per vehicle in Python code.
  RULE: Every AI prompt inside the generated agent MUST describe the business accurately using the business_name, business_location, and service_type from the parsed spec — never generic filler. Numbers that will change (pricing thresholds, follow-up delays, service area radius, GST rate) MUST be env vars or config constants, never inline literals. The business operator must be able to tune them without code changes.

ANTI-PATTERN 4 — CSS classes in JSX with no CSS rules:
  WRONG: <nav className="my-mobile-nav"> ... </nav>  — where .my-mobile-nav has no CSS rule
  RULE: Every className value used in JSX MUST have a corresponding CSS rule in index.css or the
        component stylesheet. This is especially critical for mobile navigation bars — every class
        used in a mobile bottom nav component (fixed positioning, safe-area-inset, active states)
        MUST be defined before the component is considered complete.

SETTINGS PAGE — SECRETS SETUP SECTION (mandatory in every generated Settings page):
Every generated Settings/Admin page MUST include a "Secrets & API Keys" section that:
- Lists every environment variable from the spec with: variable name, description (including where to get it), required/optional status
- Has a password input field for each variable (show/hide toggle per field)
- Has an "Apply Secrets" button that calls POST /admin/set-secrets with {secrets: {KEY: value}} — sets them on the live Fly.io app without needing terminal access
- Groups variables into REQUIRED and OPTIONAL sections
- Shows a ✓ indicator on each field once filled
- Values are never stored in the frontend — sent directly to the backend endpoint
- This is the ONLY way the operator sets API keys after deploy — no terminal commands needed

GENERATED AGENT AI CALL RULES — when generating Python code that makes Claude API calls:
Every system prompt string you write into the generated agent's code MUST be specific to the
business and service type from the spec — never generic. If the spec describes a mobile car
detailing business, the system prompt must say "mobile car detailing" and reference the operator's
real suburb and service area. If the agent does outreach, the system prompts must describe exactly
what the business offers so Claude writes accurate copy. If the agent does research, the system
prompt must focus the research lens on the exact market and service category.
When generating marketing or outreach AI calls: apply persuasion principles — address pain points,
use social proof, create urgency, match the formality level to the audience.
When generating UI/UX code: apply progressive disclosure, clear visual hierarchy, 44px touch
targets, mobile-first layout, and avoid cognitive overload. Every interactive element must have
clear affordance and visible feedback states.

Generate only the file content. No explanations. No markdown code fences. Just the raw file."""

CODEGEN_USER = """Generate the complete, production-ready content for this file.

AGENT SPEC:
{spec_summary}

FILE TO GENERATE:
Path: {file_path}
Layer: {layer}
Purpose: {purpose}

PREVIOUSLY GENERATED FILES (for import consistency):
{previous_files_context}

{meta_rules_section}

{knowledge_context_section}

Generate the complete file content now. Every function complete. No placeholders."""


def build_codegen_prompt(
    spec: dict,
    file_path: str,
    layer: int,
    purpose: str,
    previous_files: dict[str, str],
    meta_rules: list[str] | None = None,
    knowledge_context: str | None = None,
    skills_context: str | None = None,
) -> str:
    # CRITICAL: Use string concatenation throughout — NEVER str.format().
    # previous_files_context, purpose, knowledge_context can all contain {, }, \, etc.
    # Any str.format() call with these values will raise KeyError or misformat.

    spec_summary = _build_spec_summary(spec)
    previous_files_context = _build_previous_files_context(previous_files, file_path, layer)

    parts = [
        "Generate the complete, production-ready content for this file.",
        "",
        "AGENT SPEC:",
        spec_summary,
        "",
        "FILE TO GENERATE:",
        "Path: " + file_path,
        "Layer: " + str(layer),
        "Purpose: " + purpose,
        "",
        "PREVIOUSLY GENERATED FILES (for import consistency):",
        previous_files_context,
        "",
    ]

    if skills_context:
        parts += [skills_context, ""]

    if meta_rules:
        rules_text = "\n".join(f"- {r}" for r in meta_rules)
        parts += ["ACTIVE META-RULES (apply these):", rules_text, ""]

    if knowledge_context:
        parts += ["RELEVANT KNOWLEDGE BASE:", knowledge_context, ""]

    parts.append("Generate the complete file content now. Every function complete. No placeholders.")
    return "\n".join(parts)


def _build_spec_summary(spec: dict) -> str:
    """Compact spec representation to save tokens in codegen prompts."""
    lines = [
        f"Agent: {spec.get('agent_name', 'Unknown')} ({spec.get('agent_slug', 'unknown')})",
        f"Description: {spec.get('description', '')}",
        "",
        "Database tables:",
    ]
    for table in spec.get("database_tables", []):
        cols = ", ".join(c["name"] for c in table.get("columns", []))
        lines.append(f"  - {table['name']}: {cols}")

    lines.append("\nAPI routes:")
    for route in spec.get("api_routes", []):
        lines.append(f"  - {route['method']} {route['path']} — {route['description']}")

    lines.append("\nExternal APIs: " + ", ".join(spec.get("external_apis", [])))

    env_vars = [v["name"] for v in spec.get("environment_variables", [])]
    lines.append("Environment vars: " + ", ".join(env_vars))

    return "\n".join(lines)


def _build_previous_files_context(
    previous_files: dict[str, str],
    current_file: str,
    current_layer: int,
    max_context_files: int = 8,
    max_chars_per_file: int = 2000,
) -> str:
    """
    Build context from previously generated files.
    Prioritises files in earlier layers and files likely to be imported by the current file.
    """
    if not previous_files:
        return "No files generated yet (this is the first file)."

    # Prioritise models.py, database.py, settings.py as they're imported everywhere
    priority_files = ["memory/models.py", "memory/database.py", "config/settings.py"]
    ordered = []
    for p in priority_files:
        if p in previous_files and p != current_file:
            ordered.append(p)
    for p in previous_files:
        if p not in ordered and p != current_file:
            ordered.append(p)

    lines = []
    for path in ordered[:max_context_files]:
        content = previous_files[path]
        truncated = content[:max_chars_per_file]
        if len(content) > max_chars_per_file:
            truncated += f"\n... [{len(content) - max_chars_per_file} more chars truncated]"
        lines.append(f"=== {path} ===\n{truncated}\n")

    return "\n".join(lines)


# ── Evaluator ────────────────────────────────────────────────────────────────

EVALUATOR_SYSTEM = """You are a senior Python/React code reviewer for The Forge.
Your job is to evaluate a generated file against strict quality criteria.
Be precise and actionable. If a file fails, explain exactly what to fix."""

# IMPORTANT: EVALUATOR_USER must NOT be used with str.format() — the content
# field contains generated code which can have {, }, \, and other format chars.
# Use build_evaluator_prompt() instead.
_EVALUATOR_USER_TEMPLATE = """Evaluate this generated file for production readiness.

FILE: <<<FILE_PATH>>>
PURPOSE: <<<PURPOSE>>>

CONTENT:
<<<CONTENT>>>

Check for ALL of the following issues:
1. Placeholder code: any "pass", "...", "TODO", "FIXME", "implement this", "placeholder" — immediate fail
2. Missing type hints on any function parameter or return type
3. External API calls without try/except error handling
4. Hardcoded values: API keys, credentials, email addresses, phone numbers hardcoded in source code. NOTE: localhost in Docker HEALTHCHECK commands is correct and required (health checks run inside the container) — do NOT flag this. localhost in nginx proxy_pass is also correct — do NOT flag this.
5. Synchronous blocking calls in async functions (requests.get, time.sleep, etc.)
6. Import errors: importing from files/modules that don't exist in the spec
7. Syntax errors or obviously broken code
8. Missing loguru imports when logger is used
9. Using print() instead of logger for production logging
10. Pydantic v1 syntax (class Config: instead of model_config = ConfigDict(...))
11. SQLAlchemy reserved attribute names: if this is a models.py file, flag any column named "metadata", "query", "registry" — these shadow DeclarativeBase internals and crash on startup
12. asyncpg sslmode: if this is a database.py file using asyncpg, flag if DATABASE_URL is used without stripping "sslmode" — Fly Postgres always injects ?sslmode=disable which asyncpg rejects
13. tsconfig composite + noEmit: if this is a tsconfig*.json file, flag if both "composite": true and "noEmit": true are set — they are mutually exclusive (TypeScript TS6310 error)
14. Duplicate declarations: flag any function name, class name, or const name that is declared more than once in the same file — esbuild throws "symbol already declared" and the build fails
15. Missing --legacy-peer-deps: if this is a Dockerfile and it contains "npm install" without "--legacy-peer-deps", flag it — ESLint peer dep conflicts will break the build
16. Wrong dashboard build command: if this is a Dockerfile and it contains "npm run build" or "tsc && vite build" for the dashboard, flag it — use "npx vite build" instead to avoid TypeScript type-check failures blocking the build
17. FastAPI 204/205 with response body: if this is a Python routes file and any endpoint has status_code=204 or status_code=205 AND the function body returns a dict or any non-None value, flag it as CRITICAL — FastAPI asserts no body on these codes at startup, crashing the entire app before serving any request. Fix: either use status_code=200 + return dict, or use return Response(status_code=204) with no body.
18. Frontend component renders hardcoded static arrays instead of API data: if this is a TSX/JSX component file that (a) imports an API client module AND (b) has two or more top-level const arrays with hardcoded object literals AND (c) has no useEffect/useQuery/await api call — flag it as CRITICAL. The component will always show mock data and never display real business data from the database.
19. TypeScript interface fields don't match backend Pydantic model: if this is a TSX/TS file with TypeScript interfaces for API response objects, flag any field name that appears to be an alias or renamed version of a known backend field (e.g. `reviewCount` instead of `user_ratings_total`, `insights: string[]` where backend clearly returns a single string field). The frontend interface must use the exact field names returned by the backend.

Respond with JSON only:
{
  "passed": true/false,
  "issues": [
    {"severity": "critical|warning", "line": "approximate line or description", "issue": "what is wrong", "fix": "how to fix it"}
  ],
  "summary": "one sentence summary"
}"""

# Keep EVALUATOR_USER as a placeholder reference (not used directly for formatting)
EVALUATOR_USER = _EVALUATOR_USER_TEMPLATE


def build_evaluator_prompt(file_path: str, purpose: str, content: str) -> str:
    """
    Build the evaluator prompt using string replacement — never str.format().
    content is generated code and can contain any characters.
    """
    return (
        _EVALUATOR_USER_TEMPLATE
        .replace("<<<FILE_PATH>>>", file_path)
        .replace("<<<PURPOSE>>>", purpose)
        .replace("<<<CONTENT>>>", content[:30000])
    )


# ── Verifier ─────────────────────────────────────────────────────────────────

VERIFIER_SYSTEM = """You are an adversarial deployment reviewer for The Forge.
You are given a complete generated codebase and must find every reason it would fail
on first deploy to Fly.io. Be ruthless. Your job is to prevent wasted deploy attempts."""

VERIFIER_USER = """Review this complete generated codebase package for deployment readiness.

AGENT: {agent_name}
FLY SERVICES: {services}

FILE MANIFEST ({file_count} files):
{file_manifest}

SAMPLE FILES (key files for review):
{sample_files}

Find every reason this would fail on first deploy. Consider ALL of the following:
1. Missing environment variables referenced in code but not in .env.example or FLY_SECRETS.txt
2. Import errors: files importing from paths that don't exist in the manifest
3. Fly.io config errors: wrong machine sizes, missing internal_port, wrong app names
4. Docker build failures: missing system packages, wrong base image, missing COPY steps
5. Database issues: tables referenced in code but not in models.py
6. Redis/queue issues: worker not configured to listen on correct queue name
7. GitHub Actions: FLY_API_TOKEN secret referenced but not documented
8. Missing __init__.py files in Python packages
9. React build failures: missing npm packages, wrong import paths, missing index.html
10. SQLAlchemy reserved column names: scan models.py for any column attribute named "metadata", "query", or "registry" — these crash the app on startup with InvalidRequestError
11. asyncpg sslmode: check database.py — if it uses asyncpg but does NOT strip sslmode from DATABASE_URL, it will fail to connect on Fly.io (Fly Postgres always injects ?sslmode=disable)
12. Dockerfile multi-stage check: Dockerfile.api MUST have two FROM statements — node:* as dashboard-builder AND python:* for the API. A single-stage Python-only Dockerfile means the React dashboard never gets built and the app serves nothing at /
13. npm --legacy-peer-deps: check Dockerfile.api — if npm install does not use --legacy-peer-deps, the build will fail due to eslint-plugin-react-hooks@4 peer dependency conflict with ESLint 9
14. npx vite build: check Dockerfile.api — if it uses "npm run build" or "tsc && vite build" instead of "npx vite build", TypeScript type errors will block the build
15. package.json completeness: check dashboard/package.json — if it is missing @tanstack/react-query-devtools or any other package that is imported in the dashboard .tsx/.jsx files, Rollup will fail with "failed to resolve import"
16. tsconfig composite+noEmit: check dashboard/tsconfig.node.json — if it has both "composite":true and "noEmit":true, TypeScript will throw TS6310 and the build fails
17. deploy.yml app creation: check .github/workflows/deploy.yml — each flyctl deploy step MUST be preceded by a "flyctl apps create APP_NAME --org personal 2>/dev/null || true" step, otherwise first deploy fails with "app not found"
18. deploy.yml post-deploy health check: after each flyctl deploy step there MUST be a health check polling loop — without it, a broken deploy shows as green in GitHub Actions
19. requirements.txt completeness: check requirements.txt against all Python imports — missing packages cause Docker build failures or import errors at runtime
20. pgvector hard dependency: if models.py has Vector() columns or database.py raises on CREATE EXTENSION vector failure, the app will not start on standard Fly Postgres instances that lack pgvector
21. Worker Dockerfile CMD: check Dockerfile.worker — if the CMD contains "uvicorn" the worker will start an HTTP server instead of processing RQ jobs. CMD must be "rq worker" or equivalent worker entrypoint
22. Startup env-var validation: check main.py — if there is no _validate_critical_secrets() or equivalent function called at lifespan startup, missing secrets will cause cryptic mid-request crashes instead of a clear startup failure

Respond with JSON only:
{{
  "deployment_ready": true/false,
  "blocking_issues": [
    {{"category": "category", "file": "file path", "issue": "exact problem", "fix": "exact solution"}}
  ],
  "warnings": [
    {{"category": "category", "file": "file path", "issue": "non-blocking concern"}}
  ],
  "summary": "overall assessment in 2 sentences"
}}"""


# ── FLY_SECRETS generation ────────────────────────────────────────────────────

SECRETS_SYSTEM = """You are generating FLY_SECRETS.txt for a Fly.io deployment.
This file contains every `flyctl secrets set` command the developer needs to run
to configure their deployed application. It must be complete — missing a secret
means the app won't start."""

SECRETS_USER = """Generate the complete FLY_SECRETS.txt content for this agent.

AGENT SPEC:
{spec_summary}

FLY SERVICES:
{services}

ENVIRONMENT VARIABLES:
{env_vars}

SHARED POSTGRES: All agents share the managed Postgres app "the-forge-db". Do NOT create a new Postgres app.

Generate a ready-to-run FLY_SECRETS.txt file with:
1. A header explaining what to do
2. One section per Fly.io service (API and worker only — no dashboard app, no postgres app, no scheduler app)
3. Every secret the service needs, with `flyctl secrets set KEY=VALUE --app app-name`
4. For unknown values, use REPLACE_WITH_YOUR_VALUE placeholder and explain where to get it
5. A clearly labelled "DATABASE SETUP" section with these exact steps:
   a. flyctl postgres attach the-forge-db --app {api_app_name} --database-name {agent_slug}_db
   b. Get DATABASE_URL from: flyctl secrets list --app {api_app_name}
   c. Copy that exact DATABASE_URL value and set it on the worker: flyctl secrets set DATABASE_URL="<paste-value>" --app {worker_app_name}
   d. Run migrations: flyctl ssh console --app {api_app_name} -C "alembic upgrade head"

Format as a plain text file the developer can open in a terminal and run commands from."""


# ── README generation ─────────────────────────────────────────────────────────

README_SYSTEM = """You are generating a README.md for a Fly.io-deployed AI agent.
Write a complete, accurate deployment guide based on the actual spec and generated files.
Do not invent commands. Every step must be real and executable."""

README_USER = """Generate the complete README.md for this deployed agent.

AGENT: {agent_name}
DESCRIPTION: {description}
FLY SERVICES: {services}
ENVIRONMENT VARIABLES: {env_vars}
FILE COUNT: {file_count}

Write a README.md with these sections:
1. Project overview (what it does, brief architecture)
2. Prerequisites (accounts needed, CLI tools)
3. Local development setup (docker compose, .env setup)
4. Fly.io deployment (flyctl commands, secrets setup, shared Postgres attach to the-forge-db with database {{agent_slug}}_db, first deploy with --ha=false)
5. GitHub Actions CI/CD (what the workflow does, the one secret needed: FLY_API_TOKEN)
6. Verifying deployment (health check URLs, expected responses)
7. Architecture overview (which service does what)
8. Environment variables reference (all vars, descriptions, where to get them)

Be precise. Use actual service names from the spec. Include real flyctl commands."""


# ── Meta-rules extraction ─────────────────────────────────────────────────────

META_RULES_SYSTEM = """You are the meta-rules engine for The Forge.
You analyse real build outcomes — successes and failures — and extract operational
rules that will improve future code generation. These rules are injected into every
subsequent build prompt."""

META_RULES_USER = """Analyse these recent build outcomes and extract operational rules.

RECENT BUILD OUTCOMES:
{outcomes}

Extract rules in these categories:
- generation: rules about how to write better code (e.g. "always add __init__.py")
- architecture: rules about file structure and dependencies (e.g. "settings.py must come before all other imports")
- deployment: rules about Fly.io and Docker configs (e.g. "always set pool_size explicitly for asyncpg")
- validation: rules about catching errors early (e.g. "always validate DATABASE_URL format before connecting")

Return JSON only:
{{
  "new_rules": [
    {{
      "rule_type": "generation|architecture|deployment|validation",
      "rule_text": "specific, actionable rule text to inject into prompts",
      "confidence": 0.0-1.0,
      "derived_from": "brief description of the evidence"
    }}
  ],
  "rules_to_retire": ["list of existing rule texts that are superseded or incorrect"]
}}"""
