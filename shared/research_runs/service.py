"""Persistence and execution helpers for research runs."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from hashlib import sha1
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from strands.agent.agent_result import AgentResult
from strands._async import run_async
from strands.multiagent.graph import GraphBuilder
from strands.telemetry.metrics import EventLoopMetrics

from agents.orchestrator.tools import create_todo_list, execute_microtask
from shared.database import (
    Claim,
    ClaimLink,
    EvidenceArtifact,
    ExecutionAttempt,
    PolicyEvaluation,
    ResearchRun,
    ResearchRunEdge,
    ResearchRunNode,
    ResearchRunNodeStatus,
    ResearchRunStatus,
    SessionLocal,
    SwarmHandoff,
    Task,
    VerificationDecision,
)
from shared.database.models import TaskStatus
from shared.research.catalog import rank_supported_agents_for_todo
from shared.runtime import (
    HandoffContext,
    initialize_runtime_state,
    load_task_snapshot,
    persist_runtime_status,
    persist_verification_state,
    redact_sensitive_payload,
)

from .planner import (
    SUPPORTED_RESEARCH_RUN_WORKFLOW,
    DepthMode,
    ResearchMode,
    ResearchRunPlan,
    ResearchRunProfile,
    RoundsPlan,
    SourceRequirements,
    build_research_run_plan,
)
from .payloads import (
    EvidenceArtifactPayload,
    EvidenceGraphClaimPayload,
    EvidenceGraphLinkPayload,
    EvidenceGraphSummaryPayload,
    ResearchRunAttemptPayload,
    ResearchRunEdgePayload,
    ResearchRunEvidenceGraphPayload,
    ResearchRunEvidencePayload,
    ResearchRunNodePayload,
    ResearchRunPayload,
    ResearchRunReportPackPayload,
    ResearchRunReportPayload,
    ResearchRunSourcePayload,
    RoundsCompletedPayload,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_REPUTATION_SCORE = 0.7
RUN_CONTROL_ACTIVE = "active"
RUN_CONTROL_PAUSE_REQUESTED = "pause_requested"
RUN_CONTROL_PAUSED = "paused"
RUN_CONTROL_CANCEL_REQUESTED = "cancel_requested"
RUN_CONTROL_CANCELLED = "cancelled"
DEFAULT_QUORUM_POLICY = "single_verifier"
DEFAULT_RISK_LEVEL = "medium"
DEFAULT_MAX_NODE_ATTEMPTS = 1
STRICT_DEFAULT_MAX_NODE_ATTEMPTS = 2
SUPPORTED_RISK_LEVELS = {"low", "medium", "high"}
SUPPORTED_QUORUM_POLICIES = {
    "single_verifier",
    "two_of_three",
    "three_of_five",
    "unanimous",
}
PHASE2_GRAPH_SCHEMA_VERSION = "phase2.v1"
PHASE2_GRAPH_SCHEMA_META_KEY = "evidence_graph_schema_version"
CLAIM_RELATION_SUPPORTS = "supports"
PHASE2_CLAIM_SCORING_META_KEY = "phase2_scoring"
PHASE2_HIGH_CONFIDENCE_THRESHOLD = 0.8
PHASE2_CONTRADICTION_STATUS_NONE = "none"
PHASE2_CONTRADICTION_STATUS_MIXED = "mixed"
PHASE2_CONTRADICTION_STATUS_INSUFFICIENT = "insufficient_evidence"

_PHASE2_CONFIDENCE_BASE_SCORES = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.40,
}
_PHASE2_CONTRADICTION_MARKERS = (
    "conflict",
    "contradict",
    "mixed",
    "disputed",
    "counterpoint",
    "uncertain",
)

_ARTIFACT_STATUS_PRECEDENCE = {
    "gathered": 0,
    "selected": 1,
    "filtered": 1,
    "cited": 2,
}


class ResearchRunCancelledError(RuntimeError):
    """Raised when a research run has been cancelled cooperatively."""


class ResearchRunPhase2UnavailableError(RuntimeError):
    """Raised when a legacy run lacks persisted Phase 2 graph data."""


class _ResearchRunGraphNodeExecutor:
    """Minimal AgentBase-compatible wrapper for a persisted research-run node."""

    def __init__(self, node_id: str):
        self.node_id = node_id

    async def invoke_async(self, prompt: Any = None, **kwargs: Any) -> Any:
        del prompt
        invocation_state = kwargs.get("invocation_state") or {}
        runner: ResearchRunExecutor = invocation_state["runner"]
        result = await runner.execute_node(self.node_id)
        return AgentResult(
            stop_reason="end_turn",
            message={
                "role": "assistant",
                "content": [{"text": json.dumps(result, default=str)}],
            },
            metrics=EventLoopMetrics(),
            state=result,
        )

    async def stream_async(self, prompt: Any = None, **kwargs: Any):
        result = await self.invoke_async(prompt, **kwargs)
        yield {"result": result}

    def __call__(self, prompt: Any = None, **kwargs: Any) -> Any:
        return run_async(lambda: self.invoke_async(prompt, **kwargs))


def _utcnow() -> datetime:
    return datetime.utcnow()


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _normalize_risk_level(value: Any) -> str:
    candidate = str(value or DEFAULT_RISK_LEVEL).strip().lower()
    return candidate if candidate in SUPPORTED_RISK_LEVELS else DEFAULT_RISK_LEVEL


def _default_quorum_policy(*, strict_mode: bool, risk_level: str) -> str:
    if not strict_mode:
        return DEFAULT_QUORUM_POLICY
    if risk_level == "high":
        return "unanimous"
    return "two_of_three"


def _normalize_quorum_policy(
    value: Any,
    *,
    strict_mode: bool,
    risk_level: str,
) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in SUPPORTED_QUORUM_POLICIES:
        return candidate
    return _default_quorum_policy(strict_mode=strict_mode, risk_level=risk_level)


def _build_run_policy(
    *,
    strict_mode: bool = False,
    risk_level: Any = DEFAULT_RISK_LEVEL,
    quorum_policy: Any = None,
    max_node_attempts: Any = None,
    depth_mode: str = DepthMode.STANDARD.value,
) -> Dict[str, Any]:
    normalized_risk = _normalize_risk_level(risk_level)
    normalized_quorum = _normalize_quorum_policy(
        quorum_policy,
        strict_mode=bool(strict_mode),
        risk_level=normalized_risk,
    )
    if max_node_attempts in {None, ""}:
        attempts = STRICT_DEFAULT_MAX_NODE_ATTEMPTS if strict_mode else DEFAULT_MAX_NODE_ATTEMPTS
    else:
        attempts = max(1, min(int(max_node_attempts), 5))

    max_swarm_rounds = 2 if str(depth_mode) == DepthMode.DEEP.value else 1
    return {
        "strict_mode": bool(strict_mode),
        "risk_level": normalized_risk,
        "quorum_policy": normalized_quorum,
        "max_node_attempts": attempts,
        "reroute_on_failure": attempts > 1,
        "max_swarm_rounds": max_swarm_rounds,
        "escalate_on_dissent": bool(strict_mode),
    }


def _get_run_policy(meta: Dict[str, Any]) -> Dict[str, Any]:
    stored = dict(meta.get("policy") or {})
    return _build_run_policy(
        strict_mode=bool(stored.get("strict_mode", False)),
        risk_level=stored.get("risk_level", meta.get("risk_level", DEFAULT_RISK_LEVEL)),
        quorum_policy=stored.get("quorum_policy", meta.get("quorum_policy")),
        max_node_attempts=stored.get("max_node_attempts", meta.get("max_node_attempts")),
        depth_mode=str(meta.get("depth_mode", DepthMode.STANDARD.value)),
    )


def _trace_summary(
    *,
    verification_decision_count: int = 0,
    swarm_handoff_count: int = 0,
    policy_evaluation_count: int = 0,
    unresolved_dissent_count: int = 0,
) -> Dict[str, int]:
    return {
        "verification_decision_count": verification_decision_count,
        "swarm_handoff_count": swarm_handoff_count,
        "policy_evaluation_count": policy_evaluation_count,
        "unresolved_dissent_count": unresolved_dissent_count,
    }


def _normalize_rounds_completed(result: Any) -> Dict[str, int]:
    return RoundsCompletedPayload.from_payload(result).model_dump(mode="json")


def _merge_rounds_completed(*payloads: Any) -> Dict[str, int]:
    merged = RoundsCompletedPayload()
    for payload in payloads:
        rounds = RoundsCompletedPayload.from_payload(payload)
        merged.evidence_rounds = max(merged.evidence_rounds, rounds.evidence_rounds)
        merged.critique_rounds = max(merged.critique_rounds, rounds.critique_rounds)
    return merged.model_dump(mode="json")


def _build_research_run_title(description: str) -> str:
    snippet = " ".join(description.split())
    snippet = snippet[:57].rstrip()
    return f"Research Run: {snippet}..." if len(snippet) == 57 else f"Research Run: {snippet}"


def _is_terminal_run_status(status: Any) -> bool:
    return _enum_value(status) in {
        ResearchRunStatus.COMPLETED.value,
        ResearchRunStatus.FAILED.value,
        ResearchRunStatus.CANCELLED.value,
    }


def _get_control_state(meta: Dict[str, Any]) -> str:
    return str(meta.get("control_state") or RUN_CONTROL_ACTIVE)


def _get_node_result_from_payload(payload: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if not isinstance(node, dict) or node.get("node_id") != node_id:
            continue
        result = node.get("result")
        if isinstance(result, dict):
            return result
    return None


def _coerce_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed:
            normalized.append(trimmed)
    return normalized


def _normalize_source_url(url: Any) -> Optional[str]:
    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if not parsed.scheme and not parsed.netloc:
        return raw.lower()
    path = parsed.path or ""
    if path not in {"", "/"}:
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _build_fallback_artifact_key(source: Dict[str, Any]) -> tuple[str, Optional[str]]:
    normalized_url = _normalize_source_url(source.get("url"))
    if normalized_url:
        return f"url:{sha1(normalized_url.encode('utf-8')).hexdigest()[:16]}", normalized_url

    fingerprint = json.dumps(
        {
            "title": source.get("title"),
            "url": source.get("url"),
            "publisher": source.get("publisher"),
            "published_at": source.get("published_at"),
            "source_type": source.get("source_type"),
            "snippet": source.get("snippet"),
        },
        sort_keys=True,
        default=str,
    )
    return f"artifact:{sha1(fingerprint.encode('utf-8')).hexdigest()[:16]}", normalized_url


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _phase2_scoring_from_claim_meta(claim: Claim) -> Dict[str, Any]:
    meta = dict(claim.meta or {})
    scoring = meta.get(PHASE2_CLAIM_SCORING_META_KEY) or {}
    return scoring if isinstance(scoring, dict) else {}


def _collect_phase2_marker_hits(values: List[Any]) -> List[str]:
    hits = set()
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if not normalized:
            continue
        for marker in _PHASE2_CONTRADICTION_MARKERS:
            if marker in normalized:
                hits.add(marker)
    return sorted(hits)


def _compute_phase2_claim_scoring(
    *,
    run_record: ResearchRun,
    claim: Claim,
    supporting_artifacts: List[EvidenceArtifact],
    uncovered_claim_ids: set[str],
    critic_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    confidence_label = str(claim.confidence or "").strip().lower()
    confidence_score = _PHASE2_CONFIDENCE_BASE_SCORES.get(confidence_label, 0.50)
    supporting_count = len(supporting_artifacts)
    publishers = {
        str(artifact.publisher).strip()
        for artifact in supporting_artifacts
        if artifact.publisher
    }
    source_types = {
        str(artifact.source_type or "").strip().lower()
        for artifact in supporting_artifacts
        if artifact.source_type
    }
    fresh_required = bool((run_record.meta or {}).get("freshness_required", False))
    has_stale_support = fresh_required and any(
        isinstance(artifact.freshness_metadata, dict)
        and artifact.freshness_metadata.get("is_fresh") is False
        for artifact in supporting_artifacts
    )
    has_high_severity_critic_finding = any(
        str(finding.get("severity") or "").strip().lower() == "high"
        for finding in critic_findings
        if isinstance(finding, dict)
    )

    if supporting_count >= 2:
        confidence_score += 0.05
    else:
        confidence_score -= 0.15

    if len(publishers) >= 2 or bool(source_types & {"primary", "academic"}):
        confidence_score += 0.05
    if has_stale_support:
        confidence_score -= 0.15
    if has_high_severity_critic_finding:
        confidence_score -= 0.10
    confidence_score = round(max(0.0, min(1.0, confidence_score)), 3)

    claim_meta = dict(claim.meta or {})
    supporting_citation_ids = _coerce_string_list(claim_meta.get("supporting_citation_ids") or [])
    has_placeholder_artifact = any(
        bool(dict(artifact.meta or {}).get("placeholder"))
        for artifact in supporting_artifacts
    )
    has_unresolved_citation_gap = (
        not supporting_artifacts
        or not supporting_citation_ids
        or has_placeholder_artifact
        or claim.claim_id in uncovered_claim_ids
        or len(supporting_artifacts) < len(supporting_citation_ids)
    )

    contradiction_reasons: List[str] = []
    if not supporting_artifacts:
        contradiction_reasons.append("No persisted supporting evidence artifacts are linked to this claim.")
    if not supporting_citation_ids:
        contradiction_reasons.append("The claim is missing supporting citation IDs.")
    if has_placeholder_artifact or len(supporting_artifacts) < len(supporting_citation_ids):
        contradiction_reasons.append(
            "Supporting citations were not fully resolved to persisted evidence artifacts."
        )
    if claim.claim_id in uncovered_claim_ids:
        contradiction_reasons.append(
            "Research quality checks flagged unresolved citation coverage gaps for this claim."
        )
    if has_unresolved_citation_gap:
        contradiction_status = PHASE2_CONTRADICTION_STATUS_INSUFFICIENT
    else:
        artifact_marker_hits = _collect_phase2_marker_hits(
            [
                artifact.title
                for artifact in supporting_artifacts
            ]
            + [artifact.snippet for artifact in supporting_artifacts]
            + [artifact.display_snippet for artifact in supporting_artifacts]
            + [artifact.filtered_reason for artifact in supporting_artifacts]
            + [
                flag
                for artifact in supporting_artifacts
                for flag in _coerce_string_list(artifact.quality_flags or [])
            ]
        )
        critic_marker_hits = _collect_phase2_marker_hits(
            [
                finding.get("issue")
                for finding in critic_findings
                if isinstance(finding, dict)
            ]
            + [
                finding.get("recommendation")
                for finding in critic_findings
                if isinstance(finding, dict)
            ]
        )
        if artifact_marker_hits or critic_marker_hits:
            contradiction_status = PHASE2_CONTRADICTION_STATUS_MIXED
            if artifact_marker_hits:
                contradiction_reasons.append(
                    "Supporting evidence contains disagreement or uncertainty markers: "
                    + ", ".join(artifact_marker_hits)
                    + "."
                )
            if critic_marker_hits:
                contradiction_reasons.append(
                    "Critic findings highlight disagreement or uncertainty markers: "
                    + ", ".join(critic_marker_hits)
                    + "."
                )
        else:
            contradiction_status = PHASE2_CONTRADICTION_STATUS_NONE

    return {
        "confidence_score": confidence_score,
        "contradiction_status": contradiction_status,
        "contradiction_reasons": contradiction_reasons,
        "supporting_artifact_count": supporting_count,
        "publisher_count": len(publishers),
        "has_stale_support": has_stale_support,
        "has_high_severity_critic_findings": has_high_severity_critic_finding,
    }


def _apply_phase2_claim_scoring(
    *,
    run_record: ResearchRun,
    claims: List[Claim],
    artifacts: List[EvidenceArtifact],
    links: List[ClaimLink],
) -> List[Claim]:
    artifacts_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
    links_by_claim: Dict[str, List[ClaimLink]] = {}
    for link in links:
        links_by_claim.setdefault(link.claim_id, []).append(link)

    result_payload = dict(run_record.result or {}) if isinstance(run_record.result, dict) else {}
    quality_summary = (
        dict(result_payload.get("quality_summary") or {})
        if isinstance(result_payload.get("quality_summary"), dict)
        else {}
    )
    uncovered_claim_ids = set(_coerce_string_list(quality_summary.get("uncovered_claims") or []))
    critic_findings = [
        finding
        for finding in (result_payload.get("critic_findings") or [])
        if isinstance(finding, dict)
    ]

    updated_claims: List[Claim] = []
    for claim in claims:
        existing = _phase2_scoring_from_claim_meta(claim)
        if all(
            key in existing
            for key in ("confidence_score", "contradiction_status", "contradiction_reasons")
        ):
            continue
        supporting_artifacts = [
            artifacts_by_key[link.artifact_key]
            for link in links_by_claim.get(claim.claim_id, [])
            if link.artifact_key in artifacts_by_key
        ]
        claim_meta = dict(claim.meta or {})
        claim_meta[PHASE2_CLAIM_SCORING_META_KEY] = _compute_phase2_claim_scoring(
            run_record=run_record,
            claim=claim,
            supporting_artifacts=supporting_artifacts,
            uncovered_claim_ids=uncovered_claim_ids,
            critic_findings=critic_findings,
        )
        claim.meta = claim_meta
        updated_claims.append(claim)
    return updated_claims


def _detach_phase2_graph_records(
    db,
    *,
    record: Optional[ResearchRun] = None,
    artifacts: Optional[List[EvidenceArtifact]] = None,
    claims: Optional[List[Claim]] = None,
    links: Optional[List[ClaimLink]] = None,
) -> None:
    if record is not None:
        db.expunge(record)
    for artifact in artifacts or []:
        db.expunge(artifact)
    for claim in claims or []:
        db.expunge(claim)
    for link in links or []:
        db.expunge(link)


def _build_phase2_claim_scoring_summary(claims: List[Claim]) -> Dict[str, Any]:
    scores = [
        float(scoring["confidence_score"])
        for claim in claims
        for scoring in [_phase2_scoring_from_claim_meta(claim)]
        if scoring.get("confidence_score") is not None
    ]
    mixed_evidence_claim_count = sum(
        1
        for claim in claims
        if _phase2_scoring_from_claim_meta(claim).get("contradiction_status")
        == PHASE2_CONTRADICTION_STATUS_MIXED
    )
    insufficient_evidence_claim_count = sum(
        1
        for claim in claims
        if _phase2_scoring_from_claim_meta(claim).get("contradiction_status")
        == PHASE2_CONTRADICTION_STATUS_INSUFFICIENT
    )
    high_confidence_claim_count = sum(
        1
        for claim in claims
        if (_phase2_scoring_from_claim_meta(claim).get("confidence_score") or 0.0)
        >= PHASE2_HIGH_CONFIDENCE_THRESHOLD
    )
    return {
        "claim_count": len(claims),
        "high_confidence_claim_count": high_confidence_claim_count,
        "mixed_evidence_claim_count": mixed_evidence_claim_count,
        "insufficient_evidence_claim_count": insufficient_evidence_claim_count,
        "average_confidence_score": round(sum(scores) / len(scores), 3) if scores else None,
    }


def _build_freshness_metadata(
    *,
    source: Dict[str, Any],
    freshness_required: bool,
    freshness_window_days: Optional[int],
    reference_time: Optional[datetime],
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "required": freshness_required,
        "window_days": freshness_window_days,
    }
    published_at = source.get("published_at")
    if published_at:
        metadata["published_at"] = published_at

    published_at_dt = _parse_datetime(published_at)
    if published_at_dt is None or freshness_window_days is None:
        return metadata

    comparison_time = reference_time or _utcnow()
    if published_at_dt.tzinfo is not None and comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=published_at_dt.tzinfo)
    if published_at_dt.tzinfo is None and comparison_time.tzinfo is not None:
        published_at_dt = published_at_dt.replace(tzinfo=comparison_time.tzinfo)

    age_days = max((comparison_time - published_at_dt).total_seconds() / 86400.0, 0.0)
    metadata["age_days"] = round(age_days, 3)
    metadata["is_fresh"] = age_days <= freshness_window_days
    return metadata


def _artifact_status_rank(status: Optional[str]) -> int:
    return _ARTIFACT_STATUS_PRECEDENCE.get(str(status or "").lower(), -1)


def create_research_run(
    *,
    description: str,
    budget_limit: Optional[float],
    verification_mode: str,
    research_mode: str = ResearchMode.AUTO.value,
    depth_mode: str = DepthMode.STANDARD.value,
    strict_mode: bool = False,
    risk_level: str = DEFAULT_RISK_LEVEL,
    quorum_policy: Optional[str] = None,
    max_node_attempts: Optional[int] = None,
) -> str:
    """Persist a research run plus its template graph."""

    plan = build_research_run_plan(
        description,
        research_mode=ResearchMode(research_mode),
        depth_mode=DepthMode(depth_mode),
    )
    research_run_id = str(uuid.uuid4())
    policy = _build_run_policy(
        strict_mode=strict_mode,
        risk_level=risk_level,
        quorum_policy=quorum_policy,
        max_node_attempts=max_node_attempts,
        depth_mode=depth_mode,
    )

    db = SessionLocal()
    try:
        record = ResearchRun(  # type: ignore[call-arg]
            id=research_run_id,
            title=_build_research_run_title(description),
            description=description,
            status=ResearchRunStatus.PENDING,
            workflow_template=plan.workflow_template,
            budget_limit=budget_limit,
            verification_mode=verification_mode,
            meta={
                "workflow": plan.workflow,
                "research_mode": plan.profile.requested_mode.value,
                "classified_mode": plan.profile.classified_mode.value,
                "depth_mode": plan.profile.depth_mode.value,
                "freshness_required": plan.profile.freshness_required,
                "source_requirements": plan.profile.source_requirements.model_dump(),
                "rounds_planned": plan.profile.rounds_planned.model_dump(),
                "rounds_completed": {"evidence_rounds": 0, "critique_rounds": 0},
                "planner_notes": plan.profile.planner_notes,
                "scenario_analysis_requested": plan.profile.scenario_analysis_requested,
                "generated_at": plan.profile.generated_at,
                "policy": policy,
                "session_state": {
                    "session_id": f"research-run:{research_run_id}",
                    "last_node_id": None,
                    "last_attempt_id": None,
                    "blackboard_keys": [],
                },
                "trace_summary": _trace_summary(),
                PHASE2_GRAPH_SCHEMA_META_KEY: PHASE2_GRAPH_SCHEMA_VERSION,
                "control_state": RUN_CONTROL_ACTIVE,
                "control_reason": None,
            },
        )
        db.add(record)

        for node in plan.nodes:
            candidate_agent_ids = rank_supported_agents_for_todo(
                node.node_id,
                node.capability_requirements,
                node.title,
                preferred_agent_id=node.assigned_agent_id,
            )
            assigned_agent_id = candidate_agent_ids[0] if candidate_agent_ids else node.assigned_agent_id
            execution_parameters = {
                **node.execution_parameters,
                "strict_mode": policy["strict_mode"],
                "risk_level": policy["risk_level"],
                "quorum_policy": policy["quorum_policy"],
                "max_node_attempts": policy["max_node_attempts"],
                "reroute_on_failure": policy["reroute_on_failure"],
                "max_swarm_rounds": policy["max_swarm_rounds"],
            }
            db.add(
                ResearchRunNode(  # type: ignore[call-arg]
                    research_run_id=research_run_id,
                    node_id=node.node_id,
                    title=node.title,
                    description=node.description,
                    capability_requirements=node.capability_requirements,
                    assigned_agent_id=assigned_agent_id,
                    execution_order=node.execution_order,
                    status=ResearchRunNodeStatus.PENDING,
                    meta={
                        "execution_parameters": execution_parameters,
                        "input_bindings": node.input_bindings,
                        "candidate_agent_ids": candidate_agent_ids,
                        "selection_strategy": "marketplace_ranker",
                    },
                )
            )

        for edge in plan.edges:
            db.add(
                ResearchRunEdge(  # type: ignore[call-arg]
                    research_run_id=research_run_id,
                    from_node_id=edge.from_node_id,
                    to_node_id=edge.to_node_id,
                )
            )

        db.commit()
        return research_run_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def request_pause_research_run(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Request that a research run pause after the current node settles."""

    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None
        if _is_terminal_run_status(record.status):
            db.rollback()
            return get_research_run_payload(research_run_id)

        meta = dict(record.meta or {})
        control_state = _get_control_state(meta)
        if control_state in {RUN_CONTROL_PAUSE_REQUESTED, RUN_CONTROL_PAUSED}:
            db.rollback()
            return get_research_run_payload(research_run_id)

        active_node = (
            db.query(ResearchRunNode)
            .filter(ResearchRunNode.research_run_id == research_run_id)
            .filter(
                ResearchRunNode.status.in_(
                    [ResearchRunNodeStatus.RUNNING, ResearchRunNodeStatus.WAITING_FOR_REVIEW]
                )
            )
            .one_or_none()
        )
        meta["control_state"] = (
            RUN_CONTROL_PAUSE_REQUESTED if active_node is not None else RUN_CONTROL_PAUSED
        )
        meta["control_reason"] = "Pause requested by user"
        record.meta = meta
        if active_node is None:
            record.status = ResearchRunStatus.PAUSED
        db.commit()
    finally:
        db.close()

    return get_research_run_payload(research_run_id)


