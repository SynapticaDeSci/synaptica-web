"""Shaped evidence payload for a research run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchRunEvidencePayload(BaseModel):
    """Evidence-centric API payload derived from a research run."""

    model_config = ConfigDict(extra="ignore")

    research_run_id: str
    status: str
    claim_targets: list[Any] = Field(default_factory=list)
    rewritten_research_brief: str | None = None
    sources: list[Any] = Field(default_factory=list)
    filtered_sources: list[Any] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    freshness_summary: dict[str, Any] = Field(default_factory=dict)
    search_lanes_used: list[Any] = Field(default_factory=list)
