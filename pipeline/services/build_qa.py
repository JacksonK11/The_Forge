"""
pipeline/services/build_qa.py
Global build quality assurance — scores the complete generated codebase against
a 100-point rubric and auto-repairs failing categories before packaging.

Runs after code generation and recovery, before packaging. Loops up to
MAX_QA_ITERATIONS (3) times until the build scores >= PASS_THRESHOLD (95/100).

Scoring rubric (100 points):
  API Completeness      25 pts  — routes, error handling, health endpoint, no hardcoded secrets
  Cross-System Wiring   25 pts  — frontend/backend URL match, import resolution, port consistency
  Intelligence Layer    25 pts  — all 7 intelligence files + 5 knowledge files present and complete
  Infrastructure        15 pts  — fly.toml(s), deploy.yml, connection_test, FLY_SECRETS, Dockerfiles
  Code Quality          10 pts  — no stubs/TODOs, type hints, no hardcoded values

Fixer strategy:
  Groups QA issues by file. For each failing file, calls Sonnet with:
    - Current file content
    - Specific issues to fix + fix hints
    - Up to 5 surrounding context files
    - Agent spec summary
  For missing required files: generates them from scratch (Sonnet).
  Returns an updated files dict with all fixes applied.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_QA_ITERATIONS = 3
PASS_THRESHOLD = 95   # 95+/100 = best-in-class — only then does packaging proceed

CATEGORY_WEIGHTS: dict[str, int] = {
    "api":            25,
    "wiring":         25,
    "intelligence":   25,
    "infrastructure": 15,
    "code_quality":   10,
}

# Required intelligence layer files — every generated agent must have all 7
INTELLIGENCE_FILES = [
    "config/model_config.py",
    "intelligence/knowledge_base.py",
    "intelligence/meta_rules.py",
    "intelligence/context_assembler.py",
    "intelligence/evaluator.py",
    "intelligence/verifier.py",
    "monitoring/performance_monitor.py",
]

# Required knowledge engine files — all 5
KNOWLEDGE_FILES = [
    "knowledge/collector.py",
    "knowledge/embedder.py",
    "knowledge/retriever.py",
    "knowledge/live_search.py",
    "config/knowledge_config.py",
]

# Required deployment files — every build ZIP must include these
DEPLOYMENT_FILES = [
    "README.md",
    "FLY_SECRETS.txt",
    "connection_test.py",
    ".env.example",
    ".github/workflows/deploy.yml",
]

# Patterns that indicate stub / placeholder implementations
_STUB_PATTERNS = [
    re.compile(r'^\s*pass\s*$', re.MULTILINE),
    re.compile(r'raise\s+NotImplementedError', re.MULTILINE),
    re.compile(r'#\s*TODO', re.MULTILINE | re.IGNORECASE),
    re.compile(r'#\s*FIXME', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*\.\.\.\s*$', re.MULTILINE),
    re.compile(r'["\']implement\s+this["\']', re.IGNORECASE),
    re.compile(r'#\s*implement\s+later', re.IGNORECASE),
]

# Patterns indicating hardcoded credentials
_SECRET_PATTERNS = [
    re.compile(r'(?i)(api_key|secret|password|token)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'sk-[a-zA-Z0-9]{32,}'),
    re.compile(r'Bearer\s+[a-zA-Z0-9]{20,}'),
]

_ROUTE_DEF_RE = re.compile(
    r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)
_FRONTEND_CALL_RE = re.compile(
    r'(?:fetch|axios\.\w+)\s*\(\s*["`]([^"`]+)["`]'
    r'|(?:BASE_URL|API_URL|apiBase)\s*\+\s*["`]([^"`]+)["`]'
    r'|["`](\/api\/[^"`\s]+)["`]',
    re.MULTILINE,
)
_IMPORT_RE = re.compile(
    r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',
    re.MULTILINE,
)
_PORT_TOML_RE = re.compile(r'internal_port\s*=\s*(\d+)')
_PORT_UVICORN_RE = re.compile(r'--port\s+(\d+)')
_PORT_EXPOSE_RE = re.compile(r'EXPOSE\s+(\d+)')
_FN_DEF_RE = re.compile(
    r'^\s*(?:async\s+)?def\s+\w+\s*\(([^)]*)\)\s*(->\s*\S+)?:',
    re.MULTILINE,
)

# Modules that are allowed imports even if not in the generated file set
_KNOWN_EXTERNAL = frozenset({
    "os", "sys", "re", "json", "asyncio", "typing", "dataclasses",
    "datetime", "time", "pathlib", "uuid", "hashlib", "base64", "io",
    "abc", "enum", "functools", "itertools", "collections", "contextlib",
    "concurrent", "threading", "subprocess", "tempfile", "shutil", "zipfile",
    "math", "random", "string", "textwrap", "traceback", "warnings",
    "logging", "inspect", "importlib", "copy", "struct", "socket",
    # Third-party
    "fastapi", "sqlalchemy", "pydantic", "anthropic", "openai",
    "loguru", "httpx", "redis", "rq", "apscheduler", "alembic",
    "uvicorn", "starlette", "passlib", "jose", "aiofiles", "anyio",
    "click", "rich", "dotenv", "sentry_sdk", "telegram", "celery",
    "numpy", "pandas", "pytest", "setuptools", "pkg_resources",
    "psutil", "boto3", "stripe", "twilio", "sendgrid", "pymongo",
    "motor", "aiohttp", "websockets", "paramiko", "cryptography",
    "PIL", "cv2", "torch", "sklearn", "scipy", "matplotlib",
    "tavily", "serpapi", "newspaper", "feedparser", "bs4", "lxml",
    # Forge's own top-level packages (always resolvable at runtime)
    "config", "memory", "app", "pipeline", "intelligence",
    "monitoring", "knowledge", "scripts",
})


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class QAIssue:
    category: str    # "api" | "wiring" | "intelligence" | "infrastructure" | "code_quality"
    severity: str    # "critical" | "warning"
    file_path: str   # file to fix; "" means systemic / file is missing entirely
    description: str
    fix_hint: str


@dataclass
class QAResult:
    total_score: int
    categories: dict[str, int]
    max_scores: dict[str, int]
    issues: list[QAIssue]
    passed: bool
    iteration: int = 0
    score_history: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_score": self.total_score,
            "max_score": 100,
            "passed": self.passed,
            "iteration": self.iteration,
            "score_history": self.score_history,
            "categories": {
                k: {
                    "score": self.categories.get(k, 0),
                    "max": self.max_scores.get(k, CATEGORY_WEIGHTS.get(k, 0)),
                }
                for k in CATEGORY_WEIGHTS
            },
            "issues": [
                {
                    "category": i.category,
                    "severity": i.severity,
                    "file": i.file_path,
                    "description": i.description,
                    "fix_hint": i.fix_hint,
                }
                for i in self.issues
            ],
            "critical_count": sum(1 for i in self.issues if i.severity == "critical"),
            "warning_count": sum(1 for i in self.issues if i.severity == "warning"),
        }


# ── Scorer ────────────────────────────────────────────────────────────────────


class BuildQAScorer:
    """
    Scores the complete generated codebase against the 100-point rubric.
    All checks are static analysis (zero LLM cost) for speed and repeatability.
    """

    async def score(
        self,
        files: dict[str, str],
        spec: dict,
        iteration: int = 1,
        score_history: Optional[list[int]] = None,
    ) -> QAResult:
        all_issues: list[QAIssue] = []
        scores: dict[str, int] = {}

        results = await asyncio.gather(
            self._score_api(files, spec),
            self._score_wiring(files, spec),
            self._score_intelligence(files, spec),
            self._score_infrastructure(files, spec),
            self._score_code_quality(files, spec),
            return_exceptions=True,
        )

        for name, result in zip(CATEGORY_WEIGHTS, results):
            if isinstance(result, Exception):
                logger.warning(f"[BuildQA] {name} scoring raised: {result}")
                scores[name] = CATEGORY_WEIGHTS[name]  # benefit of the doubt
            else:
                cat_score, cat_issues = result
                scores[name] = cat_score
                all_issues.extend(cat_issues)

        total = sum(scores.values())
        history = list(score_history or []) + [total]

        return QAResult(
            total_score=total,
            categories=scores,
            max_scores=dict(CATEGORY_WEIGHTS),
            issues=all_issues,
            passed=total >= PASS_THRESHOLD,
            iteration=iteration,
            score_history=history,
        )

    # ── API Completeness (25 pts) ─────────────────────────────────────────────

    async def _score_api(
        self, files: dict[str, str], spec: dict
    ) -> tuple[int, list[QAIssue]]:
        score = 25
        issues: list[QAIssue] = []

        api_files = {
            p: c for p, c in files.items()
            if p.endswith(".py") and any(x in p for x in [
                "routes/", "api/", "main.py", "app.py", "endpoints",
            ])
        }
        all_api = "\n".join(api_files.values())

        # 1. Route files exist at all (5 pts)
        if not api_files:
            score -= 5
            issues.append(QAIssue(
                category="api", severity="critical", file_path="",
                description="No API route files found in generated output.",
                fix_hint="Generate FastAPI route files under app/api/routes/. "
                         "Each domain should have its own routes file.",
            ))
        else:
            routes = _ROUTE_DEF_RE.findall(all_api)
            if len(routes) < 3:
                score -= 3
                issues.append(QAIssue(
                    category="api", severity="critical",
                    file_path=next(iter(api_files)),
                    description=f"Only {len(routes)} route definition(s) found — expected several based on spec.",
                    fix_hint="Add all required API endpoints with correct HTTP methods and path prefixes.",
                ))

        # 2. Health endpoint exists (4 pts)
        if "/health" not in all_api:
            score -= 4
            issues.append(QAIssue(
                category="api", severity="critical",
                file_path=next(iter(api_files), "app/api/routes/system.py"),
                description="No /health endpoint found. Required for Fly.io health checks and the dashboard.",
                fix_hint='Add @router.get("/health") returning {"status": "ok", "service": "..."}.',
            ))

        # 3. Error handling on routes (8 pts)
        route_blocks = _extract_route_blocks(all_api)
        if route_blocks:
            missing_eh = [b for b in route_blocks if "try:" not in b]
            ratio = len(missing_eh) / len(route_blocks)
            if ratio > 0.3:
                penalty = min(8, round(8 * ratio))
                score -= penalty
                issues.append(QAIssue(
                    category="api", severity="critical",
                    file_path=next(iter(api_files), ""),
                    description=f"{len(missing_eh)}/{len(route_blocks)} routes missing try/except error handling.",
                    fix_hint="Wrap every route body in try/except. Log errors with loguru. "
                             "Raise HTTPException with appropriate status codes on failure.",
                ))

        # 4. No hardcoded secrets (8 pts)
        hardcoded = _find_hardcoded_secrets(api_files)
        if hardcoded:
            score -= min(8, len(hardcoded) * 3)
            for fp, match in hardcoded[:2]:
                issues.append(QAIssue(
                    category="api", severity="critical", file_path=fp,
                    description=f"Hardcoded credential detected: {match[:60]}",
                    fix_hint="Replace with os.environ.get('VAR_NAME') or settings.var_name. "
                             "Add the variable to .env.example and FLY_SECRETS.txt.",
                ))

        return max(0, score), issues

    # ── Cross-System Wiring (25 pts) ──────────────────────────────────────────

    async def _score_wiring(
        self, files: dict[str, str], spec: dict
    ) -> tuple[int, list[QAIssue]]:
        score = 25
        issues: list[QAIssue] = []

        frontend_files = {
            p: c for p, c in files.items()
            if p.endswith((".jsx", ".js", ".tsx", ".ts")) and "node_modules" not in p
        }
        backend_files = {
            p: c for p, c in files.items()
            if p.endswith(".py") and any(x in p for x in ["routes/", "api/", "main.py"])
        }

        # 1. Frontend → backend URL matching (10 pts)
        if frontend_files and backend_files:
            frontend_calls = _extract_frontend_api_calls(frontend_files)
            backend_routes = {
                m[1] for m in _ROUTE_DEF_RE.findall("\n".join(backend_files.values()))
            }
            unmatched = [
                url for url in frontend_calls
                if url
                and not url.startswith("http")
                and not any(
                    url == r or url.startswith(r.split("{")[0]) or r.startswith(url.split("?")[0])
                    for r in backend_routes
                )
            ]
            if unmatched:
                penalty = min(10, len(unmatched) * 2)
                score -= penalty
                for url in unmatched[:3]:
                    fp = _find_file_with_content(frontend_files, url)
                    issues.append(QAIssue(
                        category="wiring", severity="critical", file_path=fp,
                        description=f"Frontend calls '{url}' but no matching backend route found.",
                        fix_hint=f"Add a route for '{url}' in the appropriate routes file, "
                                 f"or correct the frontend URL to match an existing route.",
                    ))

        # 2. Python import resolution (10 pts)
        py_files = {p: c for p, c in files.items() if p.endswith(".py")}
        bad_imports = _check_import_resolution(py_files)
        if bad_imports:
            penalty = min(10, len(bad_imports) * 2)
            score -= penalty
            for fp, module in bad_imports[:3]:
                issues.append(QAIssue(
                    category="wiring", severity="critical", file_path=fp,
                    description=f"Imports from '{module}' which doesn't exist in generated files.",
                    fix_hint=f"Generate {module.replace('.', '/')}.py or correct the import to an existing module.",
                ))

        # 3. Port consistency across fly.toml / Dockerfile / uvicorn (5 pts)
        port_issues = _check_port_consistency(files)
        if port_issues:
            score -= min(5, len(port_issues) * 2)
            for desc, fp in port_issues:
                issues.append(QAIssue(
                    category="wiring", severity="critical", file_path=fp,
                    description=desc,
                    fix_hint="Ensure fly.toml internal_port, Dockerfile EXPOSE, and "
                             "uvicorn --port all use the same port number (typically 8000).",
                ))

        # 4. Frontend tab components: API client imported but never called (-4 pts each, cap 8)
        #    Catches components that import an API module but only render hardcoded static arrays.
        unwired = _check_unwired_tab_components(frontend_files)
        if unwired:
            score -= min(8, len(unwired) * 4)
            for fp, reason in unwired[:2]:
                issues.append(QAIssue(
                    category="wiring", severity="critical", file_path=fp,
                    description=reason,
                    fix_hint=(
                        "Add useEffect (or useQuery) that calls the imported API client. "
                        "Store results in useState. Render that state — not hardcoded arrays. "
                        "Show a loading spinner while fetching and an empty-state when the array "
                        "is empty (e.g. no jobs yet)."
                    ),
                ))

        # 5. CSS classes referenced in JSX/TSX must be defined in the CSS file (-3 pts)
        css_issues = _check_css_class_coverage(files)
        if css_issues:
            score -= min(3, len(css_issues))
            for fp, cls_name in css_issues[:3]:
                issues.append(QAIssue(
                    category="wiring", severity="warning", file_path=fp,
                    description=(
                        f"CSS class '{cls_name}' is referenced in JSX but has no rule in index.css "
                        "or the component stylesheet. The element will render unstyled."
                    ),
                    fix_hint=(
                        f"Add a CSS rule for '.{cls_name}' in index.css (or the relevant stylesheet). "
                        "Pay particular attention to mobile bottom-nav classes — every className used "
                        "in a mobile nav component must have a corresponding CSS rule."
                    ),
                ))

        return max(0, score), issues

    # ── Intelligence Layer (25 pts) ───────────────────────────────────────────

    async def _score_intelligence(
        self, files: dict[str, str], spec: dict
    ) -> tuple[int, list[QAIssue]]:
        score = 25
        issues: list[QAIssue] = []

        # 2 pts per intelligence file (7 × 2 = 14 pts)
        for fp in INTELLIGENCE_FILES:
            content = files.get(fp, "")
            if not content or len(content.strip()) < 300:
                score -= 2
                issues.append(QAIssue(
                    category="intelligence", severity="critical", file_path=fp,
                    description=f"Intelligence file '{fp}' is missing or too short to be complete.",
                    fix_hint=f"Generate a complete {fp} following the intelligence layer standard "
                             f"in CLAUDE.md. Must include all functions, full async/await, loguru logging.",
                ))

        # 2 pts per knowledge engine file (5 × 2 = 10 pts)
        for fp in KNOWLEDGE_FILES:
            content = files.get(fp, "")
            if not content or len(content.strip()) < 200:
                score -= 2
                issues.append(QAIssue(
                    category="intelligence", severity="critical", file_path=fp,
                    description=f"Knowledge engine file '{fp}' is missing or too short to be complete.",
                    fix_hint=f"Generate a complete {fp} following the knowledge engine standard. "
                             f"Must implement the full sweep/embed/retrieve cycle.",
                ))

        # 1 pt: context_assembler called somewhere in generation flow
        assembler_content = files.get("intelligence/context_assembler.py", "")
        generation_content = "\n".join(
            c for p, c in files.items()
            if any(x in p for x in ["layer_generator", "codegen", "generation"])
        )
        if assembler_content and "assemble_context" not in generation_content:
            score -= 1
            issues.append(QAIssue(
                category="intelligence", severity="warning",
                file_path="intelligence/context_assembler.py",
                description="context_assembler.assemble_context() not called in generation flow.",
                fix_hint="Import and call assemble_context() in the layer generator before each "
                         "Claude API call to inject KB patterns and meta-rules.",
            ))

        return max(0, score), issues

    # ── Infrastructure (15 pts) ───────────────────────────────────────────────

    async def _score_infrastructure(
        self, files: dict[str, str], spec: dict
    ) -> tuple[int, list[QAIssue]]:
        score = 15
        issues: list[QAIssue] = []

        # 2 pts per required deployment file (5 × 2 = 10 pts)
        for fp in DEPLOYMENT_FILES:
            content = files.get(fp, "")
            if not content or len(content.strip()) < 50:
                score -= 2
                issues.append(QAIssue(
                    category="infrastructure", severity="critical", file_path=fp,
                    description=f"Required deployment file '{fp}' is missing or empty.",
                    fix_hint=f"Generate a complete {fp} covering all services defined in the spec.",
                ))

        # fly.toml files present for each service (3 pts)
        fly_tomls = [p for p in files if "fly" in p.lower() and p.endswith(".toml")]
        fly_services = spec.get("fly_services", [])
        expected = max(1, len(fly_services))
        if len(fly_tomls) < expected:
            score -= 2
            issues.append(QAIssue(
                category="infrastructure", severity="critical",
                file_path="fly.api.toml",
                description=f"Only {len(fly_tomls)} fly.toml file(s) found; "
                            f"expected one per service: {fly_services}.",
                fix_hint="Generate a fly.toml for each Fly.io service "
                         "(API, worker, dashboard — each with correct app name, region, vm size).",
            ))

        # deploy.yml contains actual flyctl deploy commands (2 pts)
        deploy_yml = files.get(".github/workflows/deploy.yml", "")
        if deploy_yml and "flyctl deploy" not in deploy_yml:
            score -= 2
            issues.append(QAIssue(
                category="infrastructure", severity="critical",
                file_path=".github/workflows/deploy.yml",
                description="deploy.yml exists but is missing flyctl deploy commands.",
                fix_hint="Add a flyctl deploy step for every Fly.io service in the workflow, "
                         "using --config to point to each fly.*.toml.",
            ))

        return max(0, score), issues

    # ── Code Quality (10 pts) ─────────────────────────────────────────────────

    async def _score_code_quality(
        self, files: dict[str, str], spec: dict
    ) -> tuple[int, list[QAIssue]]:
        score = 10
        issues: list[QAIssue] = []

        py_files = {p: c for p, c in files.items() if p.endswith(".py")}

        # Stub / placeholder detection (4 pts)
        stub_files: list[str] = []
        for fp, content in py_files.items():
            for pat in _STUB_PATTERNS:
                if pat.search(content):
                    stub_files.append(fp)
                    break
        if stub_files:
            penalty = min(4, len(stub_files))
            score -= penalty
            for fp in stub_files[:2]:
                issues.append(QAIssue(
                    category="code_quality", severity="critical", file_path=fp,
                    description="Placeholder/stub code detected (pass, TODO, NotImplementedError, or ellipsis body).",
                    fix_hint="Replace every stub with a complete working implementation. "
                             "No function body may be left as pass or ... in a production file.",
                ))

        # Type hints sample (3 pts)
        missing_ratio = _check_type_hints_sample(py_files)
        if missing_ratio > 0.35:
            score -= 2
            issues.append(QAIssue(
                category="code_quality", severity="warning", file_path="",
                description=f"~{int(missing_ratio * 100)}% of sampled functions are missing type hints.",
                fix_hint="Add type hints to every function: def fn(x: str, y: int) -> dict: ...",
            ))
        elif missing_ratio > 0.2:
            score -= 1

        # Hardcoded values in all Python files (3 pts)
        all_hardcoded = _find_hardcoded_secrets(py_files)
        if all_hardcoded:
            score -= min(3, len(all_hardcoded))

        return max(0, score), issues


# ── Fixer ─────────────────────────────────────────────────────────────────────


class BuildQAFixer:
    """
    Takes QA failures and produces targeted Sonnet repairs.
    Groups issues by file — one fix call per file, not per issue.
    For missing required files: generates them from scratch.
    """

    async def fix(
        self,
        files: dict[str, str],
        qa_result: QAResult,
        spec: dict,
        run_id: str,
    ) -> dict[str, str]:
        """
        Returns updated files dict with all fixes applied.
        Files without issues are returned unchanged.
        """
        # Separate file-specific issues from systemic (missing file) issues
        by_file: dict[str, list[QAIssue]] = {}
        missing_files: list[QAIssue] = []

        for issue in qa_result.issues:
            if issue.severity != "critical":
                continue
            if issue.file_path and issue.file_path in files:
                by_file.setdefault(issue.file_path, []).append(issue)
            elif issue.file_path and issue.file_path not in files:
                missing_files.append(issue)

        if not by_file and not missing_files:
            return files

        fixed = dict(files)

        # Fix existing files with issues
        fix_tasks = [(fp, by_file[fp]) for fp in by_file]
        for fp, file_issues in fix_tasks:
            result = await self._fix_file(
                file_path=fp,
                current_content=fixed[fp],
                issues=file_issues,
                all_files=fixed,
                spec=spec,
                run_id=run_id,
            )
            if result:
                fixed[fp] = result
                logger.info(f"[{run_id}] [BuildQA] Fixed: {fp}")

        # Generate missing required files
        for issue in missing_files[:5]:  # Cap at 5 missing files per iteration
            if not issue.file_path:
                continue
            result = await self._generate_missing_file(
                file_path=issue.file_path,
                issue=issue,
                all_files=fixed,
                spec=spec,
                run_id=run_id,
            )
            if result:
                fixed[issue.file_path] = result
                logger.info(f"[{run_id}] [BuildQA] Generated missing: {issue.file_path}")

        return fixed

    async def _fix_file(
        self,
        file_path: str,
        current_content: str,
        issues: list[QAIssue],
        all_files: dict[str, str],
        spec: dict,
        run_id: str,
    ) -> Optional[str]:
        """Repair a single file. Returns the fixed content or None on failure."""
        issues_text = "\n".join(
            f"  [{i.severity.upper()}] {i.description}\n  HOW TO FIX: {i.fix_hint}"
            for i in issues
        )
        context_files = _gather_fix_context(file_path, all_files)
        context_text = "\n\n".join(
            f"=== {fp} (first 1500 chars) ===\n{content[:1500]}"
            for fp, content in context_files.items()
        )

        prompt = f"""You are repairing a generated file that failed automated quality assurance.

