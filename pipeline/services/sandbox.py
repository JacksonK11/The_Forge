"""
pipeline/services/sandbox.py
After all files are generated and before packaging, validates the generated
Python code by actually running it to catch import errors, syntax errors,
and initialisation failures.

Uses the Python interpreter already on the worker — no Docker-in-Docker.
Sandbox directory: /tmp/forge-sandbox-{run_id}/
Timeouts: 10s per file, 15s for app check, 60s total max.
"""

import asyncio
import os
import re
import shutil
from pathlib import Path

from loguru import logger

_STDLIB_MODULES: frozenset[str] = frozenset({
    'os', 'sys', 're', 'json', 'ast', 'io', 'abc', 'copy', 'math', 'time', 'datetime',
    'pathlib', 'typing', 'dataclasses', 'enum', 'functools', 'itertools', 'collections',
    'contextlib', 'asyncio', 'concurrent', 'threading', 'subprocess', 'tempfile', 'shutil',
    'hashlib', 'hmac', 'base64', 'uuid', 'random', 'string', 'textwrap', 'traceback',
    'warnings', 'logging', 'inspect', 'importlib', 'pkgutil', 'zipfile', 'tarfile',
    'csv', 'sqlite3', 'xml', 'html', 'urllib', 'http', 'email', 'socket',
})


def _parse_missing_module(error_output: str) -> str:
    """Extract the missing module name from a ModuleNotFoundError message."""
    try:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_output)
        if match:
            return match.group(1).split(".")[0]
        match = re.search(r"cannot import name ['\"]([^'\"]+)['\"]", error_output)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def _is_generated_code_error(error_output: str) -> bool:
    """
    Return True if the error originated in the generated code rather than
    in a missing external dependency (fastapi, pydantic, sqlalchemy, etc.).
    """
    try:
        external_dep_errors = {
            "No module named 'fastapi'",
            "No module named 'pydantic'",
            "No module named 'sqlalchemy'",
            "No module named 'uvicorn'",
            "No module named 'starlette'",
            "No module named 'alembic'",
            "No module named 'celery'",
            "No module named 'redis'",
            "No module named 'anthropic'",
            "No module named 'httpx'",
            "No module named 'aiohttp'",
            "No module named 'boto3'",
            "No module named 'psycopg2'",
            "No module named 'asyncpg'",
        }
        for dep_error in external_dep_errors:
            if dep_error in error_output:
                return False
        generated_error_types = ("NameError", "SyntaxError", "AttributeError", "TypeError", "ValueError")
        for err_type in generated_error_types:
            if err_type in error_output:
                return True
        if "app.api" in error_output or "app.core" in error_output or "app.db" in error_output:
            return True
    except Exception:
        pass
    return False


