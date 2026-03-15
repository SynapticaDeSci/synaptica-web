"""Serialized node payload for research runs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .research_run_attempt_payload import ResearchRunAttemptPayload


class ResearchRunNodePayload(BaseModel):
    """Research-run graph node with execution details."""

    model_config = ConfigDict(extra="ignore")

    node_id: str
    title: str
    description: str
    capability_requirements: str
    assigned_agent_id: str
    candidate_agent_ids: list[str] = Field(default_factory=list)
    execution_order: int
    status: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    attempts: list[ResearchRunAttemptPayload] = Field(default_factory=list)
