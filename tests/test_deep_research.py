from shared.research_runs.deep_research import (
    build_source_summary,
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
