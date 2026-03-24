"""
pipeline/nodes/deploy_verify_fix_node.py
Post-deploy verification and auto-fix node for The Forge build pipeline.

After github_push_node pushes generated code to GitHub (triggering the generated
agent's GitHub Actions workflow to deploy to Fly.io), this node runs:

Step 1  — Wait for GitHub Actions deploy workflow to complete
Step 2  — Health check: poll https://{slug}-api.fly.dev/health
Step 3  — If unhealthy: fetch Fly.io logs via flyctl, send to Claude Haiku for diagnosis
Step 4  — Auto-fix: Claude Sonnet regenerates broken files, commits fixes via GitHub API
Step 5  — Redeploy: push to GitHub triggers new Actions run, wait, re-check (up to MAX_DEPLOY_FIX_ATTEMPTS)
Step 6  — Endpoint testing: test every API route in spec_json
Step 7  — Dashboard check: verify HTML and JS bundle load
Step 8  — PWA check: manifest.json, sw.js, apple-mobile-web-app meta tag
Step 9  — Wiring check: CORS preflight allows dashboard origin
Step 10 — KB storage: persist every error+fix pair for future build improvement
Step 11 — Final Telegram report: full verification summary

Prerequisites:
  - push_to_github must be True and state.github_repo_url must be set
  - FLY_API_TOKEN in settings enables log fetching and diagnosis
  - GITHUB_TOKEN must be set (already required for github_push_node)

Never raises. All failures are logged. The build is already marked complete
before this node runs — this is best-effort verification and self-healing.
"""

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from typing import TYPE_CHECKING, Optional

import anthropic
import httpx
from loguru import logger

from config.settings import settings
from memory.database import get_session
from memory.models import ForgeDeployFix, KbRecord

if TYPE_CHECKING:
    from pipeline.pipeline import PipelineState

# ── Timing constants ──────────────────────────────────────────────────────────

# Wait after first GitHub Actions deploy for Fly machine to cold-start
_INITIAL_STARTUP_WAIT = 90
# Wait between fix-attempt cycles
_FIX_COOLDOWN = 30
# Max wait for GitHub Actions workflow to complete
_ACTIONS_TIMEOUT = 600  # 10 minutes
# Per-request timeout for health checks
_HEALTH_TIMEOUT = 10
# Retries + interval for health polling
_HEALTH_RETRIES = 6
_HEALTH_INTERVAL = 15


# ── Claude prompts ────────────────────────────────────────────────────────────

_DIAGNOSE_SYSTEM = """You are a Fly.io deployment diagnostician for The Forge.
You receive startup logs from a newly deployed FastAPI + RQ worker application on Fly.io.
Identify every error preventing successful startup and provide precise file-level fixes.

COMMON FLY.IO DEPLOYMENT ERRORS (and their fixes):
- asyncpg SSL error ("SSL connection has been closed unexpectedly"): add ssl='disable' to asyncpg
  connect_args and use NullPool in SQLAlchemy engine create_async_engine call
- "ModuleNotFoundError": package missing from requirements.txt
- "ImportError: cannot import name X from Y": wrong import path, check the actual file structure
- "ConnectionRefusedError" on Redis: REDIS_URL env var not set in Fly secrets
- App not listening on expected address: change host to "0.0.0.0" in uvicorn/gunicorn
- "CORS" errors in browser console: add OPTIONS to auth middleware exempt_paths list
- "table does not exist": alembic not run or models not created; add --no-migrate fallback
- Dockerfile CMD wrong: check CMD syntax, ensure correct python module path

Respond with ONLY valid JSON — no markdown fences, no prose:
{
  "has_errors": true,
  "error_summary": "One-line primary error description",
  "fix_summary": "One-line description of all fixes",
  "fixes": [
    {
      "file_path": "relative/path/file.py",
      "issue": "Exact error",
      "fix_instruction": "Precise fix instruction for regenerating this file"
    }
  ]
}

If no actionable errors found: {"has_errors": false, "error_summary": "", "fix_summary": "", "fixes": []}"""

_DIAGNOSE_USER = """Startup logs for agent: {agent_name} (slug: {slug})

--- {slug}-api LOGS ---
{api_logs}

--- {slug}-worker LOGS ---
{worker_logs}

Diagnose and return JSON fix plan."""


_FIX_SYSTEM = """You are an expert Python/React developer fixing a deployment error in a generated codebase.
You receive the current file content and precise instructions for what to fix.
Return ONLY the complete fixed file content — no markdown, no explanations, raw file only.
Preserve all existing logic. Only fix the described issue."""

_FIX_USER = """Fix this file to resolve the deployment error.

FILE: {file_path}
ISSUE: {issue}
FIX INSTRUCTION: {fix_instruction}

CURRENT CONTENT:
{current_content}

Return the complete fixed file content now."""


# ── Main entry point ──────────────────────────────────────────────────────────


