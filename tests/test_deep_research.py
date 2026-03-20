import pytest

from shared.research_runs.deep_research import (
    assess_source_quality_tier,
    assign_citation_ids,
    build_source_summary,
    clean_source_snippet,
    enrich_source_cards,
    filter_sources_for_curation,
    is_fresh_source,
    normalize_source_card,
)
from shared.research_runs.planner import SourceRequirements


def test_normalize_source_card_infers_published_at_from_url_path():
    source = normalize_source_card(
        {
            "title": "Oil prices soar as conflict intensifies",
            "url": "https://www.reuters.com/business/energy/example-story-2026-03-09/",
            "content": "Governments scramble to contain fallout.",
            "score": 0.9,
        },
        scout_role="breaking-news-scout",
        round_number=1,
    )

    assert source["published_at"] == "2026-03-09T00:00:00+00:00"
    assert source["source_type"] == "news"


def test_source_summary_counts_fresh_sources_with_inferred_dates():
    requirements = SourceRequirements(
        total_sources=3,
        min_fresh_sources=2,
        freshness_window_days=7,
    )
    sources = [
        normalize_source_card(
            {
                "title": "Latest Reuters oil update",
                "url": "https://www.reuters.com/world/middle-east/story-2026-03-09/",
                "content": "Published today",
            },
            scout_role="breaking-news-scout",
            round_number=1,
        ),
        normalize_source_card(
            {
                "title": "AP market reaction",
                "url": "https://apnews.com/article/example-2026-03-08",
                "content": "Published yesterday",
            },
            scout_role="market-impact-scout",
            round_number=1,
        ),
        normalize_source_card(
            {
                "title": "Background analysis",
                "url": "https://example.com/analysis/2026/02/20/context",
                "content": "Longer-term context",
            },
            scout_role="context-scout",
            round_number=1,
        ),
    ]

    summary = build_source_summary(sources, requirements=requirements)

    assert summary["total_sources"] == 3
    assert summary["fresh_sources"] == 2
    assert summary["requirements_met"] is True
    assert is_fresh_source(sources[0], requirements.freshness_window_days) is True
    assert is_fresh_source(sources[2], requirements.freshness_window_days) is False


def test_clean_source_snippet_removes_repeated_live_stream_chrome():
    cleaned = clean_source_snippet(
        "## ABC News ## Live ## Video ## Shows ## Shop ## Stream on stream logo ## Live Updates "
        "Iran war ## Oil prices surge amid war in Iran ### March 7, 2026 ### Additional Live Streams"
    )

    assert "Stream on" not in cleaned
    assert "Additional Live Streams" not in cleaned
    assert "Oil prices surge amid war in Iran" in cleaned


def test_filter_sources_for_curation_drops_low_signal_live_sources_when_not_needed():
    requirements = SourceRequirements(
        total_sources=2,
        min_fresh_sources=1,
        freshness_window_days=7,
    )
    strong_source = normalize_source_card(
        {
            "title": "Reuters oil market update",
            "url": "https://www.reuters.com/world/example-2026-03-09/",
            "content": "Governments scramble to limit fallout as oil prices surge and shipping risk grows.",
            "score": 0.9,
        },
        scout_role="breaking-news-scout",
        round_number=1,
    )
    second_strong_source = normalize_source_card(
        {
            "title": "AP market reaction",
            "url": "https://apnews.com/article/example-2026-03-08",
            "content": "Regional escalation drove a fresh risk premium into crude benchmarks.",
            "score": 0.88,
        },
        scout_role="market-impact-scout",
        round_number=1,
    )
    weak_source = normalize_source_card(
        {
            "title": "Oil Surge Spooks Markets as Iran War Escalates - YouTube",
            "url": "https://www.youtube.com/watch?v=example",
            "content": "Live Video Shows Shop Stream on stream logo",
            "score": 0.95,
        },
        scout_role="breaking-news-scout",
        round_number=1,
    )

    filtered = filter_sources_for_curation(
        [strong_source, second_strong_source, weak_source],
        requirements=requirements,
        classified_mode="live_analysis",
    )

    assert len(filtered["selected_sources"]) == 2
    assert any(source["title"] == weak_source["title"] for source in filtered["filtered_sources"])


