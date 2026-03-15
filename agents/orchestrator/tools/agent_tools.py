"""Deterministic phase 0 agent tools used by the task-backed runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from strands import tool

from agents.executor.agent import create_executor_agent
from agents.executor.tools.research_api_executor import execute_research_agent, get_agent_metadata
from agents.negotiator.tools.payment_tools import authorize_payment as _authorize_payment
from agents.negotiator.tools.payment_tools import create_payment_request
from agents.verifier.agent import create_research_verifier_agent
from agents.verifier.tools.payment_tools import reject_and_refund, release_payment
from agents.verifier.tools.research_verification_tools import calculate_quality_score
from shared.database import Agent, AgentReputation, SessionLocal
from shared.payments.service import get_payment_mode
from shared.payments.service import build_idempotency_key
from shared.payments.runtime import require_verified_payment_profile
from shared.research.agent_inventory import is_supported_builtin_research_agent
from shared.research.catalog import (
    default_research_endpoint,
    rank_supported_agents_for_todo,
    select_supported_agent_for_todo,
)
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

_EXECUTION_CONTRACT_LIST_FIELDS = {
    "sources",
    "citations",
    "claims",
    "critic_findings",
    "uncovered_claim_targets",
}
_EXECUTION_CONTRACT_DICT_FIELDS = {
    "coverage_summary",
    "source_summary",
    "freshness_summary",
    "rounds_completed",
}
_EXECUTION_CONTRACT_STRING_FIELDS = {"answer", "answer_markdown"}
_MAX_EXECUTION_RESULT_NORMALIZATION_DEPTH = 8


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
            flags=re.IGNORECASE,
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


def _validate_execution_result_contract(
    task_result: Dict[str, Any],
    execution_parameters: Optional[Dict[str, Any]] = None,
) -> list[str]:
    """Validate the executor result before verification or payment changes."""

    expected_format = dict((execution_parameters or {}).get("expected_format") or {})
    issues = _validate_expected_format(task_result, expected_format)

    for field in sorted(_EXECUTION_CONTRACT_LIST_FIELDS):
        if field not in task_result:
            continue
        value = task_result.get(field)
        if not isinstance(value, list):
            issues.append(f"Field '{field}' must be a list.")
            continue
        if any(not isinstance(item, dict) for item in value):
            issues.append(f"Field '{field}' must be a list of objects.")

    for field in sorted(_EXECUTION_CONTRACT_DICT_FIELDS):
        if field not in task_result:
            continue
        if not isinstance(task_result.get(field), dict):
            issues.append(f"Field '{field}' must be an object.")

    for field in sorted(_EXECUTION_CONTRACT_STRING_FIELDS):
        if field not in task_result:
            continue
        value = task_result.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"Field '{field}' must be a non-empty string when present.")

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


def _quorum_required_approvals(quorum_policy: str, total_votes: int) -> int:
    if quorum_policy == "single_verifier":
        return 1
    if quorum_policy == "two_of_three":
        return min(2, total_votes)
    if quorum_policy == "three_of_five":
        return min(3, total_votes)
    if quorum_policy == "unanimous":
        return total_votes
    return 1


def _build_strict_quorum_result(
    task_result: Dict[str, Any],
    verification_criteria: Dict[str, Any],
    *,
    overall_score: float,
    verification_passed: bool,
) -> Dict[str, Any]:
    strict_mode = bool(verification_criteria.get("strict_mode", False))
    quorum_policy = str(verification_criteria.get("quorum_policy") or "single_verifier")
    if not strict_mode and quorum_policy == "single_verifier":
        return {}

    node_strategy = str(verification_criteria.get("node_strategy") or "").strip().lower()
    quality_summary = (
        dict(task_result.get("quality_summary") or {})
        if isinstance(task_result.get("quality_summary"), dict)
        else {}
    )
    source_requirements = dict(verification_criteria.get("source_requirements") or {})
    quality_requirements = dict(verification_criteria.get("quality_requirements") or {})
    source_summary = (
        dict(task_result.get("source_summary") or {})
        if isinstance(task_result.get("source_summary"), dict)
        else {}
    )
    freshness_summary = (
        dict(task_result.get("freshness_summary") or {})
        if isinstance(task_result.get("freshness_summary"), dict)
        else {}
    )
    citations = list(task_result.get("citations") or [])
    sources = list(task_result.get("sources") or citations)
    critic_findings = [
        item
        for item in (task_result.get("critic_findings") or [])
        if isinstance(item, dict)
    ]
    uncovered_claims = _normalize_string_list(quality_summary.get("uncovered_claims"))
    citation_coverage_raw = quality_summary.get("citation_coverage")
    citation_coverage = float(
        citation_coverage_raw if citation_coverage_raw is not None else (1.0 if citations else 0.0)
    )
    min_citation_coverage = float(quality_requirements.get("min_citation_coverage", 0.0) or 0.0)
    required_sources = int(source_requirements.get("total_sources", 0) or 0)
    min_fresh_sources = int(source_requirements.get("min_fresh_sources", 0) or 0)
    fresh_sources = int(
        source_summary.get("fresh_sources")
        or freshness_summary.get("fresh_sources")
        or freshness_summary.get("fresh_source_count")
        or 0
    )
    high_severity_findings = [
        finding
        for finding in critic_findings
        if str(finding.get("severity") or "").strip().lower() == "high"
    ]
    has_source_artifacts = bool(sources or citations or source_summary or freshness_summary)
    citation_guard_relevant = (
        node_strategy in {"curate_sources", "revise_final_answer"}
        or bool(citations)
        or citation_coverage_raw is not None
    )
    evidence_guard_relevant = node_strategy in {"gather_evidence", "curate_sources"} or has_source_artifacts
    freshness_guard_relevant = (
        node_strategy in {"gather_evidence", "curate_sources", "revise_final_answer"}
        or bool(freshness_summary)
    ) and (min_fresh_sources > 0 or bool(freshness_summary))
    critic_guard_relevant = (
        node_strategy in {"critique_and_fact_check", "revise_final_answer"}
        or bool(critic_findings)
        or bool(uncovered_claims)
    )

    votes = [
        {
            "reviewer": "verifier",
            "approved": bool(verification_passed and overall_score >= 50),
            "reason": f"Verifier overall score {overall_score:.1f}.",
        }
    ]
    if citation_guard_relevant:
        votes.append(
            {
                "reviewer": "citation_guard",
                "approved": citation_coverage >= min_citation_coverage,
                "reason": (
                    f"Citation coverage {citation_coverage:.2f} vs required {min_citation_coverage:.2f}."
                ),
            }
        )
    if evidence_guard_relevant:
        votes.append(
            {
                "reviewer": "evidence_guard",
                "approved": len(sources) >= required_sources if required_sources else True,
                "reason": f"Collected {len(sources)} sources vs required {required_sources}.",
            }
        )
    if freshness_guard_relevant:
        votes.append(
            {
                "reviewer": "freshness_guard",
                "approved": fresh_sources >= min_fresh_sources if min_fresh_sources else True,
                "reason": f"Fresh sources {fresh_sources} vs required {min_fresh_sources}.",
            }
        )
    if critic_guard_relevant:
        votes.append(
            {
                "reviewer": "critic_guard",
                "approved": len(high_severity_findings) == 0 and len(uncovered_claims) == 0,
                "reason": (
                    f"{len(high_severity_findings)} high-severity critic findings and "
                    f"{len(uncovered_claims)} uncovered claims."
                ),
            }
        )

    if quorum_policy == "single_verifier":
        active_votes = votes[:1]
    elif quorum_policy == "two_of_three":
        active_votes = votes[:3]
    else:
        active_votes = votes[:5]

    approvals = sum(1 for vote in active_votes if vote["approved"])
    required_approvals = _quorum_required_approvals(quorum_policy, len(active_votes))
    approved = approvals >= required_approvals
    return {
        "approved": approved,
        "quorum_policy": quorum_policy,
        "required_approvals": required_approvals,
        "approvals": approvals,
        "total_votes": len(active_votes),
        "dissent_count": len(active_votes) - approvals,
        "votes": active_votes,
        "round_number": int((task_result.get("rounds_completed") or {}).get("critique_rounds", 0) or 1),
        "summary": (
            f"Quorum {'reached' if approved else 'not reached'} "
            f"({approvals}/{len(active_votes)} approvals; policy={quorum_policy})."
        ),
    }


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
        endpoint_url = (
            default_research_endpoint(agent_id)
            if is_supported_builtin_research_agent(agent_id)
            else meta.get("endpoint_url")
        )
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "endpoint_url": endpoint_url,
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
    return str(snapshot.get("status") or "").lower() == "cancelled"


def _strands_executor_relay_enabled(prefer_strands_executor_relay: bool) -> bool:
    if not prefer_strands_executor_relay:
        return False
    configured = os.getenv("RESEARCH_RUN_USE_STRANDS_EXECUTOR_RELAY")
    if configured is None:
        configured = os.getenv("RESEARCH_RUN_USE_STRANDS_BACKEND", "0")
    configured = str(configured).strip().lower()
    return configured not in {"0", "false", "no", "off"}


def _looks_like_executor_envelope(payload: Any) -> bool:
    return isinstance(payload, dict) and "success" in payload and (
        "result" in payload or "error" in payload
    )


def _looks_like_verifier_envelope(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and "success" in payload
        and "verification_passed" in payload
        and "overall_score" in payload
    )


def _parse_json_dict(candidate: Any) -> Optional[Dict[str, Any]]:
    if isinstance(candidate, dict):
        return candidate
    if not isinstance(candidate, str):
        return None

    text = candidate.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _collect_embedded_json_objects(text: str) -> list[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[Dict[str, Any]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "{":
            index += 1
            continue
        try:
            parsed, offset = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
            index += offset
            continue
        index += 1

    return objects


def _extract_json_object(raw_response: Any, *, expected_kind: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(raw_response, dict):
        return raw_response

    text = str(raw_response or "").strip()
    if not text:
        raise ValueError("Empty response")

    parsed_whole_response = _parse_json_dict(text)
    if parsed_whole_response is not None:
        return parsed_whole_response

    candidates = [text]
    fenced_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(match.strip() for match in fenced_matches if match.strip())

    parsed_objects: list[Dict[str, Any]] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)

        parsed = _parse_json_dict(candidate)
        if parsed is not None:
            parsed_objects.append(parsed)
            continue

        parsed_objects.extend(_collect_embedded_json_objects(candidate))

    if not parsed_objects:
        raise ValueError(f"Response was not valid JSON: {text[:200]}")

    matcher = None
    if expected_kind == "executor":
        matcher = _looks_like_executor_envelope
    elif expected_kind == "verifier":
        matcher = _looks_like_verifier_envelope

    if matcher is not None:
        for parsed in reversed(parsed_objects):
            if matcher(parsed):
                return parsed

    return parsed_objects[-1]


def _normalize_execution_task_result(task_result: Any) -> tuple[Dict[str, Any], list[str]]:
    current = task_result
    normalization_notes: list[str] = []

    for _ in range(_MAX_EXECUTION_RESULT_NORMALIZATION_DEPTH):
        if isinstance(current, str):
            parsed = _parse_json_dict(current)
            if parsed is None:
                break
            normalization_notes.append("parsed JSON string result")
            current = parsed
            continue

        if _looks_like_executor_envelope(current) and "result" in current:
            normalization_notes.append("unwrapped nested executor envelope")
            current = current.get("result")
            continue

        break

    deduped_notes = list(dict.fromkeys(normalization_notes))
    if isinstance(current, dict):
        return current, deduped_notes

    return {"output": current}, deduped_notes


def _describe_result_shape(task_result: Any) -> str:
    if isinstance(task_result, dict):
        keys = sorted(str(key) for key in task_result.keys())
        return ",".join(keys) if keys else "<empty-dict>"
    return f"<{type(task_result).__name__}>"


def _build_executor_agent_prompt(request: ExecutionRequest, endpoint_url: Optional[str]) -> str:
    request_payload = {
        "agent_domain": request.agent_id,
        "task_description": request.task_description,
        "context": request.context,
        "metadata": request.metadata,
        "endpoint_url": endpoint_url,
        "handoff_context": request.handoff_context.model_dump(mode="json"),
    }
    return (
        "Execute exactly one already-selected supported research agent and return exactly one JSON object.\n\n"
        "Rules:\n"
        "- Call list_research_agents first.\n"
        "- Call get_agent_metadata for REQUEST_JSON.agent_domain.\n"
        "- Call execute_research_agent exactly once for REQUEST_JSON.agent_domain.\n"
        "- Use the exact tool argument names: agent_domain, task_description, context, metadata, endpoint_url.\n"
        "- Pass REQUEST_JSON.task_description exactly as the task_description argument.\n"
        "- Pass REQUEST_JSON.context exactly as the context argument without adding, removing, or renaming keys.\n"
        "- Pass REQUEST_JSON.metadata exactly as the metadata argument without adding, removing, or renaming keys.\n"
        "- Pass REQUEST_JSON.endpoint_url exactly as the endpoint_url argument when present.\n"
        "- Do not choose a different agent.\n"
        "- Do not drop REQUEST_JSON.context. Dropping it breaks plan_query and downstream contracts.\n"
        "- Do not summarize, reshape, wrap, or stringify the tool result.\n"
        "- Return exactly the JSON object produced by execute_research_agent as the final answer.\n"
        "- Do not wrap the final JSON in markdown fences.\n\n"
        f"REQUEST_JSON:\n{json.dumps(request_payload, sort_keys=True)}"
    )


def _build_verifier_agent_prompt(request: VerificationRequest) -> str:
    request_payload = {
        "task_id": request.task_id,
        "payment_id": request.payment_id,
        "verification_mode": request.verification_mode,
        "task_result": request.task_result,
        "verification_criteria": request.verification_criteria,
        "handoff_context": request.handoff_context.model_dump(mode="json"),
    }
    return (
        "Evaluate exactly one completed research task and return exactly one JSON object.\n\n"
        "Rules:\n"
        "- Use calculate_quality_score as the primary scoring tool.\n"
        "- You may use research verification tools for analysis, but do not call release_payment or reject_and_refund.\n"
        "- Do not mutate payment state.\n"
        "- Keep the result typed and concise.\n"
        "- Do not wrap the final JSON in markdown fences.\n\n"
        "Return schema:\n"
        '{"success": true, "verification_passed": bool, "overall_score": number, "dimension_scores": object, "feedback": string, "decision": "auto_approve"|"review_required", "error": string|null}\n\n'
        f"REQUEST_JSON:\n{json.dumps(request_payload, sort_keys=True)}"
    )


def _normalize_execution_result_payload(
    payload: Dict[str, Any],
    *,
    request: ExecutionRequest,
) -> Dict[str, Any]:
    normalized = dict(payload)
    normalized["success"] = normalized.get("success") is True
    normalized.setdefault("agent_id", request.agent_id)
    normalized.setdefault("metadata", {})
    normalized["handoff_context"] = request.handoff_context.model_dump(mode="json")
    if not normalized["success"] and not normalized.get("error"):
        normalized["error"] = "Executor response was malformed or indicated failure."
    return ExecutionResult.model_validate(normalized).model_dump(mode="json")


def _build_execution_failure_result(
    *,
    agent_id: str,
    context: HandoffContext,
    error: str,
) -> Dict[str, Any]:
    return ExecutionResult(
        success=False,
        agent_id=agent_id,
        error=error,
        handoff_context=context,
    ).model_dump(mode="json")


def _finalize_verification_payload(
    *,
    task_result: Dict[str, Any],
    verification_criteria: Dict[str, Any],
    overall_score: float,
    dimension_scores: Dict[str, float],
    feedback: str,
    context: HandoffContext,
    base_passed: bool,
) -> Dict[str, Any]:
    research_contract = _evaluate_research_quality_contract(
        task_result,
        verification_criteria,
    )
    quality_summary = research_contract.get("quality_summary")
    if quality_summary:
        task_result["quality_summary"] = quality_summary

    if research_contract["issues"]:
        overall_score = min(float(overall_score), 49.0)
        feedback = (
            f"{feedback} Research contract checks: "
            + "; ".join(research_contract["issues"])
        ).strip()

    verification_passed = (
        base_passed
        and float(overall_score) >= 50
        and dimension_scores.get("ethics", 0) >= 50
        and not research_contract["issues"]
    )
    quorum_result = _build_strict_quorum_result(
        task_result,
        verification_criteria,
        overall_score=float(overall_score),
        verification_passed=verification_passed,
    )
    retry_recommended = False
    if quorum_result:
        retry_recommended = not bool(quorum_result.get("approved"))
        if retry_recommended:
            verification_passed = False
            feedback = f"{feedback} {quorum_result.get('summary', '')}".strip()
    result = VerificationResult(
        success=True,
        verification_passed=verification_passed,
        overall_score=float(overall_score),
        dimension_scores=dimension_scores,
        feedback=feedback,
        decision="auto_approve" if verification_passed else "review_required",
        handoff_context=context,
    )
    payload = result.model_dump(mode="json")
    payload["retry_recommended"] = retry_recommended
    if quorum_result:
        payload["quorum_result"] = quorum_result
    return payload


async def _run_strands_executor_step(
    *,
    agent: Any,
    request: ExecutionRequest,
    endpoint_url: Optional[str],
) -> Dict[str, Any]:
    payload = _extract_json_object(
        await agent.run(_build_executor_agent_prompt(request, endpoint_url)),
        expected_kind="executor",
    )
    return _normalize_execution_result_payload(payload, request=request)


async def _run_strands_verifier_step(
    *,
    request: VerificationRequest,
) -> Dict[str, Any]:
    agent = create_research_verifier_agent()
    payload = _extract_json_object(
        await agent.run(_build_verifier_agent_prompt(request)),
        expected_kind="verifier",
    )
    if payload.get("success") is not True:
        raise RuntimeError(
            str(payload.get("error") or "Strands verifier returned malformed verification output")
        )

    dimension_scores = {
        key: float(value)
        for key, value in (payload.get("dimension_scores") or {}).items()
    }
    return _finalize_verification_payload(
        task_result=request.task_result,
        verification_criteria=request.verification_criteria,
        overall_score=float(payload.get("overall_score", 0)),
        dimension_scores=dimension_scores,
        feedback=str(payload.get("feedback") or "Quality analysis completed."),
        context=request.handoff_context,
        base_passed=bool(payload.get("verification_passed")),
    )


async def _execute_selected_agent(
    *,
    task_id: str,
    agent_domain: str,
    task_description: str,
    execution_parameters: Optional[Dict[str, Any]] = None,
    todo_id: Optional[str] = None,
    todo_list: Optional[list] = None,
    handoff_context: Optional[Dict[str, Any]] = None,
    prefer_strands_executor_relay: bool = False,
) -> Dict[str, Any]:
    context = _to_handoff_context(task_id, todo_id or "todo_0", handoff_context, agent_id=agent_domain)
    persist_handoff_context(task_id, context)
    step_name = f"executor_{todo_id or 'todo_0'}"
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
            "todo_id": todo_id or "todo_0",
            "attempt_id": context.attempt_id,
            "payment_id": context.payment_id,
            "support_tier": "supported",
        },
        handoff_context=context,
    )

    if _strands_executor_relay_enabled(prefer_strands_executor_relay):
        try:
            agent = create_executor_agent()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Falling back to deterministic executor step for %s before invocation: %s",
                agent_domain,
                exc,
            )
        else:
            update_progress(
                task_id,
                step_name,
                "running",
                {
                    "message": f"Executing {metadata_result.get('name', agent_domain)}",
                    "agent_id": agent_domain,
                },
            )
            try:
                result = await _run_strands_executor_step(
                    agent=agent,
                    request=request,
                    endpoint_url=metadata_result.get("endpoint_url"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Strands executor step failed for %s after invocation: %s",
                    agent_domain,
                    exc,
                )
                result = _build_execution_failure_result(
                    agent_id=agent_domain,
                    context=context,
                    error=f"Strands executor step failed: {exc}",
                )

            update_progress(
                task_id,
                step_name,
                "completed" if result.get("success") else "failed",
                {
                    "message": (
                        "✓ Task execution completed"
                        if result.get("success")
                        else "✗ Task execution failed"
                    ),
                    "agent_id": agent_domain,
                    "error": result.get("error"),
                },
            )
            return result

    return await executor_agent(
        task_id=task_id,
        agent_domain=agent_domain,
        task_description=task_description,
        execution_parameters=execution_parameters,
        todo_id=todo_id,
        todo_list=todo_list,
        handoff_context=handoff_context,
    )


async def _verify_selected_agent_result(
    *,
    task_id: str,
    payment_id: str,
    task_result: Dict[str, Any],
    verification_criteria: Dict[str, Any],
    verification_mode: str = "standard",
    handoff_context: Optional[Dict[str, Any]] = None,
    prefer_strands_executor_relay: bool = False,
) -> Dict[str, Any]:
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

    if _strands_executor_relay_enabled(prefer_strands_executor_relay):
        try:
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
            result = await _run_strands_verifier_step(request=request)
            update_progress(
                task_id,
                "verifier",
                "completed",
                {
                    "message": "✓ Verification completed",
                    "payment_id": payment_id,
                    "quality_score": result["overall_score"],
                    "dimension_scores": result["dimension_scores"],
                    "feedback": result["feedback"],
                    "quality_summary": task_result.get("quality_summary"),
                },
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Falling back to deterministic verifier step for %s/%s: %s",
                task_id,
                payment_id,
                exc,
            )

    return await verifier_agent(
        task_id=task_id,
        payment_id=payment_id,
        task_result=task_result,
        verification_criteria=verification_criteria,
        verification_mode=verification_mode,
        handoff_context=handoff_context,
    )


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
    preferred_agent_id: Optional[str] = None,
    excluded_agent_ids: Optional[list[str]] = None,
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

    ranked_agent_ids = rank_supported_agents_for_todo(
        todo_id,
        capability_requirements,
        task_name or "",
        preferred_agent_id=preferred_agent_id,
        excluded_agent_ids=excluded_agent_ids or [],
    )
    candidate_agent_ids = ranked_agent_ids or [
        select_supported_agent_for_todo(todo_id, capability_requirements, task_name or "")
    ]
    selected_agent_id: Optional[str] = None
    agent_record: Optional[Dict[str, Any]] = None
    payment_profile_status = None
    selection_errors: List[str] = []

    for candidate_agent_id in candidate_agent_ids:
        candidate_record = _load_marketplace_agent(candidate_agent_id)
        if candidate_record is None:
            selection_errors.append(f"Supported agent '{candidate_agent_id}' is not registered")
            continue
        if candidate_record.get("support_tier") != "supported":
            selection_errors.append(f"Agent '{candidate_agent_id}' is not in the supported tier")
            continue
        if candidate_record.get("reputation_score", 0.0) < (min_reputation_score or 0.0):
            selection_errors.append(
                f"Agent '{candidate_agent_id}' is below the minimum reputation threshold"
            )
            continue

        db = SessionLocal()
        try:
            profile = require_verified_payment_profile(
                db,
                agent_id=candidate_agent_id,
                hedera_account_id=candidate_record.get("hedera_account_id"),
            )
            payment_profile_status = profile.status
        except Exception as exc:  # noqa: BLE001
            selection_errors.append(str(exc))
            continue
        finally:
            db.close()

        selected_agent_id = candidate_agent_id
        agent_record = candidate_record
        break

    if selected_agent_id is None or agent_record is None:
        return AgentSelectionResult(
            success=False,
            error=selection_errors[-1] if selection_errors else "No supported agent is available",
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
        payment_profile_status=payment_profile_status,
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
            "candidate_agent_ids": ranked_agent_ids or [selected_agent_id],
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

    result = _finalize_verification_payload(
        task_result=request.task_result,
        verification_criteria=verification_criteria,
        overall_score=overall_score,
        dimension_scores=dimension_scores,
        feedback=feedback,
        context=context,
        base_passed=overall_score >= 50 and dimension_scores.get("ethics", 0) >= 50,
    )
    quality_summary = request.task_result.get("quality_summary")

    update_progress(
        task_id,
        "verifier",
        "completed",
        {
            "message": "✓ Verification completed",
            "payment_id": payment_id,
            "quality_score": result["overall_score"],
            "dimension_scores": dimension_scores,
            "feedback": result["feedback"],
            "quality_summary": quality_summary,
        },
    )
    return result


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
    prefer_strands_executor_relay: bool = False,
    preferred_agent_id: Optional[str] = None,
    excluded_agent_ids: Optional[list[str]] = None,
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
        preferred_agent_id=preferred_agent_id,
        excluded_agent_ids=excluded_agent_ids,
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

    execution = await _execute_selected_agent(
        task_id=task_id,
        agent_domain=selection["agent_id"],
        task_description=task_description,
        execution_parameters=execution_parameters or {},
        todo_id=todo_id,
        todo_list=todo_list,
        handoff_context=selected_context.model_dump(mode="json"),
        prefer_strands_executor_relay=prefer_strands_executor_relay,
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

    raw_task_result = execution.get("result")
    task_result, normalization_notes = _normalize_execution_task_result(raw_task_result)

    contract_issues = _validate_execution_result_contract(
        task_result,
        execution_parameters=execution_parameters,
    )
    if contract_issues:
        node_strategy = str((execution_parameters or {}).get("node_strategy") or "unknown")
        raw_shape = _describe_result_shape(raw_task_result)
        effective_shape = _describe_result_shape(task_result)
        normalization_summary = ", ".join(normalization_notes) if normalization_notes else "none"
        logger.warning(
            "Execution contract validation failed for node_strategy=%s raw_top_level_keys=%s "
            "effective_top_level_keys=%s normalization=%s issues=%s",
            node_strategy,
            raw_shape,
            effective_shape,
            normalization_summary,
            contract_issues,
        )
        await update_todo_item(task_id, todo_id, "failed", todo_list)
        return {
            "success": False,
            "task_id": task_id,
            "todo_id": todo_id,
            "error": (
                "Execution result failed contract validation: "
                + "; ".join(contract_issues)
                + f" [node_strategy={node_strategy}; raw_top_level_keys={raw_shape}; "
                + f"effective_top_level_keys={effective_shape}; normalization={normalization_summary}]"
            ),
            "todo_status": "failed",
        }

    verification = await _verify_selected_agent_result(
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
            "strict_mode": bool((execution_parameters or {}).get("strict_mode", False)),
            "risk_level": (execution_parameters or {}).get("risk_level"),
            "quorum_policy": (execution_parameters or {}).get("quorum_policy"),
        },
        verification_mode=selected_context.verification_mode,
        handoff_context=selected_context.model_dump(mode="json"),
        prefer_strands_executor_relay=prefer_strands_executor_relay,
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

    if verification.get("retry_recommended"):
        if payment_id:
            await reject_and_refund(
                payment_id,
                verification.get("feedback", "Verifier requested retry"),
                action_context=_build_payment_action_context(selected_context, PaymentAction.REFUND),
            )
        await update_todo_item(task_id, todo_id, "failed", todo_list)
        persist_verification_state(
            task_id,
            pending=False,
            verification_data=verification,
            verification_decision={
                "approved": False,
                "reason": verification.get("feedback", "Retry recommended"),
                "retry_recommended": True,
            },
        )
        persist_handoff_context(task_id, None)
        return {
            "success": False,
            "task_id": task_id,
            "todo_id": todo_id,
            "error": verification.get("feedback", "Retry recommended"),
            "todo_status": "failed",
            "verification_score": overall_score,
            "selected_agent": selection,
            "verification": verification,
            "retry_recommended": True,
            "agent_used": selection["agent_id"],
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
