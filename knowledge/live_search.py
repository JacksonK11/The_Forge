"""
knowledge/live_search.py
Real-time Tavily web search triggered when a query contains recency signals.

Recency signals: "latest", "new", "current", "2025", "2026", "just released",
"updated", "recent"

Called from context_assembler.py when recency is detected.
Results are included in AssembledContext.live_results and injected into the
Claude prompt as "LIVE SEARCH RESULTS (current, retrieved now)".

Also called directly from pipeline nodes when explicitly needed:
  - parse_node: "latest FastAPI patterns" in blueprint
  - codegen_node: file that references a recently released API

Rate limiting: max 3 calls per pipeline run to preserve Tavily quota.
"""

import re
from typing import Optional

from loguru import logger
from tavily import TavilyClient

from config.settings import settings

tavily_client = TavilyClient(api_key=settings.tavily_api_key)

RECENCY_SIGNALS = re.compile(
    r"\b(latest|newest|new|current|2024|2025|2026|just released|updated|recent)\b",
    re.IGNORECASE,
)


async def live_search(
    query: str,
    max_results: int = 3,
    search_depth: str = "basic",
) -> list[str]:
    """
    Perform a real-time Tavily web search.

    Args:
        query:        The search query.
        max_results:  Maximum number of results to return.
        search_depth: "basic" (fast, cheap) or "advanced" (thorough, costly).

    Returns:
        List of result text strings ready for prompt injection.
        Returns empty list on any error.
    """
    try:
        results = tavily_client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
        )
        chunks: list[str] = []
        for result in results.get("results", []):
            title = result.get("title", "")
            content = result.get("content", "") or result.get("body", "")
            url = result.get("url", "")
            if content:
                chunk = f"[{title}] ({url})\n{content[:800]}"
                chunks.append(chunk)

        logger.debug(f"Live search '{query[:50]}': {len(chunks)} results")
        return chunks

    except Exception as exc:
        logger.warning(f"Live search failed for '{query[:50]}': {exc}")
        return []


async def search_for_current_versions(packages: list[str]) -> dict[str, str]:
    """
    Search for the current latest version of Python packages.
    Used by the code generator to avoid hardcoding stale version numbers.

    Returns dict of package_name → latest_version_string.
    """
    versions: dict[str, str] = {}
    for package in packages:
        try:
            results = await live_search(
                f"pypi {package} latest version 2025",
                max_results=1,
            )
            if results:
                # Best-effort version extraction from search result
                text = results[0]
                version_match = re.search(r"\b(\d+\.\d+[\.\d]*)\b", text)
                if version_match:
                    versions[package] = version_match.group(1)
        except Exception as exc:
            logger.debug(f"Version lookup failed for {package}: {exc}")

    return versions


def has_recency_signal(text: str) -> bool:
    """Check if a query text contains recency signals that warrant live search."""
    return bool(RECENCY_SIGNALS.search(text))