def test_assign_citation_ids_adds_stable_ids_to_sources_and_citations():
    sources = [
        normalize_source_card(
            {
                "title": "Reuters oil market update",
                "url": "https://www.reuters.com/world/example-2026-03-09/",
                "content": "Oil prices rose as markets priced in geopolitical risk.",
            },
            scout_role="breaking-news-scout",
            round_number=1,
        ),
        normalize_source_card(
            {
                "title": "OPEC market note",
                "url": "https://www.opec.org/example",
                "content": "Supply commentary from OPEC.",
            },
            scout_role="official-confirmation",
            round_number=1,
        ),
    ]

    updated_sources, citations = assign_citation_ids(sources)

    assert [source["citation_id"] for source in updated_sources] == ["S1", "S2"]
    assert [citation["citation_id"] for citation in citations] == ["S1", "S2"]
    assert citations[0]["title"] == "Reuters oil market update"


@pytest.mark.asyncio
async def test_enrich_source_cards_skips_private_ip_urls(monkeypatch):
    called = False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def stream(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("private hosts should be rejected before any fetch")

    monkeypatch.setattr("shared.research_runs.deep_research.httpx.AsyncClient", FakeAsyncClient)

    sources = [{"title": "Local service", "url": "http://127.0.0.1/internal", "publisher": "Unknown"}]
    enriched = await enrich_source_cards(sources)

    assert called is False
    assert enriched[0]["publisher"] == "Unknown"
    assert enriched[0].get("published_at") is None


@pytest.mark.asyncio
async def test_enrich_source_cards_skips_non_html_responses(monkeypatch):
    async def _always_safe(url: str) -> bool:
        del url
        return True

    class FakeResponse:
        status_code = 200
        headers = {
            "content-type": "application/pdf",
            "content-length": "256",
        }
        encoding = "utf-8"
        url = "https://example.com/report.pdf"

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b"%PDF-1.4"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def stream(self, *args, **kwargs):
            del args, kwargs
            return FakeStreamContext()

    monkeypatch.setattr("shared.research_runs.deep_research._is_safe_enrichment_url", _always_safe)
    monkeypatch.setattr("shared.research_runs.deep_research.httpx.AsyncClient", FakeAsyncClient)

    sources = [{"title": "Binary file", "url": "https://example.com/report.pdf", "publisher": "Unknown"}]
    enriched = await enrich_source_cards(sources)

    assert enriched[0]["publisher"] == "Unknown"
    assert enriched[0].get("published_at") is None


def _make_sources(count: int, source_type: str = "news", fresh: bool = False) -> list:
    from datetime import datetime, timezone, timedelta
    published = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat() if fresh else "2020-01-01T00:00:00+00:00"
    return [
        {
            "title": f"Source {i}",
            "url": f"https://example.com/{i}",
            "publisher": f"Publisher {i}",
            "published_at": published,
            "source_type": source_type,
            "snippet": f"Content for source {i}",
            "quality_flags": [],
        }
        for i in range(count)
    ]


def test_assess_source_quality_tier_green():
    requirements = SourceRequirements(total_sources=5, min_academic_or_primary=2)
    sources = _make_sources(3, source_type="academic") + _make_sources(3, source_type="news")
    result = assess_source_quality_tier(sources, requirements=requirements)
    assert result["tier"] == "green"
    assert result["warnings"] == []


def test_assess_source_quality_tier_yellow():
    requirements = SourceRequirements(total_sources=15, min_academic_or_primary=5)
    sources = _make_sources(6, source_type="news")
    result = assess_source_quality_tier(sources, requirements=requirements)
    assert result["tier"] == "yellow"
    assert len(result["warnings"]) > 0


def test_assess_source_quality_tier_red():
    requirements = SourceRequirements(total_sources=15, min_academic_or_primary=5)
    sources = _make_sources(2, source_type="news")
    result = assess_source_quality_tier(sources, requirements=requirements)
    assert result["tier"] == "red"
    assert any("limited" in w.lower() for w in result["warnings"])


def test_assess_source_quality_tier_red_no_sources():
    requirements = SourceRequirements(total_sources=10)
    result = assess_source_quality_tier([], requirements=requirements)
    assert result["tier"] == "red"
    assert any("no sources" in w.lower() for w in result["warnings"])