def request_resume_research_run(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Resume a paused research run."""

    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None
        if _is_terminal_run_status(record.status):
            db.rollback()
            return get_research_run_payload(research_run_id)

        meta = dict(record.meta or {})
        meta["control_state"] = RUN_CONTROL_ACTIVE
        meta["control_reason"] = None
        record.meta = meta
        if record.status == ResearchRunStatus.PAUSED:
            record.status = ResearchRunStatus.RUNNING
        db.commit()
    finally:
        db.close()

    return get_research_run_payload(research_run_id)


def request_cancel_research_run(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Request cancellation for a research run and cancel idle/pending work immediately."""

    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None
        if _is_terminal_run_status(record.status):
            db.rollback()
            return get_research_run_payload(research_run_id)

        meta = dict(record.meta or {})
        meta["control_state"] = RUN_CONTROL_CANCEL_REQUESTED
        meta["control_reason"] = "Cancelled by user"
        record.meta = meta

        candidate_attempts = (
            db.query(ExecutionAttempt)
            .filter(ExecutionAttempt.research_run_id == research_run_id)
            .filter(ExecutionAttempt.status == ResearchRunNodeStatus.RUNNING)
            .order_by(ExecutionAttempt.created_at.desc())
            .all()
        )
        waiting_attempt = next(
            (
                attempt
                for attempt in candidate_attempts
                if attempt.task_id and (load_task_snapshot(attempt.task_id) or {}).get("verification_pending")
            ),
            None,
        )
        running_attempt = (
            next(
                (
                    attempt
                    for attempt in candidate_attempts
                    if attempt is not waiting_attempt
                ),
                None,
            )
        )

        if waiting_attempt is not None and waiting_attempt.task_id:
            persist_verification_state(
                waiting_attempt.task_id,
                pending=False,
                verification_data=None,
                verification_decision={
                    "approved": False,
                    "reason": "Cancelled by user",
                    "timestamp": _utcnow().isoformat(),
                },
            )
            persist_runtime_status(
                waiting_attempt.task_id,
                status="cancelled",
                error="Cancelled by user",
            )

        if waiting_attempt is None and running_attempt is None:
            record.status = ResearchRunStatus.CANCELLED
            record.completed_at = _utcnow()
            record.result = {
                "error": "Cancelled by user",
                "classified_mode": meta.get("classified_mode"),
                "depth_mode": meta.get("depth_mode"),
            }
            record.error = "Cancelled by user"
            meta["control_state"] = RUN_CONTROL_CANCELLED
            for node in (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == research_run_id)
                .filter(
                    ResearchRunNode.status.in_(
                        [ResearchRunNodeStatus.PENDING, ResearchRunNodeStatus.BLOCKED]
                    )
                )
                .all()
            ):
                node.status = ResearchRunNodeStatus.CANCELLED
                node.completed_at = _utcnow()
                node.error = "Cancelled by user"
            record.meta = meta

        db.commit()
    finally:
        db.close()

    return get_research_run_payload(research_run_id)


