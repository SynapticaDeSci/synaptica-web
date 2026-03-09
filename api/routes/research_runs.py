"""Research-run API routes."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.research_runs import ResearchRunExecutor, create_research_run, get_research_run_payload

router = APIRouter()
_running_jobs: Dict[str, asyncio.Task[None]] = {}


class ResearchRunAttemptResponse(BaseModel):
    """Serialized execution attempt for a research-run node."""

    attempt_id: str
    attempt_number: int
    status: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    agent_id: Optional[str] = None
    verification_score: Optional[float] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None


class ResearchRunNodeResponse(BaseModel):
    """Serialized research-run node."""

    node_id: str
    title: str
    description: str
    capability_requirements: str
    assigned_agent_id: str
    execution_order: int
    status: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    attempts: List[ResearchRunAttemptResponse] = Field(default_factory=list)


class ResearchRunEdgeResponse(BaseModel):
    """Serialized dependency edge."""

    from_node_id: str
    to_node_id: str


class ResearchRunResponse(BaseModel):
    """Serialized research-run payload."""

    id: str
    title: str
    description: str
    status: str
    workflow_template: str
    workflow: str
    budget_limit: Optional[float] = None
    verification_mode: str
    research_mode: str
    classified_mode: str
    depth_mode: str
    freshness_required: bool = False
    source_requirements: Dict[str, Any] = Field(default_factory=dict)
    rounds_planned: Dict[str, int] = Field(default_factory=dict)
    rounds_completed: Dict[str, int] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    nodes: List[ResearchRunNodeResponse]
    edges: List[ResearchRunEdgeResponse]


class ResearchRunCreateRequest(BaseModel):
    """Payload for creating a research run."""

    description: str = Field(..., min_length=1)
    budget_limit: Optional[float] = Field(default=None, ge=0)
    verification_mode: str = "standard"
    research_mode: Literal["auto", "literature", "live_analysis", "hybrid"] = "auto"
    depth_mode: Literal["standard", "deep"] = "standard"


async def _run_research_run_job(research_run_id: str) -> None:
    executor = ResearchRunExecutor(research_run_id)
    try:
        await executor.run()
    finally:
        _running_jobs.pop(research_run_id, None)


@router.post("", response_model=ResearchRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_research_run_route(request: ResearchRunCreateRequest) -> ResearchRunResponse:
    """Create and immediately start a research run."""

    research_run_id = create_research_run(
        description=request.description,
        budget_limit=request.budget_limit,
        verification_mode=request.verification_mode,
        research_mode=request.research_mode,
        depth_mode=request.depth_mode,
    )
    task = asyncio.create_task(_run_research_run_job(research_run_id))
    _running_jobs[research_run_id] = task

    payload = get_research_run_payload(research_run_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Research run was created but could not be loaded",
        )
    return ResearchRunResponse.model_validate(payload)


@router.get("/{research_run_id}", response_model=ResearchRunResponse)
async def get_research_run_route(research_run_id: str) -> ResearchRunResponse:
    """Return the current research-run status, graph, and attempt state."""

    payload = get_research_run_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunResponse.model_validate(payload)
