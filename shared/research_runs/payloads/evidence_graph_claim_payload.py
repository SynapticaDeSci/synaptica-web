"""Claim payload for the evidence graph."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvidenceGraphClaimPayload(BaseModel):
    """Claim plus supporting artifact references."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    claim_order: int
    claim: str
    confidence: str | None = None
    supporting_artifact_keys: list[str] = Field(default_factory=list)
    supporting_citation_ids: list[str] = Field(default_factory=list)
