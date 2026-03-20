"""Top-level serialized research run payload."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .research_run_edge_payload import ResearchRunEdgePayload
from .research_run_node_payload import ResearchRunNodePayload
from .rounds_completed_payload import RoundsCompletedPayload


class ResearchRunPayload(BaseModel):
    """Canonical API payload for a research run."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str
    status: str
    workflow_template: str
    workflow: str
    budget_limit: Optional[float] = None
    credit_budget: Optional[int] = None
    verification_mode: str
    research_mode: str
    classified_mode: str
    depth_mode: str
    freshness_required: bool
    policy: dict[str, Any] = Field(default_factory=dict)
    trace_summary: dict[str, Any] = Field(default_factory=dict)
    source_requirements: dict[str, Any] = Field(default_factory=dict)
    rounds_planned: dict[str, Any] = Field(default_factory=dict)
    rounds_completed: RoundsCompletedPayload = Field(default_factory=RoundsCompletedPayload)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    quality_tier: Optional[str] = None
    quality_warnings: list[str] = Field(default_factory=list)
    nodes: list[ResearchRunNodePayload] = Field(default_factory=list)
    edges: list[ResearchRunEdgePayload] = Field(default_factory=list)
