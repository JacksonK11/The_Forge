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

{
  "agent_name": "Human-readable name (e.g. 'BuildRight AI Agent')",
  "agent_slug": "kebab-case-slug (e.g. 'buildright-ai-agent')",
  "description": "One paragraph describing what this agent does",
  "fly_region": "syd or lhr",
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
  ],
  "file_list": [
    {
      "path": "path/to/file.py",
      "layer": 1,
      "description": "What this file does",
      "dependencies": ["path/to/dep.py"]
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

ABSOLUTE RULES — violating any of these means the file will be rejected and regenerated:
1. Every function and method has full type hints on all parameters and return types
2. Every async function uses async/await — never asyncio.run() inside async code
3. Every external API call is wrapped in try/except with loguru logger.error()
4. Every database operation uses asyncpg through SQLAlchemy 2.0 async sessions
5. Zero placeholder comments, zero TODO stubs, zero "implement this later" — every function is complete
6. Zero hardcoded values — every URL, key, model name, and credential comes from environment/settings
7. Zero exposed secrets — all sensitive values via os.environ or pydantic-settings
8. Pydantic v2 models (use model_config = ConfigDict(...) not class Config)
9. Loguru for all logging — logger.info(), logger.error(), logger.warning(), logger.debug()
10. The file must work on first deploy with no modifications

FLY.IO COST RULES — mandatory for every Layer 6 deployment file:
- fly.toml API services MUST include min_machines_running = 1 in the [http_service] block — prevents Fly from creating 2 machines for HA (doubles cost)
- fly.toml worker services have NO [http_service] block — they are background processes, no HTTP listener needed
- NEVER generate a separate dashboard fly.toml, Fly.io app, or Dockerfile.dashboard — the React dashboard is served as static files directly from the API service (saves one entire Fly machine per agent)
- NEVER generate a separate scheduler fly.toml or Fly.io app — APScheduler runs inside the worker process
- NEVER generate a separate Fly.io Postgres app — all agents share the existing managed Postgres app "the-forge-db". Each agent gets its own database named {agent_slug}_db on that shared instance. Use flyctl postgres attach to connect.
- GitHub Actions deploy steps MUST include --ha=false flag: flyctl deploy --app NAME --config FILE --ha=false

DASHBOARD-FROM-API PATTERN — mandatory for every agent with a React dashboard:
- Dockerfile.api MUST use a multi-stage build: Stage 1 builds the React dashboard (node:22-alpine), Stage 2 runs the Python API (python:3.12-alpine) and copies the built dist/ into /app/dist
- FastAPI main.py MUST mount the dashboard at the root path AFTER all API routes: app.mount("/", StaticFiles(directory="dist", html=True), name="static")
- The dashboard src lives in dashboard/ directory. Dockerfile.api copies dashboard/ into the build stage and runs npm install && npm run build
- This gives the agent one Fly app (API) that serves both the JSON API and the React dashboard — no second machine needed

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

Find every reason this would fail on first deploy. Consider:
1. Missing environment variables referenced in code but not in .env.example or FLY_SECRETS.txt
2. Import errors: files importing from paths that don't exist in the manifest
3. Fly.io config errors: wrong machine sizes, missing internal_port, wrong app names
4. Docker build failures: missing system packages, wrong base image, missing COPY steps
5. Database issues: tables referenced in code but not in models.py
6. Redis/queue issues: worker not configured to listen on correct queue name
7. GitHub Actions: FLY_API_TOKEN secret referenced but not documented
8. Missing __init__.py files in Python packages
9. React build failures: missing npm packages, wrong import paths, missing index.html

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
4. Fly.io deployment (flyctl commands, secrets setup, shared Postgres attach to the-forge-db with database {agent_slug}_db, first deploy with --ha=false)
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
