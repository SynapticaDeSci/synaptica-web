"""Summary counters for an evidence graph payload."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EvidenceGraphSummaryPayload(BaseModel):
    """Aggregated counts for quick evidence graph inspection."""

    model_config = ConfigDict(extra="ignore")

    artifact_count: int
    cited_artifact_count: int
    filtered_artifact_count: int
    claim_count: int
    link_count: int
