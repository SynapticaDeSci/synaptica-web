"""Phase 2 JSON report pack payload."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .evidence_artifact_payload import EvidenceArtifactPayload
from .evidence_graph_claim_payload import EvidenceGraphClaimPayload
from .evidence_graph_link_payload import EvidenceGraphLinkPayload


class ResearchRunReportPackPayload(BaseModel):
    """Full report package combining answer, claims, and evidence lineage."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str
    research_run_id: str
    title: str
    description: str
    status: str
    workflow: str
    generated_at: str | None = None
    rewritten_research_brief: str | None = None
    answer_markdown: str | None = None
    answer: str | None = None
    claims: list[EvidenceGraphClaimPayload] = Field(default_factory=list)
    citations: list[EvidenceArtifactPayload] = Field(default_factory=list)
    supporting_evidence: list[EvidenceArtifactPayload] = Field(default_factory=list)
    claim_lineage: list[EvidenceGraphLinkPayload] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    critic_findings: list[Any] = Field(default_factory=list)
    limitations: list[Any] = Field(default_factory=list)
