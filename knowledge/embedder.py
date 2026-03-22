"""
knowledge/embedder.py
Splits knowledge articles into 400-token overlapping chunks and generates
OpenAI text-embedding-3-small embeddings for each chunk.

Chunks are stored in knowledge_chunks with their embedding vector.
The overlap (50 tokens) ensures no context is lost at chunk boundaries.

Called after every collection sweep by the scheduler.
Only processes articles that don't yet have chunks — safe to call repeatedly.
"""

import asyncio
from typing import Optional

import tiktoken
from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select

from config.settings import settings
from memory.database import get_session
from memory.models import KnowledgeArticle, KnowledgeChunk

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
tokeniser = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
EMBEDDING_MODEL = "text-embedding-3-small"
EMBED_BATCH_SIZE = 50  # OpenAI embeddings API batch limit


async def run_embedding_sweep(domain_name: Optional[str] = None) -> dict:
    """
    Embed all articles that don't yet have chunks.

    Args:
        domain_name: If provided, only embed articles for this domain.

    Returns:
        Summary dict: articles_processed, chunks_created, errors.
    """
    logger.info("Embedding sweep starting")

    # Find articles without chunks
    async with get_session() as session:
        stmt = (
            select(KnowledgeArticle)
            .outerjoin(
                KnowledgeChunk,
                KnowledgeArticle.id == KnowledgeChunk.article_id,
            )
            .where(KnowledgeChunk.id.is_(None))
        )
        if domain_name:
            stmt = stmt.where(KnowledgeArticle.domain == domain_name)
        result = await session.execute(stmt.order_by(KnowledgeArticle.created_at.desc()).limit(200))
        articles = result.scalars().all()

    logger.info(f"Articles pending embedding: {len(articles)}")
    if not articles:
        return {"articles_processed": 0, "chunks_created": 0, "errors": 0}

    articles_processed = 0
    chunks_created = 0
    errors = 0

    for article in articles:
        try:
            count = await _embed_article(article)
            chunks_created += count
            articles_processed += 1
            logger.debug(f"Embedded '{article.title[:50]}': {count} chunks")
        except Exception as exc:
            logger.error(f"Failed to embed article {article.id}: {exc}")
            errors += 1

    logger.info(
        f"Embedding sweep complete: {articles_processed} articles, "
        f"{chunks_created} chunks, {errors} errors"
    )
    return {
        "articles_processed": articles_processed,
        "chunks_created": chunks_created,
        "errors": errors,
    }


async def _embed_article(article: KnowledgeArticle) -> int:
    """
    Chunk and embed a single article. Returns number of chunks created.
    """
    # Prefer summary for embedding (shorter, denser information)
    text = article.summary or article.title
    if not text or len(text.strip()) < 20:
        return 0

    # Split into overlapping chunks
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    # Batch-generate embeddings
    embeddings = await _generate_embeddings_batch(chunks)

    # Store chunks with embeddings
    async with get_session() as session:
        for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = KnowledgeChunk(
                article_id=article.id,
                chunk_text=chunk_text,
                chunk_index=i,
                embedding=embedding,
            )
            session.add(chunk)

    return len(chunks)


def _chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping chunks of CHUNK_SIZE_TOKENS tokens.
    Uses tiktoken for accurate token counting.
    """
    tokens = tokeniser.encode(text)
    if len(tokens) <= CHUNK_SIZE_TOKENS:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + CHUNK_SIZE_TOKENS, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokeniser.decode(chunk_tokens)
        chunks.append(chunk_text)
        if end >= len(tokens):
            break
        start = end - CHUNK_OVERLAP_TOKENS  # Overlap for context continuity

    return chunks


async def _generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts using OpenAI batch API.
    Processes in batches of EMBED_BATCH_SIZE.
    """
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        try:
            response = await openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
            )
            # API returns embeddings in the same order as input
            batch_embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
            all_embeddings.extend(batch_embeddings)
        except Exception as exc:
            logger.error(f"Embedding batch {i//EMBED_BATCH_SIZE + 1} failed: {exc}")
            # Fill with None placeholders to maintain index alignment
            all_embeddings.extend([None] * len(batch))

    return all_embeddings