def get_research_run_evidence_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Return a shaped evidence payload for the research run."""

    payload = get_research_run_payload(research_run_id)
    if payload is None:
        return None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    planning = (
        result.get("planning") if isinstance(result, dict) else None
    ) or _get_node_result_from_payload(payload, "plan_query") or {}
    evidence = (
        result.get("evidence") if isinstance(result, dict) else None
    ) or _get_node_result_from_payload(payload, "gather_evidence") or {}
    curated_sources = (
        result.get("curated_sources") if isinstance(result, dict) else None
    ) or _get_node_result_from_payload(payload, "curate_sources") or {}
    evidence_payload = ResearchRunEvidencePayload(
        research_run_id=research_run_id,
        status=str(payload.get("status") or ""),
        claim_targets=(planning or {}).get("claim_targets") or [],
        rewritten_research_brief=(planning or {}).get("rewritten_research_brief"),
        sources=(curated_sources or {}).get("sources") or (evidence or {}).get("sources") or [],
        filtered_sources=(curated_sources or {}).get("filtered_sources") or [],
        citations=(curated_sources or {}).get("citations") or [],
        coverage_summary=(evidence or {}).get("coverage_summary") or {},
        source_summary=(curated_sources or {}).get("source_summary") or {},
        freshness_summary=(curated_sources or {}).get("freshness_summary") or {},
        search_lanes_used=(evidence or {}).get("search_lanes_used") or [],
    )
    return evidence_payload.model_dump(mode="json")


def get_research_run_report_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Return a shaped report payload for the research run."""

    payload = get_research_run_payload(research_run_id)
    if payload is None:
        return None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    report_payload = ResearchRunReportPayload(
        research_run_id=research_run_id,
        status=str(payload.get("status") or ""),
        answer_markdown=(result or {}).get("answer_markdown"),
        answer=(result or {}).get("answer"),
        claims=(result or {}).get("claims") or [],
        citations=(result or {}).get("citations") or [],
        limitations=(result or {}).get("limitations") or [],
        critic_findings=(result or {}).get("critic_findings") or [],
        quality_summary=(result or {}).get("quality_summary") or {},
    )
    return report_payload.model_dump(mode="json")


def _upsert_evidence_artifact(
    db,
    *,
    run_record: ResearchRun,
    source: Dict[str, Any],
    node_id: str,
    curation_status: str,
    order_index: int,
) -> EvidenceArtifact:
    source_payload = ResearchRunSourcePayload.model_validate(source)
    source_data = source_payload.model_dump(mode="python")
    citation_id = source_payload.citation_id
    fallback_key, normalized_url = _build_fallback_artifact_key(source_data)

    query = db.query(EvidenceArtifact).filter(EvidenceArtifact.research_run_id == run_record.id)
    artifact = None
    if citation_id:
        artifact = query.filter(EvidenceArtifact.artifact_key == citation_id).one_or_none()
    if artifact is None:
        artifact = query.filter(EvidenceArtifact.artifact_key == fallback_key).one_or_none()
    if artifact is None and citation_id and normalized_url:
        artifact = (
            query.filter(EvidenceArtifact.normalized_url == normalized_url)
            .order_by(EvidenceArtifact.id.asc())
            .one_or_none()
        )

    if artifact is None:
        artifact = EvidenceArtifact(  # type: ignore[call-arg]
            research_run_id=run_record.id,
            artifact_key=citation_id or fallback_key,
            origin_node_id=node_id,
            last_seen_node_id=node_id,
        )
        db.add(artifact)

    current_rank = _artifact_status_rank(artifact.curation_status)
    incoming_rank = _artifact_status_rank(curation_status)

    if citation_id:
        artifact.artifact_key = citation_id
        artifact.citation_id = citation_id
    elif not artifact.artifact_key:
        artifact.artifact_key = fallback_key

    artifact.artifact_type = source_payload.artifact_type or artifact.artifact_type or "source"
    artifact.origin_node_id = artifact.origin_node_id or node_id
    artifact.last_seen_node_id = node_id
    if artifact.order_index is None or incoming_rank >= current_rank:
        artifact.order_index = order_index
    if incoming_rank >= current_rank:
        artifact.curation_status = curation_status

    if source_payload.title is not None:
        artifact.title = source_payload.title
    if source_payload.url is not None:
        artifact.url = source_payload.url
    artifact.normalized_url = normalized_url or artifact.normalized_url
    if source_payload.publisher is not None:
        artifact.publisher = source_payload.publisher
    if source_payload.published_at is not None:
        artifact.published_at = source_payload.published_at
    if source_payload.source_type is not None:
        artifact.source_type = source_payload.source_type
    if source_payload.snippet is not None:
        artifact.snippet = source_payload.snippet
    if source_payload.display_snippet is not None:
        artifact.display_snippet = source_payload.display_snippet
    if source_payload.filtered_reason is not None:
        artifact.filtered_reason = source_payload.filtered_reason
    if source_payload.relevance_score is not None:
        artifact.relevance_score = source_payload.relevance_score

    merged_quality_flags = sorted(
        set(_coerce_string_list(artifact.quality_flags or []))
        | set(source_payload.quality_flags)
    )
    artifact.quality_flags = merged_quality_flags

    source_requirements = dict((run_record.meta or {}).get("source_requirements") or {})
    freshness_window_days = source_requirements.get("freshness_window_days")
    try:
        freshness_window_days = (
            int(freshness_window_days) if freshness_window_days is not None else None
        )
    except (TypeError, ValueError):
        freshness_window_days = None
    artifact.freshness_metadata = _build_freshness_metadata(
        source=source_data,
        freshness_required=bool((run_record.meta or {}).get("freshness_required", False)),
        freshness_window_days=freshness_window_days,
        reference_time=run_record.completed_at or run_record.updated_at or run_record.created_at,
    )
    artifact.raw_payload = redact_sensitive_payload(
        source_payload.model_dump(mode="json", exclude_none=True)
    )

    artifact_meta = dict(artifact.meta or {})
    observed_node_ids = _coerce_string_list(artifact_meta.get("observed_node_ids") or [])
    if node_id not in observed_node_ids:
        observed_node_ids.append(node_id)
    artifact_meta["observed_node_ids"] = observed_node_ids
    artifact_meta["fallback_key"] = fallback_key
    artifact.meta = artifact_meta
    return artifact


def _persist_phase2_evidence_artifacts(
    db,
    *,
    run_record: ResearchRun,
    node_id: str,
    node_result: Any,
) -> None:
    if not isinstance(node_result, dict):
        return

    if node_id == "gather_evidence":
        sources = [item for item in (node_result.get("sources") or []) if isinstance(item, dict)]
        for index, source in enumerate(sources, start=1):
            _upsert_evidence_artifact(
                db,
                run_record=run_record,
                source=source,
                node_id=node_id,
                curation_status="gathered",
                order_index=index,
            )
        return

    if node_id != "curate_sources":
        return

    citations = [item for item in (node_result.get("citations") or []) if isinstance(item, dict)]
    sources = [item for item in (node_result.get("sources") or []) if isinstance(item, dict)]
    filtered_sources = [
        item for item in (node_result.get("filtered_sources") or []) if isinstance(item, dict)
    ]

    for index, citation in enumerate(citations, start=1):
        _upsert_evidence_artifact(
            db,
            run_record=run_record,
            source=citation,
            node_id=node_id,
            curation_status="cited",
            order_index=index,
        )
    for index, source in enumerate(sources, start=1):
        _upsert_evidence_artifact(
            db,
            run_record=run_record,
            source=source,
            node_id=node_id,
            curation_status="selected",
            order_index=index,
        )
    for index, source in enumerate(filtered_sources, start=len(sources) + 1):
        _upsert_evidence_artifact(
            db,
            run_record=run_record,
            source=source,
            node_id=node_id,
            curation_status="filtered",
            order_index=index,
        )


def _ensure_placeholder_artifact(
    db,
    *,
    run_record: ResearchRun,
    citation_id: str,
    order_index: int,
) -> EvidenceArtifact:
    artifact = (
        db.query(EvidenceArtifact)
        .filter(EvidenceArtifact.research_run_id == run_record.id)
        .filter(EvidenceArtifact.artifact_key == citation_id)
        .one_or_none()
    )
    if artifact is not None:
        return artifact

    artifact = EvidenceArtifact(  # type: ignore[call-arg]
        research_run_id=run_record.id,
        artifact_key=citation_id,
        citation_id=citation_id,
        artifact_type="source",
        origin_node_id="revise_final_answer",
        last_seen_node_id="revise_final_answer",
        order_index=order_index,
        curation_status="cited",
        quality_flags=[],
        freshness_metadata={},
        raw_payload={"citation_id": citation_id},
        meta={"placeholder": True},
    )
    db.add(artifact)
    return artifact