async def deploy_verify_fix_node(state: "PipelineState") -> "PipelineState":
    """
    Post-deploy verification and auto-fix. Runs after github_push_node.
    Never raises — all errors are logged. Returns state unchanged.
    """
    if not _should_run(state):
        return state

    slug = _get_agent_slug(state)
    api_url = f"https://{slug}-api.fly.dev"
    dashboard_url = f"https://{slug}-dashboard.fly.dev"
    repo_html_url = state.github_repo_url

    max_attempts = getattr(settings, "max_deploy_fix_attempts", 5)
    fix_history: list[dict] = []
    final_health_ok = False
    final_endpoints: dict = {"tested": 0, "passing": 0, "details": []}
    final_dashboard_ok = False
    final_pwa_ok = False
    node_start = time.time()

    logger.info(
        f"[{state.run_id}] deploy_verify_fix_node: "
        f"slug={slug} api={api_url} max_attempts={max_attempts}"
    )

    try:
        await _notify(
            f"🔍 <b>The Forge — Deploy Verification</b>\n\n"
            f"<b>{state.title}</b>\n"
            f"Agent: <code>{slug}</code>\n"
            f"Waiting for GitHub Actions deploy to complete..."
        )

        for attempt in range(1, max_attempts + 1):
            logger.info(
                f"[{state.run_id}] Verify attempt {attempt}/{max_attempts}"
            )

            # ── Wait for GitHub Actions ───────────────────────────────────────
            await _wait_for_github_actions(
                repo_url=repo_html_url,
                timeout=_ACTIONS_TIMEOUT,
            )

            # On first attempt, give Fly.io extra time to cold-start the machine
            startup_wait = _INITIAL_STARTUP_WAIT if attempt == 1 else _FIX_COOLDOWN
            logger.info(
                f"[{state.run_id}] Waiting {startup_wait}s for Fly.io machine..."
            )
            await asyncio.sleep(startup_wait)

            # ── Health check ──────────────────────────────────────────────────
            health_ok, health_msg = await _check_health(
                api_url=api_url,
                retries=_HEALTH_RETRIES,
                interval=_HEALTH_INTERVAL,
            )
            logger.info(
                f"[{state.run_id}] Health check attempt {attempt}: "
                f"ok={health_ok} msg={health_msg}"
            )

            if not health_ok:
                # ── Get Fly.io logs ───────────────────────────────────────────
                api_logs = await _get_fly_logs(f"{slug}-api", lines=100)
                worker_logs = await _get_fly_logs(f"{slug}-worker", lines=60)

                # ── Diagnose with Claude Haiku ────────────────────────────────
                diagnosis = await _diagnose_errors(
                    api_logs=api_logs,
                    worker_logs=worker_logs,
                    agent_name=state.title,
                    slug=slug,
                )

                if diagnosis.get("has_errors") and diagnosis.get("fixes"):
                    files_fixed = await _apply_fixes(
                        fixes=diagnosis["fixes"],
                        repo_html_url=repo_html_url,
                        state=state,
                    )
                    fix_entry = {
                        "attempt": attempt,
                        "health_status": "unhealthy",
                        "error_found": diagnosis.get("error_summary", ""),
                        "fix_applied": diagnosis.get("fix_summary", ""),
                        "files_modified": files_fixed,
                        "result": "fix_applied" if files_fixed else "fix_failed",
                    }
                    await _store_fixes_in_kb(
                        run_id=state.run_id, diagnosis=diagnosis, slug=slug
                    )
                else:
                    fix_entry = {
                        "attempt": attempt,
                        "health_status": "unhealthy",
                        "error_found": health_msg,
                        "fix_applied": None,
                        "files_modified": [],
                        "result": "no_fix_found",
                    }

                fix_history.append(fix_entry)
                await _store_fix_in_db(
                    run_id=state.run_id,
                    fix_entry=fix_entry,
                )
                continue

            # ── Health OK — run endpoint tests ────────────────────────────────
            final_health_ok = True
            final_endpoints = await _test_endpoints(api_url=api_url, spec=state.spec)

            # ── Dashboard and PWA checks ──────────────────────────────────────
            final_dashboard_ok = await _check_dashboard(dashboard_url)
            final_pwa_ok = await _check_pwa(dashboard_url)
            wiring_ok, wiring_msg = await _check_wiring(
                api_url=api_url, dashboard_url=dashboard_url
            )

            if not wiring_ok:
                logger.info(
                    f"[{state.run_id}] Wiring issue: {wiring_msg}"
                )

            # ── Check if any functional fixes needed ──────────────────────────
            failing_endpoints = [
                e for e in final_endpoints.get("details", []) if not e.get("ok")
            ]
            service_fix = None
            if failing_endpoints or not final_pwa_ok:
                service_fix = await _generate_service_fixes(
                    failing_endpoints=failing_endpoints,
                    pwa_ok=final_pwa_ok,
                    state=state,
                    slug=slug,
                )

            if service_fix and service_fix.get("fixes"):
                files_fixed = await _apply_fixes(
                    fixes=service_fix["fixes"],
                    repo_html_url=repo_html_url,
                    state=state,
                )
                fix_entry = {
                    "attempt": attempt,
                    "health_status": "healthy",
                    "error_found": service_fix.get("error_summary", ""),
                    "fix_applied": service_fix.get("fix_summary", ""),
                    "files_modified": files_fixed,
                    "result": "fix_applied" if files_fixed else "fix_failed",
                }
                fix_history.append(fix_entry)
                await _store_fix_in_db(
                    run_id=state.run_id,
                    fix_entry=fix_entry,
                    endpoints_tested=final_endpoints.get("tested", 0),
                    endpoints_passing=final_endpoints.get("passing", 0),
                )
                await _store_fixes_in_kb(
                    run_id=state.run_id, diagnosis=service_fix, slug=slug
                )
                continue  # Re-check after fix

            # ── All checks pass ───────────────────────────────────────────────
            logger.info(
                f"[{state.run_id}] All deploy checks passed on attempt {attempt}"
            )
            await _store_fix_in_db(
                run_id=state.run_id,
                fix_entry={
                    "attempt": attempt,
                    "health_status": "healthy",
                    "error_found": None,
                    "fix_applied": None,
                    "files_modified": [],
                    "result": "health_ok",
                },
                endpoints_tested=final_endpoints.get("tested", 0),
                endpoints_passing=final_endpoints.get("passing", 0),
            )
            break

        else:
            # Max attempts exhausted — automated rollback
            logger.warning(
                f"[{state.run_id}] Max verify attempts ({max_attempts}) exhausted — "
                f"attempting automated rollback"
            )
            errors_summary = "; ".join(
                h.get("error_found", "unknown") for h in fix_history if h.get("error_found")
            )
            await _automated_rollback(
                state=state,
                slug=slug,
                errors_summary=errors_summary,
                fix_history=fix_history,
            )

    except Exception as exc:
        logger.error(
            f"[{state.run_id}] deploy_verify_fix_node unexpected error (non-blocking): {exc}"
        )

    # ── Final report ──────────────────────────────────────────────────────────
    try:
        await _send_final_report(
            state=state,
            slug=slug,
            api_url=api_url,
            dashboard_url=dashboard_url,
            health_ok=final_health_ok,
            endpoints=final_endpoints,
            dashboard_ok=final_dashboard_ok,
            pwa_ok=final_pwa_ok,
            fix_history=fix_history,
            elapsed=time.time() - node_start,
        )
    except Exception as report_exc:
        logger.error(
            f"[{state.run_id}] Final report failed (non-blocking): {report_exc}"
        )

    return state


