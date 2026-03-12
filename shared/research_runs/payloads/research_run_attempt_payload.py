"""Serialized attempt payload for research run nodes."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ResearchRunAttemptPayload(BaseModel):
    """Single execution attempt details for a node."""

    model_config = ConfigDict(extra="ignore")

    attempt_id: str
    attempt_number: int
    status: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    agent_id: Optional[str] = None
    verification_score: Any = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
