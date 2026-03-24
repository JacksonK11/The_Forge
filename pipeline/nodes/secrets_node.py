"""
pipeline/nodes/secrets_node.py
Generates FLY_SECRETS.txt — the ready-to-run deployment secrets file.

Uses a deterministic template built directly from the spec — no Claude call needed.
Every flyctl secrets set command is included for every service.
"""

from loguru import logger

from pipeline.pipeline import PipelineState


async def generate_secrets_content(state: PipelineState) -> str:
    """Generate the complete FLY_SECRETS.txt content for the run's spec."""
    if not state.spec:
        raise ValueError("Secrets node requires spec")

    content = _build_secrets_content(state.spec)
    logger.info(f"[{state.run_id}] FLY_SECRETS.txt generated ({len(content)} chars)")
    return content


def _build_secrets_content(spec: dict) -> str:
    """Build FLY_SECRETS.txt deterministically from spec — no Claude call required."""
    agent_name = spec.get("agent_name", "Agent")
    lines = [
        f"# FLY_SECRETS.txt — {agent_name}",
        "# Run these commands to configure your Fly.io deployment.",
        "# Replace all REPLACE_WITH_YOUR_VALUE placeholders before running.",
        "# Order matters: set secrets before deploying each service.",
        "",
    ]

    env_vars = spec.get("environment_variables", [])
    services = spec.get("fly_services", [])

    for service in services:
        service_name = service.get("name", "")
        service_type = service.get("type", "")
        lines.append(f"# ── {service_name} ({service_type}) ──────────────────────────────────")
        for env_var in env_vars:
            var_name = env_var.get("name", "")
            description = env_var.get("description", "")
            example = env_var.get("example", "")
            required = env_var.get("required", True)
            if not required:
                lines.append(f"# Optional: {var_name} — {description}")
                lines.append(f"# flyctl secrets set {var_name}={example or 'REPLACE_WITH_YOUR_VALUE'} --app {service_name}")
            else:
                comment = f"  # {description}" if description else ""
                lines.append(
                    f"flyctl secrets set {var_name}={example or 'REPLACE_WITH_YOUR_VALUE'} --app {service_name}{comment}"
                )
        lines.append("")

    # Redeploy reminder
    if services:
        lines.append("# After setting all secrets, deploy each service:")
        for service in services:
            lines.append(f"# flyctl deploy --app {service.get('name', '')}")

    return "\n".join(lines)