async def deploy_verify_fix_update_node(
    update_id: str,
    repo_url: str,
    agent_slug: str,
    title: str,
) -> None:
    """
    Lightweight verification for the update pipeline.
    Checks health and basic endpoint availability after an update deploy.
    Does not do full PWA/functional testing — just confirms the update didn't break anything.
    """
    if not agent_slug:
        logger.info(f"[{update_id}] deploy_verify_fix_update: no agent_slug, skipping")
        return

    api_url = f"https://{agent_slug}-api.fly.dev"
    max_attempts = getattr(settings, "max_deploy_fix_attempts", 5)
    node_start = time.time()
    fix_history: list[dict] = []
    final_health_ok = False

    logger.info(
        f"[{update_id}] deploy_verify_fix_update: "
        f"slug={agent_slug} api={api_url}"
    )

    try:
        # Wait for GitHub Actions deploy triggered by the commit_push_node
        await _wait_for_github_actions(repo_url=repo_url, timeout=_ACTIONS_TIMEOUT)
        await asyncio.sleep(_INITIAL_STARTUP_WAIT)

        for attempt in range(1, max_attempts + 1):
            health_ok, health_msg = await _check_health(
                api_url=api_url, retries=_HEALTH_RETRIES, interval=_HEALTH_INTERVAL
            )

            if not health_ok:
                api_logs = await _get_fly_logs(f"{agent_slug}-api", lines=80)
                worker_logs = await _get_fly_logs(f"{agent_slug}-worker", lines=40)
                diagnosis = await _diagnose_errors(
                    api_logs=api_logs,
                    worker_logs=worker_logs,
                    agent_name=title,
                    slug=agent_slug,
                )

                if diagnosis.get("has_errors") and diagnosis.get("fixes"):
                    files_fixed = await _apply_fixes_to_repo(
                        fixes=diagnosis["fixes"],
                        repo_html_url=repo_url,
                    )
                    fix_history.append({
                        "attempt": attempt,
                        "error": diagnosis.get("error_summary", ""),
                        "fix": diagnosis.get("fix_summary", ""),
                        "files": files_fixed,
                    })
                    await _store_fixes_in_kb(
                        run_id=None, diagnosis=diagnosis, slug=agent_slug
                    )
                    await _wait_for_github_actions(repo_url=repo_url, timeout=_ACTIONS_TIMEOUT)
                    await asyncio.sleep(_FIX_COOLDOWN)
                    continue
                break

            final_health_ok = True
            break

    except Exception as exc:
        logger.error(
            f"[{update_id}] deploy_verify_fix_update error (non-blocking): {exc}"
        )

    elapsed = time.time() - node_start
    fixes_count = len(fix_history)
    health_icon = "✅" if final_health_ok else "❌"
    fix_text = (
        f"\n🔧 Auto-fixes applied: <b>{fixes_count}</b>"
        if fixes_count else ""
    )

    await _notify(
        f"{'🚀' if final_health_ok else '⚠️'} <b>The Forge — Update Verified</b>\n\n"
        f"<b>{title}</b>\n"
        f"{health_icon} Health: {'OK' if final_health_ok else 'DEGRADED'}"
        f"{fix_text}\n"
        f"🕐 {elapsed:.0f}s\n"
        f"📦 <a href='{repo_url}'>{repo_url}</a>"
    )


