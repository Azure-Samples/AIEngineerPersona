"""
Wikipedia fetch utility for the RAG feature.

Resolves a user-supplied topic string to the best-matching Wikipedia article
and returns a plain-text extract suitable for injection into an LLM prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_MAX_EXTRACT_CHARS = 10000
_USER_AGENT = "ChildrensStoryApp/1.0 (https://github.com/demo; demo@example.com)"


@dataclass
class WikipediaResult:
    title: str
    extract: str
    url: str


async def fetch_wikipedia(topic: str) -> Optional[WikipediaResult]:
    """
    Fetch a Wikipedia article extract for the given topic.

    1. Uses opensearch to resolve the topic to the best-matching article title.
    2. Fetches the full plain-text extract for that article.
    3. Truncates to _MAX_EXTRACT_CHARS characters.

    Returns None if no article is found or a network/parse error occurs.
    """
    topic = topic.strip()
    if not topic:
        return None

    headers = {"User-Agent": _USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # ── Step 1: Resolve topic to a canonical Wikipedia page title ──────
            search_resp = await client.get(
                _WIKIPEDIA_API,
                params={
                    "action": "opensearch",
                    "search": topic,
                    "limit": 1,
                    "namespace": 0,
                    "format": "json",
                },
                headers=headers,
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()

            titles: list[str] = search_data[1]
            if not titles:
                logger.warning("[Wikipedia] No results found for topic: %r", topic)
                return None

            resolved_title = titles[0]
            article_url = f"https://en.wikipedia.org/wiki/{resolved_title.replace(' ', '_')}"

            # ── Step 2: Fetch plain-text extract for the resolved title ─────────
            extract_resp = await client.get(
                _WIKIPEDIA_API,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": 1,
                    "exsectionformat": "plain",
                    "titles": resolved_title,
                    "format": "json",
                },
                headers=headers,
            )
            extract_resp.raise_for_status()
            extract_data = extract_resp.json()

            pages: dict = extract_data.get("query", {}).get("pages", {})
            if not pages:
                logger.warning("[Wikipedia] Empty pages response for title: %r", resolved_title)
                return None

            page = next(iter(pages.values()))
            extract: str = page.get("extract", "").strip()

            if not extract:
                logger.warning("[Wikipedia] Empty extract for title: %r", resolved_title)
                return None

            # ── Step 3: Truncate to stay within context limits ───────────────────
            if len(extract) > _MAX_EXTRACT_CHARS:
                extract = extract[:_MAX_EXTRACT_CHARS].rsplit(" ", 1)[0] + "..."

            logger.info("[Wikipedia] Fetched %d chars for topic %r → %r", len(extract), topic, resolved_title)

            return WikipediaResult(
                title=resolved_title,
                extract=extract,
                url=article_url,
            )

    except httpx.HTTPError as exc:
        logger.error("[Wikipedia] HTTP error fetching topic %r: %s", topic, exc)
        return None
    except Exception as exc:
        logger.error("[Wikipedia] Unexpected error fetching topic %r: %s", topic, exc)
        return None
