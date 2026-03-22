"""
knowledge/collector.py
Scheduled knowledge sweeps via Tavily web search and RSS feeds.

For each domain in knowledge_config.py:
  1. Run each search query through Tavily
  2. Parse configured RSS feeds
  3. For each article: compute SHA256 content hash, skip duplicates
  4. Call Claude Haiku to summarise each new article
  5. Store in knowledge_articles table

Called daily by the scheduler. Triggers embedder after completion.
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import anthropic
import feedparser
from loguru import logger
from tavily import TavilyClient

from config.knowledge_config import KNOWLEDGE_DOMAINS, KnowledgeDomain
from config.model_config import router
from config.settings import settings
from memory.database import get_session
from memory.models import KnowledgeArticle

anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
tavily_client = TavilyClient(api_key=settings.tavily_api_key)

SUMMARISE_SYSTEM = (
    "You are a technical knowledge summariser. "
    "Given an article about software development, produce a concise summary "
    "focusing on practical patterns, best practices, and actionable insights. "
    "Maximum 200 words. No markdown. Plain text."
)


async def run_collection_sweep(domain_name: Optional[str] = None) -> dict:
    """
    Run a full knowledge collection sweep.

    Args:
        domain_name: If provided, only sweep this domain. Otherwise sweep all.

    Returns:
        Summary dict with articles collected per domain.
    """
    domains = KNOWLEDGE_DOMAINS
    if domain_name:
        domains = [d for d in KNOWLEDGE_DOMAINS if d.name == domain_name]
        if not domains:
            logger.warning(f"Domain '{domain_name}' not found in knowledge_config.py")
            return {}

    logger.info(f"Knowledge collection sweep starting: {len(domains)} domains")
    results: dict[str, int] = {}

    for domain in domains:
        try:
            count = await _sweep_domain(domain)
            results[domain.name] = count
            logger.info(f"Domain '{domain.name}': {count} new articles collected")
            time.sleep(1)  # Brief pause between domains to respect rate limits
        except Exception as exc:
            logger.error(f"Domain '{domain.name}' sweep failed: {exc}")
            results[domain.name] = 0

    total = sum(results.values())
    logger.info(f"Knowledge sweep complete: {total} total new articles across {len(domains)} domains")
    return results


async def _sweep_domain(domain: KnowledgeDomain) -> int:
    """Sweep a single domain via Tavily search and RSS. Returns new article count."""
    collected = 0

    # ── Tavily web search ──────────────────────────────────────────────────────
    for query in domain.search_queries:
        try:
            results = tavily_client.search(
                query=query,
                max_results=3,
                search_depth="basic",
            )
            for result in results.get("results", []):
                url = result.get("url", "")
                title = result.get("title", "")
                raw_content = result.get("content", "") or result.get("body", "")
                if not raw_content:
                    continue

                saved = await _process_article(
                    domain=domain.name,
                    title=title,
                    url=url,
                    raw_content=raw_content,
                    source_type="web",
                )
                if saved:
                    collected += 1
                    if collected >= domain.max_articles_per_sweep:
                        return collected
        except Exception as exc:
            logger.warning(f"Tavily query failed for '{query}': {exc}")

    # ── RSS feeds ──────────────────────────────────────────────────────────────
    for feed_url in domain.rss_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                url = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                if not summary:
                    continue

                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                saved = await _process_article(
                    domain=domain.name,
                    title=title,
                    url=url,
                    raw_content=summary,
                    source_type="rss",
                    published_at=published,
                )
                if saved:
                    collected += 1
        except Exception as exc:
            logger.warning(f"RSS feed failed for '{feed_url}': {exc}")

    return collected


async def _process_article(
    domain: str,
    title: str,
    url: str,
    raw_content: str,
    source_type: str,
    published_at: Optional[datetime] = None,
) -> bool:
    """
    Process a single article: deduplicate, summarise, and store.
    Returns True if the article was new and saved.
    """
    if not raw_content.strip():
        return False

    # Deduplicate by content hash
    content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

    async with get_session() as session:
        from sqlalchemy import select
        existing = await session.execute(
            select(KnowledgeArticle).where(
                KnowledgeArticle.content_hash == content_hash
            )
        )
        if existing.scalar_one_or_none():
            return False

    # Summarise with Claude Haiku (cheap, fast)
    summary = await _summarise_article(title, raw_content)

    # Store article
    async with get_session() as session:
        article = KnowledgeArticle(
            domain=domain,
            title=title[:500],
            url=url[:1000] if url else None,
            summary=summary,
            content_hash=content_hash,
            source_type=source_type,
            published_at=published_at,
        )
        session.add(article)

    logger.debug(f"Collected: [{domain}] {title[:60]}")
    return True


async def _summarise_article(title: str, content: str) -> str:
    """Use Claude Haiku to summarise an article. Returns summary or truncated content."""
    model = router.get_model("summarisation")
    try:
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=300,
            system=SUMMARISE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Article: {title}\n\n{content[:3000]}",
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.warning(f"Article summarisation failed: {exc}")
        return content[:500]