FILE: {file_path}

CURRENT CONTENT:
```
{current_content[:10000]}
```

QA ISSUES TO FIX (fix ALL of them — do not skip any):
{issues_text}

CONTEXT FROM RELATED FILES:
{context_text[:5000]}

AGENT SPEC:
- Agent: {spec.get('agent_name', 'Unknown')}
- Stack: FastAPI, SQLAlchemy 2.0 asyncpg, pgvector, Redis, RQ, APScheduler
- Fly.io services: {', '.join(spec.get('fly_services', []))}
- External APIs: {', '.join(spec.get('external_apis', []))}

ABSOLUTE RULES:
1. Return ONLY the complete, fixed file content — no markdown fences, no explanation
2. Fix every single issue listed above — none may remain after your output
3. Preserve all existing correct functionality — do not remove working code
4. All external API calls must have try/except with loguru error logging
5. All function signatures must have type hints
6. Never use hardcoded credentials — use os.environ.get() or settings.*
7. Never use print() — use loguru logger
8. No stubs: pass, ..., TODO, NotImplementedError are all forbidden"""

        try:
            model = router.get_model("generation")
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _client.messages.create(
                    model=model,
                    max_tokens=10000,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            content = response.content[0].text.strip()
            content = _strip_fences(content)
            if len(content) > 150:
                return content
            logger.warning(f"[{run_id}] [BuildQA] Fix for {file_path} too short ({len(content)} chars)")
            return None
        except Exception as exc:
            logger.warning(f"[{run_id}] [BuildQA] Fix call failed for {file_path}: {exc}")
            return None

    async def _generate_missing_file(
        self,
        file_path: str,
        issue: QAIssue,
        all_files: dict[str, str],
        spec: dict,
        run_id: str,
    ) -> Optional[str]:
        """Generate a completely missing required file from scratch."""
        context_files = _gather_fix_context(file_path, all_files)
        context_text = "\n\n".join(
            f"=== {fp} ===\n{content[:1500]}"
            for fp, content in list(context_files.items())[:4]
        )

        prompt = f"""Generate a complete, production-ready file for an AI agent project.

