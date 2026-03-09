"""Research-run API routes."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.research_runs import (
    ResearchRunExecutor,
    create_research_run,
    get_research_run_evidence_payload,
    get_research_run_payload,
    get_research_run_report_payload,
    request_cancel_research_run,
    request_pause_research_run,
    request_resume_research_run,
)

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


class ResearchRunEvidenceResponse(BaseModel):
    """Shaped evidence payload for a research run."""

    research_run_id: str
    status: str
    claim_targets: List[Dict[str, Any]] = Field(default_factory=list)
    rewritten_research_brief: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    filtered_sources: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    coverage_summary: Dict[str, Any] = Field(default_factory=dict)
    source_summary: Dict[str, Any] = Field(default_factory=dict)
    freshness_summary: Dict[str, Any] = Field(default_factory=dict)
    search_lanes_used: List[str] = Field(default_factory=list)


class ResearchRunReportResponse(BaseModel):
    """Shaped final report payload for a research run."""

    research_run_id: str
    status: str
    answer_markdown: Optional[str] = None
    answer: Optional[str] = None
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[Any] = Field(default_factory=list)
    critic_findings: List[Dict[str, Any]] = Field(default_factory=list)
    quality_summary: Dict[str, Any] = Field(default_factory=dict)


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


def _ensure_research_run_job(research_run_id: str) -> None:
    existing = _running_jobs.get(research_run_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_run_research_run_job(research_run_id))
    _running_jobs[research_run_id] = task


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
    _ensure_research_run_job(research_run_id)

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


@router.post("/{research_run_id}/pause", response_model=ResearchRunResponse)
async def pause_research_run_route(research_run_id: str) -> ResearchRunResponse:
    """Request a cooperative pause for a running research run."""

    payload = request_pause_research_run(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunResponse.model_validate(payload)


@router.post("/{research_run_id}/resume", response_model=ResearchRunResponse)
async def resume_research_run_route(research_run_id: str) -> ResearchRunResponse:
    """Resume a paused research run and restart its executor if needed."""

    payload = request_resume_research_run(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    _ensure_research_run_job(research_run_id)
    refreshed_payload = get_research_run_payload(research_run_id) or payload
    return ResearchRunResponse.model_validate(refreshed_payload)


@router.post("/{research_run_id}/cancel", response_model=ResearchRunResponse)
async def cancel_research_run_route(research_run_id: str) -> ResearchRunResponse:
    """Cancel a research run cooperatively and stop downstream scheduling."""

    payload = request_cancel_research_run(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunResponse.model_validate(payload)


@router.get("/{research_run_id}/evidence", response_model=ResearchRunEvidenceResponse)
async def get_research_run_evidence_route(research_run_id: str) -> ResearchRunEvidenceResponse:
    """Return the shaped evidence view for a research run."""

    payload = get_research_run_evidence_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunEvidenceResponse.model_validate(payload)


@router.get("/{research_run_id}/report", response_model=ResearchRunReportResponse)
async def get_research_run_report_route(research_run_id: str) -> ResearchRunReportResponse:
    """Return the shaped final report view for a research run."""

    payload = get_research_run_report_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunReportResponse.model_validate(payload)
