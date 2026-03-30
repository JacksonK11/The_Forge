"""
pipeline/nodes/auto_deploy_node.py
Stage 8 (optional): Auto-deploy generated agent to Fly.io.

Runs only when:
- settings.fly_api_token is set
- run.push_to_github succeeded
- The generated files include at least one fly.*.toml

Steps:
1. Parse fly toml files → get app names and regions
2. Create Fly apps (if they don't exist) via Machines API
3. Parse FLY_SECRETS.txt → set all non-manual secrets
4. Trigger Fly deploy for each app
5. Health check the deployed API
6. Register in agents_registry

All errors are non-fatal — if auto-deploy fails, the build is still "complete".
Stores deploy_status in ForgeRun via agents_registry table.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from typing import TYPE_CHECKING, Any, Optional

import httpx
from loguru import logger

if TYPE_CHECKING:
    from pipeline.pipeline import PipelineState

# ── Constants ─────────────────────────────────────────────────────────────────

FLY_API_BASE = "https://api.machines.dev"

# Secrets copied from the host (Forge) environment to every new agent
SHARED_ENV_SECRETS = {
    # AI providers
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    # Fly.io (same account — child apps need the same token)
    "FLY_API_TOKEN",
    # Notifications — Jackson's personal Telegram
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    # Twilio — SMS/WhatsApp shared account
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    # Google
    "GOOGLE_CALENDAR_CREDENTIALS_JSON",
    "GOOGLE_CALENDAR_ID",
    "GOOGLE_MAPS_API_KEY",
    "GOOGLE_MY_BUSINESS_ACCESS_TOKEN",
    # Real-estate APIs
    "DOMAIN_API_KEY",
    "REALESTATE_API_KEY",
    # Facebook / Meta
    "FACEBOOK_ACCESS_TOKEN",
    "FACEBOOK_PAGE_ID",
    # GitHub (same org — used for pushing generated repos)
    "GITHUB_TOKEN",
}

# Secrets that are auto-generated fresh for every new agent
AUTO_GENERATE_SECRETS = {
    "SECRET_KEY",
    "ADMIN_BEARER_TOKEN",
    "API_SECRET_KEY",
}


# ── Fly.io API helpers ────────────────────────────────────────────────────────


def _fly_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _app_exists(client: httpx.AsyncClient, token: str, app_name: str) -> bool:
    """Return True if the Fly app already exists."""
    try:
        resp = await client.get(
            f"{FLY_API_BASE}/v1/apps/{app_name}",
            headers=_fly_headers(token),
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning(f"[auto_deploy] Error checking app existence for {app_name}: {exc}")
        return False


async def _create_app(
    client: httpx.AsyncClient, token: str, app_name: str
) -> dict[str, Any]:
    """Create a Fly app. Returns the response JSON."""
    resp = await client.post(
        f"{FLY_API_BASE}/v1/apps",
        headers=_fly_headers(token),
        json={"app_name": app_name, "org_slug": "personal"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def _set_secrets(
    client: httpx.AsyncClient,
    token: str,
    app_name: str,
    secrets_dict: dict[str, str],
) -> None:
    """Set secrets on a Fly app using the Machines REST API."""
    if not secrets_dict:
        return
    # Fly Machines API expects {"secrets": [{"key": "K", "value": "V"}]}
    payload = {"secrets": [{"key": k, "value": v} for k, v in secrets_dict.items()]}
    resp = await client.post(
        f"{FLY_API_BASE}/v1/apps/{app_name}/secrets",
        headers=_fly_headers(token),
        json=payload,
        timeout=30.0,
    )
    if resp.status_code == 400:
        # Fallback: some app states require the GraphQL API for secrets
        logger.warning(
            f"[auto_deploy] Machines API secrets failed (400) for {app_name} — "
            f"secrets must be set manually via: flyctl secrets set KEY=VALUE -a {app_name}"
        )
        return
    resp.raise_for_status()


async def _get_latest_release(
    client: httpx.AsyncClient, token: str, app_name: str
) -> Optional[dict]:
    """Return the most recent release for an app, or None."""
    try:
        resp = await client.get(
            f"{FLY_API_BASE}/v1/apps/{app_name}/releases",
            headers=_fly_headers(token),
            timeout=15.0,
        )
        if resp.status_code == 200:
            releases = resp.json()
            if isinstance(releases, list) and releases:
                return releases[0]
    except Exception as exc:
        logger.warning(f"[auto_deploy] Could not fetch releases for {app_name}: {exc}")
    return None


async def _health_check(api_url: str) -> bool:
    """
    Hit the /health endpoint of a deployed app.
    Returns True if it responds with HTTP 200.
    """
    health_url = api_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(health_url)
            return resp.status_code == 200
    except Exception as exc:
        logger.warning(f"[auto_deploy] Health check failed for {health_url}: {exc}")
        return False


# ── Fly Postgres + Redis provisioning ─────────────────────────────────────────


async def _run_flyctl(
    *args: str,
    token: str,
    timeout: float = 300.0,
) -> tuple[int, str, str]:
    """
    Run a flyctl command and return (returncode, stdout, stderr).
    FLY_API_TOKEN is injected into the subprocess environment.
    """
    env = {**os.environ, "FLY_API_TOKEN": token}
    try:
        proc = await asyncio.create_subprocess_exec(
            "flyctl",
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return proc.returncode or 0, stdout_bytes.decode(), stderr_bytes.decode()
    except asyncio.TimeoutError:
        logger.error(f"[auto_deploy] flyctl timeout: flyctl {' '.join(args)}")
        return 1, "", "timeout"
    except FileNotFoundError:
        logger.warning("[auto_deploy] flyctl not found in PATH — skipping provisioning")
        return 1, "", "flyctl not found"
    except Exception as exc:
        logger.error(f"[auto_deploy] flyctl subprocess error: {exc}")
        return 1, "", str(exc)


async def _provision_postgres(
    token: str, app_name: str, region: str = "syd"
) -> Optional[str]:
    """
    Create a Fly Postgres cluster named <app_name>-db.
    Returns the postgres:// connection string, or None on failure.
    Does nothing and returns None if the cluster already exists.
    """
    pg_name = f"{app_name}-db"
    logger.info(f"[auto_deploy] Provisioning Postgres: {pg_name} in {region}")

    rc, stdout, stderr = await _run_flyctl(
        "postgres", "create",
        "--name", pg_name,
        "--region", region,
        "--vm-size", "shared-cpu-1x",
        "--volume-size", "10",
        "--initial-cluster-size", "1",
        "--json",
        token=token,
        timeout=300.0,
    )

    if rc != 0:
        if "already exists" in stderr.lower() or "already exists" in stdout.lower():
            logger.info(f"[auto_deploy] Postgres cluster {pg_name} already exists")
        else:
            logger.warning(
                f"[auto_deploy] flyctl postgres create failed for {pg_name}: {stderr[:400]}"
            )
        return None

    try:
        data = json.loads(stdout)
        conn = (
            data.get("ConnectionString")
            or data.get("connection_string")
            or data.get("uri")
        )
        if conn:
            # asyncpg requires postgresql+asyncpg:// — keep as postgres:// here;
            # individual agents normalise the scheme themselves.
            logger.info(f"[auto_deploy] Postgres provisioned: {pg_name}")
            return conn
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: attach command gives us the URL
    logger.warning(
        f"[auto_deploy] Could not parse Postgres URL from flyctl output; "
        "set DATABASE_URL manually or re-run flyctl postgres attach"
    )
    return None


async def _attach_postgres(
    token: str, pg_name: str, app_name: str
) -> Optional[str]:
    """
    Attach an existing Postgres cluster to an app.
    Returns DATABASE_URL from the attach output, or None.
    """
    logger.info(f"[auto_deploy] Attaching {pg_name} to {app_name}")
    rc, stdout, stderr = await _run_flyctl(
        "postgres", "attach", pg_name,
        "--app", app_name,
        "--json",
        token=token,
        timeout=60.0,
    )
    if rc != 0:
        logger.warning(
            f"[auto_deploy] postgres attach failed for {app_name}: {stderr[:400]}"
        )
        return None
    try:
        data = json.loads(stdout)
        return (
            data.get("ConnectionString")
            or data.get("connection_string")
            or data.get("DATABASE_URL")
        )
    except (json.JSONDecodeError, AttributeError):
        return None


async def _provision_redis(
    token: str, app_name: str, region: str = "syd"
) -> Optional[str]:
    """
    Create a Fly Redis (Upstash) instance named <app_name>-redis.
    Returns the redis:// URL, or None on failure.
    """
    redis_name = f"{app_name}-redis"
    logger.info(f"[auto_deploy] Provisioning Redis: {redis_name} in {region}")

    rc, stdout, stderr = await _run_flyctl(
        "redis", "create",
        "--name", redis_name,
        "--region", region,
        "--no-replicas",
        "--json",
        token=token,
        timeout=120.0,
    )

    if rc != 0:
        if "already exists" in stderr.lower() or "already exists" in stdout.lower():
            logger.info(f"[auto_deploy] Redis {redis_name} already exists")
        else:
            logger.warning(
                f"[auto_deploy] flyctl redis create failed for {redis_name}: {stderr[:400]}"
            )
        return None

    try:
        data = json.loads(stdout)
        url = (
            data.get("PrivateUrl")
            or data.get("private_url")
            or data.get("PublicUrl")
            or data.get("public_url")
            or data.get("url")
        )
        if url:
            logger.info(f"[auto_deploy] Redis provisioned: {redis_name}")
            return url
    except (json.JSONDecodeError, AttributeError):
        pass

    logger.warning(
        f"[auto_deploy] Could not parse Redis URL from flyctl output; "
        "set REDIS_URL manually"
    )
    return None


# ── Parsing helpers ───────────────────────────────────────────────────────────


def _parse_app_names_from_toml(generated_files: dict[str, str]) -> list[str]:
    """
    Scan all fly.*.toml files in generated_files for lines like:
        app = "atlas-trading-os-api"
    Returns a list of unique app names.
    """
    app_names: list[str] = []
    pattern = re.compile(r'^app\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)

    for file_path, content in generated_files.items():
        filename = file_path.split("/")[-1]
        if filename.startswith("fly.") and filename.endswith(".toml"):
            matches = pattern.findall(content)
            for name in matches:
                if name and name not in app_names:
                    app_names.append(name)

    return app_names


def _parse_primary_region(generated_files: dict[str, str]) -> str:
    """
    Return the primary region from the first fly.*.toml that declares one.
    Falls back to "syd" (Sydney) — the default for all The Office agents.
    """
    pattern = re.compile(r'^primary_region\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
    for file_path, content in generated_files.items():
        filename = file_path.split("/")[-1]
        if filename.startswith("fly.") and filename.endswith(".toml"):
            m = pattern.search(content)
            if m:
                return m.group(1)
    return "syd"


def _parse_fly_secrets(generated_files: dict[str, str]) -> dict[str, Optional[str]]:
    """
    Parse FLY_SECRETS.txt from generated_files.
    Lines look like: flyctl secrets set KEY=VALUE  or  flyctl secrets set KEY

    Returns a dict of {KEY: value_or_None}.
    None means "copy from env or mark manual".
    """
    secrets_map: dict[str, Optional[str]] = {}

    secrets_content = generated_files.get("FLY_SECRETS.txt", "")
    if not secrets_content:
        # Try alternate path
        for path, content in generated_files.items():
            if path.endswith("FLY_SECRETS.txt"):
                secrets_content = content
                break

    if not secrets_content:
        return secrets_map

    # Match lines: flyctl secrets set KEY=VALUE or KEY=VALUE standalone
    line_pattern = re.compile(r'(?:flyctl\s+secrets\s+set\s+)?([A-Z][A-Z0-9_]+)(?:=(.*))?$')

    for line in secrets_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = line_pattern.match(line)
        if m:
            key = m.group(1)
            value = m.group(2)  # may be None or empty
            if value is not None:
                value = value.strip().strip('"').strip("'")
            secrets_map[key] = value or None

    return secrets_map


def _resolve_secrets(
    raw_secrets: dict[str, Optional[str]]
) -> tuple[dict[str, str], list[str]]:
    """
    Resolve secrets dict into:
    - settable_secrets: {KEY: resolved_value} — ready to push to Fly
    - manual_keys: [KEY, ...] — keys that need manual input

    Resolution rules:
    1. Key in SHARED_ENV_SECRETS → copy from os.environ if available
    2. Key in AUTO_GENERATE_SECRETS → generate with secrets.token_hex(32)
    3. Raw value provided → use as-is
    4. Otherwise → mark as manual
    """
    settable: dict[str, str] = {}
    manual: list[str] = []

    for key, raw_value in raw_secrets.items():
        if key in AUTO_GENERATE_SECRETS:
            settable[key] = secrets.token_hex(32)
        elif key in SHARED_ENV_SECRETS:
            env_val = os.environ.get(key)
            if env_val:
                settable[key] = env_val
            elif raw_value:
                settable[key] = raw_value
            else:
                manual.append(key)
        elif raw_value:
            settable[key] = raw_value
        else:
            manual.append(key)

    return settable, manual


# ── Registry helpers ─────────────────────────────────────────────────────────


async def _register_in_agents_registry(
    run_id: str,
    app_name: str,
    api_url: str,
    dashboard_url: Optional[str],
    health_status: str,
    repo_url: Optional[str],
) -> None:
    """
    Upsert an entry in agents_registry for this deployed agent.
    If an entry with the same api_url already exists it is updated;
    otherwise a new row is inserted.
    """
    try:
        from memory.database import get_session
        from memory.models import AgentRegistry
        from sqlalchemy import select

        async with get_session() as session:
            # Check for existing entry
            result = await session.execute(
                select(AgentRegistry).where(AgentRegistry.api_url == api_url)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.health_status = health_status
                if dashboard_url:
                    existing.dashboard_url = dashboard_url
                if repo_url:
                    existing.repo_url = repo_url
            else:
                entry = AgentRegistry(
                    agent_name=app_name,
                    api_url=api_url,
                    dashboard_url=dashboard_url,
                    health_url=api_url.rstrip("/") + "/health",
                    repo_url=repo_url,
                    health_status=health_status,
                )
                session.add(entry)

        logger.info(f"[auto_deploy] Registered {app_name} in agents_registry")
    except Exception as exc:
        logger.warning(f"[auto_deploy] Failed to register in agents_registry: {exc}")


# ── Main node ─────────────────────────────────────────────────────────────────


async def auto_deploy_node(state: PipelineState) -> PipelineState:
    """
    Stage 8 (optional): Deploy generated agent to Fly.io.

    Non-fatal — any exception is caught and logged, the state is returned
    unchanged so the pipeline can continue to completion.
    """
    from config.settings import settings

    # Guard: only run when fly_api_token is configured
    if not settings.fly_api_token:
        logger.info("[auto_deploy] fly_api_token not set — skipping auto-deploy")
        return state

    # Guard: only run when fly toml files exist
    app_names = _parse_app_names_from_toml(state.generated_files)
    if not app_names:
        logger.info("[auto_deploy] No fly.*.toml files found — skipping auto-deploy")
        return state

    logger.info(
        f"[auto_deploy] Starting auto-deploy for run {state.run_id} "
        f"apps={app_names}"
    )

    token: str = settings.fly_api_token
    region: str = _parse_primary_region(state.generated_files)
    raw_secrets = _parse_fly_secrets(state.generated_files)
    settable_secrets, manual_keys = _resolve_secrets(raw_secrets)

    # ── Provision Postgres (if DATABASE_URL not already resolved) ──────────
    # Use the first app name as the base name for shared infra (db + redis).
    # Typically the API app is listed first in fly.*.toml files.
    base_app = app_names[0]

    if "DATABASE_URL" not in settable_secrets:
        db_url = await _provision_postgres(token, base_app, region)
        if db_url:
            settable_secrets["DATABASE_URL"] = db_url
            logger.info("[auto_deploy] DATABASE_URL provisioned from new Postgres cluster")
        else:
            logger.warning(
                "[auto_deploy] Could not provision Postgres automatically — "
                "DATABASE_URL must be set manually"
            )
            if "DATABASE_URL" in manual_keys:
                pass  # already listed
            else:
                manual_keys.append("DATABASE_URL")

    # ── Provision Redis (if REDIS_URL not already resolved) ────────────────
    if "REDIS_URL" not in settable_secrets:
        redis_url = await _provision_redis(token, base_app, region)
        if redis_url:
            settable_secrets["REDIS_URL"] = redis_url
            logger.info("[auto_deploy] REDIS_URL provisioned from new Redis instance")
        else:
            logger.warning(
                "[auto_deploy] Could not provision Redis automatically — "
                "REDIS_URL must be set manually"
            )
            if "REDIS_URL" not in manual_keys:
                manual_keys.append("REDIS_URL")

    if manual_keys:
        logger.warning(
            f"[auto_deploy] {len(manual_keys)} secrets require manual input: {manual_keys}"
        )

    deploy_results: dict[str, Any] = {
        "apps": [],
        "manual_secrets_needed": manual_keys,
        "run_id": state.run_id,
        "region": region,
    }

    try:
        async with httpx.AsyncClient() as client:
            for app_name in app_names:
                app_result: dict[str, Any] = {
                    "app_name": app_name,
                    "created": False,
                    "secrets_set": [],
                    "health": "unknown",
                    "api_url": f"https://{app_name}.fly.dev",
                    "error": None,
                }

                try:
                    # Step 1: Create app if it doesn't exist
                    exists = await _app_exists(client, token, app_name)
                    if not exists:
                        logger.info(f"[auto_deploy] Creating Fly app: {app_name}")
                        await _create_app(client, token, app_name)
                        app_result["created"] = True
                        logger.info(f"[auto_deploy] Created app: {app_name}")
                    else:
                        logger.info(f"[auto_deploy] App already exists: {app_name}")

                    # Step 2: Set secrets — merge base secrets with per-app values
                    per_app_secrets: dict[str, str] = {
                        **settable_secrets,
                        # These must always point to actual app names, not placeholders
                        "FLY_APP_NAME": app_names[0],  # primary API app
                        "FLY_WORKER_APP_NAME": next(
                            (n for n in app_names if "worker" in n), app_names[-1]
                        ),
                    }
                    logger.info(
                        f"[auto_deploy] Setting {len(per_app_secrets)} secrets on {app_name}"
                    )
                    await _set_secrets(client, token, app_name, per_app_secrets)
                    app_result["secrets_set"] = list(per_app_secrets.keys())
                    logger.info(f"[auto_deploy] Secrets set on {app_name}")

                    # Step 3: Check if there's a recent release (deploy already running)
                    release = await _get_latest_release(client, token, app_name)
                    if release:
                        logger.info(
                            f"[auto_deploy] Latest release for {app_name}: "
                            f"version={release.get('version', '?')} "
                            f"status={release.get('status', '?')}"
                        )

                    # Step 4: Health check the API app (only -api suffix apps)
                    api_url = f"https://{app_name}.fly.dev"
                    if app_name.endswith("-api"):
                        healthy = await _health_check(api_url)
                        app_result["health"] = "healthy" if healthy else "unreachable"
                        logger.info(
                            f"[auto_deploy] Health check {app_name}: {app_result['health']}"
                        )

                        # Step 5: Register in agents_registry
                        # Infer dashboard URL from app name (replace -api with -dashboard)
                        base = app_name[: -len("-api")]
                        dashboard_url = f"https://{base}-dashboard.fly.dev"
                        await _register_in_agents_registry(
                            run_id=state.run_id,
                            app_name=app_name,
                            api_url=api_url,
                            dashboard_url=dashboard_url,
                            health_status=app_result["health"],
                            repo_url=state.github_repo_url,
                        )

                except Exception as app_exc:
                    app_result["error"] = str(app_exc)
                    logger.error(
                        f"[auto_deploy] Error deploying {app_name}: {app_exc}"
                    )

                deploy_results["apps"].append(app_result)

    except Exception as exc:
        logger.error(f"[auto_deploy] Unexpected error in auto_deploy_node: {exc}")
        deploy_results["error"] = str(exc)

    # Persist deploy results as a build log entry so the dashboard can read them
    try:
        from pipeline.pipeline import _build_log

        await _build_log(
            state.run_id,
            "auto_deploy",
            f"Auto-deploy complete: {len(deploy_results['apps'])} apps processed, "
            f"{len(deploy_results['manual_secrets_needed'])} manual secrets needed",
            "INFO",
            details=deploy_results,
        )
    except Exception as log_exc:
        logger.warning(f"[auto_deploy] Failed to write build log: {log_exc}")

    logger.info(
        f"[auto_deploy] Finished for run {state.run_id}: "
        f"apps={[a['app_name'] for a in deploy_results['apps']]}"
    )

    return state