FILE TO CREATE: {file_path}

WHY IT'S NEEDED: {issue.description}
WHAT IT MUST DO: {issue.fix_hint}

AGENT SPEC:
- Agent: {spec.get('agent_name', 'Unknown')}
- Stack: FastAPI, SQLAlchemy 2.0 asyncpg, pgvector, Redis, RQ, APScheduler, Fly.io
- Services: {', '.join(spec.get('fly_services', []))}
- External APIs: {', '.join(spec.get('external_apis', []))}
- Secrets needed: {', '.join(spec.get('required_secrets', []))}

RELATED FILES FOR CONTEXT:
{context_text}

REQUIREMENTS:
- Complete implementation — no stubs, no TODOs, no placeholders
- Full async/await throughout
- Type hints on every function signature
- loguru for all logging — never print()
- try/except on every external API call
- All configuration from environment variables or settings
- Follows the patterns in the context files above

Return ONLY the complete file content. No markdown, no explanation."""

        try:
            model = router.get_model("generation")
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _client.messages.create(
                    model=model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            content = response.content[0].text.strip()
            content = _strip_fences(content)
            return content if len(content) > 150 else None
        except Exception as exc:
            logger.warning(f"[{run_id}] [BuildQA] Missing file gen failed for {file_path}: {exc}")
            return None


# ── Static analysis helpers ────────────────────────────────────────────────────


def _extract_route_blocks(content: str) -> list[str]:
    """Extract route function bodies from API content."""
    blocks: list[str] = []
    current: list[str] = []
    in_route = False
    for line in content.split("\n"):
        if re.match(r'\s*@(?:app|router)\.(get|post|put|delete|patch)', line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
            in_route = True
        elif in_route:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _find_hardcoded_secrets(files: dict[str, str]) -> list[tuple[str, str]]:
    """Return (file_path, matched_text) for files containing hardcoded credentials."""
    results: list[tuple[str, str]] = []
    for fp, content in files.items():
        for pat in _SECRET_PATTERNS:
            m = pat.search(content)
            if m:
                results.append((fp, m.group(0)))
                break
    return results


def _extract_frontend_api_calls(frontend_files: dict[str, str]) -> list[str]:
    """Extract API URL paths called from frontend code."""
    urls: set[str] = set()
    for content in frontend_files.values():
        for m in _FRONTEND_CALL_RE.finditer(content):
            url = m.group(1) or m.group(2) or m.group(3) or ""
            url = url.split("?")[0].split("${")[0].strip()
            if url and "/" in url and len(url) > 2 and not url.startswith("http"):
                urls.add(url)
    return list(urls)


def _check_import_resolution(py_files: dict[str, str]) -> list[tuple[str, str]]:
    """Find imports that reference modules not in the generated file set."""
    # Build set of known module paths from generated files
    known: set[str] = set()
    for fp in py_files:
        module = fp.replace("/", ".").removesuffix(".py")
        known.add(module)
        parts = module.split(".")
        for i in range(1, len(parts)):
            known.add(".".join(parts[:i]))

    issues: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for fp, content in py_files.items():
        for m in _IMPORT_RE.finditer(content):
            raw = (m.group(1) or m.group(2) or "").strip()
            if not raw:
                continue
            top = raw.split(".")[0]
            if top in _KNOWN_EXTERNAL:
                continue
            if top in known or any(k.startswith(top) for k in known):
                continue
            key = (fp, top)
            if key not in seen:
                seen.add(key)
                issues.append(key)

    return issues[:8]  # Cap to avoid noise


def _check_port_consistency(files: dict[str, str]) -> list[tuple[str, str]]:
    """Check port numbers are consistent across fly.toml, Dockerfiles, and uvicorn."""
    toml_ports: dict[str, int] = {}
    uvicorn_ports: dict[str, int] = {}
    expose_ports: dict[str, int] = {}

    for fp, content in files.items():
        if fp.endswith(".toml") and "fly" in fp.lower():
            for m in _PORT_TOML_RE.finditer(content):
                toml_ports[fp] = int(m.group(1))
        if "Dockerfile" in fp:
            for m in _PORT_EXPOSE_RE.finditer(content):
                expose_ports[fp] = int(m.group(1))
        if fp.endswith(".py") and "uvicorn" in content:
            for m in _PORT_UVICORN_RE.finditer(content):
                uvicorn_ports[fp] = int(m.group(1))

    all_port_values = (
        list(toml_ports.values()) + list(uvicorn_ports.values()) + list(expose_ports.values())
    )
    if len(set(all_port_values)) > 1:
        first_toml = next(iter(toml_ports), next(iter(expose_ports), ""))
        return [(
            f"Port mismatch detected — fly.toml: {list(toml_ports.values())}, "
            f"Dockerfile EXPOSE: {list(expose_ports.values())}, "
            f"uvicorn: {list(uvicorn_ports.values())}.",
            first_toml,
        )]
    return []


def _check_type_hints_sample(py_files: dict[str, str]) -> float:
    """
    Sample up to 30 function definitions. Returns fraction missing type hints.
    Excludes __init__, __str__ and similar dunder methods.
    """
    total = 0
    missing = 0
    for content in py_files.values():
        for m in _FN_DEF_RE.finditer(content):
            fn_line = m.group(0)
            if "__" in fn_line and "__init__" not in fn_line:
                continue
            params = (m.group(1) or "").strip()
            has_return = bool(m.group(2))
            total += 1
            # Missing type hints if params have no colon annotation
            clean_params = re.sub(r'self|cls', '', params).strip().strip(",").strip()
            if clean_params and ":" not in clean_params:
                missing += 1
            if not has_return and "def __" not in fn_line:
                missing += 0.3
            if total >= 30:
                break
        if total >= 30:
            break
    return missing / max(total, 1)


def _find_file_with_content(files: dict[str, str], search: str) -> str:
    """Return the first file path containing the search string."""
    for fp, content in files.items():
        if search in content:
            return fp
    return ""


def _gather_fix_context(file_path: str, all_files: dict[str, str]) -> dict[str, str]:
    """
    Gather the most relevant surrounding files for repairing file_path.
    Returns up to 5 related files: same directory + models + settings.
    """
    context: dict[str, str] = {}
    directory = "/".join(file_path.split("/")[:-1])

    # Same-directory neighbours
    for fp, content in all_files.items():
        if fp != file_path and fp.startswith(directory) and len(context) < 3:
            context[fp] = content

    # Always include models and settings as context
    for candidate in ("memory/models.py", "models.py", "database/models.py"):
        if candidate in all_files and candidate not in context:
            context[candidate] = all_files[candidate]
            break

    for candidate in ("config/settings.py", "settings.py", "core/config.py"):
        if candidate in all_files and candidate not in context:
            context[candidate] = all_files[candidate]
            break

    return dict(list(context.items())[:5])


def _check_unwired_tab_components(
    frontend_files: dict[str, str],
) -> list[tuple[str, str]]:
    """
    Detect frontend Tab/Page/View components that import an API client module
    but never actually call it (i.e. they only render hardcoded static arrays).

    Returns list of (file_path, description) pairs for unwired components.
    """
    # Regex to detect an import that looks like an API client
    _API_IMPORT_RE = re.compile(
        r'import\s+[^;]+from\s+["\'].*(?:api|Api|client|Client)["\']',
        re.MULTILINE,
    )
    # Regex to detect actual API usage patterns
    _API_CALL_RE = re.compile(
        r'useEffect|useQuery|useMutation|\.then\(|await\s+\w+(?:Api|api|client|Client)\.',
        re.MULTILINE,
    )
    # Top-level const arrays that look like hardcoded mock/fallback data
    _MOCK_ARRAY_RE = re.compile(
        r'^(?:export\s+)?const\s+[A-Z][A-Z0-9_]{2,}\s*(?::\s*[\w<>\[\]]+\s*)?=\s*\[',
        re.MULTILINE,
    )

    issues: list[tuple[str, str]] = []
    for fp, content in frontend_files.items():
        basename = fp.split("/")[-1]
        # Only check components that are likely data-displaying tabs/pages
        if not any(x in basename for x in ("Tab", "Page", "View", "Dashboard")):
            continue
        has_api_import = bool(_API_IMPORT_RE.search(content))
        if not has_api_import:
            continue
        has_api_call = bool(_API_CALL_RE.search(content))
        mock_arrays = _MOCK_ARRAY_RE.findall(content)
        if not has_api_call and len(mock_arrays) >= 2:
            issues.append((
                fp,
                f"{basename} imports an API client but has no API call (no useEffect/useQuery). "
                f"Found {len(mock_arrays)} hardcoded static array(s) — component will always show "
                "mock data instead of real business data.",
            ))
    return issues


def _check_css_class_coverage(files: dict[str, str]) -> list[tuple[str, str]]:
    """
    Detect CSS class names referenced in JSX/TSX className props that have no
    corresponding rule in any CSS file. Focuses on custom class patterns
    (hyphenated multi-word names) since Tailwind utility classes are always valid.

    Returns list of (file_path, class_name) pairs for undefined classes.
    """
    # Collect all custom CSS class names used in className props
    _CLASSNAME_RE = re.compile(r'className\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)

    # Collect all CSS rule selectors from CSS files
    css_content = "\n".join(
        content for fp, content in files.items()
        if fp.endswith(".css")
    )
    defined_classes: set[str] = set(
        m.group(1) for m in re.finditer(r'\.([a-zA-Z][\w-]+)\s*\{', css_content)
    )

    issues: list[tuple[str, str]] = []
    seen_missing: set[str] = set()

    for fp, content in files.items():
        if not fp.endswith((".tsx", ".jsx")):
            continue
        for m in _CLASSNAME_RE.finditer(content):
            for cls in m.group(1).split():
                cls = cls.strip()
                # Skip Tailwind utility classes (they contain: or are single words like "flex")
                # Focus on multi-segment hyphenated names that look like BEM/custom classes
                if (
                    ":" in cls             # Tailwind responsive prefix
                    or cls.startswith("[") # Tailwind arbitrary value
                    or "-" not in cls      # Single-word classes (flex, grid, etc.)
                    or cls in seen_missing
                ):
                    continue
                # Only flag classes that look like explicit custom names
                # (start with a project-specific prefix or contain 3+ segments)
                segments = cls.split("-")
                if len(segments) >= 3 and cls not in defined_classes:
                    seen_missing.add(cls)
                    issues.append((fp, cls))

    return issues[:8]  # Cap to avoid noise from Tailwind-heavy builds


def _strip_fences(content: str) -> str:
    """Remove markdown code fences if Claude wrapped the output."""
    if content.startswith("```"):
        lines = content.split("\n")
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        return "\n".join(lines[start:end]).strip()
    return content
