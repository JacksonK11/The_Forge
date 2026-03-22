"""
intelligence/knowledge_base.py
Stores outcomes from every build operation and retrieves via pgvector similarity.

The agent improves with every run: build patterns, deployment failures,
successful configurations, and architectural decisions are stored here and
retrieved before every major Claude call via semantic similarity search.

Every build stores its outcome in store_build_outcome() after completion.
retrieve_similar() is called from context_assembler.py before code generation.
"""

from typing import Optional

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select

from config.settings import settings
from memory.database import get_session
from memory.models import KbRecord

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


# ── Store operations ──────────────────────────────────────────────────────────


async def store_build_outcome(
    run_id: str,
    agent_name: str,
    agent_slug: str,
    total_files: int,
    failed_files: int,
    external_apis: list[str],
    fly_services: list[str],
    duration_seconds: float,
) -> None:
    """
    Store a build outcome in the knowledge base after every completed pipeline run.
    Called from package_node.py after assembly.
    """
    outcome = "success" if failed_files == 0 else "partial" if failed_files < total_files else "failure"
    content = (
        f"Build pattern for {agent_name} ({agent_slug}). "
        f"APIs: {', '.join(external_apis)}. "
        f"Services: {', '.join(fly_services)}. "
        f"Files: {total_files} generated, {failed_files} failed. "
        f"Duration: {duration_seconds:.0f}s. "
        f"Result: {outcome}."
    )
    await store_record(
        record_type="build_pattern",
        content=content,
        outcome=outcome,
        run_id=run_id,
        metadata={
            "agent_slug": agent_slug,
            "total_files": total_files,
            "failed_files": failed_files,
            "external_apis": external_apis,
            "fly_services": fly_services,
            "duration_seconds": duration_seconds,
        },
    )


async def store_file_pattern(
    run_id: str,
    file_path: str,
    pattern_type: str,
    description: str,
    outcome: str,
) -> None:
    """
    Store a notable file generation pattern — what worked, what failed.
    Called when a file succeeds after retries or fails permanently.
    """
    content = (
        f"File pattern: {file_path}. Type: {pattern_type}. "
        f"{description}. Outcome: {outcome}."
    )
    await store_record(
        record_type="file_pattern",
        content=content,
        outcome=outcome,
        run_id=run_id,
        metadata={"file_path": file_path, "pattern_type": pattern_type},
    )


async def store_deployment_note(
    note_type: str,
    description: str,
    affected_files: list[str],
) -> None:
    """
    Store a deployment-related finding (e.g. missing __init__.py, wrong port config).
    Called from verifier when blocking issues are found.
    """
    content = f"Deployment note [{note_type}]: {description}. Affected: {', '.join(affected_files)}."
    await store_record(
        record_type="deployment_note",
        content=content,
        outcome="warning",
        metadata={"note_type": note_type, "affected_files": affected_files},
    )


async def store_record(
    record_type: str,
    content: str,
    outcome: str,
    run_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """
    Core storage function. Generates embedding and persists KbRecord.
    Returns the record ID.
    """
    try:
        embedding = await _generate_embedding(content)
        async with get_session() as session:
            record = KbRecord(
                run_id=run_id,
                record_type=record_type,
                content=content,
                outcome=outcome,
                embedding=embedding,
                metadata_json=metadata,
            )
            session.add(record)
            await session.flush()
            record_id = record.id
        logger.debug(f"KB stored: type={record_type} outcome={outcome}")
        return record_id
    except Exception as exc:
        logger.error(f"KB store_record failed: {exc}")
        raise


# ── Retrieve operations ───────────────────────────────────────────────────────


async def retrieve_similar(
    query: str,
    record_type: Optional[str] = None,
    top_k: int = 8,
    outcome_filter: Optional[str] = None,
) -> list[str]:
    """
    Retrieve the most semantically similar past records for a given query.
    Uses pgvector cosine similarity on OpenAI embeddings.
    Returns list of content strings ready for prompt injection.
    """
    try:
        query_embedding = await _generate_embedding(query)
        async with get_session() as session:
            stmt = (
                select(KbRecord)
                .where(KbRecord.embedding.isnot(None))
                .order_by(KbRecord.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )
            if record_type:
                stmt = stmt.where(KbRecord.record_type == record_type)
            if outcome_filter:
                stmt = stmt.where(KbRecord.outcome == outcome_filter)
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.content for r in records]
    except Exception as exc:
        logger.warning(f"KB retrieve_similar failed (returning empty): {exc}")
        return []


async def get_recent_outcomes(limit: int = 50) -> list[dict]:
    """
    Return recent build outcomes for meta-rules extraction.
    Called weekly by meta_rules.py.
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(KbRecord)
                .order_by(KbRecord.created_at.desc())
                .limit(limit)
            )
            records = result.scalars().all()
            return [
                {
                    "type": r.record_type,
                    "content": r.content,
                    "outcome": r.outcome,
                    "metadata": r.metadata_json,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]
    except Exception as exc:
        logger.error(f"KB get_recent_outcomes failed: {exc}")
        return []


async def get_record_count() -> int:
    """Return total number of KB records — used by performance monitor."""
    try:
        from sqlalchemy import func
        async with get_session() as session:
            result = await session.execute(select(func.count(KbRecord.id)))
            return result.scalar_one()
    except Exception as exc:
        logger.error(f"KB count failed: {exc}")
        return 0


# ── Internal ──────────────────────────────────────────────────────────────────


async def _generate_embedding(text: str) -> list[float]:
    """Generate OpenAI text-embedding-3-small vector for text."""
    response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],
    )
    return response.data[0].embedding
