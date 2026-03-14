"""Persisted Phase 2 evidence graph payload."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .evidence_artifact_payload import EvidenceArtifactPayload
from .evidence_graph_claim_payload import EvidenceGraphClaimPayload
from .evidence_graph_link_payload import EvidenceGraphLinkPayload
from .evidence_graph_summary_payload import EvidenceGraphSummaryPayload


class ResearchRunEvidenceGraphPayload(BaseModel):
    """Public payload for the persisted evidence graph."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str
    research_run_id: str
    title: str
    description: str
    status: str
    workflow: str
    artifacts: list[EvidenceArtifactPayload] = Field(default_factory=list)
    claims: list[EvidenceGraphClaimPayload] = Field(default_factory=list)
    links: list[EvidenceGraphLinkPayload] = Field(default_factory=list)
    summary: EvidenceGraphSummaryPayload
