"""
pipeline/nodes/test_generator.py
Generates basic smoke tests for every API route and pipeline node.
Tests run in the sandbox to verify structural correctness before packaging.

Uses Haiku (evaluation model) — cheap, fast.
Tests are basic smoke tests: 20-40 lines each. Goal is catching obvious
structural failures, not comprehensive business logic testing.

Called from codegen_node.py after all layer 1-4 files are generated.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import anthropic
from loguru import logger

from config.model_config import router
from config.settings import settings


# ---------------------------------------------------------------------------
# Minimal hardcoded fallback tests — returned when Claude fails
# ---------------------------------------------------------------------------

_FALLBACK_CONFTEST = """\
from fastapi.testclient import TestClient
from app.api.main import app
import pytest


@pytest.fixture
def client():
    return TestClient(app)
"""

_FALLBACK_HEALTH_TEST = """\
def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_has_status_key(client):
    response = client.get("/health")
    data = response.json()
    assert "status" in data
"""

_FALLBACK_FILES: list[dict] = [
    {"path": "tests/conftest.py", "content": _FALLBACK_CONFTEST},
    {"path": "tests/test_health.py", "content": _FALLBACK_HEALTH_TEST},
]


# ---------------------------------------------------------------------------
# TestGenerator
# ---------------------------------------------------------------------------


class TestGenerator:
    """
    Generates lightweight pytest smoke tests for a Forge-built agent.
    Tests cover every API route and pipeline node at a structural level —
    no mocking, no business logic, just catching obvious failures fast.
    """

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ------------------------------------------------------------------
    # 1. Generate Tests
    # ------------------------------------------------------------------

    async def generate_tests(
        self,
        spec: dict,
        all_files: list[dict],
    ) -> list[dict]:
        """
        Generate smoke test files for the given spec and file list.

        Returns a list of {"path": str, "content": str} dicts.
        Falls back to minimal hardcoded tests if Claude fails.
        """
        try:
            # ---- Extract routes ----------------------------------------
            routes: list[Any] = spec.get("api_routes", []) or spec.get(
                "endpoints", []
            )
            routes_summary = self._summarise_routes(routes)

            # ---- Extract pipeline node paths ---------------------------
            node_paths = [
                f["path"]
                for f in all_files
                if "/nodes/" in f.get("path", "")
                and f.get("path", "").endswith(".py")
            ]

            # ---- Build prompt ------------------------------------------
            node_line = (
                f"\nPIPELINE NODES: {', '.join(node_paths)}\n" if node_paths else ""
            )
            prompt = (
                "Generate basic pytest smoke tests for this FastAPI agent.\n\n"
                f"ROUTES: {routes_summary}"
                f"{node_line}"
                "\nWrite:\n"
                "1. tests/conftest.py with a TestClient fixture:\n"
                "   from fastapi.testclient import TestClient\n"
                "   from app.api.main import app\n"
                "   import pytest\n"
                "   @pytest.fixture\n"
                "   def client(): return TestClient(app)\n\n"
                "2. tests/test_api_smoke.py with one test per route:\n"
                "   - Call endpoint with minimal valid data\n"
                "   - Assert status_code < 500\n"
                "   - Assert response is JSON\n\n"
                "3. tests/test_health.py:\n"
                '   - Test GET /health returns 200\n'
                '   - Test response has "status" key\n\n'
                "Keep each test function under 15 lines. No mocking.\n"
                "Return ONLY valid JSON — no markdown, no code fences:\n"
                '{"files": [{"path": "tests/conftest.py", "content": "..."}, ...]}'
            )

            model = router.get_model("evaluation")
            response = await self._client.messages.create(
                model=model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text.strip()

            # Strip markdown code fences if Claude included them
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                inner = lines[1:] if lines else []
                if inner and not inner[-1].strip("`"):
                    inner = inner
                elif inner and inner[-1].strip() == "```":
                    inner = inner[:-1]
                raw_text = "\n".join(inner).strip()

            parsed = json.loads(raw_text)
            files: list[dict] = parsed.get("files", [])

            if not files:
                logger.warning(
                    "test_generator.generate_tests: Claude returned empty files list — using fallback"
                )
                return _FALLBACK_FILES

            # Validate structure
            validated: list[dict] = []
            for entry in files:
                if isinstance(entry, dict) and "path" in entry and "content" in entry:
                    validated.append(
                        {"path": str(entry["path"]), "content": str(entry["content"])}
                    )

            if not validated:
                logger.warning(
                    "test_generator.generate_tests: no valid file entries after validation — using fallback"
                )
                return _FALLBACK_FILES

            logger.info(
                "test_generator.generate_tests: generated {} test files", len(validated)
            )
            return validated

        except Exception as exc:
            logger.warning(
                "test_generator.generate_tests: Claude call failed — {} — using fallback",
                exc,
            )
            return _FALLBACK_FILES

    # ------------------------------------------------------------------
    # 2. Run Tests in Sandbox
    # ------------------------------------------------------------------

    async def run_tests_in_sandbox(
        self,
        run_id: str,
        sandbox_dir: str,
        test_files: list[dict],
    ) -> dict:
        """
        Write test files into sandbox_dir and execute pytest.

        Returns:
        {
            "total":    int,
            "passed":   int,
            "failed":   int,
            "failures": [str],
        }
        """
        try:
            # ---- Write test files to sandbox ---------------------------
            for file_entry in test_files:
                rel_path: str = file_entry.get("path", "")
                content: str = file_entry.get("content", "")
                if not rel_path:
                    continue
                dest = Path(sandbox_dir) / rel_path
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(content, encoding="utf-8")
                except Exception as write_exc:
                    logger.warning(
                        "test_generator.run_tests_in_sandbox: could not write {} — {}",
                        rel_path,
                        write_exc,
                    )

            tests_dir = str(Path(sandbox_dir) / "tests")

            # ---- Run pytest in subprocess (async) ----------------------
            cmd = [
                "python3",
                "-m",
                "pytest",
                tests_dir,
                "--tb=short",
                "-q",
                "--no-header",
            ]
            logger.debug(
                "test_generator.run_tests_in_sandbox: running pytest in {}",
                tests_dir,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=sandbox_dir,
            )

            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning(
                    "test_generator.run_tests_in_sandbox: pytest timed out after 30s"
                )
                return {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "failures": ["pytest timed out after 30 seconds"],
                }

            output = stdout_bytes.decode("utf-8", errors="replace")
            logger.debug(
                "test_generator.run_tests_in_sandbox: pytest output:\n{}", output
            )

            return self._parse_pytest_output(output)

        except Exception as exc:
            logger.warning(
                "test_generator.run_tests_in_sandbox: error — {}", exc
            )
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "failures": [str(exc)],
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _summarise_routes(self, routes: list[Any]) -> str:
        """Produce a compact human-readable summary of API routes."""
        if not routes:
            return "(no routes defined)"
        parts: list[str] = []
        for route in routes[:30]:  # cap to avoid giant prompts
            if isinstance(route, dict):
                method = route.get("method", route.get("http_method", "GET")).upper()
                path = route.get("path", route.get("url", ""))
                name = route.get("name", route.get("description", ""))
                parts.append(f"{method} {path}" + (f" — {name}" if name else ""))
            elif isinstance(route, str):
                parts.append(route)
        return "\n".join(parts) if parts else "(no routes parsed)"

    def _parse_pytest_output(self, output: str) -> dict:
        """
        Parse the summary line from pytest -q output.

        Examples:
          "5 passed in 0.42s"
          "3 passed, 2 failed in 1.03s"
          "1 error in 0.12s"
        """
        passed = 0
        failed = 0
        errors = 0
        failures: list[str] = []

        passed_match = re.search(r"(\d+)\s+passed", output)
        failed_match = re.search(r"(\d+)\s+failed", output)
        error_match = re.search(r"(\d+)\s+error", output)

        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed = int(failed_match.group(1))
        if error_match:
            errors = int(error_match.group(1))

        total = passed + failed + errors

        # Collect short failure/error lines
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("FAILED") or stripped.startswith("ERROR"):
                failures.append(stripped[:200])

        # Fallback: capture raw output if nothing parsed
        if total == 0 and not failures:
            failures = [output[:500]] if output.strip() else ["No output from pytest"]

        return {
            "total": total,
            "passed": passed,
            "failed": failed + errors,
            "failures": failures,
        }


# ---------------------------------------------------------------------------
# Module-level backward-compatibility wrapper
# ---------------------------------------------------------------------------


async def generate_test_files(state: Any) -> dict[str, str]:
    """
    Module-level wrapper called by codegen_node.py.
    Generates test files and returns {path: content} dict.
    """
    try:
        gen = TestGenerator()
        all_files = [
            {"path": p, "content": c}
            for p, c in (state.generated_files or {}).items()
        ]
        test_file_list = await gen.generate_tests(state.spec or {}, all_files)
        return {f["path"]: f["content"] for f in test_file_list}
    except Exception as exc:
        logger.warning(
            "test_generator.generate_test_files: wrapper error — {}", exc
        )
        return {f["path"]: f["content"] for f in _FALLBACK_FILES}