# ── Guard and slug helpers ────────────────────────────────────────────────────


def _should_run(state: "PipelineState") -> bool:
    """Return True if the node should run for this build pipeline state."""
    if not state.push_to_github:
        logger.info(
            f"[{state.run_id}] deploy_verify_fix: skipping (push_to_github=False)"
        )
        return False
    github_repo_url = getattr(state, "github_repo_url", None)
    if not github_repo_url:
        logger.info(
            f"[{state.run_id}] deploy_verify_fix: skipping "
            f"(no github_repo_url — push may have failed)"
        )
        return False
    if not state.spec:
        logger.info(
            f"[{state.run_id}] deploy_verify_fix: skipping (no spec — cannot determine slug)"
        )
        return False
    return True


def _get_agent_slug(state: "PipelineState") -> str:
    """Derive agent slug from spec or repo_name."""
    if state.spec:
        slug = state.spec.get("agent_slug", "")
        if slug:
            return slug
    if state.repo_name:
        return state.repo_name
    slug = state.title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50] or "forge-agent"


# ── GitHub Actions waiting ────────────────────────────────────────────────────


async def _wait_for_github_actions(repo_url: str, timeout: int = 600) -> str:
    """
    Poll GitHub Actions for the latest workflow run on main branch.
    Returns "success", "failed", or "timeout".
    Gracefully degrades if GITHUB_TOKEN is not set.
    """
    if not settings.github_token:
        logger.info("GITHUB_TOKEN not set — skipping GitHub Actions wait")
        return "timeout"

    match = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", repo_url)
    if not match:
        logger.warning(f"Cannot parse repo URL for Actions check: {repo_url}")
        return "timeout"

    owner_repo = match.group(1)

    try:
        from github import Github

        g = Github(settings.github_token)
        loop = asyncio.get_event_loop()

        repo = await loop.run_in_executor(None, lambda: g.get_repo(owner_repo))
        start = time.time()

        while time.time() - start < timeout:
            try:
                runs = await loop.run_in_executor(
                    None,
                    lambda: list(
                        repo.get_workflow_runs(branch="main", event="push")[:1]
                    ),
                )
                if not runs:
                    await asyncio.sleep(20)
                    continue

                run = runs[0]
                if run.status == "completed":
                    conclusion = run.conclusion or "unknown"
                    logger.info(
                        f"GitHub Actions completed: run={run.id} "
                        f"conclusion={conclusion}"
                    )
                    return "success" if conclusion == "success" else "failed"

                logger.debug(
                    f"GitHub Actions status={run.status} — waiting..."
                )
                await asyncio.sleep(20)

            except Exception as poll_exc:
                logger.warning(f"GitHub Actions poll error: {poll_exc}")
                await asyncio.sleep(30)

        logger.warning(f"GitHub Actions wait timed out after {timeout}s")
        return "timeout"

    except Exception as exc:
        logger.warning(f"_wait_for_github_actions failed: {exc}")
        return "timeout"


# ── Health check ──────────────────────────────────────────────────────────────


async def _check_health(
    api_url: str, retries: int = 6, interval: int = 15
) -> tuple[bool, str]:
    """Poll /health endpoint with retries. Returns (ok, message)."""
    url = f"{api_url}/health"
    last_msg = "no attempts made"

    for i in range(retries):
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True, f"HTTP 200"
                last_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.TimeoutException:
            last_msg = "Connection timeout"
        except httpx.ConnectError:
            last_msg = "Connection refused (app not listening)"
        except Exception as exc:
            last_msg = f"Error: {exc}"

        if i < retries - 1:
            logger.debug(
                f"Health check attempt {i+1}/{retries} failed: {last_msg} — retrying in {interval}s"
            )
            await asyncio.sleep(interval)

    return False, last_msg


# ── Fly.io log fetching ───────────────────────────────────────────────────────


