"""Deterministic phase 0 agent tools used by the task-backed runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict, Optional

from strands import tool

from agents.executor.tools.research_api_executor import execute_research_agent, get_agent_metadata
from agents.negotiator.tools.payment_tools import authorize_payment as _authorize_payment
from agents.negotiator.tools.payment_tools import create_payment_request
from agents.verifier.tools.payment_tools import reject_and_refund, release_payment
from agents.verifier.tools.research_verification_tools import calculate_quality_score
from shared.database import Agent, AgentReputation, SessionLocal
from shared.payments.service import get_payment_mode
from shared.payments.service import build_idempotency_key
from shared.research.catalog import select_supported_agent_for_todo
from shared.runtime import (
    AgentSelectionResult,
    ExecutionRequest,
    ExecutionResult,
    HandoffContext,
    PaymentAction,
    PaymentActionContext,
    TelemetryEnvelope,
    VerificationRequest,
    VerificationResult,
    append_progress_event,
    build_task_snapshot,
    load_task_snapshot,
    persist_handoff_context,
    persist_verification_state,
)
from shared.task_progress import update_progress

logger = logging.getLogger(__name__)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _extract_inline_citation_ids(answer_markdown: str) -> set[str]:
    return set(re.findall(r"\[(S\d+)\]", answer_markdown or ""))


def _contains_absolute_date(answer_markdown: str) -> bool:
    return bool(
        re.search(r"\b20\d{2}-\d{2}-\d{2}\b", answer_markdown)
        or re.search(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)\s+\d{1,2},\s+20\d{2}\b",
            answer_markdown,
        )
    )


def _contains_uncertainty_language(answer_markdown: str) -> bool:
    normalized = (answer_markdown or "").lower()
    return any(
        marker in normalized
        for marker in (
            "appears",
            "likely",
            "uncertain",
            "reported",
            "as of",
            "so far",
            "suggests",
            "indicates",
            "may",
            "still evolving",
            "mixed",
        )
    )


def _validate_expected_format(task_result: Dict[str, Any], expected_format: Dict[str, Any]) -> list[str]:
    required_fields = _normalize_string_list(expected_format.get("required"))
    if not required_fields:
        return []

    issues: list[str] = []
    for field in required_fields:
        value = task_result.get(field)
        if value is None:
            issues.append(f"Missing required field: {field}.")
            continue
        if isinstance(value, str) and not value.strip():
            issues.append(f"Missing required field: {field}.")
    return issues


def _evaluate_research_quality_contract(
    task_result: Dict[str, Any],
    verification_criteria: Dict[str, Any],
) -> Dict[str, Any]:
    expected_format = dict(verification_criteria.get("expected_format") or {})
    quality_requirements = dict(verification_criteria.get("quality_requirements") or {})
    node_strategy = str(verification_criteria.get("node_strategy") or "")
    classified_mode = str(verification_criteria.get("classified_mode") or "")

    existing_summary = (
        dict(task_result.get("quality_summary") or {})
        if isinstance(task_result.get("quality_summary"), dict)
        else {}
    )
    issues = _validate_expected_format(task_result, expected_format)

    if node_strategy != "revise_final_answer":
        merged_summary = dict(existing_summary)
        if issues:
            merged_summary["verification_notes"] = sorted(
                dict.fromkeys(
                    _normalize_string_list(existing_summary.get("verification_notes")) + issues
                )
            )
        return {"issues": issues, "quality_summary": merged_summary or None}

    answer_markdown = str(task_result.get("answer_markdown") or task_result.get("answer") or "")
    citations = list(task_result.get("citations") or [])
    claims = list(task_result.get("claims") or [])
    citation_lookup = {
        str(citation.get("citation_id")).strip(): citation
        for citation in citations
        if isinstance(citation, dict) and str(citation.get("citation_id") or "").strip()
    }
    title_lookup = {
        str(citation.get("title") or "").strip().lower(): citation_id
        for citation_id, citation in citation_lookup.items()
        if citation.get("title")
    }
    inline_citation_ids = _extract_inline_citation_ids(answer_markdown)

    covered_claims = 0
    uncovered_claims: list[str] = []
    claim_count = 0
    verification_notes = _normalize_string_list(existing_summary.get("verification_notes"))

    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict) or not claim.get("claim"):
            continue
        claim_count += 1
        claim_id = str(claim.get("claim_id") or f"C{index}")
        supporting_ids = [
            str(item).strip()
            for item in (claim.get("supporting_citation_ids") or [])
            if isinstance(item, str) and item.strip()
        ]
        if not supporting_ids:
            supporting_ids = [
                title_lookup[str(title).strip().lower()]
                for title in (claim.get("supporting_citations") or [])
                if str(title).strip().lower() in title_lookup
            ]
        unknown_ids = [citation_id for citation_id in supporting_ids if citation_id not in citation_lookup]
        if supporting_ids and not unknown_ids:
            covered_claims += 1
        else:
            uncovered_claims.append(claim_id)
            if not supporting_ids:
                issues.append(f"Claim {claim_id} is missing supporting citation IDs.")
            if unknown_ids:
                issues.append(
                    f"Claim {claim_id} references unknown citation IDs: {', '.join(sorted(unknown_ids))}."
                )

    citation_coverage = (covered_claims / claim_count) if claim_count else 0.0
    min_claim_count = int(quality_requirements.get("min_claim_count", 0) or 0)
    min_citation_coverage = float(quality_requirements.get("min_citation_coverage", 0.0) or 0.0)
    required_sections = _normalize_string_list(quality_requirements.get("required_sections"))

    if min_claim_count and claim_count < min_claim_count:
        issues.append(f"Need at least {min_claim_count} explicit claims; found {claim_count}.")
    if claim_count and citation_coverage < min_citation_coverage:
        issues.append("Citation coverage is incomplete for the final claims.")

    missing_sections = [
        section
        for section in required_sections
        if section.lower() not in answer_markdown.lower()
    ]
    if missing_sections:
        issues.append(f"Answer is missing required sections: {', '.join(missing_sections)}.")

    if quality_requirements.get("require_inline_citations") and citations:
        if not inline_citation_ids:
            issues.append("Answer is missing inline citation markers such as [S1].")
        else:
            unknown_inline = sorted(citation_id for citation_id in inline_citation_ids if citation_id not in citation_lookup)
            if unknown_inline:
                issues.append(
                    "Answer references unknown inline citation IDs: " + ", ".join(unknown_inline) + "."
                )

    if quality_requirements.get("require_absolute_dates") and not _contains_absolute_date(answer_markdown):
        issues.append("Live-analysis answer must include an absolute date.")
    if quality_requirements.get("require_uncertainty_language") and not _contains_uncertainty_language(answer_markdown):
        issues.append("Live-analysis answer must include uncertainty language.")

    source_types = {
        str(citation.get("source_type") or "unknown")
        for citation in citations
        if isinstance(citation, dict) and citation.get("source_type")
    }
    publishers = {
        str(citation.get("publisher") or "").strip()
        for citation in citations
        if isinstance(citation, dict) and citation.get("publisher")
    }
    source_summary = dict(task_result.get("source_summary") or {})
    merged_summary = {
        **existing_summary,
        "citation_coverage": round(citation_coverage, 3),
        "uncovered_claims": uncovered_claims,
        "source_diversity": existing_summary.get("source_diversity")
        or {
            "publishers": len(publishers) or len(source_summary.get("publishers") or []),
            "source_types": len(source_types),
            "fresh_sources": int(source_summary.get("fresh_sources", 0) or 0),
            "academic_or_primary_sources": int(
                source_summary.get("academic_or_primary_sources", 0) or 0
            ),
        },
        "verification_notes": sorted(dict.fromkeys(verification_notes + issues)),
        "strict_live_analysis_checks_passed": False,
    }

    if classified_mode not in {"live_analysis", "hybrid"} and not quality_requirements.get("strict_live_analysis"):
        merged_summary["strict_live_analysis_checks_passed"] = len(issues) == 0
    elif len(issues) == 0:
        merged_summary["strict_live_analysis_checks_passed"] = True

    return {"issues": issues, "quality_summary": merged_summary}


def _to_handoff_context(
    task_id: str,
    todo_id: str,
    handoff_context: Optional[Dict[str, Any]],
    *,
    payment_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    budget_remaining: Optional[float] = None,
    verification_mode: str = "standard",
) -> HandoffContext:
    if handoff_context:
        merged = dict(handoff_context)
        if payment_id is not None:
            merged["payment_id"] = payment_id
        if agent_id is not None:
            merged["agent_id"] = agent_id
        if budget_remaining is not None:
            merged["budget_remaining"] = budget_remaining
        merged.setdefault("verification_mode", verification_mode)
        return HandoffContext.model_validate(merged)

    return HandoffContext(
        task_id=task_id,
        todo_id=todo_id,
        attempt_id=str(uuid.uuid4()),
        payment_id=payment_id,
        agent_id=agent_id,
        budget_remaining=budget_remaining,
        verification_mode=verification_mode,
    )


def _build_payment_action_context(context: HandoffContext, action: PaymentAction) -> Dict[str, Any]:
    return PaymentActionContext(
        payment_id=context.payment_id,
        task_id=context.task_id,
        todo_id=context.todo_id,
        attempt_id=context.attempt_id,
        action=action,
        idempotency_key=build_idempotency_key(
            context.task_id,
            context.todo_id,
            context.attempt_id,
            action,
            research_run_id=context.research_run_id,
            node_id=context.node_id,
        ),
        mode=get_payment_mode(),
        metadata={"handoff_context": context.model_dump(mode="json")},
    ).model_dump(mode="json")


def _load_marketplace_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).one_or_none()
        if agent is None:
            return None
        reputation = (
            db.query(AgentReputation)
            .filter(AgentReputation.agent_id == agent_id)
            .one_or_none()
        )
        score = reputation.reputation_score if reputation else 0.0
        meta = agent.meta or {}
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "endpoint_url": meta.get("endpoint_url"),
            "pricing": meta.get("pricing") or {},
            "hedera_account_id": agent.hedera_account_id,
            "support_tier": meta.get("support_tier", "experimental"),
            "reputation_score": score,
        }
    finally:
        db.close()


def _check_task_cancelled(task_id: str) -> bool:
    snapshot = load_task_snapshot(task_id)
    if snapshot is None:
        return False
    return snapshot.get("status") == "CANCELLED"


async def _request_human_verification(
    task_id: str,
    todo_id: str,
    payment_id: Optional[str],
    quality_score: float,
    dimension_scores: Dict[str, float],
    feedback: str,
    task_result: Any,
    agent_name: str,
) -> None:
    verification_data = {
        "todo_id": todo_id,
        "payment_id": payment_id,
        "quality_score": quality_score,
        "dimension_scores": dimension_scores,
        "feedback": feedback,
        "task_result": task_result,
        "agent_name": agent_name,
        "ethics_passed": dimension_scores.get("ethics", 100) >= 50,
    }
    persist_verification_state(
        task_id,
        pending=True,
        verification_data=verification_data,
        verification_decision=None,
    )
    update_progress(
        task_id,
        f"verification_{todo_id}",
        "waiting_for_human",
        {
            "message": f"⏸ Verification requires human review (score: {quality_score}/100)",
            "quality_score": quality_score,
            "dimension_scores": dimension_scores,
            "payment_id": payment_id,
            "todo_id": todo_id,
        },
    )


async def _wait_for_human_decision(task_id: str, timeout: int = 3600) -> Dict[str, Any]:
    attempts = 0
    max_attempts = timeout // 2

    while attempts < max_attempts:
        snapshot = load_task_snapshot(task_id)
        if snapshot and snapshot.get("verification_decision"):
            return snapshot["verification_decision"]
        await asyncio.sleep(2)
        attempts += 1

    return {
        "approved": False,
        "reason": "Verification timeout - no human response after 1 hour",
    }


@tool
async def negotiator_agent(
    task_id: str,
    capability_requirements: str,
    budget_limit: Optional[float] = None,
    min_reputation_score: Optional[float] = 0.2,
    task_name: Optional[str] = None,
    todo_id: Optional[str] = None,
    handoff_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Select a supported marketplace agent and create a payment proposal."""

    todo_id = todo_id or "todo_0"
    step_name = f"negotiator_{todo_id}"
    context = _to_handoff_context(
        task_id,
        todo_id,
        handoff_context,
        budget_remaining=budget_limit,
    )
    persist_handoff_context(task_id, context)

    update_progress(
        task_id,
        step_name,
        "running",
        {
            "message": f"Selecting supported agent for {task_name or todo_id}",
            "capability_requirements": capability_requirements,
        },
    )

    selected_agent_id = select_supported_agent_for_todo(
        todo_id,
        capability_requirements,
        task_name or "",
    )
    agent_record = _load_marketplace_agent(selected_agent_id)
    if agent_record is None:
        return AgentSelectionResult(
            success=False,
            error=f"Supported agent '{selected_agent_id}' is not registered",
            handoff_context=context,
        ).model_dump(mode="json")

    if agent_record.get("support_tier") != "supported":
        return AgentSelectionResult(
            success=False,
            error=f"Agent '{selected_agent_id}' is not in the supported tier",
            handoff_context=context,
        ).model_dump(mode="json")

    if agent_record.get("reputation_score", 0.0) < (min_reputation_score or 0.0):
        return AgentSelectionResult(
            success=False,
            error=f"Agent '{selected_agent_id}' is below the minimum reputation threshold",
            handoff_context=context,
        ).model_dump(mode="json")

    payment_result = await create_payment_request(
        task_id=task_id,
        from_agent_id="orchestrator-agent",
        to_agent_id=selected_agent_id,
        to_hedera_account=agent_record.get("hedera_account_id") or "",
        amount=float((agent_record.get("pricing") or {}).get("rate", 0.0)),
        description=task_name or capability_requirements,
        action_context=_build_payment_action_context(context, PaymentAction.PROPOSAL),
    )

    enriched_context = context.model_copy(
        update={
            "payment_id": payment_result.get("payment_id"),
            "agent_id": selected_agent_id,
        }
    )
    persist_handoff_context(task_id, enriched_context)

    selection = AgentSelectionResult(
        success=True,
        agent_id=selected_agent_id,
        agent_name=agent_record.get("name"),
        description=agent_record.get("description"),
        endpoint_url=agent_record.get("endpoint_url"),
        hedera_account_id=agent_record.get("hedera_account_id"),
        pricing=agent_record.get("pricing") or {},
        support_tier="supported",
        payment_id=payment_result.get("payment_id"),
        payment_thread_id=((payment_result.get("a2a") or {}).get("thread_id")),
        summary=f"Selected {agent_record.get('name')} for {task_name or todo_id}",
        handoff_context=enriched_context,
    )

    update_progress(
        task_id,
        step_name,
        "completed",
        {
            "message": f"✓ Selected {agent_record.get('name')}",
            "agent_id": selected_agent_id,
            "payment_id": payment_result.get("payment_id"),
        },
    )
    return selection.model_dump(mode="json")


