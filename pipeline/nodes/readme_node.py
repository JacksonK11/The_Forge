"""
pipeline/nodes/readme_node.py
Generates README.md — the complete deployment guide for the generated agent.

Uses Claude Sonnet with the full spec and file count to produce an accurate,
executable README with real flyctl commands, real service names, and real
environment variable references from the spec.
"""

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.settings import settings
from pipeline.pipeline import PipelineState
from pipeline.prompts.prompts import README_SYSTEM, README_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def generate_readme_content(state: PipelineState) -> str:
    """Generate the complete README.md for the run's spec."""
    if not state.spec:
        raise ValueError("README node requires spec")

    spec = state.spec
    services_text = ", ".join(
        f"{s['name']} ({s.get('type', '')})"
        for s in spec.get("fly_services", [])
    )
    env_vars_text = "\n".join(
        f"  - {v['name']}: {v.get('description', '')}"
        for v in spec.get("environment_variables", [])
    )

    prompt = README_USER.format(
        agent_name=spec.get("agent_name", "Agent"),
        description=spec.get("description", ""),
        services=services_text,
        env_vars=env_vars_text,
        file_count=len(state.generated_files),
    )

    try:
        content = await retry_async(
            _call_claude_for_readme,
            prompt,
            max_attempts=2,
            label=f"readme:{state.run_id}",
        )
        logger.info(f"[{state.run_id}] README.md generated ({len(content)} chars)")
        return content
    except Exception as exc:
        logger.error(f"[{state.run_id}] README generation failed: {exc}")
        return _fallback_readme(spec)


async def _call_claude_for_readme(prompt: str) -> str:
    """Call Claude to generate README.md."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=6000,
        system=README_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _fallback_readme(spec: dict) -> str:
    """Basic fallback README if Claude generation fails."""
    agent_name = spec.get("agent_name", "Agent")
    agent_slug = spec.get("agent_slug", "agent")
    return f"""# {agent_name}

{spec.get("description", "AI Agent built with The Forge.")}

## Quick Start

1. Copy `.env.example` to `.env` and fill in all values
2. Run `docker compose up --build`
3. API available at http://localhost:8000
4. Dashboard available at http://localhost:5173

## Deployment

Run all commands in `FLY_SECRETS.txt` to configure Fly.io secrets.
Push to GitHub to trigger automated deployment via GitHub Actions.

## Services

{chr(10).join(f"- {s['name']}: {s.get('description', '')}" for s in spec.get("fly_services", []))}

## Environment Variables

{chr(10).join(f"- `{v['name']}`: {v.get('description', '')}" for v in spec.get("environment_variables", []))}
"""
