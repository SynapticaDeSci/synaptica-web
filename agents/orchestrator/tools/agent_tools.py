"""Deterministic phase 0 agent tools used by the task-backed runtime."""

from __future__ import annotations

import asyncio
import json
import logging
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
            phase_validation={},
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

    verification_passed = overall_score >= 50 and dimension_scores.get("ethics", 0) >= 50
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
