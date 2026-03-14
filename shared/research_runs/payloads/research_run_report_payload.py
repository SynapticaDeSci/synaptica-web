"""Shaped report payload for a research run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchRunReportPayload(BaseModel):
    """Report-centric API payload derived from a research run."""

    model_config = ConfigDict(extra="ignore")

    research_run_id: str
    status: str
    answer_markdown: str | None = None
    answer: str | None = None
    claims: list[Any] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)
    limitations: list[Any] = Field(default_factory=list)
    critic_findings: list[Any] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