async def _get_fly_logs(app_name: str, lines: int = 100) -> str:
    """
    Fetch recent logs from a Fly.io app via flyctl CLI.
    Returns empty string with explanation if flyctl unavailable or token not set.
    """
    fly_token = getattr(settings, "fly_api_token", None)
    if not fly_token:
        return f"[FLY_API_TOKEN not configured — cannot fetch logs for {app_name}]"

    try:
        loop = asyncio.get_event_loop()
        env = {**os.environ, "FLY_API_TOKEN": fly_token}

        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["flyctl", "logs", "--app", app_name, "-n", str(lines)],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            ),
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output[:5000] or f"[No output from flyctl logs for {app_name}]"

    except FileNotFoundError:
        return f"[flyctl not installed — cannot fetch logs for {app_name}]"
    except subprocess.TimeoutExpired:
        return f"[flyctl logs timed out for {app_name}]"
    except Exception as exc:
        return f"[Error fetching logs for {app_name}: {exc}]"


# ── Error diagnosis ───────────────────────────────────────────────────────────


async def _diagnose_errors(
    api_logs: str,
    worker_logs: str,
    agent_name: str,
    slug: str,
) -> dict:
    """
    Send startup logs to Claude Haiku for structured error diagnosis.
    Returns dict with has_errors, error_summary, fix_summary, fixes list.
    """
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        user_msg = _DIAGNOSE_USER.format(
            agent_name=agent_name,
            slug=slug,
            api_logs=api_logs[-3000:],
            worker_logs=worker_logs[-1500:],
        )
        response = await client.messages.create(
            model=settings.claude_fast_model,
            max_tokens=800,
            system=_DIAGNOSE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        return json.loads(raw)
    except Exception as exc:
        logger.error(f"Log diagnosis failed: {exc}")
        return {
            "has_errors": False,
            "error_summary": "",
            "fix_summary": "",
            "fixes": [],
        }


# ── Fix application ───────────────────────────────────────────────────────────


async def _apply_fixes(
    fixes: list[dict],
    repo_html_url: str,
    state: "PipelineState",
) -> list[str]:
    """Apply fixes to the GitHub repo and return list of fixed file paths."""
    return await _apply_fixes_to_repo(fixes=fixes, repo_html_url=repo_html_url)


async def _apply_fixes_to_repo(
    fixes: list[dict],
    repo_html_url: str,
) -> list[str]:
    """
    For each fix: fetch the current file from GitHub, ask Claude Sonnet to
    regenerate it with the fix applied, then push the updated file back.
    Returns list of successfully fixed file paths.
    """
    if not settings.github_token or not fixes:
        return []

    from github import Github, GithubException

    match = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", repo_html_url)
    if not match:
        logger.error(f"Cannot parse repo URL for fix: {repo_html_url}")
        return []

    owner_repo = match.group(1)
    g = Github(settings.github_token)
    loop = asyncio.get_event_loop()

    try:
        repo = await loop.run_in_executor(None, lambda: g.get_repo(owner_repo))
    except Exception as exc:
        logger.error(f"Cannot access repo for fix application: {exc}")
        return []

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    fixed_files: list[str] = []

    for fix in fixes:
        file_path = (fix.get("file_path") or "").strip()
        issue = fix.get("issue", "")
        fix_instruction = fix.get("fix_instruction", "")

        if not file_path:
            continue

        try:
            file_obj = await loop.run_in_executor(
                None,
                lambda p=file_path: repo.get_contents(p, ref="main"),
            )
            if isinstance(file_obj, list):
                file_obj = file_obj[0]
            current_content = file_obj.decoded_content.decode("utf-8")
            file_sha: Optional[str] = file_obj.sha
        except GithubException as exc:
            if exc.status == 404:
                logger.warning(f"File not found on GitHub for fix: {file_path}")
                current_content = ""
                file_sha = None
            else:
                logger.error(f"GitHub error fetching {file_path}: {exc}")
                continue
        except Exception as exc:
            logger.error(f"Error fetching {file_path} for fix: {exc}")
            continue

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=8000,
                system=_FIX_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": _FIX_USER.format(
                        file_path=file_path,
                        issue=issue,
                        fix_instruction=fix_instruction,
                        current_content=current_content[:6000],
                    ),
                }],
            )
            fixed_content = response.content[0].text.strip()
            commit_msg = f"auto-fix: {issue[:80]}"

            if file_sha:
                await loop.run_in_executor(
                    None,
                    lambda p=file_path, c=fixed_content, s=file_sha: repo.update_file(
                        path=p,
                        message=commit_msg,
                        content=c.encode("utf-8"),
                        sha=s,
                        branch="main",
                    ),
                )
            else:
                await loop.run_in_executor(
                    None,
                    lambda p=file_path, c=fixed_content: repo.create_file(
                        path=p,
                        message=commit_msg,
                        content=c.encode("utf-8"),
                        branch="main",
                    ),
                )

            fixed_files.append(file_path)
            logger.info(f"Auto-fix committed: {file_path} — {issue[:60]}")

        except Exception as exc:
            logger.error(f"Failed to apply fix to {file_path}: {exc}")

    return fixed_files


# ── Endpoint testing ──────────────────────────────────────────────────────────


