"""Helpers for deep-research evidence gathering and source validation."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from .planner import SourceRequirements

_ACADEMIC_DOMAINS = (
    "arxiv.org",
    "doi.org",
    "nature.com",
    "sciencedirect.com",
    "springer.com",
    "ieee.org",
    "acm.org",
    "jstor.org",
    "pubmed.ncbi.nlm.nih.gov",
    "biorxiv.org",
    "medrxiv.org",
)

_PRIMARY_HINTS = (
    ".gov",
    "ministry",
    "state.gov",
    "treasury.gov",
    "whitehouse.gov",
    "imf.org",
    "worldbank.org",
    "opec.org",
    "un.org",
    "europa.eu",
    "reuters.com/world",
    "apnews.com",
)

_NEWS_HINTS = (
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "channelnewsasia.com",
    "aljazeera.com",
    "bbc.com",
    "nytimes.com",
)

_LOW_SIGNAL_HINTS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "livestream",
    "/live/",
)

_AGGREGATOR_HINTS = (
    "livemint.com",
    "ts2.tech",
    "oedigital.com",
)

_DATE_META_SELECTORS = (
    ("property", "article:published_time"),
    ("name", "article:published_time"),
    ("property", "og:published_time"),
    ("name", "og:published_time"),
    ("name", "publish-date"),
    ("name", "pubdate"),
    ("name", "parsely-pub-date"),
    ("name", "date"),
    ("itemprop", "datePublished"),
)

_PUBLISHER_META_SELECTORS = (
    ("property", "og:site_name"),
    ("name", "application-name"),
    ("name", "publisher"),
)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = _extract_datetime_from_text(candidate)
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _extract_datetime_from_text(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None

    relative_match = re.search(
        r"\b(?P<count>\d+)\s+(?P<unit>minute|minutes|hour|hours|day|days|week|weeks)\s+ago\b",
        text,
        flags=re.IGNORECASE,
    )
    if relative_match:
        count = int(relative_match.group("count"))
        unit = relative_match.group("unit").lower()
        if unit.startswith("minute"):
            delta = timedelta(minutes=count)
        elif unit.startswith("hour"):
            delta = timedelta(hours=count)
        elif unit.startswith("day"):
            delta = timedelta(days=count)
        else:
            delta = timedelta(weeks=count)
        return datetime.now(UTC) - delta

    for pattern, date_format in (
        (r"\b\d{4}-\d{1,2}-\d{1,2}\b", "%Y-%m-%d"),
        (r"\b\d{4}/\d{1,2}/\d{1,2}\b", "%Y/%m/%d"),
        (r"\b[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\b", "%b %d, %Y"),
        (r"\b[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\b", "%B %d, %Y"),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(0), date_format).replace(tzinfo=UTC)
        except ValueError:
            continue

    slash_match = re.search(r"/(?P<year>20\d{2})/(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/|$)", text)
    if slash_match:
        try:
            return datetime(
                int(slash_match.group("year")),
                int(slash_match.group("month")),
                int(slash_match.group("day")),
                tzinfo=UTC,
            )
        except ValueError:
            return None

    return None


def _infer_published_at(*parts: Any) -> Optional[str]:
    for part in parts:
        if not isinstance(part, str) or not part.strip():
            continue
        parsed = _extract_datetime_from_text(part)
        if parsed is not None:
            return parsed.astimezone(UTC).isoformat()
    return None


def _extract_meta_content(soup: BeautifulSoup, selectors: tuple[tuple[str, str], ...]) -> Optional[str]:
    for attr, value in selectors:
        tag = soup.find("meta", attrs={attr: value})
        content = tag.get("content") if tag else None
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _iter_json_values(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_json_values(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_json_values(item)


def _extract_json_ld_metadata(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    published_at: Optional[str] = None
    publisher: Optional[str] = None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for node in _iter_json_values(payload):
            if not isinstance(node, dict):
                continue
            if published_at is None:
                date_value = (
                    node.get("datePublished")
                    or node.get("dateCreated")
                    or node.get("uploadDate")
                    or node.get("dateModified")
                )
                parsed = _parse_datetime(date_value)
                if parsed is not None:
                    published_at = parsed.isoformat()
            if publisher is None:
                publisher_value = node.get("publisher")
                if isinstance(publisher_value, dict):
                    publisher_value = publisher_value.get("name")
                if isinstance(publisher_value, str) and publisher_value.strip():
                    publisher = publisher_value.strip()
            if published_at and publisher:
                return {"published_at": published_at, "publisher": publisher}

    return {"published_at": published_at, "publisher": publisher}


def infer_publisher(url: str | None, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    if not url:
        return "Unknown"
    netloc = urlparse(url).netloc.lower().strip()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "Unknown"


def infer_source_type(url: str | None, publisher: str | None = None) -> str:
    target = f"{url or ''} {publisher or ''}".lower()
    if any(domain in target for domain in _ACADEMIC_DOMAINS):
        return "academic"
    if any(hint in target for hint in _PRIMARY_HINTS):
        return "primary"
    if any(hint in target for hint in _NEWS_HINTS):
        return "news"
    return "analysis"


def normalize_source_card(
    item: Dict[str, Any],
    *,
    scout_role: str,
    round_number: int,
) -> Dict[str, Any]:
    url = item.get("url")
    publisher = infer_publisher(url, item.get("source") or item.get("publisher"))
    source_type = item.get("source_type") or infer_source_type(url, publisher)
    published_at = (
        item.get("published")
        or item.get("published_at")
        or item.get("published_date")
        or _infer_published_at(
            item.get("url"),
            item.get("title"),
            item.get("content"),
            item.get("snippet"),
        )
    )
    snippet = clean_source_snippet(
        (item.get("content") or item.get("snippet") or item.get("abstract") or "")[:4000]
    )
    quality_flags = score_source_quality(
        {
            "title": item.get("title"),
            "url": url,
            "publisher": publisher,
            "published_at": published_at,
            "source_type": source_type,
            "snippet": snippet,
        }
    )
    return {
        "title": (item.get("title") or "Untitled source")[:240],
        "url": url,
        "publisher": publisher,
        "published_at": published_at,
        "source_type": source_type,
        "snippet": snippet[:1200],
        "display_snippet": snippet[:700],
        "relevance_score": float(item.get("score") or item.get("relevance_score") or 0.0),
        "quality_flags": quality_flags,
        "scout_role": scout_role,
        "round_number": round_number,
    }


def clean_source_snippet(snippet: str | None) -> str:
    if not snippet:
        return ""

    text = snippet.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?:#{2,}\s*)+", "", text)
    text = re.sub(r"\b(?:live|video|shows|shop|stream on|stream logo)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:\b[A-Z][A-Za-z]+\s+News\b\s*){2,}", " ", text)
    text = re.sub(r"(\b[\w'/-]+\b)(?:\s+\1\b){2,}", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[|>]+\s*", " ", text)
    text = re.sub(r"\b(?:additional live streams|watch live|click here|read more)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -|")

    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned_sentences: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        normalized = re.sub(r"\W+", " ", sentence).strip().lower()
        if len(normalized) < 20:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned_sentences.append(sentence.strip())
        if len(" ".join(cleaned_sentences)) >= 700:
            break
    return " ".join(cleaned_sentences)[:700].strip()


def score_source_quality(source: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    url = str(source.get("url") or "").lower()
    publisher = str(source.get("publisher") or "").lower()
    snippet = str(source.get("snippet") or "")
    source_type = str(source.get("source_type") or "")

    if any(hint in url for hint in _LOW_SIGNAL_HINTS):
        flags.append("video_only")
    if any(hint in url or hint in publisher for hint in _AGGREGATOR_HINTS):
        flags.append("aggregator")
    if 0 < len(snippet) < 45:
        flags.append("thin_snippet")
    if snippet.count("###") >= 2 or re.search(r"\b(?:shows|shop|live updates|stream)\b", snippet, re.IGNORECASE):
        flags.append("junk_snippet")
    if source_type == "analysis" and not snippet:
        flags.append("weak_analysis")
    return sorted(set(flags))


def filter_sources_for_curation(
    sources: Iterable[Dict[str, Any]],
    *,
    requirements: SourceRequirements,
    classified_mode: str,
) -> Dict[str, List[Dict[str, Any]]]:
    source_list = [dict(source) for source in sources]
    if classified_mode != "live_analysis":
        return {"selected_sources": source_list, "filtered_sources": []}

    prioritized = sorted(
        source_list,
        key=lambda source: (
            len(source.get("quality_flags") or []),
            0 if str(source.get("source_type") or "") in {"primary", "academic", "news"} else 1,
            -float(source.get("relevance_score") or 0.0),
        ),
    )

    selected: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []
    remaining_total = len(prioritized)
    remaining_fresh = sum(
        1 for source in prioritized if is_fresh_source(source, requirements.freshness_window_days)
    )

    for source in prioritized:
        remaining_total -= 1
        if is_fresh_source(source, requirements.freshness_window_days):
            remaining_fresh -= 1

        quality_flags = list(source.get("quality_flags") or [])
        weak_source = bool(set(quality_flags) & {"video_only", "aggregator", "thin_snippet", "junk_snippet"})

        selected_total = len(selected)
        selected_fresh = sum(
            1 for item in selected if is_fresh_source(item, requirements.freshness_window_days)
        )
        needs_total = selected_total < requirements.total_sources
        needs_fresh = selected_fresh < requirements.min_fresh_sources
        could_still_meet_total = selected_total + remaining_total >= requirements.total_sources
        could_still_meet_fresh = selected_fresh + remaining_fresh >= requirements.min_fresh_sources

        if weak_source and could_still_meet_total and could_still_meet_fresh:
            filtered_source = dict(source)
            filtered_source["filtered_reason"] = ",".join(quality_flags)
            filtered.append(filtered_source)
            continue

        if not weak_source or needs_total or needs_fresh:
            selected.append(source)
        else:
            filtered_source = dict(source)
            filtered_source["filtered_reason"] = ",".join(quality_flags)
            filtered.append(filtered_source)

    for source in filtered:
        if len(selected) >= requirements.total_sources and build_source_summary(
            selected, requirements=requirements
        )["requirements_met"]:
            break
        selected.append({key: value for key, value in source.items() if key != "filtered_reason"})

    return {"selected_sources": selected, "filtered_sources": filtered}


def dedupe_sources(sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        url = (source.get("url") or "").strip().lower()
        title = re.sub(r"\s+", " ", (source.get("title") or "").strip().lower())
        key = url or title
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = dict(source)
            continue
        existing_score = float(existing.get("relevance_score") or 0.0)
        new_score = float(source.get("relevance_score") or 0.0)
        if new_score > existing_score:
            deduped[key] = dict(source)
            existing = deduped[key]
        if not existing.get("published_at") and source.get("published_at"):
            existing["published_at"] = source["published_at"]
        if not existing.get("snippet") and source.get("snippet"):
            existing["snippet"] = source["snippet"]
        if not existing.get("display_snippet") and source.get("display_snippet"):
            existing["display_snippet"] = source["display_snippet"]
        merged_flags = sorted(set(existing.get("quality_flags") or []) | set(source.get("quality_flags") or []))
        if merged_flags:
            existing["quality_flags"] = merged_flags
    return list(deduped.values())


def sort_sources(sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _priority(source: Dict[str, Any]) -> tuple[int, int, float]:
        source_type = str(source.get("source_type") or "")
        source_rank = {"primary": 0, "academic": 1, "news": 2, "analysis": 3}.get(source_type, 4)
        published = _parse_datetime(source.get("published_at"))
        freshness_rank = 0 if published else 1
        return (source_rank, freshness_rank, -float(source.get("relevance_score") or 0.0))

    return sorted(list(sources), key=_priority)


def is_fresh_source(source: Dict[str, Any], freshness_window_days: Optional[int]) -> bool:
    if not freshness_window_days:
        return False
    published = _parse_datetime(source.get("published_at"))
    if not published:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=freshness_window_days)
    return published >= cutoff


def is_academic_or_primary(source: Dict[str, Any]) -> bool:
    return str(source.get("source_type") or "") in {"academic", "primary"}


def build_source_summary(
    sources: Iterable[Dict[str, Any]],
    *,
    requirements: SourceRequirements,
) -> Dict[str, Any]:
    source_list = list(sources)
    fresh_sources = [
        source for source in source_list if is_fresh_source(source, requirements.freshness_window_days)
    ]
    academic_or_primary = [source for source in source_list if is_academic_or_primary(source)]
    return {
        "total_sources": len(source_list),
        "academic_or_primary_sources": len(academic_or_primary),
        "fresh_sources": len(fresh_sources),
        "publishers": sorted(
            {
                str(source.get("publisher"))
                for source in source_list
                if source.get("publisher")
            }
        ),
        "requirements_met": (
            len(source_list) >= requirements.total_sources
            and len(academic_or_primary) >= requirements.min_academic_or_primary
            and len(fresh_sources) >= requirements.min_fresh_sources
        ),
    }


def validate_source_requirements(
    sources: Iterable[Dict[str, Any]],
    *,
    requirements: SourceRequirements,
) -> Dict[str, Any]:
    summary = build_source_summary(sources, requirements=requirements)
    issues: List[str] = []
    if summary["total_sources"] < requirements.total_sources:
        issues.append(
            f"Need at least {requirements.total_sources} sources; found {summary['total_sources']}."
        )
    if summary["academic_or_primary_sources"] < requirements.min_academic_or_primary:
        issues.append(
            "Not enough academic or primary sources "
            f"({summary['academic_or_primary_sources']}/{requirements.min_academic_or_primary})."
        )
    if summary["fresh_sources"] < requirements.min_fresh_sources:
        issues.append(
            "Not enough fresh sources "
            f"({summary['fresh_sources']}/{requirements.min_fresh_sources}) within "
            f"{requirements.freshness_window_days} days."
        )
    return {
        "passed": not issues,
        "issues": issues,
        "summary": summary,
    }


async def search_web(
    *,
    query: str,
    max_results: int = 8,
    time_range: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search the web using Tavily when configured, otherwise fall back to DDG HTML."""

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if api_key:
        payload: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max(1, min(int(max_results), 20)),
            "include_answer": False,
        }
        if time_range:
            payload["time_range"] = time_range
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post("https://api.tavily.com/search", json=payload)
                response.raise_for_status()
            data = response.json()
            return list(data.get("results") or [])
        except Exception:
            pass

    return await _search_duckduckgo_html(query, max_results=max_results)