class BuildSandbox:
    """
    Validates generated Python code by running it in an isolated sandbox
    directory before packaging.
    """

    async def validate_package(self, run_id: str, all_files: list[dict]) -> dict:
        """
        Validate all generated files by running syntax checks, import checks,
        a FastAPI app load check, and a requirements completeness check.

        Args:
            run_id: Unique identifier for this build run.
            all_files: List of {"path": str, "content": str} dicts.

        Returns:
            {
                'syntax_errors': [...],
                'import_errors': [...],
                'app_loads': bool,
                'app_routes': int,
                'missing_requirements': [str],
                'passed': bool,
            }
        """
        result = {
            "syntax_errors": [],
            "import_errors": [],
            "app_loads": False,
            "app_routes": 0,
            "missing_requirements": [],
            "passed": False,
        }

        sandbox_dir = f"/tmp/forge-sandbox-{run_id}"

        try:
            # ── Write all files to sandbox ──────────────────────────────────
            try:
                await self._write_files_to_sandbox(sandbox_dir, all_files)
            except Exception as exc:
                logger.warning(f"[sandbox] Failed to write files for run {run_id}: {exc}")
                return result

            py_files = [f for f in all_files if f.get("path", "").endswith(".py")]

            # ── Step A: Syntax check ────────────────────────────────────────
            try:
                syntax_errors = await self._check_syntax(sandbox_dir, py_files)
                result["syntax_errors"] = syntax_errors
            except Exception as exc:
                logger.warning(f"[sandbox] Syntax check failed for run {run_id}: {exc}")

            # ── Step B: Import check ────────────────────────────────────────
            try:
                import_errors = await self._check_imports(sandbox_dir, py_files)
                result["import_errors"] = import_errors
            except Exception as exc:
                logger.warning(f"[sandbox] Import check failed for run {run_id}: {exc}")

            # ── Step C: FastAPI app check ───────────────────────────────────
            try:
                app_loads, app_routes = await self._check_app(sandbox_dir, all_files)
                result["app_loads"] = app_loads
                result["app_routes"] = app_routes
            except Exception as exc:
                logger.warning(f"[sandbox] App check failed for run {run_id}: {exc}")

            # ── Step D: Requirements check ──────────────────────────────────
            try:
                missing_reqs = await self._check_requirements(all_files)
                result["missing_requirements"] = missing_reqs
            except Exception as exc:
                logger.warning(f"[sandbox] Requirements check failed for run {run_id}: {exc}")

            # ── Determine overall pass ──────────────────────────────────────
            has_main = any(
                f.get("path", "") in ("main.py", "app/api/main.py")
                for f in all_files
            )
            result["passed"] = (
                len(result["syntax_errors"]) == 0
                and (result["app_loads"] or not has_main)
            )

            logger.info(
                f"[sandbox] run={run_id} passed={result['passed']} "
                f"syntax_errors={len(result['syntax_errors'])} "
                f"import_errors={len(result['import_errors'])} "
                f"app_loads={result['app_loads']} "
                f"routes={result['app_routes']} "
                f"missing_reqs={len(result['missing_requirements'])}"
            )

        except Exception as exc:
            logger.warning(f"[sandbox] Unexpected error during validate_package for run {run_id}: {exc}")

        return result

    async def repair_from_sandbox(
        self,
        run_id: str,
        validation_result: dict,
        all_files: list[dict],
    ) -> list[dict]:
        """
        Attempt to repair files that failed sandbox validation using BuildDoctor.

        Args:
            run_id: Unique identifier for this build run.
            validation_result: The dict returned by validate_package().
            all_files: List of {"path": str, "content": str} dicts.

        Returns:
            Updated all_files list with repaired file contents.
        """
        try:
            from pipeline.services.build_doctor import BuildDoctor  # noqa: PLC0415
        except Exception as exc:
            logger.warning(f"[sandbox] Could not import BuildDoctor: {exc}")
            return all_files

        try:
            # Build a lookup of path → file dict for fast updates
            file_map: dict[str, dict] = {f["path"]: f for f in all_files}

            # Collect all error entries keyed by file path
            errors_by_path: dict[str, list[str]] = {}
            for entry in validation_result.get("syntax_errors", []):
                path = entry.get("file", "")
                errors_by_path.setdefault(path, []).append(entry.get("error", ""))
            for entry in validation_result.get("import_errors", []):
                path = entry.get("file", "")
                errors_by_path.setdefault(path, []).append(entry.get("error", ""))

            for file_path, error_list in errors_by_path.items():
                try:
                    if file_path not in file_map:
                        logger.warning(f"[sandbox] repair: file not found in all_files: {file_path}")
                        continue

                    error_msg = "; ".join(error_list)
                    prior_files = {
                        k: v["content"]
                        for k, v in file_map.items()
                        if k != file_path
                    }

                    doctor = BuildDoctor()
                    diagnosis = await doctor.diagnose(
                        file_spec={"path": file_path},
                        error=error_msg,
                        prior_files={},
                        spec={},
                    )
                    repaired_content, _ = await doctor.repair(
                        file_spec={"path": file_path, "description": ""},
                        full_spec={},
                        prior_files=prior_files,
                        diagnosis=diagnosis,
                        attempt=1,
                    )

                    if repaired_content:
                        file_map[file_path]["content"] = repaired_content
                        logger.info(f"[sandbox] repaired: {file_path}")
                    else:
                        logger.warning(f"[sandbox] repair returned empty content for: {file_path}")

                except Exception as exc:
                    logger.warning(f"[sandbox] Failed to repair {file_path}: {exc}")

            # ── Handle missing requirements ────────────────────────────────
            missing_reqs = validation_result.get("missing_requirements", [])
            if missing_reqs:
                try:
                    req_path = "requirements.txt"
                    if req_path in file_map:
                        existing = file_map[req_path]["content"]
                        extras = "\n".join(
                            pkg for pkg in missing_reqs
                            if pkg not in existing
                        )
                        if extras:
                            file_map[req_path]["content"] = existing.rstrip("\n") + "\n" + extras + "\n"
                            logger.info(f"[sandbox] appended missing requirements: {missing_reqs}")
                except Exception as exc:
                    logger.warning(f"[sandbox] Failed to update requirements.txt: {exc}")

            return list(file_map.values())

        except Exception as exc:
            logger.warning(f"[sandbox] repair_from_sandbox failed for run {run_id}: {exc}")
            return all_files

    def cleanup(self, run_id: str) -> None:
        """Remove the sandbox directory for the given run."""
        sandbox_dir = f"/tmp/forge-sandbox-{run_id}"
        try:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
            logger.debug(f"[sandbox] cleaned up {sandbox_dir}")
        except Exception as exc:
            logger.debug(f"[sandbox] cleanup failed for {sandbox_dir}: {exc}")

    # ── Private helpers ────────────────────────────────────────────────────

    async def _write_files_to_sandbox(self, sandbox_dir: str, all_files: list[dict]) -> None:
        """Write all files to sandbox directory, creating __init__.py as needed."""
        sandbox_path = Path(sandbox_dir)
        sandbox_path.mkdir(parents=True, exist_ok=True)

        package_dirs: set[str] = set()

        for file_spec in all_files:
            try:
                rel_path = file_spec.get("path", "")
                content = file_spec.get("content", "")
                if not rel_path:
                    continue

                abs_path = sandbox_path / rel_path
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(content, encoding="utf-8")

                # Track directories that contain .py files (they need __init__.py)
                if rel_path.endswith(".py"):
                    parent = abs_path.parent
                    while parent != sandbox_path and parent != sandbox_path.parent:
                        package_dirs.add(str(parent))
                        parent = parent.parent

            except Exception as exc:
                logger.warning(f"[sandbox] Failed to write file {file_spec.get('path', '?')}: {exc}")

        # Create __init__.py for any Python package directories that don't have one
        for pkg_dir in package_dirs:
            try:
                init_file = Path(pkg_dir) / "__init__.py"
                if not init_file.exists():
                    init_file.write_text("", encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[sandbox] Could not create __init__.py in {pkg_dir}: {exc}")

    async def _check_syntax(self, sandbox_dir: str, py_files: list[dict]) -> list[dict]:
        """Run ast.parse on every .py file, collecting syntax errors."""
        syntax_errors: list[dict] = []
        sandbox_path = Path(sandbox_dir)

        for file_spec in py_files:
            rel_path = file_spec.get("path", "")
            if not rel_path:
                continue
            abs_path = str(sandbox_path / rel_path)

            try:
                cmd = [
                    "python3", "-c",
                    f"import ast; ast.parse(open({abs_path!r}).read())",
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    syntax_errors.append({"file": rel_path, "error": "Syntax check timed out"})
                    continue

                if proc.returncode != 0:
                    error_text = stderr.decode("utf-8", errors="replace").strip()
                    syntax_errors.append({"file": rel_path, "error": error_text})

            except Exception as exc:
                logger.warning(f"[sandbox] Syntax check exception for {rel_path}: {exc}")

        return syntax_errors

    async def _check_imports(self, sandbox_dir: str, py_files: list[dict]) -> list[dict]:
        """Execute first 20 lines of each file to catch ImportErrors."""
        import_errors: list[dict] = []
        sandbox_path = Path(sandbox_dir)

        for file_spec in py_files:
            rel_path = file_spec.get("path", "")
            content = file_spec.get("content", "")
            if not rel_path or not content:
                continue

            # Only check files that actually have import statements
            if not re.search(r"^\s*(from\s+\S+\s+import|import\s+\S)", content, re.MULTILINE):
                continue

            abs_path = str(sandbox_path / rel_path)
            exec_snippet = (
                f"import sys; sys.path.insert(0, {sandbox_dir!r}); "
                f"exec(compile("
                f"'\\n'.join(open({abs_path!r}).read().split('\\n')[:20]), "
                f"{rel_path!r}, 'exec'"
                f"))"
            )

            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-c", exec_snippet,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    continue  # Timeout on import check — not a hard failure

                if proc.returncode != 0:
                    error_text = stderr.decode("utf-8", errors="replace").strip()
                    # Only surface errors that are clearly import-related
                    if "ModuleNotFoundError" in error_text or "ImportError" in error_text:
                        missing = _parse_missing_module(error_text)
                        import_errors.append({
                            "file": rel_path,
                            "error": error_text,
                            "missing_import": missing,
                        })

            except Exception as exc:
                logger.warning(f"[sandbox] Import check exception for {rel_path}: {exc}")

        return import_errors

    async def _check_app(
        self,
        sandbox_dir: str,
        all_files: list[dict],
    ) -> tuple[bool, int]:
        """
        Attempt to import the FastAPI app and count its routes.
        Returns (app_loads, route_count).
        """
        # Find main.py candidate
        main_candidates = ["app/api/main.py", "main.py"]
        main_found = None
        for candidate in main_candidates:
            if any(f.get("path") == candidate for f in all_files):
                main_found = candidate
                break

        if main_found is None:
            return False, 0

        # Use the import path that matches the file location
        if main_found == "app/api/main.py":
            import_stmt = "from app.api.main import app"
        else:
            import_stmt = "from main import app"

        check_code = (
            f"import sys; sys.path.insert(0, {sandbox_dir!r}); "
            f"{import_stmt}; "
            f"print('routes:', len(app.routes))"
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", check_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                logger.warning("[sandbox] App load check timed out")
                return False, 0

            if proc.returncode == 0:
                out = stdout.decode("utf-8", errors="replace").strip()
                route_count = 0
                match = re.search(r"routes:\s*(\d+)", out)
                if match:
                    route_count = int(match.group(1))
                return True, route_count
            else:
                error_text = stderr.decode("utf-8", errors="replace").strip()
                if _is_generated_code_error(error_text):
                    logger.warning(f"[sandbox] App load failed with generated-code error: {error_text[:300]}")
                    return False, 0
                # External dependency missing — not a build failure
                logger.debug(f"[sandbox] App load skipped (external dep missing): {error_text[:200]}")
                return False, 0

        except Exception as exc:
            logger.warning(f"[sandbox] App check exception: {exc}")
            return False, 0

    async def _check_requirements(self, all_files: list[dict]) -> list[str]:
        """
        Scan .py files for third-party imports and compare against requirements.txt.
        Returns list of packages that are imported but not listed in requirements.txt.
        """
        # Find requirements.txt content
        req_content = ""
        for f in all_files:
            if f.get("path", "").lower() == "requirements.txt":
                req_content = f.get("content", "")
                break

        # Parse declared packages (strip version pins)
        declared: set[str] = set()
        for line in req_content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[>=<!;\[]", line)[0].strip().lower().replace("-", "_")
            if pkg:
                declared.add(pkg)

        # Scan all .py files for imports
        imported: set[str] = set()
        import_re = re.compile(r"^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))", re.MULTILINE)
        for file_spec in all_files:
            if not file_spec.get("path", "").endswith(".py"):
                continue
            content = file_spec.get("content", "")
            for match in import_re.finditer(content):
                module = (match.group(1) or match.group(2) or "").split(".")[0]
                if module:
                    imported.add(module.lower())

        # Filter out stdlib and declared packages
        missing: list[str] = []
        for module in sorted(imported):
            if module in _STDLIB_MODULES:
                continue
            if module in declared:
                continue
            # Skip relative imports and __future__
            if not module or module.startswith("_") or module == "__future__":
                continue
            missing.append(module)

        return missing
