"""Claim-to-artifact link payload for evidence graphs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EvidenceGraphLinkPayload(BaseModel):
    """Directed relation between a claim and an artifact."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    artifact_key: str
    citation_id: str | None = None
    relation_type: str
    link_order: int | None = None
