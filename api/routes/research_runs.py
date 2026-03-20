"""Research-run API routes."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.database import SessionLocal
from shared.database import UserCredits
from shared.database.models import ResearchRun
from shared.research_runs import (
    ResearchRunExecutor,
    ResearchRunPhase2UnavailableError,
    create_research_run,
    get_research_run_evidence_graph_payload,
    get_research_run_evidence_payload,
    get_research_run_payload,
    get_research_run_policy_evaluations_payload,
    get_research_run_report_pack_payload,
    get_research_run_report_payload,
    get_research_run_swarm_handoffs_payload,
    get_research_run_verification_decisions_payload,
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
    candidate_agent_ids: List[str] = Field(default_factory=list)
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
    credit_budget: Optional[int] = None
    verification_mode: str
    research_mode: str
    classified_mode: str
    depth_mode: str
    freshness_required: bool = False
    policy: Dict[str, Any] = Field(default_factory=dict)
    trace_summary: Dict[str, Any] = Field(default_factory=dict)
    source_requirements: Dict[str, Any] = Field(default_factory=dict)
    rounds_planned: Dict[str, int] = Field(default_factory=dict)
    rounds_completed: Dict[str, int] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    quality_tier: Optional[str] = None
    quality_warnings: List[str] = Field(default_factory=list)
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
    quality_tier: Optional[str] = None
    quality_warnings: List[str] = Field(default_factory=list)


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


class ResearchRunArtifactResponse(BaseModel):
    """Serialized evidence artifact for Phase 2 graph/report endpoints."""

    artifact_key: str
    citation_id: Optional[str] = None
    artifact_type: str
    origin_node_id: Optional[str] = None
    last_seen_node_id: Optional[str] = None
    order_index: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    normalized_url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    source_type: Optional[str] = None
    snippet: Optional[str] = None
    display_snippet: Optional[str] = None
    relevance_score: Optional[float] = None
    curation_status: str
    quality_flags: List[str] = Field(default_factory=list)
    filtered_reason: Optional[str] = None
    freshness_metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchRunPersistedClaimResponse(BaseModel):
    """Serialized persisted claim record for Phase 2 graph/report endpoints."""

    claim_id: str
    claim_order: int
    claim: str
    confidence: Optional[str] = None
    confidence_score: Optional[float] = None
    contradiction_status: Optional[str] = None
    contradiction_reasons: List[str] = Field(default_factory=list)
    supporting_artifact_keys: List[str] = Field(default_factory=list)
    supporting_citation_ids: List[str] = Field(default_factory=list)


class ResearchRunClaimLinkResponse(BaseModel):
    """Serialized persisted claim-to-evidence lineage link."""

    claim_id: str
    artifact_key: str
    citation_id: Optional[str] = None
    relation_type: str
    link_order: Optional[int] = None


class ResearchRunEvidenceGraphSummaryResponse(BaseModel):
    """Compact summary for a persisted evidence graph."""

    artifact_count: int
    cited_artifact_count: int
    filtered_artifact_count: int
    claim_count: int
    link_count: int
    high_confidence_claim_count: int = 0
    mixed_evidence_claim_count: int = 0
    insufficient_evidence_claim_count: int = 0


class ResearchRunEvidenceGraphResponse(BaseModel):
    """Persisted evidence graph payload for a research run."""

    schema_version: str
    research_run_id: str
    title: str
    description: str
    status: str
    workflow: str
    artifacts: List[ResearchRunArtifactResponse] = Field(default_factory=list)
    claims: List[ResearchRunPersistedClaimResponse] = Field(default_factory=list)
    links: List[ResearchRunClaimLinkResponse] = Field(default_factory=list)
    summary: ResearchRunEvidenceGraphSummaryResponse


class ResearchRunReportPackResponse(BaseModel):
    """Persisted JSON report pack for a research run."""

    schema_version: str
    research_run_id: str
    title: str
    description: str
    status: str
    workflow: str
    generated_at: Optional[str] = None
    rewritten_research_brief: Optional[str] = None
    answer_markdown: Optional[str] = None
    answer: Optional[str] = None
    claims: List[ResearchRunPersistedClaimResponse] = Field(default_factory=list)
    citations: List[ResearchRunArtifactResponse] = Field(default_factory=list)
    supporting_evidence: List[ResearchRunArtifactResponse] = Field(default_factory=list)
    claim_lineage: List[ResearchRunClaimLinkResponse] = Field(default_factory=list)
    quality_summary: Dict[str, Any] = Field(default_factory=dict)
    critic_findings: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[Any] = Field(default_factory=list)


class ResearchRunVerificationDecisionResponse(BaseModel):
    """Persisted verification decision for a research run attempt."""

    id: int
    research_run_id: str
    node_id: str
    attempt_id: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    agent_id: Optional[str] = None
    decision: str
    approved: bool
    decision_source: str
    overall_score: Optional[float] = None
    dimension_scores: Dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = None
    dissent_count: Optional[int] = None
    quorum_policy: Optional[str] = None
    policy_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ResearchRunSwarmHandoffResponse(BaseModel):
    """Persisted swarm handoff / blackboard entry for a research run attempt."""

    id: int
    research_run_id: str
    node_id: str
    attempt_id: str
    handoff_index: int
    from_agent_id: Optional[str] = None
    to_agent_id: Optional[str] = None
    handoff_type: str
    round_number: int
    status: str
    budget_remaining: Optional[float] = None
    verification_mode: Optional[str] = None
    idempotency_key: Optional[str] = None
    blackboard_delta: Dict[str, Any] = Field(default_factory=dict)
    decision_log: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ResearchRunPolicyEvaluationResponse(BaseModel):
    """Persisted policy evaluation for a research run attempt."""

    id: int
    research_run_id: str
    node_id: str
    attempt_id: str
    task_id: Optional[str] = None
    payment_id: Optional[str] = None
    evaluation_type: str
    status: str
    outcome: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ResearchRunCreateRequest(BaseModel):
    """Payload for creating a research run."""

    description: str = Field(..., min_length=1)
    credit_budget: Optional[int] = Field(default=None, ge=1, description="Credit spending cap (null = no cap)")
    budget_limit: Optional[float] = Field(default=None, ge=0, description="Deprecated USD budget (ignored if credit_budget is set)")
    verification_mode: str = "standard"
    max_node_attempts: Optional[int] = Field(default=None, ge=1, le=5)


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

    credit_budget = request.credit_budget
    hbar_per_credit = float(os.environ.get("HBAR_PER_CREDIT", "0.5"))

    # Reserve credits if a budget cap is set
    if credit_budget is not None:
        with SessionLocal() as db:
            row = db.query(UserCredits).filter(UserCredits.user_id == "default").one_or_none()
            balance = row.balance if row else 0
            if balance < credit_budget:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "insufficient_credits",
                        "required": credit_budget,
                        "balance": balance,
                    },
                )
            if row is None:
                row = UserCredits(user_id="default", balance=0)
                db.add(row)
            row.balance -= credit_budget
            db.commit()

    # Derive HBAR budget_limit from credit_budget for pipeline compat
    derived_budget = credit_budget * hbar_per_credit if credit_budget is not None else request.budget_limit

    research_run_id = create_research_run(
        description=request.description,
        budget_limit=derived_budget,
        credit_budget=credit_budget,
        verification_mode=request.verification_mode,
        max_node_attempts=request.max_node_attempts,
    )
    _ensure_research_run_job(research_run_id)

    payload = get_research_run_payload(research_run_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Research run was created but could not be loaded",
        )
    return ResearchRunResponse.model_validate(payload)


class ResearchRunHistoryItem(BaseModel):
    """Lightweight research-run summary for sidebar history."""

    id: str
    title: str
    status: str
    created_at: str


@router.get("/history", response_model=List[ResearchRunHistoryItem])
async def get_research_run_history(limit: int = 20) -> List[ResearchRunHistoryItem]:
    """Return recent research runs for the sidebar history list."""

    capped_limit = max(1, min(limit, 100))
    with SessionLocal() as session:
        runs = (
            session.query(ResearchRun)
            .order_by(ResearchRun.created_at.desc())
            .limit(capped_limit)
            .all()
        )
        return [
            ResearchRunHistoryItem(
                id=run.id,
                title=run.title,
                status=run.status.value if hasattr(run.status, "value") else str(run.status),
                created_at=run.created_at.isoformat() if run.created_at else "",
            )
            for run in runs
        ]


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


@router.get("/{research_run_id}/evidence-graph", response_model=ResearchRunEvidenceGraphResponse)
async def get_research_run_evidence_graph_route(
    research_run_id: str,
) -> ResearchRunEvidenceGraphResponse:
    """Return the persisted Phase 2 evidence graph for a research run."""

    try:
        payload = get_research_run_evidence_graph_payload(research_run_id)
    except ResearchRunPhase2UnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunEvidenceGraphResponse.model_validate(payload)


@router.get("/{research_run_id}/report-pack", response_model=ResearchRunReportPackResponse)
async def get_research_run_report_pack_route(research_run_id: str) -> ResearchRunReportPackResponse:
    """Return the persisted Phase 2 JSON report pack for a research run."""

    try:
        payload = get_research_run_report_pack_payload(research_run_id)
    except ResearchRunPhase2UnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunReportPackResponse.model_validate(payload)


@router.get(
    "/{research_run_id}/verification-decisions",
    response_model=List[ResearchRunVerificationDecisionResponse],
)
async def get_research_run_verification_decisions_route(
    research_run_id: str,
) -> List[ResearchRunVerificationDecisionResponse]:
    """Return persisted verification decision rows for a research run."""

    payload = get_research_run_verification_decisions_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return [ResearchRunVerificationDecisionResponse.model_validate(item) for item in payload]


@router.get("/{research_run_id}/swarm-handoffs", response_model=List[ResearchRunSwarmHandoffResponse])
async def get_research_run_swarm_handoffs_route(
    research_run_id: str,
) -> List[ResearchRunSwarmHandoffResponse]:
    """Return persisted swarm / blackboard handoff rows for a research run."""

    payload = get_research_run_swarm_handoffs_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return [ResearchRunSwarmHandoffResponse.model_validate(item) for item in payload]


@router.get(
    "/{research_run_id}/policy-evaluations",
    response_model=List[ResearchRunPolicyEvaluationResponse],
)
async def get_research_run_policy_evaluations_route(
    research_run_id: str,
) -> List[ResearchRunPolicyEvaluationResponse]:
    """Return persisted policy evaluation rows for a research run."""

    payload = get_research_run_policy_evaluations_payload(research_run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return [ResearchRunPolicyEvaluationResponse.model_validate(item) for item in payload]