def _persist_phase2_claims_and_links(
    db,
    *,
    run_record: ResearchRun,
    final_answer: Any,
) -> None:
    if not isinstance(final_answer, dict):
        return

    citations = [item for item in (final_answer.get("citations") or []) if isinstance(item, dict)]
    for index, citation in enumerate(citations, start=1):
        _upsert_evidence_artifact(
            db,
            run_record=run_record,
            source=citation,
            node_id="revise_final_answer",
            curation_status="cited",
            order_index=index,
        )
    db.flush()

    db.query(ClaimLink).filter(ClaimLink.research_run_id == run_record.id).delete(
        synchronize_session=False
    )
    db.query(Claim).filter(Claim.research_run_id == run_record.id).delete(synchronize_session=False)

    artifacts = (
        db.query(EvidenceArtifact)
        .filter(EvidenceArtifact.research_run_id == run_record.id)
        .order_by(EvidenceArtifact.id.asc())
        .all()
    )
    artifacts_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
    artifacts_by_citation = {
        artifact.citation_id: artifact for artifact in artifacts if artifact.citation_id
    }

    claims = [item for item in (final_answer.get("claims") or []) if isinstance(item, dict)]
    used_claim_ids: set[str] = set()
    for claim_index, item in enumerate(claims, start=1):
        raw_claim_id = item.get("claim_id")
        candidate_id = str(raw_claim_id).strip() if raw_claim_id is not None else ""
        if not candidate_id:
            candidate_id = f"C{claim_index}"

        claim_id = candidate_id
        suffix = 2
        while claim_id in used_claim_ids:
            claim_id = f"{candidate_id}-{suffix}"
            suffix += 1
        used_claim_ids.add(claim_id)

        claim_text = str(item.get("claim") or "").strip() or f"Claim {claim_index}"
        supporting_citation_ids: List[str] = []
        seen_citation_ids = set()
        for citation_id in _coerce_string_list(item.get("supporting_citation_ids") or []):
            if citation_id in seen_citation_ids:
                continue
            seen_citation_ids.add(citation_id)
            supporting_citation_ids.append(citation_id)

        db.add(
            Claim(  # type: ignore[call-arg]
                research_run_id=run_record.id,
                claim_id=claim_id,
                claim_order=claim_index,
                claim=claim_text,
                confidence=str(item.get("confidence")) if item.get("confidence") is not None else None,
                source_of_truth_node_id="revise_final_answer",
                raw_payload=redact_sensitive_payload(dict(item)),
                meta={"supporting_citation_ids": supporting_citation_ids},
            )
        )

        for link_order, citation_id in enumerate(supporting_citation_ids, start=1):
            artifact = artifacts_by_key.get(citation_id) or artifacts_by_citation.get(citation_id)
            if artifact is None:
                artifact = _ensure_placeholder_artifact(
                    db,
                    run_record=run_record,
                    citation_id=citation_id,
                    order_index=link_order,
                )
                artifacts_by_key[artifact.artifact_key] = artifact
                if artifact.citation_id:
                    artifacts_by_citation[artifact.citation_id] = artifact

            db.add(
                ClaimLink(  # type: ignore[call-arg]
                    research_run_id=run_record.id,
                    claim_id=claim_id,
                    artifact_key=artifact.artifact_key,
                    relation_type=CLAIM_RELATION_SUPPORTS,
                    link_order=link_order,
                    raw_payload={"citation_id": citation_id},
                )
            )


def _load_phase2_graph_records(
    research_run_id: str,
) -> Optional[tuple[ResearchRun, List[EvidenceArtifact], List[Claim], List[ClaimLink]]]:
    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None

        meta = dict(record.meta or {})
        if meta.get(PHASE2_GRAPH_SCHEMA_META_KEY) != PHASE2_GRAPH_SCHEMA_VERSION:
            raise ResearchRunPhase2UnavailableError(
                "Research run predates Phase 2 graph persistence. Rerun the research job to hydrate evidence graph data."
            )

        artifacts = (
            db.query(EvidenceArtifact)
            .filter(EvidenceArtifact.research_run_id == research_run_id)
            .order_by(EvidenceArtifact.id.asc())
            .all()
        )
        claims = (
            db.query(Claim)
            .filter(Claim.research_run_id == research_run_id)
            .order_by(Claim.claim_order.asc(), Claim.id.asc())
            .all()
        )
        links = (
            db.query(ClaimLink)
            .filter(ClaimLink.research_run_id == research_run_id)
            .order_by(ClaimLink.claim_id.asc(), ClaimLink.link_order.asc(), ClaimLink.id.asc())
            .all()
        )
        updated_claims = _apply_phase2_claim_scoring(
            run_record=record,
            claims=claims,
            artifacts=artifacts,
            links=links,
        )
        if updated_claims:
            unchanged_claims = [claim for claim in claims if claim not in updated_claims]
            db.flush()
            _detach_phase2_graph_records(
                db,
                record=record,
                artifacts=artifacts,
                claims=unchanged_claims,
                links=links,
            )
            db.commit()
            claims = (
                db.query(Claim)
                .filter(Claim.research_run_id == research_run_id)
                .order_by(Claim.claim_order.asc(), Claim.id.asc())
                .all()
            )
            _detach_phase2_graph_records(
                db,
                claims=claims,
            )
        else:
            _detach_phase2_graph_records(
                db,
                record=record,
                artifacts=artifacts,
                claims=claims,
                links=links,
            )
        return record, artifacts, claims, links
    finally:
        db.close()


def get_research_run_evidence_graph_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Return the persisted Phase 2 evidence graph for a research run."""

    loaded = _load_phase2_graph_records(research_run_id)
    if loaded is None:
        return None

    record, artifacts, claims, links = loaded
    payload = get_research_run_payload(research_run_id) or {}
    artifacts = sorted(
        artifacts,
        key=lambda item: (
            item.order_index is None,
            item.order_index or 0,
            item.citation_id or item.artifact_key,
        ),
    )
    claim_order_by_id = {claim.claim_id: claim.claim_order for claim in claims}
    artifact_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
    links = sorted(
        links,
        key=lambda item: (
            claim_order_by_id.get(item.claim_id, 0),
            item.link_order or 0,
            item.artifact_key,
        ),
    )
    links_by_claim: Dict[str, List[ClaimLink]] = {}
    for link in links:
        links_by_claim.setdefault(link.claim_id, []).append(link)

    serialized_artifacts = [EvidenceArtifactPayload.from_record(item) for item in artifacts]
    serialized_claims: List[EvidenceGraphClaimPayload] = []
    for claim in claims:
        scoring = _phase2_scoring_from_claim_meta(claim)
        claim_links = links_by_claim.get(claim.claim_id, [])
        supporting_artifact_keys = [link.artifact_key for link in claim_links]
        supporting_citation_ids = [
            artifact_by_key.get(link.artifact_key).citation_id if artifact_by_key.get(link.artifact_key) else None
            for link in claim_links
        ]
        serialized_claims.append(
            EvidenceGraphClaimPayload(
                claim_id=claim.claim_id,
                claim_order=claim.claim_order,
                claim=claim.claim,
                confidence=claim.confidence,
                confidence_score=scoring.get("confidence_score"),
                contradiction_status=scoring.get("contradiction_status"),
                contradiction_reasons=_coerce_string_list(scoring.get("contradiction_reasons") or []),
                supporting_artifact_keys=supporting_artifact_keys,
                supporting_citation_ids=[item for item in supporting_citation_ids if item],
            )
        )

    serialized_links: List[EvidenceGraphLinkPayload] = []
    for link in links:
        artifact = artifact_by_key.get(link.artifact_key)
        serialized_links.append(
            EvidenceGraphLinkPayload(
                claim_id=link.claim_id,
                artifact_key=link.artifact_key,
                citation_id=artifact.citation_id if artifact else None,
                relation_type=link.relation_type,
                link_order=link.link_order,
            )
        )

    meta = dict(record.meta or {})
    claim_scoring_summary = _build_phase2_claim_scoring_summary(claims)
    graph_payload = ResearchRunEvidenceGraphPayload(
        schema_version=PHASE2_GRAPH_SCHEMA_VERSION,
        research_run_id=record.id,
        title=record.title,
        description=record.description,
        status=str(payload.get("status") or _enum_value(record.status)),
        workflow=meta.get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
        artifacts=serialized_artifacts,
        claims=serialized_claims,
        links=serialized_links,
        summary=EvidenceGraphSummaryPayload(
            artifact_count=len(serialized_artifacts),
            cited_artifact_count=sum(
                1 for item in serialized_artifacts if item.curation_status == "cited"
            ),
            filtered_artifact_count=sum(
                1 for item in serialized_artifacts if item.curation_status == "filtered"
            ),
            claim_count=len(serialized_claims),
            link_count=len(serialized_links),
            high_confidence_claim_count=claim_scoring_summary["high_confidence_claim_count"],
            mixed_evidence_claim_count=claim_scoring_summary["mixed_evidence_claim_count"],
            insufficient_evidence_claim_count=claim_scoring_summary["insufficient_evidence_claim_count"],
        ),
    )
    return graph_payload.model_dump(mode="json")


def get_research_run_report_pack_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Return the persisted Phase 2 JSON report pack for a research run."""

    loaded = _load_phase2_graph_records(research_run_id)
    if loaded is None:
        return None

    record, artifacts, claims, _links = loaded
    evidence_payload = get_research_run_evidence_payload(research_run_id) or {}
    report_payload = get_research_run_report_payload(research_run_id) or {}
    graph_payload = get_research_run_evidence_graph_payload(research_run_id) or {}

    artifact_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
    artifact_by_citation = {
        artifact.citation_id: artifact for artifact in artifacts if artifact.citation_id
    }

    citation_artifacts: List[EvidenceArtifactPayload] = []
    seen_citations = set()
    for index, citation in enumerate(report_payload.get("citations") or [], start=1):
        if not isinstance(citation, dict):
            continue
        citation_payload = ResearchRunSourcePayload.model_validate(citation)
        citation_id = citation_payload.citation_id or ""
        artifact = artifact_by_citation.get(citation_id) or artifact_by_key.get(citation_id)
        if artifact is None:
            fallback_key, _ = _build_fallback_artifact_key(citation)
            artifact = artifact_by_key.get(fallback_key)
        if artifact is None:
            artifact_payload = EvidenceArtifactPayload(
                artifact_key=citation_id or f"report-citation-{index}",
                citation_id=citation_id or None,
                artifact_type="source",
                origin_node_id="revise_final_answer",
                last_seen_node_id="revise_final_answer",
                order_index=index,
                title=citation_payload.title,
                url=citation_payload.url,
                normalized_url=_normalize_source_url(citation_payload.url),
                publisher=citation_payload.publisher,
                published_at=citation_payload.published_at,
                source_type=citation_payload.source_type,
                snippet=citation_payload.snippet,
                display_snippet=citation_payload.display_snippet,
                relevance_score=citation_payload.relevance_score,
                curation_status="cited",
                quality_flags=citation_payload.quality_flags,
                filtered_reason=citation_payload.filtered_reason,
                freshness_metadata={},
            )
        else:
            artifact_payload = EvidenceArtifactPayload.from_record(artifact)
        dedupe_key = artifact_payload.artifact_key
        if dedupe_key in seen_citations:
            continue
        seen_citations.add(dedupe_key)
        citation_artifacts.append(artifact_payload)

    supporting_evidence: List[EvidenceArtifactPayload] = []
    seen_supporting_keys = set()
    for link in graph_payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        artifact_key = link.get("artifact_key")
        if not artifact_key or artifact_key in seen_supporting_keys:
            continue
        artifact = artifact_by_key.get(artifact_key)
        if artifact is None:
            continue
        supporting_evidence.append(EvidenceArtifactPayload.from_record(artifact))
        seen_supporting_keys.add(artifact_key)

    graph_claims = [
        EvidenceGraphClaimPayload.model_validate(item)
        for item in graph_payload.get("claims") or []
        if isinstance(item, dict)
    ]
    graph_links = [
        EvidenceGraphLinkPayload.model_validate(item)
        for item in graph_payload.get("links") or []
        if isinstance(item, dict)
    ]

    generated_at = record.completed_at or record.updated_at or record.created_at
    meta = dict(record.meta or {})
    quality_summary = dict(report_payload.get("quality_summary") or {})
    quality_summary["claim_scoring"] = _build_phase2_claim_scoring_summary(claims)
    report_pack_payload = ResearchRunReportPackPayload(
        schema_version=PHASE2_GRAPH_SCHEMA_VERSION,
        research_run_id=record.id,
        title=record.title,
        description=record.description,
        status=str(report_payload.get("status") or _enum_value(record.status)),
        workflow=meta.get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
        generated_at=generated_at.isoformat() if generated_at else None,
        rewritten_research_brief=evidence_payload.get("rewritten_research_brief"),
        answer_markdown=report_payload.get("answer_markdown"),
        answer=report_payload.get("answer"),
        claims=graph_claims,
        citations=citation_artifacts,
        supporting_evidence=supporting_evidence,
        claim_lineage=graph_links,
        quality_summary=quality_summary,
        critic_findings=report_payload.get("critic_findings") or [],
        limitations=report_payload.get("limitations") or [],
    )
    return report_pack_payload.model_dump(mode="json")


