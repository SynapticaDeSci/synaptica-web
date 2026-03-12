"""Serialized evidence artifact payload."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.database import EvidenceArtifact


class EvidenceArtifactPayload(BaseModel):
    """Public payload describing a persisted evidence artifact."""

    model_config = ConfigDict(extra="ignore")

    artifact_key: str
    citation_id: Optional[str] = None
    artifact_type: Optional[str] = None
    origin_node_id: Optional[str] = None
    last_seen_node_id: Optional[str] = None
    order_index: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    normalized_url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    display_snippet: Optional[str] = None
    relevance_score: Optional[float] = None
    curation_status: Optional[str] = None
    quality_flags: list[str] = Field(default_factory=list)
    filtered_reason: Optional[str] = None
    freshness_metadata: dict[str, Any] = Field(default_factory=dict)

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

    @classmethod
    def from_record(cls, artifact: EvidenceArtifact) -> "EvidenceArtifactPayload":
        return cls(
            artifact_key=artifact.artifact_key,
            citation_id=artifact.citation_id,
            artifact_type=artifact.artifact_type,
            origin_node_id=artifact.origin_node_id,
            last_seen_node_id=artifact.last_seen_node_id,
            order_index=artifact.order_index,
            title=artifact.title,
            url=artifact.url,
            normalized_url=artifact.normalized_url,
            publisher=artifact.publisher,
            published_at=artifact.published_at,
            source_type=artifact.source_type,
            snippet=artifact.snippet,
            display_snippet=artifact.display_snippet,
            relevance_score=artifact.relevance_score,
            curation_status=artifact.curation_status,
            quality_flags=artifact.quality_flags or [],
            filtered_reason=artifact.filtered_reason,
            freshness_metadata=dict(artifact.freshness_metadata or {}),
        )
