"""
pipeline/nodes/secrets_node.py
Generates FLY_SECRETS.txt — the ready-to-run deployment secrets file.

Uses Claude Sonnet to produce a complete, accurate FLY_SECRETS.txt
based on the spec's services and environment variables.
Every flyctl secrets set command is included for every service.
"""

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.settings import settings
from pipeline.pipeline import PipelineState
from pipeline.prompts.prompts import SECRETS_SYSTEM, SECRETS_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def generate_secrets_content(state: PipelineState) -> str:
    """Generate the complete FLY_SECRETS.txt content for the run's spec."""
    if not state.spec:
        raise ValueError("Secrets node requires spec")

    spec = state.spec
    services_text = "\n".join(
        f"  - {s['name']} ({s.get('type', 'unknown')}, {s.get('machine', '')}, {s.get('memory', '')})"
        for s in spec.get("fly_services", [])
    )
    env_vars_text = "\n".join(
        f"  - {v['name']}: {v.get('description', '')} (required={v.get('required', True)}, example={v.get('example', 'N/A')})"
        for v in spec.get("environment_variables", [])
    )

    prompt = SECRETS_USER.format(
        spec_summary=f"Agent: {spec.get('agent_name')} ({spec.get('agent_slug')})\n{spec.get('description', '')}",
        services=services_text,
        env_vars=env_vars_text,
    )

    try:
        content = await retry_async(
            _call_claude_for_secrets,
            prompt,
            max_attempts=2,
            label=f"secrets:{state.run_id}",
        )
        logger.info(f"[{state.run_id}] FLY_SECRETS.txt generated ({len(content)} chars)")
        return content
    except Exception as exc:
        logger.error(f"[{state.run_id}] Secrets generation failed: {exc}")
        return _fallback_secrets_content(spec)


async def _call_claude_for_secrets(prompt: str) -> str:
    """Call Claude to generate FLY_SECRETS.txt."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=SECRETS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _fallback_secrets_content(spec: dict) -> str:
    """Generate a basic FLY_SECRETS.txt if Claude call fails."""
    agent_slug = spec.get("agent_slug", "agent")
    lines = [
        f"# FLY_SECRETS.txt — {spec.get('agent_name', 'Agent')}",
        "# Run these commands to configure your Fly.io deployment.",
        "# Replace all REPLACE_WITH_YOUR_VALUE placeholders before running.",
        "",
    ]
    for service in spec.get("fly_services", []):
        service_name = service["name"]
        lines.append(f"# ── {service_name} ──────────────────────────────────")
        for env_var in spec.get("environment_variables", []):
            lines.append(
                f"flyctl secrets set {env_var['name']}=REPLACE_WITH_YOUR_VALUE --app {service_name}"
            )
        lines.append("")
    return "\n".join(lines)
