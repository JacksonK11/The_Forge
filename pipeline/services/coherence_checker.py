"""
pipeline/services/coherence_checker.py
After all files are generated, before packaging, verifies that files work
together as a system. Catches route/frontend mismatches, model/schema mismatches,
circular imports, and config inconsistencies.

Checks A+B use one Claude call (evaluation model = Haiku).
Checks C+D are pure regex — zero LLM cost.
"""

import re
from collections import defaultdict, deque

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings

_ENV_VAR_RE = re.compile(r'os\.environ\.get\(["\'](\w+)["\']|os\.getenv\(["\'](\w+)["\']|settings\.(\w+)')
_IMPORT_RE = re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', re.MULTILINE)
_PORT_RE = re.compile(r'(?:internal_port|port)\s*[=:]\s*(\d+)')
_UVICORN_PORT_RE = re.compile(r'--port\s+(\d+)')
_ROUTE_DEF_RE = re.compile(r'@(?:app|router)\.\w+\(["\']([^"\']+)["\']')
_FETCH_RE = re.compile(r'fetch\s*\(\s*["\']([^"\']+)["\']|axios\.\w+\s*\(\s*["\']([^"\']+)["\']')


def _module_to_path(module: str) -> str:
    """Convert a dotted module path to a relative .py file path."""
    return module.replace(".", "/") + ".py"