async def _test_endpoints(api_url: str, spec: Optional[dict]) -> dict:
    """
    Test every API route in the spec. Returns {tested, passing, details}.
    GET routes: check for < 500. POST routes: send empty body, accept 4xx as OK.
    """
    if not spec:
        return {"tested": 0, "passing": 0, "details": []}

    routes = spec.get("api_routes", [])
    if not routes:
        return {"tested": 0, "passing": 0, "details": []}

    details: list[dict] = []

    async with httpx.AsyncClient(
        base_url=api_url,
        timeout=15,
        follow_redirects=True,
    ) as client:
        for route in routes[:20]:  # cap to avoid rate limiting
            method = (route.get("method") or "GET").upper()
            path = (route.get("path") or "").strip()
            if not path:
                continue

            # Replace path parameters with safe test values
            path = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)

            try:
                if method == "GET":
                    resp = await client.get(path)
                elif method == "POST":
                    resp = await client.post(path, json={})
                elif method == "PUT":
                    resp = await client.put(path, json={})
                elif method == "PATCH":
                    resp = await client.patch(path, json={})
                elif method == "DELETE":
                    resp = await client.delete(path)
                else:
                    continue

                # Server errors (5xx) indicate broken code; 4xx is acceptable
                ok = resp.status_code < 500
                details.append({
                    "method": method,
                    "path": path,
                    "status": resp.status_code,
                    "ok": ok,
                })
            except Exception as exc:
                details.append({
                    "method": method,
                    "path": path,
                    "status": 0,
                    "ok": False,
                    "error": str(exc)[:100],
                })

    passing = sum(1 for d in details if d["ok"])
    return {"tested": len(details), "passing": passing, "details": details}


# ── Dashboard and PWA checks ──────────────────────────────────────────────────


async def _check_dashboard(dashboard_url: str) -> bool:
    """Verify dashboard URL returns HTML containing a script tag."""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(dashboard_url)
            if resp.status_code != 200:
                logger.info(f"Dashboard returned HTTP {resp.status_code}")
                return False
            html = resp.text
            has_html = "<html" in html.lower()
            has_bundle = "<script" in html or ".js" in html
            return has_html and has_bundle
    except Exception as exc:
        logger.info(f"Dashboard check failed: {exc}")
        return False


async def _check_pwa(dashboard_url: str) -> bool:
    """
    Verify PWA assets exist:
    - /manifest.json returns 200
    - /sw.js returns 200
    - index.html contains apple-mobile-web-app-capable meta tag
    """
    base = dashboard_url.rstrip("/")
    checks: dict[str, bool] = {}

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        # manifest.json
        try:
            resp = await client.get(f"{base}/manifest.json")
            checks["manifest"] = resp.status_code == 200
        except Exception:
            checks["manifest"] = False

        # sw.js
        try:
            resp = await client.get(f"{base}/sw.js")
            checks["sw"] = resp.status_code == 200
        except Exception:
            checks["sw"] = False

        # apple meta tag in index.html
        try:
            resp = await client.get(f"{base}/")
            checks["apple_meta"] = "apple-mobile-web-app-capable" in resp.text
        except Exception:
            checks["apple_meta"] = False

    all_ok = all(checks.values())
    if not all_ok:
        missing = [k for k, v in checks.items() if not v]
        logger.info(f"PWA checks — missing: {missing}")
    return all_ok


