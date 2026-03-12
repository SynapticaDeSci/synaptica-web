"""Typed source payload used for evidence artifact upserts."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchRunSourcePayload(BaseModel):
    """Normalized source/citation input used for artifact persistence."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    citation_id: Optional[str] = None
    artifact_type: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    display_snippet: Optional[str] = None
    filtered_reason: Optional[str] = None
    relevance_score: Optional[float] = None
    quality_flags: list[str] = Field(default_factory=list)

    @field_validator(
        "citation_id",
        "artifact_type",
        "title",
        "url",
        "publisher",
        "published_at",
        "source_type",
        "snippet",
        "display_snippet",
        "filtered_reason",
        mode="before",
    )
    @classmethod
    def _coerce_optional_string(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _coerce_relevance_score(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @field_validator("quality_flags", mode="before")
    @classmethod
    def _coerce_quality_flags(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            trimmed = item.strip()
            if trimmed:
                normalized.append(trimmed)
        return normalized