@tool
async def authorize_payment_request(
    payment_id: str,
    action_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Authorize a payment proposal through the shared payment helper."""

    try:
        response = await _authorize_payment(payment_id, action_context=action_context)
        return {"success": True, **response}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "payment_id": payment_id, "error": str(exc)}


@tool
async def executor_agent(
    task_id: str,
    agent_domain: str,
    task_description: str,
    execution_parameters: Optional[Dict[str, Any]] = None,
    todo_id: Optional[str] = None,
    todo_list: Optional[list] = None,
    handoff_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Dispatch directly to a supported research agent over HTTP."""

    del todo_list  # retained for backwards-compatible signature
    todo_id = todo_id or "todo_0"
    step_name = f"executor_{todo_id}"
    context = _to_handoff_context(task_id, todo_id, handoff_context, agent_id=agent_domain)
    persist_handoff_context(task_id, context)

    metadata_result = await get_agent_metadata(agent_domain)
    if not metadata_result.get("success"):
        return ExecutionResult(
            success=False,
            agent_id=agent_domain,
            error=metadata_result.get("error"),
            handoff_context=context,
        ).model_dump(mode="json")

    if metadata_result.get("support_tier") != "supported":
        return ExecutionResult(
            success=False,
            agent_id=agent_domain,
            error=f"Agent '{agent_domain}' is not in the supported tier",
            handoff_context=context,
        ).model_dump(mode="json")

    request = ExecutionRequest(
        agent_id=agent_domain,
        task_description=task_description,
        context=execution_parameters or {},
        metadata={
            "task_id": task_id,
            "todo_id": todo_id,
            "attempt_id": context.attempt_id,
            "payment_id": context.payment_id,
            "support_tier": "supported",
        },
        handoff_context=context,
    )

    update_progress(
        task_id,
        step_name,
        "running",
        {
            "message": f"Executing {metadata_result.get('name', agent_domain)}",
            "agent_id": agent_domain,
        },
    )

    response = await execute_research_agent(
        agent_domain=request.agent_id,
        task_description=request.task_description,
        context=request.context,
        metadata=request.metadata,
        endpoint_url=metadata_result.get("endpoint_url"),
    )
    result = ExecutionResult(
        success=bool(response.get("success")),
        agent_id=agent_domain,
        result=response.get("result"),
        metadata=response.get("metadata") or {},
        error=response.get("error"),
        handoff_context=context,
    )

    update_progress(
        task_id,
        step_name,
        "completed" if result.success else "failed",
        {
            "message": "✓ Task execution completed" if result.success else "✗ Task execution failed",
            "agent_id": agent_domain,
            "error": result.error,
        },
    )
    return result.model_dump(mode="json")


@tool
async def verifier_agent(
    task_id: str,
    payment_id: str,
    task_result: Dict[str, Any],
    verification_criteria: Dict[str, Any],
    verification_mode: str = "standard",
    handoff_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministically score the task result and return a typed verification result."""

    context = _to_handoff_context(
        task_id,
        handoff_context.get("todo_id", "todo_0") if handoff_context else "todo_0",
        handoff_context,
        payment_id=payment_id,
        verification_mode=verification_mode,
    )
    request = VerificationRequest(
        task_id=task_id,
        payment_id=payment_id,
        task_result=task_result,
        verification_criteria=verification_criteria,
        verification_mode=verification_mode,
        handoff_context=context,
    )

    update_progress(
        task_id,
        "verifier",
        "running",
        {
            "message": "Verifying task results and quality",
            "verification_mode": verification_mode,
            "payment_id": payment_id,
        },
    )

    try:
        quality_score_result = await calculate_quality_score(
            output=request.task_result,
            phase=verification_criteria.get("phase", "knowledge_retrieval"),
            agent_role=verification_criteria.get("agent_role", context.agent_id or "unknown"),
            phase_validation=verification_criteria,
        )
        overall_score = float(quality_score_result.get("overall_score", 0))
        dimension_scores = {
            key: float(value)
            for key, value in (quality_score_result.get("dimension_scores") or {}).items()
        }
        feedback = quality_score_result.get("feedback", "Quality analysis completed.")
    except Exception as exc:  # noqa: BLE001
        overall_score = 45.0
        dimension_scores = {
            "completeness": 40.0,
            "correctness": 40.0,
            "academic_rigor": 40.0,
            "clarity": 50.0,
            "innovation": 50.0,
            "ethics": 85.0,
        }
        feedback = f"Verification fallback triggered: {exc}"

    research_contract = _evaluate_research_quality_contract(
        request.task_result,
        verification_criteria,
    )
    quality_summary = research_contract.get("quality_summary")
    if quality_summary:
        request.task_result["quality_summary"] = quality_summary

    if research_contract["issues"]:
        overall_score = min(overall_score, 49.0)
        feedback = (
            f"{feedback} Research contract checks: "
            + "; ".join(research_contract["issues"])
        ).strip()

    verification_passed = (
        overall_score >= 50
        and dimension_scores.get("ethics", 0) >= 50
        and not research_contract["issues"]
    )
    result = VerificationResult(
        success=True,
        verification_passed=verification_passed,
        overall_score=overall_score,
        dimension_scores=dimension_scores,
        feedback=feedback,
        decision="auto_approve" if verification_passed else "review_required",
        handoff_context=context,
    )

    update_progress(
        task_id,
        "verifier",
        "completed",
        {
            "message": "✓ Verification completed",
            "payment_id": payment_id,
            "quality_score": overall_score,
            "dimension_scores": dimension_scores,
            "feedback": feedback,
            "quality_summary": quality_summary,
        },
    )
    return result.model_dump(mode="json")


@tool
async def execute_microtask(
    task_id: str,
    todo_id: str,
    task_name: str,
    task_description: str,
    capability_requirements: str,
    budget_limit: Optional[float] = None,
    min_reputation_score: Optional[float] = 0.2,
    execution_parameters: Optional[Dict[str, Any]] = None,
    todo_list: Optional[list] = None,
    handoff_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the full negotiation -> payment -> execution -> verification flow."""

    from agents.orchestrator.tools.todo_tools import update_todo_item

    if _check_task_cancelled(task_id):
        return {"success": False, "error": "Task cancelled by user", "todo_status": "cancelled"}

    await update_todo_item(task_id, todo_id, "in_progress", todo_list)
    context = _to_handoff_context(
        task_id,
        todo_id,
        handoff_context,
        budget_remaining=budget_limit,
    )
    persist_handoff_context(task_id, context)

    selection = await negotiator_agent(
        task_id=task_id,
        capability_requirements=capability_requirements,
        budget_limit=budget_limit,
        min_reputation_score=min_reputation_score,
        task_name=task_name,
        todo_id=todo_id,
        handoff_context=context.model_dump(mode="json"),
    )
    if not selection.get("success"):
        await update_todo_item(task_id, todo_id, "failed", todo_list)
        return {
            "success": False,
            "task_id": task_id,
            "todo_id": todo_id,
            "error": selection.get("error", "Agent negotiation failed"),
            "todo_status": "failed",
        }

    selected_context = HandoffContext.model_validate(selection["handoff_context"])
    payment_id = selection.get("payment_id")

    if payment_id:
        auth_result = await authorize_payment_request(
            payment_id,
            action_context=_build_payment_action_context(selected_context, PaymentAction.AUTHORIZE),
        )
        if not auth_result.get("success"):
            await update_todo_item(task_id, todo_id, "failed", todo_list)
            return {
                "success": False,
                "task_id": task_id,
                "todo_id": todo_id,
                "error": auth_result.get("error", "Payment authorization failed"),
                "todo_status": "failed",
            }

    execution = await executor_agent(
        task_id=task_id,
        agent_domain=selection["agent_id"],
        task_description=task_description,
        execution_parameters=execution_parameters or {},
        todo_id=todo_id,
        todo_list=todo_list,
        handoff_context=selected_context.model_dump(mode="json"),
    )
    if not execution.get("success"):
        await update_todo_item(task_id, todo_id, "failed", todo_list)
        return {
            "success": False,
            "task_id": task_id,
            "todo_id": todo_id,
            "error": execution.get("error", "Task execution failed"),
            "todo_status": "failed",
        }

    task_result = execution.get("result")
    if not isinstance(task_result, dict):
        task_result = {"output": task_result}

    verification = await verifier_agent(
        task_id=task_id,
        payment_id=payment_id or "missing-payment-id",
        task_result=task_result,
        verification_criteria={
            "expected_format": (execution_parameters or {}).get("expected_format"),
            "quality_requirements": (execution_parameters or {}).get("quality_requirements"),
            "agent_role": selection["agent_id"],
            "phase": (execution_parameters or {}).get("phase"),
            "node_strategy": (execution_parameters or {}).get("node_strategy"),
            "classified_mode": (execution_parameters or {}).get("classified_mode"),
            "freshness_required": (execution_parameters or {}).get("freshness_required"),
            "source_requirements": (execution_parameters or {}).get("source_requirements"),
            "claim_targets": (execution_parameters or {}).get("claim_targets"),
        },
        verification_mode=selected_context.verification_mode,
        handoff_context=selected_context.model_dump(mode="json"),
    )
    overall_score = float(verification.get("overall_score", 0))
    dimension_scores = verification.get("dimension_scores") or {}

    if verification.get("verification_passed"):
        if payment_id:
            await release_payment(
                payment_id,
                f"Auto-approved: Quality score {overall_score}/100",
                action_context=_build_payment_action_context(selected_context, PaymentAction.RELEASE),
            )
        await update_todo_item(task_id, todo_id, "completed", todo_list)
        persist_verification_state(task_id, pending=False, verification_data=None, verification_decision=None)
        persist_handoff_context(task_id, None)
        return {
            "success": True,
            "task_id": task_id,
            "todo_id": todo_id,
            "result": task_result,
            "agent_used": selection["agent_id"],
            "todo_status": "completed",
            "verification_score": overall_score,
            "auto_approved": True,
            "selected_agent": selection,
            "verification": verification,
        }

    await _request_human_verification(
        task_id=task_id,
        todo_id=todo_id,
        payment_id=payment_id,
        quality_score=overall_score,
        dimension_scores=dimension_scores,
        feedback=verification.get("feedback", ""),
        task_result=task_result,
        agent_name=selection.get("agent_name") or selection["agent_id"],
    )
    decision = await _wait_for_human_decision(task_id)

    if decision.get("approved"):
        if payment_id:
            await release_payment(
                payment_id,
                "Approved by human reviewer",
                action_context=_build_payment_action_context(selected_context, PaymentAction.RELEASE),
            )
        await update_todo_item(task_id, todo_id, "completed", todo_list)
        persist_verification_state(task_id, pending=False, verification_data=None, verification_decision=decision)
        persist_handoff_context(task_id, None)
        return {
            "success": True,
            "task_id": task_id,
            "todo_id": todo_id,
            "result": task_result,
            "agent_used": selection["agent_id"],
            "todo_status": "completed",
            "verification_score": overall_score,
            "human_approved": True,
            "selected_agent": selection,
            "verification": verification,
        }

    if payment_id:
        await reject_and_refund(
            payment_id,
            decision.get("reason", "Rejected by human reviewer"),
            action_context=_build_payment_action_context(selected_context, PaymentAction.REFUND),
        )
    await update_todo_item(task_id, todo_id, "failed", todo_list)
    persist_verification_state(task_id, pending=False, verification_data=None, verification_decision=decision)
    persist_handoff_context(task_id, None)
    return {
        "success": False,
        "task_id": task_id,
        "todo_id": todo_id,
        "result": task_result,
        "agent_used": selection["agent_id"],
        "todo_status": "failed",
        "verification_score": overall_score,
        "human_rejected": True,
        "error": decision.get("reason", "Rejected by human reviewer"),
        "selected_agent": selection,
        "verification": verification,
    }