async def _search_duckduckgo_html(query: str, *, max_results: int) -> List[Dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SynapticaResearch/1.0)"},
            )
            response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    cards: List[Dict[str, Any]] = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")
        if link is None:
            continue
        cards.append(
            {
                "title": link.get_text(strip=True),
                "url": link.get("href"),
                "content": snippet.get_text(" ", strip=True) if snippet else "",
                "score": 0.5,
                "published_date": None,
                "source": infer_publisher(link.get("href")),
            }
        )
    return cards


def build_citation_cards(sources: Iterable[Dict[str, Any]], *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    cards = [
        {
            "title": source.get("title"),
            "url": source.get("url"),
            "publisher": source.get("publisher"),
            "published_at": source.get("published_at"),
            "source_type": source.get("source_type"),
            "display_snippet": source.get("display_snippet"),
            "quality_flags": source.get("quality_flags") or [],
        }
        for source in sources
        if source.get("title") and source.get("url")
    ]
    if limit is not None:
        return cards[:limit]
    return cards


def assign_citation_ids(
    sources: Iterable[Dict[str, Any]],
    *,
    limit: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    selected_sources = [dict(source) for source in sources]
    if limit is not None:
        selected_sources = selected_sources[:limit]

    citations: List[Dict[str, Any]] = []
    updated_sources: List[Dict[str, Any]] = []
    for index, source in enumerate(selected_sources, start=1):
        citation_id = f"S{index}"
        updated = dict(source)
        updated["citation_id"] = citation_id
        citations.append(
            {
                "citation_id": citation_id,
                "title": updated.get("title"),
                "url": updated.get("url"),
                "publisher": updated.get("publisher"),
                "published_at": updated.get("published_at"),
                "source_type": updated.get("source_type"),
                "display_snippet": updated.get("display_snippet"),
                "quality_flags": updated.get("quality_flags") or [],
            }
        )
        updated_sources.append(updated)
    return updated_sources, citations


async def enrich_source_cards(
    sources: Iterable[Dict[str, Any]],
    *,
    max_fetches: int = 8,
) -> List[Dict[str, Any]]:
    source_list = [dict(source) for source in sources]
    candidates = [
        source
        for source in source_list
        if source.get("url")
        and (
            not source.get("published_at")
            or source.get("publisher") in {None, "", "Unknown"}
        )
    ][: max(0, max_fetches)]

    if not candidates:
        return source_list

    semaphore = asyncio.Semaphore(4)

    async with httpx.AsyncClient(
        timeout=8.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SynapticaResearch/1.0)"},
    ) as client:
        async def _enrich(source: Dict[str, Any]) -> None:
            url = source.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                return
            try:
                async with semaphore:
                    response = await client.get(url)
                    response.raise_for_status()
            except Exception:
                return

            soup = BeautifulSoup(response.text, "html.parser")
            if not source.get("published_at"):
                published = _extract_meta_content(soup, _DATE_META_SELECTORS)
                parsed = _parse_datetime(published) if published else None
                if parsed is None:
                    time_tag = soup.find("time")
                    datetime_value = time_tag.get("datetime") if time_tag else None
                    parsed = _parse_datetime(datetime_value) if datetime_value else None
                if parsed is None:
                    json_ld = _extract_json_ld_metadata(soup)
                    parsed = _parse_datetime(json_ld.get("published_at"))
                if parsed is not None:
                    source["published_at"] = parsed.isoformat()

            if source.get("publisher") in {None, "", "Unknown"}:
                publisher = _extract_meta_content(soup, _PUBLISHER_META_SELECTORS)
                if not publisher:
                    publisher = _extract_json_ld_metadata(soup).get("publisher")
                if publisher:
                    source["publisher"] = publisher
                    source["source_type"] = infer_source_type(source.get("url"), publisher)

        await asyncio.gather(*[_enrich(source) for source in candidates])

    return source_list