def _serialize_verification_decision_record(record: VerificationDecision) -> Dict[str, Any]:
    return {
        "id": record.id,
        "research_run_id": record.research_run_id,
        "node_id": record.node_id,
        "attempt_id": record.attempt_id,
        "task_id": record.task_id,
        "payment_id": record.payment_id,
        "agent_id": record.agent_id,
        "decision": record.decision,
        "approved": bool(record.approved),
        "decision_source": record.decision_source,
        "overall_score": record.overall_score,
        "dimension_scores": record.dimension_scores or {},
        "rationale": record.rationale,
        "dissent_count": record.dissent_count,
        "quorum_policy": record.quorum_policy,
        "policy_snapshot": record.policy_snapshot or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "meta": record.meta or {},
    }


def _serialize_swarm_handoff_record(record: SwarmHandoff) -> Dict[str, Any]:
    return {
        "id": record.id,
        "research_run_id": record.research_run_id,
        "node_id": record.node_id,
        "attempt_id": record.attempt_id,
        "handoff_index": record.handoff_index,
        "from_agent_id": record.from_agent_id,
        "to_agent_id": record.to_agent_id,
        "handoff_type": record.handoff_type,
        "round_number": record.round_number,
        "status": record.status,
        "budget_remaining": record.budget_remaining,
        "verification_mode": record.verification_mode,
        "idempotency_key": record.idempotency_key,
        "blackboard_delta": record.blackboard_delta or {},
        "decision_log": record.decision_log or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "meta": record.meta or {},
    }


def _serialize_policy_evaluation_record(record: PolicyEvaluation) -> Dict[str, Any]:
    return {
        "id": record.id,
        "research_run_id": record.research_run_id,
        "node_id": record.node_id,
        "attempt_id": record.attempt_id,
        "task_id": record.task_id,
        "payment_id": record.payment_id,
        "evaluation_type": record.evaluation_type,
        "status": record.status,
        "outcome": record.outcome,
        "summary": record.summary,
        "details": record.details or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "meta": record.meta or {},
    }


def get_research_run_verification_decisions_payload(
    research_run_id: str,
) -> Optional[List[Dict[str, Any]]]:
    db = SessionLocal()
    try:
        exists = db.query(ResearchRun.id).filter(ResearchRun.id == research_run_id).one_or_none()
        if exists is None:
            return None
        records = (
            db.query(VerificationDecision)
            .filter(VerificationDecision.research_run_id == research_run_id)
            .order_by(VerificationDecision.created_at.asc(), VerificationDecision.id.asc())
            .all()
        )
        return [_serialize_verification_decision_record(record) for record in records]
    finally:
        db.close()


def get_research_run_swarm_handoffs_payload(
    research_run_id: str,
) -> Optional[List[Dict[str, Any]]]:
    db = SessionLocal()
    try:
        exists = db.query(ResearchRun.id).filter(ResearchRun.id == research_run_id).one_or_none()
        if exists is None:
            return None
        records = (
            db.query(SwarmHandoff)
            .filter(SwarmHandoff.research_run_id == research_run_id)
            .order_by(SwarmHandoff.created_at.asc(), SwarmHandoff.id.asc())
            .all()
        )
        return [_serialize_swarm_handoff_record(record) for record in records]
    finally:
        db.close()


def get_research_run_policy_evaluations_payload(
    research_run_id: str,
) -> Optional[List[Dict[str, Any]]]:
    db = SessionLocal()
    try:
        exists = db.query(ResearchRun.id).filter(ResearchRun.id == research_run_id).one_or_none()
        if exists is None:
            return None
        records = (
            db.query(PolicyEvaluation)
            .filter(PolicyEvaluation.research_run_id == research_run_id)
            .order_by(PolicyEvaluation.created_at.asc(), PolicyEvaluation.id.asc())
            .all()
        )
        return [_serialize_policy_evaluation_record(record) for record in records]
    finally:
        db.close()


def _load_plan_for_run(research_run_id: str) -> ResearchRunPlan:
    db = SessionLocal()
    try:
        run_record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one()
        meta = run_record.meta or {}
        nodes = (
            db.query(ResearchRunNode)
            .filter(ResearchRunNode.research_run_id == research_run_id)
            .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
            .all()
        )
        edges = (
            db.query(ResearchRunEdge)
            .filter(ResearchRunEdge.research_run_id == research_run_id)
            .order_by(ResearchRunEdge.id.asc())
            .all()
        )
        return ResearchRunPlan(
            workflow_template=run_record.workflow_template,
            workflow=meta.get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
            profile=ResearchRunProfile(
                requested_mode=ResearchMode(meta.get("research_mode", ResearchMode.AUTO.value)),
                classified_mode=ResearchMode(
                    meta.get("classified_mode", ResearchMode.LITERATURE.value)
                ),
                depth_mode=DepthMode(meta.get("depth_mode", DepthMode.STANDARD.value)),
                freshness_required=bool(meta.get("freshness_required", False)),
                source_requirements=SourceRequirements.model_validate(
                    meta.get("source_requirements")
                    or SourceRequirements(total_sources=6, min_academic_or_primary=3).model_dump()
                ),
                rounds_planned=RoundsPlan.model_validate(
                    meta.get("rounds_planned")
                    or RoundsPlan(evidence_rounds=1, critique_rounds=1).model_dump()
                ),
                scenario_analysis_requested=bool(meta.get("scenario_analysis_requested", False)),
                planner_notes=list(meta.get("planner_notes") or []),
                generated_at=str(meta.get("generated_at") or run_record.created_at.isoformat()),
            ),
            nodes=[
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "description": node.description,
                    "capability_requirements": node.capability_requirements,
                    "assigned_agent_id": node.assigned_agent_id,
                    "execution_order": node.execution_order,
                    "execution_parameters": dict((node.meta or {}).get("execution_parameters") or {}),
                    "input_bindings": dict((node.meta or {}).get("input_bindings") or {}),
                }
                for node in nodes
            ],
            edges=[
                {
                    "from_node_id": edge.from_node_id,
                    "to_node_id": edge.to_node_id,
                }
                for edge in edges
            ],
        )
    finally:
        db.close()


def _extract_node_candidate_agent_ids(node_record: ResearchRunNode) -> List[str]:
    return [
        str(item).strip()
        for item in list((node_record.meta or {}).get("candidate_agent_ids") or [])
        if str(item).strip()
    ]


def _serialize_blackboard_delta(
    *,
    node_id: str,
    result_payload: Dict[str, Any],
    verification_payload: Dict[str, Any],
) -> Dict[str, Any]:
    sources = [
        {
            "citation_id": item.get("citation_id"),
            "title": item.get("title"),
            "url": item.get("url"),
        }
        for item in (result_payload.get("sources") or result_payload.get("citations") or [])[:5]
        if isinstance(item, dict)
    ]
    claims = [
        {
            "claim_id": item.get("claim_id"),
            "claim": item.get("claim"),
            "confidence": item.get("confidence"),
        }
        for item in (result_payload.get("claims") or [])[:5]
        if isinstance(item, dict)
    ]
    critic_notes = [
        {
            "issue": item.get("issue"),
            "severity": item.get("severity"),
        }
        for item in (result_payload.get("critic_findings") or [])[:5]
        if isinstance(item, dict)
    ]
    decision_logs = []
    if verification_payload:
        decision_logs.append(
            {
                "overall_score": verification_payload.get("overall_score"),
                "decision": verification_payload.get("decision"),
                "retry_recommended": verification_payload.get("retry_recommended", False),
                "feedback": verification_payload.get("feedback"),
                "quorum_result": verification_payload.get("quorum_result") or {},
            }
        )
    return {
        "node_id": node_id,
        "evidence_cards": sources,
        "claim_drafts": claims,
        "critic_notes": critic_notes,
        "decision_logs": decision_logs,
    }


