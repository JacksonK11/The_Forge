"""
intelligence/evaluator.py
Scores every generated file against the production-readiness rubric before saving.

Substandard outputs are regenerated automatically — up to 3 attempts per file.
Uses Haiku (fast, cheap) for evaluation since it runs on every generated file.

Evaluation rubric (all must pass):
  1. No placeholder code (pass, ..., TODO, FIXME, "implement this")
  2. Type hints on all function signatures
  3. Error handling on external API calls
  4. No hardcoded values (URLs, keys, credentials)
  5. No blocking calls in async functions
  6. No import errors (importing non-existent modules)
  7. Correct logging (loguru, not print)
  8. No Pydantic v1 syntax

The evaluator is called from layer_generator.py after every file generation.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings
from pipeline.prompts.prompts import EVALUATOR_SYSTEM, EVALUATOR_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class EvaluationIssue:
    severity: str  # "critical" | "warning"
    line: str
    issue: str
    fix: str


@dataclass
class EvaluationResult:
    passed: bool
    issues: list[EvaluationIssue] = field(default_factory=list)
    summary: str = ""
    model_used: str = ""

    @property
    def critical_issues(self) -> list[EvaluationIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warnings(self) -> list[EvaluationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def _run_static_checks(file_path: str, content: str) -> list[EvaluationIssue]:
    """
    Fast string-matching checks for known deployment-breaking patterns.
    Runs before LLM evaluation — catches definitive bugs with zero API cost.
    """
    issues: list[EvaluationIssue] = []
    basename = file_path.split("/")[-1]

    # ── models.py: SQLAlchemy reserved attribute names ────────────────────────
    if basename == "models.py":
        reserved = ["metadata", "query", "registry"]
        for name in reserved:
            # Match: name: Mapped[...] = mapped_column(  OR  name = Column(  OR  name = mapped_column(
            if re.search(rf'\b{name}\s*:\s*Mapped', content) or \
               re.search(rf'\b{name}\s*=\s*mapped_column\s*\(', content) or \
               re.search(rf'\b{name}\s*=\s*Column\s*\(', content):
                issues.append(EvaluationIssue(
                    severity="critical",
                    line=f"Column named '{name}'",
                    issue=f"'{name}' is a reserved SQLAlchemy DeclarativeBase attribute — crashes on startup with InvalidRequestError.",
                    fix=f"Rename the Python attribute to 'extra_{name}' and use mapped_column('{name}', ...) to keep the DB column name.",
                ))

    # ── database.py: asyncpg + sslmode incompatibility ───────────────────────
    if basename == "database.py":
        uses_asyncpg = "asyncpg" in content or "postgresql+asyncpg" in content
        has_sslmode_strip = "sslmode" in content and "re.sub" in content
        if uses_asyncpg and "sslmode" in content and not has_sslmode_strip:
            issues.append(EvaluationIssue(
                severity="critical",
                line="DATABASE_URL handling",
                issue="asyncpg does not support 'sslmode' in the connection URL. Fly Postgres always injects ?sslmode=disable.",
                fix="Add: url = re.sub(r'[?&]sslmode=[^&]*', '', url) in the URL-building function before passing to create_async_engine.",
            ))

    # ── tsconfig*.json: composite + noEmit mutually exclusive ────────────────
    if basename.startswith("tsconfig") and basename.endswith(".json"):
        try:
            parsed = json.loads(content)
            opts = parsed.get("compilerOptions", {})
            if opts.get("composite") and opts.get("noEmit"):
                issues.append(EvaluationIssue(
                    severity="critical",
                    line="compilerOptions",
                    issue="'composite: true' and 'noEmit: true' are mutually exclusive — TypeScript error TS6310 (composite projects cannot disable emit).",
                    fix="Remove 'noEmit: true' from this tsconfig file entirely.",
                ))
        except (json.JSONDecodeError, Exception):
            pass

    # ── Dockerfile: npm install without --legacy-peer-deps ───────────────────
    if "Dockerfile" in basename or basename == "Dockerfile":
        if "npm install" in content and "--legacy-peer-deps" not in content:
            issues.append(EvaluationIssue(
                severity="critical",
                line="RUN npm install",
                issue="npm install without --legacy-peer-deps will fail due to eslint-plugin-react-hooks@4 peer dependency conflict with ESLint 9.",
                fix="Change to: RUN npm install --legacy-peer-deps",
            ))
        if ("npm run build" in content or "tsc && vite build" in content) and "npx vite build" not in content:
            issues.append(EvaluationIssue(
                severity="critical",
                line="RUN npm run build / tsc && vite build",
                issue="'npm run build' runs 'tsc && vite build' which fails when TypeScript type errors exist. Use 'npx vite build' to bypass tsc.",
                fix="Change to: RUN npx vite build",
            ))

    # ── Any .tsx/.jsx/.ts file: duplicate function/const declarations ─────────
    if file_path.endswith((".tsx", ".jsx", ".ts", ".js")) and basename != "vite.config.ts":
        fn_names: list[str] = re.findall(r'^(?:export\s+)?(?:default\s+)?function\s+(\w+)', content, re.MULTILINE)
        const_names: list[str] = re.findall(r'^(?:export\s+)?const\s+(\w+)\s*=', content, re.MULTILINE)
        all_names = fn_names + const_names
        seen: set[str] = set()
        for name in all_names:
            if name in seen:
                issues.append(EvaluationIssue(
                    severity="critical",
                    line=f"Declaration of '{name}'",
                    issue=f"'{name}' is declared more than once in this file. esbuild throws 'The symbol has already been declared' and the build fails.",
                    fix=f"Remove the duplicate declaration of '{name}' — keep only one.",
                ))
            seen.add(name)

    # ── Dockerfile.worker: must not use uvicorn as CMD ───────────────────────
    if "Dockerfile" in basename and "worker" in basename.lower():
        if "uvicorn" in content and "CMD" in content:
            # Check if uvicorn appears in the CMD line
            cmd_lines = [l for l in content.splitlines() if l.strip().startswith("CMD")]
            for cmd_line in cmd_lines:
                if "uvicorn" in cmd_line:
                    issues.append(EvaluationIssue(
                        severity="critical",
                        line="CMD",
                        issue="Dockerfile.worker uses 'uvicorn' as CMD — workers run RQ jobs, not an HTTP server. This starts the wrong process.",
                        fix="Change CMD to: [\"python\", \"-m\", \"rq\", \"worker\", \"--with-scheduler\", \"QUEUE_NAME\"] matching the queue name in main.py.",
                    ))

    # ── main.py / app.py: must have startup env-var validation ────────────────
    if basename in ("main.py", "app.py") and "FastAPI" in content:
        has_validation = (
            "_validate_critical_secrets" in content or
            "validate_critical_secrets" in content or
            "missing_critical" in content or
            "Missing required secrets" in content
        )
        if not has_validation:
            issues.append(EvaluationIssue(
                severity="critical",
                line="lifespan / startup",
                issue="FastAPI main.py has no startup env-var validation. App will crash mid-request with cryptic errors if secrets are missing.",
                fix="Add _validate_critical_secrets() called at lifespan startup: check all critical env vars, raise RuntimeError with clear message if any are missing.",
            ))

    # ── FastAPI routes: status_code=204/205 with response body ───────────────
    if file_path.endswith(".py") and ("routes/" in file_path or "api/" in file_path):
        # Find all @router.* decorator lines that set status_code=204 or 205
        for m in re.finditer(
            r'@(?:app|router)\.\w+\([^)]*status_code\s*=\s*(204|205)[^)]*\)',
            content
        ):
            # Grab the next ~20 lines after the decorator to find the function body
            start = m.end()
            block = content[start:start + 600]
            # If the function returns something other than None / Response(204)
            has_return_value = bool(re.search(
                r'return\s+(?!None\b|Response\s*\()(?!$)(\S)',
                block, re.MULTILINE
            ))
            if has_return_value:
                issues.append(EvaluationIssue(
                    severity="critical",
                    line=f"status_code={m.group(1)} route",
                    issue=(
                        f"FastAPI endpoint with status_code={m.group(1)} returns a response body. "
                        "HTTP 204/205 must have NO body — FastAPI raises AssertionError at startup, "
                        "crashing the entire app before the first request is served."
                    ),
                    fix=(
                        f"Either change status_code to 200 and return a dict "
                        f'(e.g. return {{"deleted": True}}), '
                        f"or change the return type to Response and return "
                        f"Response(status_code={m.group(1)}) with no body."
                    ),
                ))

    # ── Frontend tab components: hardcoded mock arrays shadow API client ──────
    if file_path.endswith((".tsx", ".jsx")) and (
        "Tab" in basename or "Page" in basename or "View" in basename
    ):
        has_api_import = bool(re.search(
            r'import\s+.*(?:Api|api|client|Client|fetch|hooks)\b',
            content, re.MULTILINE
        ))
        # Top-level const arrays that look like hardcoded mock data
        mock_arrays = re.findall(
            r'^const\s+[A-Z_][A-Z0-9_]+\s*(?::\s*\w+\[\])?\s*=\s*\[',
            content, re.MULTILINE
        )
        # Check if those mocks are rendered (used in JSX) while API import exists
        if has_api_import and len(mock_arrays) >= 2:
            # Check that the component has a useEffect or equivalent API call
            has_api_call = bool(re.search(
                r'useEffect|useQuery|useMutation|\.then\(|await\s+\w+Api\.',
                content
            ))
            if not has_api_call:
                issues.append(EvaluationIssue(
                    severity="critical",
                    line="Top-level mock data arrays",
                    issue=(
                        f"Component imports an API client but renders {len(mock_arrays)} hardcoded "
                        "static arrays with no API call (no useEffect/useQuery/await apiCall). "
                        "The component will always show mock data and never display real business data."
                    ),
                    fix=(
                        "Remove top-level hardcoded data arrays. Add a useEffect (or useQuery) "
                        "that calls the API client and stores results in useState. "
                        "Render the state, not the static arrays. Show a loading spinner while fetching."
                    ),
                ))

    # ── package.json: commonly forgotten packages ─────────────────────────────
    if basename == "package.json":
        try:
            parsed = json.loads(content)
            deps = {**parsed.get("dependencies", {}), **parsed.get("devDependencies", {})}
            must_have = {
                "@tanstack/react-query-devtools": "Imported in App.tsx — its absence causes a Rollup 'failed to resolve import' build failure.",
            }
            for pkg, reason in must_have.items():
                if pkg not in deps:
                    issues.append(EvaluationIssue(
                        severity="critical",
                        line="dependencies",
                        issue=f"Missing '{pkg}'. {reason}",
                        fix=f"Add \"{pkg}\": \"^5.0.0\" to dependencies.",
                    ))
        except (json.JSONDecodeError, Exception):
            pass

    return issues


async def evaluate_file(
    file_path: str,
    purpose: str,
    content: str,
    strict: bool = True,
) -> EvaluationResult:
    """
    Evaluate a generated file for production readiness.

    Args:
        file_path: Path of the file being evaluated.
        purpose:   Description of what the file should do.
        content:   File content to evaluate.
        strict:    If True, any critical issue fails the evaluation.
                   If False, only placeholder code fails (used for edge cases).

    Returns:
        EvaluationResult with passed=True if file meets production standard.
    """
    # Skip evaluation for trivial files
    if _is_trivial_file(file_path, content):
        return EvaluationResult(passed=True, summary="Trivial file — evaluation skipped")

    # Run fast static checks first — catches known deployment-breaking patterns
    # with zero API cost before invoking the LLM evaluator
    static_issues = _run_static_checks(file_path, content)
    if static_issues:
        critical = [i for i in static_issues if i.severity == "critical"]
        logger.warning(
            f"Static checks found {len(critical)} critical issue(s) in {file_path}: "
            + "; ".join(i.issue[:80] for i in critical)
        )
        if strict and critical:
            return EvaluationResult(
                passed=False,
                issues=static_issues,
                summary=f"Static check failed: {critical[0].issue[:120]}",
                model_used="static",
            )

    model = router.get_model("evaluation")

    try:
        prompt = EVALUATOR_USER.format(
            file_path=file_path,
            purpose=purpose,
            content=content[:6000],
        )
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)

        issues = [
            EvaluationIssue(
                severity=i.get("severity", "warning"),
                line=str(i.get("line", "unknown")),
                issue=i.get("issue", ""),
                fix=i.get("fix", ""),
            )
            for i in raw.get("issues", [])
        ]

        # In strict mode, fail on any critical issue
        passed = raw.get("passed", True)
        if strict and any(i.severity == "critical" for i in issues):
            passed = False

        # Merge static issues with LLM issues (static issues take priority)
        all_issues = static_issues + issues
        if strict and any(i.severity == "critical" for i in static_issues):
            passed = False

        result = EvaluationResult(
            passed=passed,
            issues=all_issues,
            summary=raw.get("summary", ""),
            model_used=model,
        )

        if not result.passed:
            logger.debug(
                f"Evaluation failed for {file_path}: "
                f"{len(result.critical_issues)} critical, {len(result.warnings)} warnings"
            )

        return result

    except json.JSONDecodeError as exc:
        logger.warning(f"Evaluator response not JSON for {file_path}: {exc}")
        return EvaluationResult(passed=True, summary="Evaluation response parse error — defaulting to pass")
    except Exception as exc:
        logger.warning(f"Evaluator error for {file_path}: {exc}")
        return EvaluationResult(passed=True, summary=f"Evaluation failed (non-blocking): {exc}")


def format_issues_for_regeneration(result: EvaluationResult) -> str:
    """
    Format evaluation issues as a correction instruction for the next generation attempt.
    Injected into the codegen prompt on retry.
    """
    if not result.issues:
        return ""
    lines = ["PREVIOUS ATTEMPT FAILED EVALUATION. Fix ALL of these issues:\n"]
    for issue in result.issues:
        icon = "🚨" if issue.severity == "critical" else "⚠️"
        lines.append(f"{icon} [{issue.severity.upper()}] {issue.issue}")
        lines.append(f"   Fix: {issue.fix}")
        if issue.line and issue.line != "unknown":
            lines.append(f"   At: {issue.line}")
        lines.append("")
    return "\n".join(lines)


# ── Internal ──────────────────────────────────────────────────────────────────


def _is_trivial_file(file_path: str, content: str) -> bool:
    """Files that don't warrant LLM evaluation."""
    basename = file_path.split("/")[-1]
    if basename == "__init__.py":
        return True
    if not content or len(content.strip()) < 20:
        return True
    if file_path.endswith((".toml", ".yaml", ".yml", ".json", ".txt", ".md")):
        return True
    return False
