"""
pipeline/nodes/architecture_node.py
Stage 4: Architecture Mapping.

Takes the approved spec JSON and produces the definitive build manifest:
- Exact folder structure (mkdir commands)
- Complete ordered file list with layer assignments and dependency map
- No file is ever generated before the file it imports from

This manifest is what the code generator follows strictly. Files are never
generated in the wrong order.
"""

import json

import anthropic
from loguru import logger

from app.api.services.retry import retry_async
from config.settings import settings
from memory.database import get_session
from memory.models import ForgeRun
from pipeline.pipeline import PipelineState
from pipeline.prompts.prompts import ARCHITECTURE_SYSTEM, ARCHITECTURE_USER

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def architecture_node(state: PipelineState) -> PipelineState:
    """
    Generate the build manifest from the approved spec.
    Stores manifest in DB and updates PipelineState.
    """
    if not state.spec:
        raise ValueError("Architecture node requires spec — was parse_node skipped?")

    logger.info(f"[{state.run_id}] Architecture node started")

    manifest = await retry_async(
        _generate_manifest,
        state.spec,
        max_attempts=3,
        label=f"architecture:{state.run_id}",
    )

    # Ensure all standard files are in the manifest (add any missing)
    manifest = _ensure_standard_files(manifest, state.spec)

    # Store manifest in DB
    async with get_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(ForgeRun)
            .where(ForgeRun.run_id == state.run_id)
            .values(
                manifest_json=manifest,
                file_count=len(manifest.get("file_manifest", [])),
            )
        )

    # Pre-create ForgeFile records for all planned files
    await _create_file_records(state.run_id, manifest)

    state.manifest = manifest
    state.current_stage = "generating"

    logger.info(
        f"[{state.run_id}] Architecture complete: "
        f"files={manifest.get('total_files', 0)} "
        f"layers={len(manifest.get('layers_summary', {}))}"
    )
    return state


async def _generate_manifest(spec: dict) -> dict:
    """Use Sonnet to generate the build manifest from spec."""
    from pipeline.nodes.parse_node import _extract_json_from_response, _recover_truncated_json

    # Allow up to 24K chars of spec JSON — large specs need full context
    spec_json_str = json.dumps(spec, indent=2)
    prompt = ARCHITECTURE_USER.format(spec_json=spec_json_str[:24000])
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=64000,
            system=ARCHITECTURE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        was_truncated = response.stop_reason == "max_tokens"
        if was_truncated:
            logger.warning("Architecture manifest hit max_tokens — attempting recovery")

        text = _extract_json_from_response(response.content[0].text.strip())

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            recovered = _recover_truncated_json(text)
            if recovered:
                return recovered
            raise

    except json.JSONDecodeError as exc:
        logger.error(f"Architecture manifest not valid JSON: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Architecture generation error: {exc}")
        raise


def _ensure_standard_files(manifest: dict, spec: dict) -> dict:
    """
    Ensure every agent has the standard required files.
    Adds missing files that every agent must have but Claude might omit.
    """
    existing_paths = {f["path"] for f in manifest.get("file_manifest", [])}
    agent_slug = spec.get("agent_slug", "agent")

    required_files = [
        {"path": "requirements.txt", "layer": 2, "description": "Python package dependencies", "dependencies": []},
        {"path": "docker-compose.yml", "layer": 2, "description": "Local development environment", "dependencies": []},
        {"path": ".env.example", "layer": 2, "description": "Environment variables template", "dependencies": []},
        {"path": ".gitignore", "layer": 6, "description": "Git ignore rules", "dependencies": []},
        {"path": "Dockerfile.api", "layer": 6, "description": "API service Dockerfile", "dependencies": ["requirements.txt"]},
        {"path": "Dockerfile.worker", "layer": 6, "description": "Worker service Dockerfile", "dependencies": ["requirements.txt"]},
        {"path": f"fly.{agent_slug}-api.toml", "layer": 6, "description": "API Fly.io config", "dependencies": []},
        {"path": f"fly.{agent_slug}-worker.toml", "layer": 6, "description": "Worker Fly.io config", "dependencies": []},
        {"path": ".github/workflows/deploy.yml", "layer": 6, "description": "GitHub Actions CI/CD", "dependencies": []},
        {"path": "memory/__init__.py", "layer": 1, "description": "Python package init", "dependencies": []},
        {"path": "memory/models.py", "layer": 1, "description": "SQLAlchemy models", "dependencies": []},
        {"path": "memory/database.py", "layer": 1, "description": "Async database engine", "dependencies": ["memory/models.py"]},
    ]

    for rf in required_files:
        if rf["path"] not in existing_paths:
            manifest["file_manifest"].append(rf)
            logger.debug(f"Added required file to manifest: {rf['path']}")

    # Sort by layer
    manifest["file_manifest"].sort(key=lambda f: (f.get("layer", 9), f.get("path", "")))
    manifest["total_files"] = len(manifest["file_manifest"])

    return manifest


async def _create_file_records(run_id: str, manifest: dict) -> None:
    """Pre-create ForgeFile records for all planned files."""
    async with get_session() as session:
        from memory.models import FileStatus, ForgeFile
        for file_entry in manifest.get("file_manifest", []):
            forge_file = ForgeFile(
                run_id=run_id,
                file_path=file_entry["path"],
                layer=file_entry.get("layer", 1),
                purpose=file_entry.get("description"),
                status=FileStatus.PENDING.value,
            )
            session.add(forge_file)
        logger.info(f"[{run_id}] Created {len(manifest.get('file_manifest', []))} file records")