def _build_swarm_handoff_entries(
    *,
    node_id: str,
    attempt: ExecutionAttempt,
    run_record: ResearchRun,
    node_record: ResearchRunNode,
    selected_agent_id: Optional[str],
    verification_payload: Dict[str, Any],
    result_payload: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    handoff_context = dict((snapshot or {}).get("current_handoff_context") or {})
    budget_remaining = handoff_context.get("budget_remaining")
    verification_mode = handoff_context.get("verification_mode") or run_record.verification_mode
    idempotency_key = handoff_context.get("idempotency_key")
    blackboard_delta = _serialize_blackboard_delta(
        node_id=node_id,
        result_payload=result_payload,
        verification_payload=verification_payload,
    )

    stages_by_node = {
        "plan_query": [("orchestrator-agent", selected_agent_id, "plan_dispatch"), (selected_agent_id, selected_agent_id, "blackboard_update")],
        "gather_evidence": [("orchestrator-agent", selected_agent_id, "scout_dispatch"), (selected_agent_id, selected_agent_id, "evidence_merge")],
        "curate_sources": [("orchestrator-agent", selected_agent_id, "curation_dispatch"), (selected_agent_id, selected_agent_id, "source_filter_merge")],
        "draft_synthesis": [("orchestrator-agent", selected_agent_id, "synthesis_dispatch"), (selected_agent_id, selected_agent_id, "claim_draft_merge")],
        "critique_and_fact_check": [("orchestrator-agent", selected_agent_id, "critic_dispatch"), (selected_agent_id, selected_agent_id, "debate_merge")],
        "revise_final_answer": [("orchestrator-agent", selected_agent_id, "revision_dispatch"), (selected_agent_id, "orchestrator-agent", "final_merge")],
    }
    stages = stages_by_node.get(
        node_id,
        [("orchestrator-agent", selected_agent_id, "task_dispatch"), (selected_agent_id, "orchestrator-agent", "task_merge")],
    )

    entries: List[Dict[str, Any]] = []
    for handoff_index, (from_agent_id, to_agent_id, handoff_type) in enumerate(stages, start=1):
        entries.append(
            {
                "research_run_id": run_record.id,
                "node_id": node_record.node_id,
                "attempt_id": attempt.id,
                "handoff_index": handoff_index,
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "handoff_type": handoff_type,
                "round_number": int((verification_payload.get("quorum_result") or {}).get("round_number", 1) or 1),
                "status": "completed",
                "budget_remaining": budget_remaining,
                "verification_mode": verification_mode,
                "idempotency_key": idempotency_key,
                "blackboard_delta": blackboard_delta,
                "decision_log": {
                    "feedback": verification_payload.get("feedback"),
                    "decision": verification_payload.get("decision"),
                },
                "meta": {
                    "session_id": dict((run_record.meta or {}).get("session_state") or {}).get("session_id"),
                    "candidate_agent_ids": _extract_node_candidate_agent_ids(node_record),
                },
            }
        )
    return entries


def _update_trace_summary(db: Any, run_record: ResearchRun) -> None:
    verification_count = (
        db.query(VerificationDecision)
        .filter(VerificationDecision.research_run_id == run_record.id)
        .count()
    )
    handoff_count = (
        db.query(SwarmHandoff)
        .filter(SwarmHandoff.research_run_id == run_record.id)
        .count()
    )
    evaluation_count = (
        db.query(PolicyEvaluation)
        .filter(PolicyEvaluation.research_run_id == run_record.id)
        .count()
    )
    unresolved_count = (
        db.query(VerificationDecision)
        .filter(VerificationDecision.research_run_id == run_record.id)
        .filter(VerificationDecision.approved.is_(False))
        .count()
    )
    run_meta = dict(run_record.meta or {})
    run_meta["trace_summary"] = _trace_summary(
        verification_decision_count=verification_count,
        swarm_handoff_count=handoff_count,
        policy_evaluation_count=evaluation_count,
        unresolved_dissent_count=unresolved_count,
    )
    run_record.meta = run_meta


def _persist_attempt_trace_bundle(
    db: Any,
    *,
    run_record: ResearchRun,
    node_record: ResearchRunNode,
    attempt: ExecutionAttempt,
    task: Optional[Task],
    result: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    cancelled: bool = False,
    error: Optional[str] = None,
) -> None:
    verification_payload = (
        dict(result.get("verification") or {})
        if isinstance(result.get("verification"), dict)
        else {}
    )
    selected_agent = (
        dict(result.get("selected_agent") or {})
        if isinstance(result.get("selected_agent"), dict)
        else {}
    )
    selected_agent_id = str(
        selected_agent.get("agent_id")
        or result.get("agent_used")
        or attempt.agent_id
        or node_record.assigned_agent_id
        or ""
    ).strip() or None
    run_policy = _get_run_policy(dict(run_record.meta or {}))
    quorum_result = (
        dict(verification_payload.get("quorum_result") or {})
        if isinstance(verification_payload.get("quorum_result"), dict)
        else {}
    )
    retry_recommended = bool(verification_payload.get("retry_recommended") or result.get("retry_recommended"))
    approved = bool(result.get("success")) and not cancelled and not retry_recommended

    if cancelled:
        decision = "cancelled"
        decision_source = "cancellation"
    elif retry_recommended:
        decision = "retry_requested"
        decision_source = "strict_quorum"
    elif approved:
        decision = "approved"
        decision_source = "human_reviewer" if result.get("human_approved") else "auto_verifier"
    else:
        decision = "rejected"
        decision_source = "runtime_failure"

    decision_row = VerificationDecision(  # type: ignore[call-arg]
        research_run_id=run_record.id,
        node_id=node_record.node_id,
        attempt_id=attempt.id,
        task_id=task.id if task else attempt.task_id,
        payment_id=attempt.payment_id,
        agent_id=selected_agent_id,
        decision=decision,
        approved=approved,
        decision_source=decision_source,
        overall_score=verification_payload.get("overall_score") or attempt.verification_score,
        dimension_scores=verification_payload.get("dimension_scores") or {},
        rationale=verification_payload.get("feedback") or error or result.get("error"),
        dissent_count=quorum_result.get("dissent_count"),
        quorum_policy=quorum_result.get("quorum_policy") or run_policy.get("quorum_policy"),
        policy_snapshot={**run_policy, **quorum_result},
        meta={
            "auto_approved": bool(result.get("auto_approved")),
            "human_approved": bool(result.get("human_approved")),
            "retry_recommended": retry_recommended,
        },
    )
    db.add(decision_row)

    policy_rows = []
    if selected_agent_id:
        policy_rows.append(
            PolicyEvaluation(  # type: ignore[call-arg]
                research_run_id=run_record.id,
                node_id=node_record.node_id,
                attempt_id=attempt.id,
                task_id=task.id if task else attempt.task_id,
                payment_id=attempt.payment_id,
                evaluation_type="agent_selection",
                status="passed",
                outcome="selected",
                summary=f"Selected agent {selected_agent_id} for node {node_record.node_id}",
                details={
                    "selected_agent_id": selected_agent_id,
                    "candidate_agent_ids": _extract_node_candidate_agent_ids(node_record),
                },
                meta={"selection_strategy": (node_record.meta or {}).get("selection_strategy")},
            )
        )
    policy_rows.append(
        PolicyEvaluation(  # type: ignore[call-arg]
            research_run_id=run_record.id,
            node_id=node_record.node_id,
            attempt_id=attempt.id,
            task_id=task.id if task else attempt.task_id,
            payment_id=attempt.payment_id,
            evaluation_type="verification_gate",
            status="passed" if approved else ("retry" if retry_recommended else "failed"),
            outcome="allow" if approved else ("retry" if retry_recommended else "reject"),
            summary=verification_payload.get("feedback") or error or result.get("error"),
            details={
                "overall_score": verification_payload.get("overall_score") or attempt.verification_score,
                "decision": verification_payload.get("decision"),
                "quorum_result": quorum_result,
                "strict_mode": run_policy.get("strict_mode", False),
            },
            meta={"policy": run_policy},
        )
    )
    for row in policy_rows:
        db.add(row)

    result_payload = (
        dict(result.get("result") or {})
        if isinstance(result.get("result"), dict)
        else {}
    )
    for entry in _build_swarm_handoff_entries(
        node_id=node_record.node_id,
        attempt=attempt,
        run_record=run_record,
        node_record=node_record,
        selected_agent_id=selected_agent_id,
        verification_payload=verification_payload,
        result_payload=result_payload,
        snapshot=snapshot,
    ):
        db.add(SwarmHandoff(**entry))  # type: ignore[arg-type]

    run_meta = dict(run_record.meta or {})
    session_state = dict(run_meta.get("session_state") or {})
    blackboard_delta = _serialize_blackboard_delta(
        node_id=node_record.node_id,
        result_payload=result_payload,
        verification_payload=verification_payload,
    )
    session_state["last_node_id"] = node_record.node_id
    session_state["last_attempt_id"] = attempt.id
    session_state["blackboard_keys"] = sorted(
        key for key, value in blackboard_delta.items() if value
    )
    run_meta["session_state"] = session_state
    run_record.meta = run_meta
    _update_trace_summary(db, run_record)


class ResearchRunExecutor:
    """Execute a persisted research run through a Strands graph."""

    def __init__(self, research_run_id: str):
        self.research_run_id = research_run_id

    async def run(self) -> None:
        """Execute the full research run and persist terminal state."""

        self._mark_started()
        graph = self._build_graph()

        try:
            await self._wait_for_control_state()
            await graph.invoke_async(
                f"Execute research run {self.research_run_id}",
                invocation_state={"runner": self},
            )
            self._mark_completed()
        except ResearchRunCancelledError as exc:
            logger.info("Research run %s cancelled: %s", self.research_run_id, exc)
            self._mark_cancelled(str(exc))
            self._cancel_pending_nodes(reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Research run %s failed", self.research_run_id)
            self._mark_failed(str(exc))
            self._block_pending_descendants()

    async def execute_node(self, node_id: str) -> Dict[str, Any]:
        """Execute one node by creating a backing task and reusing the phase 0 microtask flow."""

        node_record = self._get_node(node_id)
        if _enum_value(node_record.status) == ResearchRunNodeStatus.COMPLETED.value and node_record.result is not None:
            return {
                "success": True,
                "task_id": node_record.latest_task_id,
                "todo_id": node_id,
                "result": node_record.result,
                "todo_status": "completed",
                "resumed": True,
            }
        if _enum_value(node_record.status) == ResearchRunNodeStatus.CANCELLED.value:
            raise ResearchRunCancelledError(node_record.error or "Cancelled by user")

        await self._wait_for_control_state()
        max_node_attempts = self._resolve_max_node_attempts(
            self._resolve_execution_parameters(node_record)
        )

        while True:
            attempt_id, task_id, node_title = self._create_attempt(node_id)
            await self._initialize_attempt_runtime(
                node_id=node_id,
                attempt_id=attempt_id,
                task_id=task_id,
            )
            attempt_failure_recorded = False

            try:
                context = self._build_handoff_context(
                    node_id=node_id,
                    attempt_id=attempt_id,
                    task_id=task_id,
                )
                node_record = self._get_node(node_id)
                execution_parameters = self._resolve_execution_parameters(node_record)
                previous_attempts = self._load_attempts_for_node(node_id)
                previous_agent_ids = [
                    str(item.agent_id or "").strip()
                    for item in previous_attempts
                    if item.id != attempt_id and item.agent_id
                ]

                result = await execute_microtask(
                    task_id=task_id,
                    todo_id=node_id,
                    task_name=node_title,
                    task_description=node_record.description,
                    capability_requirements=node_record.capability_requirements,
                    budget_limit=self._get_research_run().budget_limit,
                    min_reputation_score=DEFAULT_MIN_REPUTATION_SCORE,
                    execution_parameters=execution_parameters,
                    todo_list=[
                        {
                            "id": node_id,
                            "title": node_record.title,
                            "description": node_record.description,
                            "assigned_to": node_record.assigned_agent_id,
                            "status": "pending",
                        }
                    ],
                    handoff_context=context.model_dump(mode="json"),
                    prefer_strands_executor_relay=True,
                    preferred_agent_id=node_record.assigned_agent_id,
                    excluded_agent_ids=previous_agent_ids,
                )

                snapshot = load_task_snapshot(task_id)
                cancelled = self._attempt_was_cancelled(result=result, snapshot=snapshot)
                if result.get("success"):
                    self._finalize_attempt(
                        node_id=node_id,
                        attempt_id=attempt_id,
                        task_id=task_id,
                        result=result,
                        snapshot=snapshot,
                        cancelled=cancelled,
                    )
                    return result

                if cancelled:
                    self._finalize_attempt(
                        node_id=node_id,
                        attempt_id=attempt_id,
                        task_id=task_id,
                        result=result,
                        snapshot=snapshot,
                        cancelled=True,
                    )
                    raise ResearchRunCancelledError(result.get("error") or "Cancelled by user")

                self._record_attempt_failure(
                    node_id=node_id,
                    attempt_id=attempt_id,
                    task_id=task_id,
                    error=str(result.get("error") or f"Research run node '{node_id}' failed"),
                    result=result,
                    cancelled=False,
                )
                attempt_failure_recorded = True

                if self._should_retry_attempt(
                    max_node_attempts=max_node_attempts,
                    completed_attempts=len(previous_attempts),
                    result=result,
                    cancelled=False,
                ):
                    self._prepare_retry_candidate(
                        node_id,
                        error=str(result.get("error") or "Retrying failed node"),
                    )
                    continue

                raise RuntimeError(result.get("error", f"Research run node '{node_id}' failed"))
            except ResearchRunCancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not attempt_failure_recorded:
                    self._record_attempt_failure(
                        node_id=node_id,
                        attempt_id=attempt_id,
                        task_id=task_id,
                        error=str(exc),
                        cancelled=False,
                    )
                completed_attempts = len(self._load_attempts_for_node(node_id))
                if self._should_retry_attempt(
                    max_node_attempts=max_node_attempts,
                    completed_attempts=completed_attempts,
                    result=None,
                    cancelled=False,
                ):
                    self._prepare_retry_candidate(node_id, error=str(exc))
                    continue
                raise

    def _build_graph(self):
        plan = _load_plan_for_run(self.research_run_id)
        builder = GraphBuilder()
        builder.set_graph_id(f"research_run:{self.research_run_id}")
        builder.set_execution_timeout(3600)
        builder.set_max_node_executions(max(len(plan.nodes), 1))

        for node in sorted(plan.nodes, key=lambda item: item.execution_order):
            builder.add_node(_ResearchRunGraphNodeExecutor(node.node_id), node_id=node.node_id)
        for edge in plan.edges:
            builder.add_edge(edge.from_node_id, edge.to_node_id)
        return builder.build()

    def _get_research_run(self) -> ResearchRun:
        db = SessionLocal()
        try:
            return db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
        finally:
            db.close()

    def _get_node(self, node_id: str) -> ResearchRunNode:
        db = SessionLocal()
        try:
            return (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
        finally:
            db.close()

    def _load_attempts_for_node(self, node_id: str) -> List[ExecutionAttempt]:
        db = SessionLocal()
        try:
            return (
                db.query(ExecutionAttempt)
                .filter(ExecutionAttempt.research_run_id == self.research_run_id)
                .filter(ExecutionAttempt.node_id == node_id)
                .order_by(ExecutionAttempt.attempt_number.asc(), ExecutionAttempt.created_at.asc())
                .all()
            )
        finally:
            db.close()

    def _get_run_meta(self) -> Dict[str, Any]:
        run_record = self._get_research_run()
        return dict(run_record.meta or {})

    def _resolve_max_node_attempts(self, execution_parameters: Dict[str, Any]) -> int:
        return max(
            1,
            int(
                execution_parameters.get("max_node_attempts")
                or self._get_run_policy().get("max_node_attempts")
                or DEFAULT_MAX_NODE_ATTEMPTS
            ),
        )

    def _get_run_policy(self) -> Dict[str, Any]:
        return _get_run_policy(self._get_run_meta())

    def _prepare_retry_candidate(self, node_id: str, *, error: str) -> str:
        db = SessionLocal()
        try:
            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
            attempts = (
                db.query(ExecutionAttempt)
                .filter(ExecutionAttempt.research_run_id == self.research_run_id)
                .filter(ExecutionAttempt.node_id == node_id)
                .order_by(ExecutionAttempt.attempt_number.asc(), ExecutionAttempt.created_at.asc())
                .all()
            )
            used_agent_ids = [str(item.agent_id or "").strip() for item in attempts if item.agent_id]
            candidate_agent_ids = _extract_node_candidate_agent_ids(node_record)
            next_agent_id = node_record.assigned_agent_id
            if self._get_run_policy().get("reroute_on_failure", False):
                for candidate_agent_id in candidate_agent_ids:
                    if candidate_agent_id not in used_agent_ids:
                        next_agent_id = candidate_agent_id
                        break

            node_meta = dict(node_record.meta or {})
            node_meta["last_retry_error"] = error
            node_record.meta = node_meta
            node_record.status = ResearchRunNodeStatus.PENDING
            node_record.completed_at = None
            node_record.result = None
            node_record.error = error
            node_record.assigned_agent_id = next_agent_id
            db.commit()
            return next_agent_id
        finally:
            db.close()

    def _should_retry_attempt(
        self,
        *,
        max_node_attempts: int,
        completed_attempts: int,
        result: Optional[Dict[str, Any]],
        cancelled: bool,
    ) -> bool:
        if cancelled or completed_attempts >= max_node_attempts:
            return False
        if result is None:
            return True
        return bool(result.get("retry_recommended")) or completed_attempts < max_node_attempts

    async def _wait_for_control_state(self) -> None:
        while True:
            meta = self._get_run_meta()
            control_state = _get_control_state(meta)
            if control_state == RUN_CONTROL_ACTIVE:
                return
            if control_state in {RUN_CONTROL_PAUSE_REQUESTED, RUN_CONTROL_PAUSED}:
                self._mark_paused()
                await asyncio.sleep(0.2)
                continue
            if control_state in {RUN_CONTROL_CANCEL_REQUESTED, RUN_CONTROL_CANCELLED}:
                raise ResearchRunCancelledError(str(meta.get("control_reason") or "Cancelled by user"))
            return

    def _mark_started(self) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            if _is_terminal_run_status(record.status):
                db.rollback()
                return
            meta = dict(record.meta or {})
            if _get_control_state(meta) == RUN_CONTROL_PAUSED:
                record.status = ResearchRunStatus.PAUSED
            else:
                record.status = ResearchRunStatus.RUNNING
            record.started_at = record.started_at or _utcnow()
            db.commit()
        finally:
            db.close()

    def _mark_paused(self) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            if _is_terminal_run_status(record.status):
                db.rollback()
                return
            meta = dict(record.meta or {})
            meta["control_state"] = RUN_CONTROL_PAUSED
            record.meta = meta
            record.status = ResearchRunStatus.PAUSED
            db.commit()
        finally:
            db.close()

    def _mark_completed(self) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            record_meta = record.meta or {}
            nodes = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
                .all()
            )
            node_payloads = [
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "status": _enum_value(node.status),
                    "assigned_agent_id": node.assigned_agent_id,
                    "task_id": node.latest_task_id,
                    "payment_id": node.latest_payment_id,
                    "result": node.result,
                }
                for node in nodes
            ]
            planning = next(
                (item["result"] for item in node_payloads if item["node_id"] == "plan_query"),
                None,
            )
            evidence = next(
                (item["result"] for item in node_payloads if item["node_id"] == "gather_evidence"),
                None,
            )
            curated_sources = next(
                (item["result"] for item in node_payloads if item["node_id"] == "curate_sources"),
                None,
            )
            draft = next(
                (item["result"] for item in node_payloads if item["node_id"] == "draft_synthesis"),
                None,
            )
            critique = next(
                (item["result"] for item in node_payloads if item["node_id"] == "critique_and_fact_check"),
                None,
            )
            final_answer = next(
                (item["result"] for item in node_payloads if item["node_id"] == "revise_final_answer"),
                None,
            )
            rounds_completed = _merge_rounds_completed(evidence, critique, final_answer)
            result = {
                "research_run_id": record.id,
                "workflow": record_meta.get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
                "template": record.workflow_template,
                "research_mode": record_meta.get("research_mode", ResearchMode.AUTO.value),
                "classified_mode": record_meta.get(
                    "classified_mode", ResearchMode.LITERATURE.value
                ),
                "depth_mode": record_meta.get("depth_mode", DepthMode.STANDARD.value),
                "freshness_required": record_meta.get("freshness_required", False),
                "source_requirements": record_meta.get("source_requirements") or {},
                "rounds_planned": record_meta.get("rounds_planned") or {},
                "rounds_completed": rounds_completed,
                "steps": node_payloads,
                "planning": planning,
                "evidence": evidence,
                "curated_sources": curated_sources,
                "draft": draft,
                "critique": critique,
                "report": final_answer,
                "answer": final_answer.get("answer") if isinstance(final_answer, dict) else None,
                "answer_markdown": (
                    final_answer.get("answer_markdown")
                    if isinstance(final_answer, dict)
                    else None
                )
                or (
                    final_answer.get("answer")
                    if isinstance(final_answer, dict)
                    else None
                ),
                "citations": final_answer.get("citations", []) if isinstance(final_answer, dict) else [],
                "source_summary": (
                    final_answer.get("source_summary")
                    if isinstance(final_answer, dict)
                    else None
                ) or (
                    curated_sources.get("source_summary")
                    if isinstance(curated_sources, dict)
                    else None
                ),
                "freshness_summary": (
                    final_answer.get("freshness_summary")
                    if isinstance(final_answer, dict)
                    else None
                ) or (
                    curated_sources.get("freshness_summary")
                    if isinstance(curated_sources, dict)
                    else None
                ),
                "quality_summary": (
                    final_answer.get("quality_summary")
                    if isinstance(final_answer, dict)
                    else None
                ) or (
                    draft.get("quality_summary")
                    if isinstance(draft, dict)
                    else None
                ),
                "limitations": final_answer.get("limitations", []) if isinstance(final_answer, dict) else [],
                "claims": final_answer.get("claims", []) if isinstance(final_answer, dict) else [],
                "critic_findings": (
                    critique.get("critic_findings", []) if isinstance(critique, dict) else []
                ),
                "filtered_sources": (
                    curated_sources.get("filtered_sources")
                    if isinstance(curated_sources, dict)
                    else []
                )
                or [],
                "sources": (
                    final_answer.get("sources")
                    if isinstance(final_answer, dict)
                    else None
                )
                or (
                    curated_sources.get("sources")
                    if isinstance(curated_sources, dict)
                    else None
                )
                or (
                    evidence.get("sources")
                    if isinstance(evidence, dict)
                    else []
                ),
            }
            record_meta["rounds_completed"] = rounds_completed
            record.meta = record_meta
            record.status = ResearchRunStatus.COMPLETED
            record.completed_at = _utcnow()
            record.result = redact_sensitive_payload(result)
            _persist_phase2_claims_and_links(
                db,
                run_record=record,
                final_answer=final_answer,
            )
            artifacts = (
                db.query(EvidenceArtifact)
                .filter(EvidenceArtifact.research_run_id == self.research_run_id)
                .order_by(EvidenceArtifact.id.asc())
                .all()
            )
            claims = (
                db.query(Claim)
                .filter(Claim.research_run_id == self.research_run_id)
                .order_by(Claim.claim_order.asc(), Claim.id.asc())
                .all()
            )
            links = (
                db.query(ClaimLink)
                .filter(ClaimLink.research_run_id == self.research_run_id)
                .order_by(ClaimLink.claim_id.asc(), ClaimLink.link_order.asc(), ClaimLink.id.asc())
                .all()
            )
            _apply_phase2_claim_scoring(
                run_record=record,
                claims=claims,
                artifacts=artifacts,
                links=links,
            )
            record.error = None
            db.commit()
        finally:
            db.close()

    def _mark_failed(self, error: str) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            if _enum_value(record.status) == ResearchRunStatus.CANCELLED.value:
                db.rollback()
                return
            record.status = ResearchRunStatus.FAILED
            record.completed_at = _utcnow()
            record.error = error
            record_meta = record.meta or {}
            if record.result is None:
                record.result = {
                    "error": error,
                    "classified_mode": record_meta.get("classified_mode"),
                    "depth_mode": record_meta.get("depth_mode"),
                }
            db.commit()
        finally:
            db.close()

    def _mark_cancelled(self, error: str) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            record_meta = dict(record.meta or {})
            record_meta["control_state"] = RUN_CONTROL_CANCELLED
            record_meta["control_reason"] = error
            record.meta = record_meta
            record.status = ResearchRunStatus.CANCELLED
            record.completed_at = _utcnow()
            record.error = error
            if record.result is None:
                record.result = {
                    "error": error,
                    "classified_mode": record_meta.get("classified_mode"),
                    "depth_mode": record_meta.get("depth_mode"),
                }
            db.commit()
        finally:
            db.close()

    def _create_attempt(self, node_id: str) -> tuple[str, str, str]:
        db = SessionLocal()
        try:
            run_record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
            existing_attempts = (
                db.query(ExecutionAttempt)
                .filter(ExecutionAttempt.research_run_id == self.research_run_id)
                .filter(ExecutionAttempt.node_id == node_id)
                .count()
            )
            attempt_number = existing_attempts + 1
            attempt_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())

            task = Task(  # type: ignore[call-arg]
                id=task_id,
                title=f"{run_record.title} - {node_record.title}",
                description=node_record.description,
                status=TaskStatus.IN_PROGRESS,
                created_by="research-run-runner",
                assigned_to=node_record.assigned_agent_id,
                created_at=_utcnow(),
                meta={
                    "research_run_id": self.research_run_id,
                    "node_id": node_id,
                    "attempt_id": attempt_id,
                    "workflow_type": "research_run_node",
                    "budget_limit": run_record.budget_limit,
                    "verification_mode": run_record.verification_mode,
                },
            )
            db.add(task)

            attempt = ExecutionAttempt(  # type: ignore[call-arg]
                id=attempt_id,
                research_run_id=self.research_run_id,
                node_id=node_id,
                attempt_number=attempt_number,
                status=ResearchRunNodeStatus.RUNNING,
                task_id=task_id,
                agent_id=node_record.assigned_agent_id,
                created_at=_utcnow(),
                started_at=_utcnow(),
            )
            db.add(attempt)

            node_record.status = ResearchRunNodeStatus.RUNNING
            node_record.started_at = node_record.started_at or _utcnow()
            node_record.latest_task_id = task_id
            node_record.error = None
            run_record.status = ResearchRunStatus.RUNNING
            run_record.started_at = run_record.started_at or _utcnow()
            db.commit()
            return attempt_id, task_id, node_record.title
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _initialize_attempt_runtime(self, *, node_id: str, attempt_id: str, task_id: str) -> None:
        node_record = self._get_node(node_id)
        run_record = self._get_research_run()

        initialize_runtime_state(
            task_id,
            request_meta={
                "research_run_id": self.research_run_id,
                "node_id": node_id,
                "attempt_id": attempt_id,
                "budget_limit": run_record.budget_limit,
                "verification_mode": run_record.verification_mode,
                "assigned_agent_id": node_record.assigned_agent_id,
            },
        )

        await create_todo_list(
            task_id,
            [
                {
                    "id": node_id,
                    "title": node_record.title,
                    "description": node_record.description,
                    "assigned_to": node_record.assigned_agent_id,
                }
            ],
        )

    def _build_handoff_context(self, *, node_id: str, attempt_id: str, task_id: str) -> HandoffContext:
        run_record = self._get_research_run()
        node_record = self._get_node(node_id)
        return HandoffContext(
            task_id=task_id,
            todo_id=node_id,
            attempt_id=attempt_id,
            research_run_id=self.research_run_id,
            node_id=node_id,
            agent_id=node_record.assigned_agent_id,
            budget_remaining=run_record.budget_limit,
            verification_mode=run_record.verification_mode,
        )

    def _resolve_execution_parameters(self, node_record: ResearchRunNode) -> Dict[str, Any]:
        parameters = dict((node_record.meta or {}).get("execution_parameters") or {})
        input_bindings = dict((node_record.meta or {}).get("input_bindings") or {})
        if not input_bindings:
            return parameters

        db = SessionLocal()
        try:
            for param_name, source_node_id in input_bindings.items():
                source_node = (
                    db.query(ResearchRunNode)
                    .filter(ResearchRunNode.research_run_id == self.research_run_id)
                    .filter(ResearchRunNode.node_id == source_node_id)
                    .one()
                )
                parameters[param_name] = source_node.result
            return parameters
        finally:
            db.close()

    def _extract_payment_id(self, result: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
        selection = result.get("selected_agent")
        if isinstance(selection, dict) and selection.get("payment_id"):
            return str(selection["payment_id"])

        handoff_context = (snapshot or {}).get("current_handoff_context") or {}
        if isinstance(handoff_context, dict) and handoff_context.get("payment_id"):
            return str(handoff_context["payment_id"])
        return None

    def _extract_agent_id(self, result: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
        if result.get("agent_used"):
            return str(result["agent_used"])

        selection = result.get("selected_agent")
        if isinstance(selection, dict) and selection.get("agent_id"):
            return str(selection["agent_id"])

        handoff_context = (snapshot or {}).get("current_handoff_context") or {}
        if isinstance(handoff_context, dict) and handoff_context.get("agent_id"):
            return str(handoff_context["agent_id"])
        return None

    def _attempt_was_cancelled(
        self,
        *,
        result: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
    ) -> bool:
        if str(result.get("todo_status") or "").lower() == "cancelled":
            return True
        snapshot_status = str((snapshot or {}).get("status", "")).lower()
        if snapshot_status == "cancelled":
            return True
        error = str(result.get("error") or "").lower()
        return "cancel" in error

    def _finalize_attempt(
        self,
        *,
        node_id: str,
        attempt_id: str,
        task_id: str,
        result: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
        cancelled: bool = False,
    ) -> None:
        success = bool(result.get("success"))
        payment_id = self._extract_payment_id(result, snapshot)
        agent_id = self._extract_agent_id(result, snapshot)
        if cancelled:
            task_status = TaskStatus.CANCELLED
            attempt_status = ResearchRunNodeStatus.CANCELLED
            node_status = ResearchRunNodeStatus.CANCELLED
        else:
            task_status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
            attempt_status = ResearchRunNodeStatus.COMPLETED if success else ResearchRunNodeStatus.FAILED
            node_status = ResearchRunNodeStatus.COMPLETED if success else ResearchRunNodeStatus.FAILED
        task_result = (
            redact_sensitive_payload(result.get("result"))
            if success
            else {"error": result.get("error", "Research run node failed")}
        )

        db = SessionLocal()
        try:
            attempt = db.query(ExecutionAttempt).filter(ExecutionAttempt.id == attempt_id).one()
            run_record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
            task = db.query(Task).filter(Task.id == task_id).one()

            attempt.status = attempt_status
            attempt.payment_id = payment_id
            attempt.agent_id = agent_id or node_record.assigned_agent_id
            attempt.verification_score = result.get("verification_score")
            attempt.completed_at = _utcnow()
            attempt.result = redact_sensitive_payload(result)
            attempt.error = None if success else result.get("error")

            node_record.status = node_status
            node_record.latest_payment_id = payment_id
            node_record.completed_at = _utcnow()
            node_record.result = redact_sensitive_payload(result.get("result")) if success else None
            node_record.error = None if success else result.get("error")

            task.status = task_status
            task.result = task_result
            if success or cancelled:
                task.completed_at = _utcnow()

            if success:
                _persist_phase2_evidence_artifacts(
                    db,
                    run_record=run_record,
                    node_id=node_id,
                    node_result=result.get("result"),
                )

            _persist_attempt_trace_bundle(
                db,
                run_record=run_record,
                node_record=node_record,
                attempt=attempt,
                task=task,
                result=result,
                snapshot=snapshot,
                cancelled=cancelled,
                error=None if success else result.get("error"),
            )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _record_attempt_failure(
        self,
        *,
        node_id: str,
        attempt_id: str,
        task_id: str,
        error: str,
        result: Optional[Dict[str, Any]] = None,
        cancelled: bool = False,
    ) -> None:
        db = SessionLocal()
        try:
            attempt = db.query(ExecutionAttempt).filter(ExecutionAttempt.id == attempt_id).one_or_none()
            if attempt is not None and _enum_value(attempt.status) == ResearchRunNodeStatus.RUNNING.value:
                attempt.status = (
                    ResearchRunNodeStatus.CANCELLED if cancelled else ResearchRunNodeStatus.FAILED
                )
                attempt.completed_at = _utcnow()
                attempt.error = error
                attempt.result = {"error": error}

            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one_or_none()
            )
            if node_record is not None and _enum_value(node_record.status) == ResearchRunNodeStatus.RUNNING.value:
                node_record.status = (
                    ResearchRunNodeStatus.CANCELLED if cancelled else ResearchRunNodeStatus.FAILED
                )
                node_record.completed_at = _utcnow()
                node_record.error = error

            task = db.query(Task).filter(Task.id == task_id).one_or_none()
            if task is not None and _enum_value(task.status) == TaskStatus.IN_PROGRESS.value:
                task.status = TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED
                task.result = {"error": error}
                task.completed_at = _utcnow()

            if attempt is not None and node_record is not None:
                run_record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
                _persist_attempt_trace_bundle(
                    db,
                    run_record=run_record,
                    node_record=node_record,
                    attempt=attempt,
                    task=task,
                    result=result
                    or {
                        "success": False,
                        "error": error,
                        "agent_used": attempt.agent_id or node_record.assigned_agent_id,
                        "selected_agent": {
                            "agent_id": attempt.agent_id or node_record.assigned_agent_id,
                        },
                    },
                    snapshot=load_task_snapshot(task_id) if task_id else None,
                    cancelled=cancelled,
                    error=error,
                )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _block_pending_descendants(self) -> None:
        db = SessionLocal()
        try:
            pending_nodes = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.status == ResearchRunNodeStatus.PENDING)
                .all()
            )
            for node in pending_nodes:
                node.status = ResearchRunNodeStatus.BLOCKED
                node.error = "Blocked by an upstream node failure"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _cancel_pending_nodes(self, *, reason: str) -> None:
        db = SessionLocal()
        try:
            pending_nodes = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(
                    ResearchRunNode.status.in_(
                        [ResearchRunNodeStatus.PENDING, ResearchRunNodeStatus.BLOCKED]
                    )
                )
                .all()
            )
            for node in pending_nodes:
                node.status = ResearchRunNodeStatus.CANCELLED
                node.completed_at = _utcnow()
                node.error = reason
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _derive_attempt_status(attempt: ExecutionAttempt) -> str:
    status = _enum_value(attempt.status)
    if attempt.task_id:
        snapshot = load_task_snapshot(str(attempt.task_id))
        if snapshot and snapshot.get("verification_pending"):
            return ResearchRunNodeStatus.WAITING_FOR_REVIEW.value
        snapshot_status = str((snapshot or {}).get("status", "")).lower()
        if snapshot_status == "cancelled":
            return ResearchRunNodeStatus.CANCELLED.value
    return status