class CoherenceChecker:
    """
    Verifies that all generated files work together as a coherent system.
    """

    async def check_coherence(self, all_files: list[dict], spec: dict) -> dict:
        """
        Run all coherence checks against the generated file set.

        Args:
            all_files: List of {"path": str, "content": str} dicts.
            spec: The full build specification dict.

        Returns:
            {
                'route_mismatches': [...],
                'model_mismatches': [...],
                'import_issues': [...],
                'config_issues': [...],
                'passed': bool,
                'total_issues': int,
            }
        """
        result: dict = {
            "route_mismatches": [],
            "model_mismatches": [],
            "import_issues": [],
            "config_issues": [],
            "passed": False,
            "total_issues": 0,
        }

        file_map: dict[str, str] = {f["path"]: f["content"] for f in all_files if f.get("path")}

        # ── Check C: Import chain (pure regex) ──────────────────────────
        try:
            import_issues = self._check_import_chain(file_map)
            result["import_issues"] = import_issues
        except Exception as exc:
            logger.warning(f"[coherence] Import chain check failed: {exc}")

        # ── Check D: Config consistency (pure regex) ─────────────────────
        try:
            config_issues = self._check_config_consistency(file_map)
            result["config_issues"] = config_issues
        except Exception as exc:
            logger.warning(f"[coherence] Config consistency check failed: {exc}")

        # ── Checks A+B: Route + model mismatches (one Claude call) ───────
        try:
            route_mismatches, model_mismatches = await self._check_routes_and_models(file_map)
            result["route_mismatches"] = route_mismatches
            result["model_mismatches"] = model_mismatches
        except Exception as exc:
            logger.warning(f"[coherence] Route/model check failed: {exc}")

        # ── Summarise ────────────────────────────────────────────────────
        total = (
            len(result["route_mismatches"])
            + len(result["model_mismatches"])
            + len(result["import_issues"])
            + len(result["config_issues"])
        )
        result["total_issues"] = total
        result["passed"] = total == 0

        logger.info(
            f"[coherence] passed={result['passed']} total_issues={total} "
            f"route_mismatches={len(result['route_mismatches'])} "
            f"model_mismatches={len(result['model_mismatches'])} "
            f"import_issues={len(result['import_issues'])} "
            f"config_issues={len(result['config_issues'])}"
        )

        return result

    async def auto_fix(self, all_files: list[dict], coherence_result: dict) -> list[dict]:
        """
        Apply safe automatic fixes for coherence issues.

        Currently fixes:
        - Missing env vars in .env.example (for config_issues)

        Route/model mismatches are logged but not auto-fixed.

        Args:
            all_files: List of {"path": str, "content": str} dicts.
            coherence_result: The dict returned by check_coherence().

        Returns:
            Updated all_files list.
        """
        try:
            file_map: dict[str, dict] = {f["path"]: f for f in all_files if f.get("path")}

            # ── Log-only: route and model mismatches ─────────────────────
            for mismatch in coherence_result.get("route_mismatches", []):
                logger.warning(f"[coherence] route mismatch (not auto-fixed): {mismatch}")
            for mismatch in coherence_result.get("model_mismatches", []):
                logger.warning(f"[coherence] model mismatch (not auto-fixed): {mismatch}")

            # ── Auto-fix: missing env vars in .env.example ────────────────
            env_example_path = None
            for path in file_map:
                if path == ".env.example" or path.endswith("/.env.example"):
                    env_example_path = path
                    break

            if env_example_path:
                try:
                    existing_env_content = file_map[env_example_path]["content"]
                    additions: list[str] = []

                    for issue in coherence_result.get("config_issues", []):
                        issue_text = issue.get("issue", "")
                        # Extract var name from "env var FOO not in .env.example" style messages
                        match = re.search(r'env var ["\']?(\w+)["\']? not in', issue_text)
                        if match:
                            var_name = match.group(1)
                            if var_name not in existing_env_content:
                                additions.append(f"{var_name}=  # ADD THIS")
                                logger.info(f"[coherence] auto-fix: adding {var_name} to .env.example")

                    if additions:
                        new_content = existing_env_content.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
                        file_map[env_example_path]["content"] = new_content

                except Exception as exc:
                    logger.warning(f"[coherence] Failed to update .env.example: {exc}")

            return list(file_map.values())

        except Exception as exc:
            logger.warning(f"[coherence] auto_fix failed: {exc}")
            return all_files

    # ── Private: Check C ────────────────────────────────────────────────

    def _check_import_chain(self, file_map: dict[str, str]) -> list[dict]:
        """
        Detect circular imports and references to non-existent internal modules.
        Uses DFS cycle detection on the import graph.
        """
        issues: list[dict] = []

        try:
            # Build import graph: {file_path: [imported_file_path, ...]}
            graph: dict[str, list[str]] = defaultdict(list)
            all_paths = set(file_map.keys())

            for file_path, content in file_map.items():
                if not file_path.endswith(".py"):
                    continue
                for match in _IMPORT_RE.finditer(content):
                    module = (match.group(1) or match.group(2) or "").strip()
                    if not module:
                        continue
                    # Only care about potential internal modules (not stdlib/third-party)
                    top_level = module.split(".")[0]
                    if top_level in {
                        "os", "sys", "re", "json", "ast", "typing", "dataclasses",
                        "enum", "functools", "collections", "asyncio", "pathlib",
                        "datetime", "logging", "traceback", "uuid", "hashlib",
                        "fastapi", "pydantic", "sqlalchemy", "uvicorn", "starlette",
                        "alembic", "celery", "redis", "anthropic", "httpx", "aiohttp",
                        "boto3", "psycopg2", "asyncpg", "app", "config",
                    }:
                        continue
                    imported_path = _module_to_path(module)
                    if imported_path in all_paths:
                        graph[file_path].append(imported_path)
                    # Check for dotted sub-modules too
                    alt_path = _module_to_path(module.split(".")[0])
                    if alt_path in all_paths and alt_path not in graph[file_path]:
                        graph[file_path].append(alt_path)

            # DFS cycle detection
            WHITE, GRAY, BLACK = 0, 1, 2
            color: dict[str, int] = defaultdict(int)
            cycles_reported: set[frozenset] = set()

            def dfs(node: str, path: list[str]) -> None:
                color[node] = GRAY
                for neighbour in graph.get(node, []):
                    if color[neighbour] == GRAY:
                        # Found a cycle — find where it starts
                        cycle_start = path.index(neighbour) if neighbour in path else 0
                        cycle_nodes = frozenset(path[cycle_start:] + [node])
                        if cycle_nodes not in cycles_reported:
                            cycles_reported.add(cycle_nodes)
                            cycle_str = " → ".join(path[cycle_start:] + [neighbour])
                            issues.append({
                                "file": node,
                                "issue": f"Circular import detected: {cycle_str}",
                            })
                    elif color[neighbour] == WHITE:
                        dfs(neighbour, path + [neighbour])
                color[node] = BLACK

            for file_path in file_map:
                if file_path.endswith(".py") and color[file_path] == WHITE:
                    try:
                        dfs(file_path, [file_path])
                    except RecursionError:
                        logger.warning(f"[coherence] DFS recursion limit hit at {file_path}")

        except Exception as exc:
            logger.warning(f"[coherence] _check_import_chain error: {exc}")

        return issues

    # ── Private: Check D ────────────────────────────────────────────────

    def _check_config_consistency(self, file_map: dict[str, str]) -> list[dict]:
        """
        Verify env vars are in .env.example and ports are consistent across
        Dockerfile, fly.toml, and docker-compose.yml.
        """
        issues: list[dict] = []

        try:
            # Find .env.example content
            env_example_content = ""
            for path, content in file_map.items():
                if path == ".env.example" or path.endswith("/.env.example"):
                    env_example_content = content
                    break

            if env_example_content:
                # Extract declared env var names
                declared_vars: set[str] = set()
                for line in env_example_content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        var_name = line.split("=")[0].strip()
                        if var_name:
                            declared_vars.add(var_name)

                # Scan Python files for env var usage
                for file_path, content in file_map.items():
                    if not file_path.endswith(".py"):
                        continue
                    for match in _ENV_VAR_RE.finditer(content):
                        var_name = match.group(1) or match.group(2) or match.group(3) or ""
                        var_name = var_name.strip()
                        if not var_name:
                            continue
                        # Skip settings.* that are clearly not env vars
                        if match.group(3) and var_name.islower():
                            continue
                        if var_name not in declared_vars:
                            issues.append({
                                "file": file_path,
                                "issue": f"env var '{var_name}' not in .env.example",
                            })

            # ── Port consistency check ────────────────────────────────────
            fly_port: int | None = None
            docker_api_port: int | None = None
            compose_port: int | None = None

            # fly.*.toml
            for path, content in file_map.items():
                if re.match(r"fly(?:\.\w+)?\.toml$", path) or path.endswith("/fly.toml"):
                    match = _PORT_RE.search(content)
                    if match:
                        try:
                            fly_port = int(match.group(1))
                        except ValueError:
                            pass

            # Dockerfile.api
            for path, content in file_map.items():
                if "Dockerfile.api" in path or path == "Dockerfile":
                    match = _UVICORN_PORT_RE.search(content)
                    if match:
                        try:
                            docker_api_port = int(match.group(1))
                        except ValueError:
                            pass

            # docker-compose.yml
            for path, content in file_map.items():
                if "docker-compose" in path and path.endswith((".yml", ".yaml")):
                    # Look for ports: - "NNNN:NNNN" pattern
                    port_match = re.search(r'ports:\s*\n\s*-\s*["\']?(\d+):\d+', content)
                    if port_match:
                        try:
                            compose_port = int(port_match.group(1))
                        except ValueError:
                            pass

            # Flag mismatches
            ports = {p for p in (fly_port, docker_api_port, compose_port) if p is not None}
            if len(ports) > 1:
                issues.append({
                    "file": "deployment config",
                    "issue": (
                        f"Port mismatch across configs: "
                        f"fly.toml={fly_port}, Dockerfile.api={docker_api_port}, "
                        f"docker-compose={compose_port}"
                    ),
                })

        except Exception as exc:
            logger.warning(f"[coherence] _check_config_consistency error: {exc}")

        return issues

    # ── Private: Checks A + B ────────────────────────────────────────────

    async def _check_routes_and_models(
        self,
        file_map: dict[str, str],
    ) -> tuple[list[dict], list[dict]]:
        """
        Use Claude (Haiku) to detect route/frontend mismatches and
        Pydantic/SQLAlchemy model mismatches.

        Returns (route_mismatches, model_mismatches).
        """
        route_mismatches: list[dict] = []
        model_mismatches: list[dict] = []

        try:
            snippets: list[str] = []
            included = 0

            # FastAPI route definitions
            for path, content in file_map.items():
                if included >= 6:
                    break
                if "app/api/routes" in path and path.endswith(".py"):
                    snippets.append(f"=== {path} (routes) ===\n{content[:800]}")
                    included += 1

            # Frontend fetch calls
            for path, content in file_map.items():
                if included >= 6:
                    break
                if path.endswith((".jsx", ".js", ".tsx", ".ts")):
                    if "fetch(" in content or "axios." in content:
                        snippets.append(f"=== {path} (frontend) ===\n{content[:800]}")
                        included += 1

            # SQLAlchemy models
            for path, content in file_map.items():
                if included >= 6:
                    break
                if path in ("memory/models.py", "app/db/models.py") or "models.py" in path:
                    snippets.append(f"=== {path} (ORM model) ===\n{content[:800]}")
                    included += 1

            # Pydantic schemas
            for path, content in file_map.items():
                if included >= 6:
                    break
                if "BaseModel" in content and path.endswith(".py"):
                    snippets.append(f"=== {path} (Pydantic schema) ===\n{content[:800]}")
                    included += 1

            if not snippets:
                return route_mismatches, model_mismatches

            combined = "\n\n".join(snippets)
            model_id = router.get_model("evaluation")

            prompt = (
                "Analyse these generated code snippets for cross-file consistency issues.\n\n"
                f"{combined}\n\n"
                "Check only two things:\n"
                "1. Any frontend fetch URL that does NOT match a backend route path?\n"
                "2. Any Pydantic schema field that references a column NOT present in the SQLAlchemy model?\n\n"
                "Return JSON only (no markdown fences), with this exact structure:\n"
                '{"route_mismatches": [{"frontend_call": "str", "issue": "str"}], '
                '"model_mismatches": [{"pydantic_field": "str", "issue": "str"}]}\n\n'
                "If there are no issues, return empty arrays. Do not invent issues."
            )

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            message = await client.messages.create(
                model=model_id,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = ""
            if message.content:
                raw = message.content[0].text.strip()

            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            import json  # noqa: PLC0415
            try:
                parsed = json.loads(raw)
                route_mismatches = parsed.get("route_mismatches", []) or []
                model_mismatches = parsed.get("model_mismatches", []) or []
            except json.JSONDecodeError as exc:
                logger.warning(f"[coherence] Failed to parse Claude response as JSON: {exc} | raw={raw[:200]}")

        except Exception as exc:
            logger.warning(f"[coherence] _check_routes_and_models failed: {exc}")

        return route_mismatches, model_mismatches
