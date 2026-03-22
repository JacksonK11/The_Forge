"""
knowledge/retriever.py
Semantic similarity retrieval from the knowledge base using pgvector.

Queries KnowledgeChunk embeddings for the most semantically relevant chunks
to inject into code generation prompts. Called before every major Claude call
via context_assembler.py.

Returns the top_k most similar chunk texts, deduplicated by article.
"""

from typing import Optional

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select

from config.settings import settings
from memory.database import get_session
from memory.models import KnowledgeArticle, KnowledgeChunk

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

EMBEDDING_MODEL = "text-embedding-3-small"


async def retrieve_relevant_chunks(
    query: str,
    top_k: int = 8,
    domain_filter: Optional[str] = None,
) -> list[str]:
    """
    Retrieve the top_k most semantically relevant knowledge chunks for a query.
    Uses pgvector cosine distance on OpenAI embeddings.

    Args:
        query:         The query text to find similar chunks for.
        top_k:         Number of chunks to return (default 8).
        domain_filter: If provided, only search chunks from this domain.

    Returns:
        List of chunk text strings, ready for prompt injection.
        Returns empty list if knowledge base is empty or retrieval fails.
    """
    try:
        # Quick check — skip if KB is empty
        async with get_session() as session:
            from sqlalchemy import func
            count_result = await session.execute(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.embedding.isnot(None)
                )
            )
            if count_result.scalar_one() == 0:
                return []

        # Generate query embedding
        query_embedding = await _embed_query(query)

        # Vector similarity search
        async with get_session() as session:
            stmt = (
                select(KnowledgeChunk, KnowledgeArticle.domain)
                .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
                .where(KnowledgeChunk.embedding.isnot(None))
                .order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))
                .limit(top_k * 2)  # Fetch more for deduplication
            )
            if domain_filter:
                stmt = stmt.where(KnowledgeArticle.domain == domain_filter)

            result = await session.execute(stmt)
            rows = result.all()

        # Deduplicate by article — return at most 2 chunks per article
        seen_articles: dict[str, int] = {}
        chunks: list[str] = []
        for chunk, domain in rows:
            article_count = seen_articles.get(chunk.article_id, 0)
            if article_count < 2:
                chunks.append(chunk.chunk_text)
                seen_articles[chunk.article_id] = article_count + 1
            if len(chunks) >= top_k:
                break

        logger.debug(f"Retrieved {len(chunks)} knowledge chunks for query: '{query[:50]}'")
        return chunks

    except Exception as exc:
        logger.debug(f"Knowledge retrieval skipped: {exc}")
        return []


async def retrieve_by_domain(domain: str, limit: int = 20) -> list[str]:
    """
    Retrieve recent chunks from a specific domain.
    Used for domain-specific context injection.
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(KnowledgeChunk)
                .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
                .where(KnowledgeArticle.domain == domain)
                .order_by(KnowledgeArticle.created_at.desc())
                .limit(limit)
            )
            chunks = result.scalars().all()
            return [c.chunk_text for c in chunks]
    except Exception as exc:
        logger.warning(f"retrieve_by_domain failed for '{domain}': {exc}")
        return []


async def get_knowledge_stats() -> dict:
    """Return statistics about the knowledge base for dashboard display."""
    try:
        from sqlalchemy import func
        async with get_session() as session:
            articles_result = await session.execute(
                select(KnowledgeArticle.domain, func.count(KnowledgeArticle.id))
                .group_by(KnowledgeArticle.domain)
            )
            chunks_result = await session.execute(
                select(func.count(KnowledgeChunk.id))
            )
            return {
                "articles_by_domain": dict(articles_result.all()),
                "total_chunks": chunks_result.scalar_one(),
            }
    except Exception as exc:
        logger.error(f"get_knowledge_stats failed: {exc}")
        return {"articles_by_domain": {}, "total_chunks": 0}


# ── Internal ──────────────────────────────────────────────────────────────────


async def _embed_query(text: str) -> list[float]:
    """Generate OpenAI embedding for query text."""
    response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],
    )
    return response.data[0].embedding