def get_research_run_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Serialize a research run for API responses."""

    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None

        nodes = (
            db.query(ResearchRunNode)
            .filter(ResearchRunNode.research_run_id == research_run_id)
            .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
            .all()
        )
        edges = (
            db.query(ResearchRunEdge)
            .filter(ResearchRunEdge.research_run_id == research_run_id)
            .order_by(ResearchRunEdge.id.asc())
            .all()
        )
        attempts = (
            db.query(ExecutionAttempt)
            .filter(ExecutionAttempt.research_run_id == research_run_id)
            .order_by(ExecutionAttempt.attempt_number.asc(), ExecutionAttempt.created_at.asc())
            .all()
        )
        verification_decision_count = (
            db.query(VerificationDecision)
            .filter(VerificationDecision.research_run_id == research_run_id)
            .count()
        )
        swarm_handoff_count = (
            db.query(SwarmHandoff)
            .filter(SwarmHandoff.research_run_id == research_run_id)
            .count()
        )
        policy_evaluation_count = (
            db.query(PolicyEvaluation)
            .filter(PolicyEvaluation.research_run_id == research_run_id)
            .count()
        )
        unresolved_dissent_count = (
            db.query(VerificationDecision)
            .filter(VerificationDecision.research_run_id == research_run_id)
            .filter(VerificationDecision.approved.is_(False))
            .count()
        )
    finally:
        db.close()

    attempts_by_node: Dict[str, List[ExecutionAttempt]] = {}
    for attempt in attempts:
        attempts_by_node.setdefault(attempt.node_id, []).append(attempt)

    any_waiting_for_review = False
    nodes_payload: List[ResearchRunNodePayload] = []
    for node in nodes:
        attempt_payloads: List[ResearchRunAttemptPayload] = []
        latest_attempt_status = None
        for attempt in attempts_by_node.get(node.node_id, []):
            derived_status = _derive_attempt_status(attempt)
            any_waiting_for_review = any_waiting_for_review or (
                derived_status == ResearchRunNodeStatus.WAITING_FOR_REVIEW.value
            )
            latest_attempt_status = derived_status
            attempt_payloads.append(
                ResearchRunAttemptPayload(
                    attempt_id=attempt.id,
                    attempt_number=attempt.attempt_number,
                    status=derived_status,
                    task_id=attempt.task_id,
                    payment_id=attempt.payment_id,
                    agent_id=attempt.agent_id,
                    verification_score=attempt.verification_score,
                    created_at=attempt.created_at.isoformat() if attempt.created_at else None,
                    started_at=attempt.started_at.isoformat() if attempt.started_at else None,
                    completed_at=attempt.completed_at.isoformat() if attempt.completed_at else None,
                    result=attempt.result,
                    error=attempt.error,
                )
            )

        node_status = _enum_value(node.status)
        if node_status in {
            ResearchRunNodeStatus.PENDING.value,
            ResearchRunNodeStatus.RUNNING.value,
        } and latest_attempt_status == ResearchRunNodeStatus.WAITING_FOR_REVIEW.value:
            node_status = ResearchRunNodeStatus.WAITING_FOR_REVIEW.value

        nodes_payload.append(
            ResearchRunNodePayload(
                node_id=node.node_id,
                title=node.title,
                description=node.description,
                capability_requirements=node.capability_requirements,
                assigned_agent_id=node.assigned_agent_id,
                candidate_agent_ids=list((node.meta or {}).get("candidate_agent_ids") or []),
                execution_order=node.execution_order,
                status=node_status,
                task_id=node.latest_task_id,
                payment_id=node.latest_payment_id,
                created_at=node.created_at.isoformat() if node.created_at else None,
                started_at=node.started_at.isoformat() if node.started_at else None,
                completed_at=node.completed_at.isoformat() if node.completed_at else None,
                result=node.result,
                error=node.error,
                attempts=attempt_payloads,
            )
        )

    run_status = _enum_value(record.status)
    meta = record.meta or {}
    control_state = _get_control_state(meta)
    nodes_payload_dicts = [item.model_dump(mode="json") for item in nodes_payload]
    evidence_result = _get_node_result_from_payload({"nodes": nodes_payload_dicts}, "gather_evidence")
    critique_result = _get_node_result_from_payload(
        {"nodes": nodes_payload_dicts}, "critique_and_fact_check"
    )
    final_result = _get_node_result_from_payload({"nodes": nodes_payload_dicts}, "revise_final_answer")
    derived_rounds_completed = _merge_rounds_completed(
        evidence_result,
        critique_result,
        final_result,
    )
    if run_status == ResearchRunStatus.RUNNING.value and any_waiting_for_review:
        run_status = ResearchRunStatus.WAITING_FOR_REVIEW.value
    if run_status == ResearchRunStatus.RUNNING.value and control_state == RUN_CONTROL_PAUSED:
        run_status = ResearchRunStatus.PAUSED.value
    if run_status == ResearchRunStatus.RUNNING.value and control_state == RUN_CONTROL_CANCEL_REQUESTED:
        run_status = ResearchRunStatus.CANCELLED.value if record.completed_at else ResearchRunStatus.RUNNING.value
    rounds_completed_payload = (
        (record.result or {}).get("rounds_completed")
        if isinstance(record.result, dict)
        else None
    ) or (derived_rounds_completed if any(derived_rounds_completed.values()) else None) or meta.get(
        "rounds_completed"
    )

    research_run_payload = ResearchRunPayload(
        id=record.id,
        title=record.title,
        description=record.description,
        status=run_status,
        workflow_template=record.workflow_template,
        workflow=meta.get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
        budget_limit=record.budget_limit,
        verification_mode=record.verification_mode,
        research_mode=meta.get("research_mode", ResearchMode.AUTO.value),
        classified_mode=meta.get("classified_mode", ResearchMode.LITERATURE.value),
        depth_mode=meta.get("depth_mode", DepthMode.STANDARD.value),
        freshness_required=bool(meta.get("freshness_required", False)),
        policy=_get_run_policy(meta),
        trace_summary=_trace_summary(
            verification_decision_count=verification_decision_count,
            swarm_handoff_count=swarm_handoff_count,
            policy_evaluation_count=policy_evaluation_count,
            unresolved_dissent_count=unresolved_dissent_count,
        ),
        source_requirements=meta.get("source_requirements") or {},
        rounds_planned=meta.get("rounds_planned") or {},
        rounds_completed=RoundsCompletedPayload.from_payload(rounds_completed_payload),
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
        started_at=record.started_at.isoformat() if record.started_at else None,
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
        result=record.result,
        error=record.error,
        nodes=nodes_payload,
        edges=[
            ResearchRunEdgePayload(
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
            )
            for edge in edges
        ],
    )
    return research_run_payload.model_dump(mode="json")