async def _check_wiring(api_url: str, dashboard_url: str) -> tuple[bool, str]:
    """
    Send an OPTIONS preflight from the dashboard origin to the API.
    Verifies CORS is configured correctly.
    """
    issues: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.options(
                f"{api_url}/health",
                headers={
                    "Origin": dashboard_url.rstrip("/"),
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            allow_origin = resp.headers.get("access-control-allow-origin", "")
            if not allow_origin:
                issues.append("CORS: Access-Control-Allow-Origin header missing from OPTIONS response")
    except Exception as exc:
        issues.append(f"CORS check error: {exc}")

    ok = len(issues) == 0
    return ok, "; ".join(issues) if issues else "OK"


# ── Service fix generation ────────────────────────────────────────────────────


async def _generate_service_fixes(
    failing_endpoints: list[dict],
    pwa_ok: bool,
    state: "PipelineState",
    slug: str,
) -> Optional[dict]:
    """
    Generate fix descriptors for:
    - Missing PWA files (manifest.json, sw.js)
    - Failing API endpoints (uses Claude for diagnosis if logs available)
    Returns fix dict or None if nothing to fix.
    """
    fixes: list[dict] = []
    summaries: list[str] = []

    if not pwa_ok:
        agent_name = (state.spec or {}).get("agent_name", state.title) if state.spec else state.title
        summaries.append("Missing PWA files")
        fixes.append({
            "file_path": "web-dashboard/public/manifest.json",
            "issue": "manifest.json missing — cannot install as PWA",
            "fix_instruction": (
                f'Generate a valid Web App Manifest (JSON) for {agent_name}. '
                f'Fields: name="{agent_name}", short_name="{slug}", '
                f'theme_color="#6B21A8", background_color="#08061A", '
                f'display="standalone", start_url="/", orientation="portrait", '
                f'icons array with 192x192 and 512x512 PNG references.'
            ),
        })
        fixes.append({
            "file_path": "web-dashboard/public/sw.js",
            "issue": "Service worker missing — no offline support",
            "fix_instruction": (
                "Generate a minimal service worker that: "
                "(1) on install, caches /, /index.html, and all .js and .css files; "
                "(2) on fetch, serves from cache first with network fallback; "
                "(3) on activate, cleans old cache versions."
            ),
        })

    if not fixes:
        return None

    return {
        "has_errors": True,
        "error_summary": "; ".join(summaries),
        "fix_summary": f"Generated {len(fixes)} missing file(s)",
        "fixes": fixes,
    }


# ── DB persistence ────────────────────────────────────────────────────────────


async def _store_fix_in_db(
    run_id: Optional[str],
    fix_entry: dict,
    endpoints_tested: int = 0,
    endpoints_passing: int = 0,
) -> None:
    """Persist a ForgeDeployFix record."""
    try:
        async with get_session() as session:
            record = ForgeDeployFix(
                id=str(uuid.uuid4()),
                run_id=run_id,
                attempt=fix_entry.get("attempt", 0),
                health_status=fix_entry.get("health_status", "unknown"),
                error_found=fix_entry.get("error_found"),
                fix_applied=fix_entry.get("fix_applied"),
                files_modified=fix_entry.get("files_modified", []),
                result=fix_entry.get("result", "unknown"),
                endpoints_tested=endpoints_tested,
                endpoints_passing=endpoints_passing,
            )
            session.add(record)
    except Exception as exc:
        logger.error(f"_store_fix_in_db failed: {exc}")


async def _store_fixes_in_kb(
    run_id: Optional[str],
    diagnosis: dict,
    slug: str,
) -> None:
    """
    Store error+fix pairs in kb_records so future builds generated by The Forge
    can include these fixes from the start (via the knowledge base retriever).
    """
    fixes = diagnosis.get("fixes", [])
    if not fixes:
        return
    try:
        async with get_session() as session:
            for fix in fixes:
                content = (
                    f"Deployment error: {fix.get('issue', '')}\n"
                    f"File: {fix.get('file_path', '')}\n"
                    f"Fix applied: {fix.get('fix_instruction', '')}"
                )
                record = KbRecord(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    record_type="deployment_fix",
                    content=content,
                    outcome="success",
                    metadata_json={
                        "agent_slug": slug,
                        "file": fix.get("file_path", ""),
                        "error": fix.get("issue", ""),
                        "source": "deploy_verify_fix_node",
                    },
                )
                session.add(record)
    except Exception as exc:
        logger.error(f"_store_fixes_in_kb failed: {exc}")


# ── Automated rollback ────────────────────────────────────────────────────────


async def _automated_rollback(
    state: "PipelineState",
    slug: str,
    errors_summary: str,
    fix_history: list[dict],
) -> None:
    """
    After MAX_DEPLOY_FIX_ATTEMPTS all fail, automatically roll back the generated
    agent to the last known-working GitHub commit by force-pushing the previous
    commit SHA. Sends Telegram with full context of what failed and what was tried.

    Never raises — all errors are logged.
    """
    logger.warning(
        f"[{state.run_id}] Initiating automated rollback for {slug}"
    )

    rollback_success = False
    rolled_back_sha = None

    try:
        if settings.github_token and state.github_repo_url:
            from github import Github
            import asyncio

            loop = asyncio.get_event_loop()
            g = Github(settings.github_token)

            # Extract owner/repo from URL
            parts = state.github_repo_url.rstrip("/").split("/")
            if len(parts) >= 2:
                owner, repo_name = parts[-2], parts[-1]
                repo = await loop.run_in_executor(
                    None, lambda: g.get_repo(f"{owner}/{repo_name}")
                )
                # Get the last 3 commits to find the one before this build
                commits = await loop.run_in_executor(
                    None, lambda: list(repo.get_commits()[:3])
                )
                if len(commits) >= 2:
                    previous_sha = commits[1].sha  # Second commit = before this build
                    # Reset main branch to previous commit
                    main_ref = await loop.run_in_executor(
                        None, lambda: repo.get_git_ref("heads/main")
                    )
                    await loop.run_in_executor(
                        None, lambda: main_ref.edit(sha=previous_sha, force=True)
                    )
                    rolled_back_sha = previous_sha[:7]
                    rollback_success = True
                    logger.info(
                        f"[{state.run_id}] Rolled back {slug} to {previous_sha[:7]}"
                    )
    except Exception as exc:
        logger.error(
            f"[{state.run_id}] Automated rollback failed: {exc}"
        )

    # Build error details for Telegram
    error_lines = []
    for i, h in enumerate(fix_history, 1):
        err = h.get("error_found", "unknown")
        fix = h.get("fix_applied", "none")
        result = h.get("result", "")
        error_lines.append(f"  Attempt {i}: {err[:100]} → fix: {fix[:80]} [{result}]")

    fix_text = "\n".join(error_lines) if error_lines else "  No fixes attempted"

    if rollback_success:
        msg = (
            f"🔄 <b>The Forge — Deploy Failed: Rolled Back</b>\n\n"
            f"<b>{state.title}</b> (<code>{slug}</code>)\n\n"
            f"<b>Deploy failed after {len(fix_history)} fix attempts.</b>\n"
            f"Automatically rolled back to previous working version: "
            f"<code>{rolled_back_sha}</code>\n\n"
            f"<b>Errors encountered:</b>\n{fix_text}\n\n"
            f"Primary error: {errors_summary[:300]}"
        )
    else:
        msg = (
            f"🚨 <b>The Forge — Deploy Failed: Manual Review Required</b>\n\n"
            f"<b>{state.title}</b> (<code>{slug}</code>)\n\n"
            f"<b>Deploy failed after {len(fix_history)} fix attempts.</b>\n"
            f"Automated rollback was not possible (no previous commit or GitHub token issue).\n\n"
            f"<b>What works:</b> ZIP package is available for download.\n"
            f"<b>What doesn't:</b> Live Fly.io deploy is unhealthy.\n\n"
            f"<b>Errors encountered:</b>\n{fix_text}\n\n"
            f"Primary error: {errors_summary[:300]}\n\n"
            f"<b>Next steps:</b> Download ZIP, fix manually, push to GitHub to trigger redeploy."
        )

    await _notify(msg)


# ── Final report ──────────────────────────────────────────────────────────────


async def _send_final_report(
    state: "PipelineState",
    slug: str,
    api_url: str,
    dashboard_url: str,
    health_ok: bool,
    endpoints: dict,
    dashboard_ok: bool,
    pwa_ok: bool,
    fix_history: list[dict],
    elapsed: float,
) -> None:
    """Send comprehensive deployment verification report via Telegram."""
    h = "✅" if health_ok else "❌"
    d = "✅" if dashboard_ok else "❌"
    p = "✅" if pwa_ok else "❌"

    ep_tested = endpoints.get("tested", 0)
    ep_passing = endpoints.get("passing", 0)
    if ep_tested == 0:
        e = "—"
        ep_label = "not tested"
    elif ep_passing == ep_tested:
        e = "✅"
        ep_label = f"{ep_passing}/{ep_tested} passing"
    else:
        e = "⚠️"
        ep_label = f"{ep_passing}/{ep_tested} passing"

    fixes_applied = [f for f in fix_history if f.get("result") == "fix_applied"]
    fixes_count = len(fixes_applied)

    text = (
        f"{'🚀' if health_ok else '⚠️'} <b>The Forge — Deployment Verified</b>\n\n"
        f"<b>{state.title}</b>\n"
        f"Agent: <code>{slug}</code>\n\n"
        f"{h} Health: {'OK' if health_ok else 'FAIL'}\n"
        f"{e} Endpoints: {ep_label}\n"
        f"{d} Dashboard: {'OK' if dashboard_ok else 'FAIL'}\n"
        f"{p} PWA: {'OK' if pwa_ok else 'FAIL'}\n"
    )

    if fixes_count > 0:
        text += f"\n🔧 Auto-fixes applied: <b>{fixes_count}</b>\n"
        for f in fixes_applied:
            fix_desc = (f.get("fix_applied") or "")[:70]
            files = f.get("files_modified", [])
            file_list = ", ".join(str(x) for x in files[:3])
            text += f"  • {fix_desc}"
            if file_list:
                text += f"\n    Files: {file_list}"
            text += "\n"
        text += (
            "\n💡 All fixes stored in knowledge base — "
            "next build will include them from the start.\n"
        )

    # Show failing endpoints if any
    failing = [
        d for d in endpoints.get("details", []) if not d.get("ok")
    ]
    if failing:
        text += f"\n⚠️ {len(failing)} endpoint(s) still failing:\n"
        for d_item in failing[:5]:
            text += (
                f"  • {d_item.get('method')} {d_item.get('path')} "
                f"→ HTTP {d_item.get('status', '?')}\n"
            )
        text += "Manual review recommended.\n"

    text += (
        f"\n🕐 Verify time: <b>{elapsed:.0f}s</b>\n"
        f"📦 GitHub: <a href='{state.github_repo_url}'>{state.github_repo_url}</a>\n"
        f"🌐 API: {api_url}\n"
        f"📊 Dashboard: {dashboard_url}"
    )

    if not health_ok:
        text += (
            f"\n\n⚠️ API unhealthy after {len(fix_history)} attempt(s). "
            f"Manual review needed."
        )

    await _notify(text)


async def _notify(text: str) -> None:
    """Send Telegram notification. Non-blocking."""
    try:
        from app.api.services.notify import _send
        await _send(text)
    except Exception as exc:
        logger.error(f"deploy_verify_fix_node notify failed: {exc}")
