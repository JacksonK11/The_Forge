"""
intelligence/context_assembler.py
Assembles optimal context before every major Claude call.

Combines three sources:
  1. Knowledge base — similar past build patterns (pgvector similarity)
  2. Meta-rules — active operational rules extracted from real outcomes
  3. Live search — real-time Tavily results when recency signals detected

The assembled context is injected into Claude prompts to ensure every
generation call benefits from accumulated experience and current knowledge.

Usage:
    from intelligence.context_assembler import assemble_context
    ctx = await assemble_context(query="FastAPI asyncpg connection pool", task_type="generation")
    # ctx.kb_chunks, ctx.meta_rules, ctx.knowledge_chunks, ctx.live_results
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

RECENCY_SIGNALS = re.compile(
    r"\b(latest|newest|new|current|2024|2025|2026|just released|updated|recent)\b",
    re.IGNORECASE,
)


@dataclass
class AssembledContext:
    """Context assembled for a single Claude call."""

    kb_chunks: list[str] = field(default_factory=list)
    meta_rules: list[str] = field(default_factory=list)
    knowledge_chunks: list[str] = field(default_factory=list)
    live_results: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Render the assembled context as a formatted prompt section."""
        parts = []

        if self.meta_rules:
            rules_text = "\n".join(f"- {r}" for r in self.meta_rules)
            parts.append(f"ACTIVE META-RULES (apply these to your output):\n{rules_text}")

        if self.kb_chunks:
            kb_text = "\n\n".join(self.kb_chunks[:4])
            parts.append(f"RELEVANT PAST BUILD PATTERNS:\n{kb_text}")

        if self.knowledge_chunks:
            kb_text = "\n\n".join(self.knowledge_chunks[:4])
            parts.append(f"DOMAIN KNOWLEDGE (current best practices):\n{kb_text}")

        if self.live_results:
            live_text = "\n\n".join(self.live_results[:3])
            parts.append(f"LIVE SEARCH RESULTS (current, retrieved now):\n{live_text}")

        return "\n\n".join(parts)

    def is_empty(self) -> bool:
        return not any([
            self.kb_chunks, self.meta_rules, self.knowledge_chunks, self.live_results
        ])


async def assemble_context(
    query: str,
    task_type: str = "generation",
    run_id: Optional[str] = None,
    include_live_search: bool = True,
) -> AssembledContext:
    """
    Assemble optimal context for a Claude call.
    All sources are fetched concurrently. Individual failures are non-blocking.

    Args:
        query:              The query/question driving context retrieval.
        task_type:          Type of task (affects KB filtering).
        run_id:             Current run ID (for KB filtering).
        include_live_search: Whether to check for recency signals and live search.

    Returns:
        AssembledContext with all available context sources.
    """
    import asyncio

    ctx = AssembledContext()

    # Run all retrieval concurrently
    tasks = [
        _fetch_kb_chunks(query, task_type),
        _fetch_meta_rules(),
        _fetch_knowledge_chunks(query),
    ]

    needs_live_search = (
        include_live_search and bool(RECENCY_SIGNALS.search(query))
    )
    if needs_live_search:
        tasks.append(_fetch_live_results(query))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug(f"Context source {i} failed (non-blocking): {result}")
            continue
        if i == 0:
            ctx.kb_chunks = result or []
            if ctx.kb_chunks:
                ctx.sources_used.append("knowledge_base")
        elif i == 1:
            ctx.meta_rules = result or []
            if ctx.meta_rules:
                ctx.sources_used.append("meta_rules")
        elif i == 2:
            ctx.knowledge_chunks = result or []
            if ctx.knowledge_chunks:
                ctx.sources_used.append("knowledge_engine")
        elif i == 3:
            ctx.live_results = result or []
            if ctx.live_results:
                ctx.sources_used.append("live_search")

    logger.debug(
        f"Context assembled for '{query[:50]}': "
        f"kb={len(ctx.kb_chunks)} rules={len(ctx.meta_rules)} "
        f"knowledge={len(ctx.knowledge_chunks)} live={len(ctx.live_results)}"
    )
    return ctx


# ── Individual fetchers ───────────────────────────────────────────────────────


async def _fetch_kb_chunks(query: str, task_type: str) -> list[str]:
    """Retrieve similar past build patterns from knowledge base."""
    from intelligence.knowledge_base import retrieve_similar
    return await retrieve_similar(query, record_type="build_pattern", top_k=4)


async def _fetch_meta_rules() -> list[str]:
    """Retrieve active meta-rules."""
    from intelligence.meta_rules import get_active_rules
    return await get_active_rules()


async def _fetch_knowledge_chunks(query: str) -> list[str]:
    """Retrieve relevant domain knowledge chunks via pgvector."""
    from knowledge.retriever import retrieve_relevant_chunks
    return await retrieve_relevant_chunks(query, top_k=5)


async def _fetch_live_results(query: str) -> list[str]:
    """Perform real-time web search for queries with recency signals."""
    from knowledge.live_search import live_search
    return await live_search(query)
