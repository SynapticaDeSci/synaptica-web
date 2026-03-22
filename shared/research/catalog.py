"""Catalog helpers for support tiers and active research-agent selection."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

from shared.database import Agent, AgentReputation, SessionLocal
from shared.research.agent_inventory import (
    get_builtin_research_agent,
    is_supported_builtin_research_agent,
    iter_supported_builtin_research_agents,
    supported_builtin_research_agent_ids,
)
from shared.runtime.contracts import SupportTier


SUPPORTED_RESEARCH_AGENT_IDS = supported_builtin_research_agent_ids()

SUPPORTED_AGENT_DETAILS: Dict[str, Dict[str, Any]] = {
    record.agent_id: record.catalog_details()
    for record in iter_supported_builtin_research_agents()
}

_ROLE_HINTS: Dict[str, tuple[str, ...]] = {
    "planning": (
        "plan_query",
        "todo_0",
        "frame",
        "framing",
        "question",
        "scope",
        "investigation",
        "problem",
        "hypothesis",
    ),
    "evidence": (
        "gather_evidence",
        "curate_sources",
        "todo_1",
        "literature",
        "citation",
        "source",
        "evidence",
        "curation",
        "search",
        "retrieval",
    ),
    "synthesis": (
        "draft_synthesis",
        "critique_and_fact_check",
        "revise_final_answer",
        "todo_2",
        "synthesis",
        "summarization",
        "report",
        "draft",
        "critique",
        "revise",
        "fact-check",
    ),
}

_DEFAULT_AGENT_ID_BY_ROLE_FAMILY: Dict[str, str] = {
    "planning": "problem-framer-001",
    "evidence": "literature-miner-001",
    "synthesis": "knowledge-synthesizer-001",
}

RESEARCH_RUN_CONTRACT_VERSION = "phase2.v1"

_TODO_ROLE_FAMILIES: Dict[str, str] = {
    "plan_query": "planning",
    "todo_0": "planning",
    "gather_evidence": "evidence",
    "curate_sources": "evidence",
    "todo_1": "evidence",
    "draft_synthesis": "synthesis",
    "critique_and_fact_check": "synthesis",
    "revise_final_answer": "synthesis",
    "todo_2": "synthesis",
}

_ROLE_SIGNATURES: Dict[str, tuple[str, ...]] = {
    "planning": (
        "plan",
        "planning",
        "problem",
        "question",
        "scope",
        "frame",
        "framing",
        "brief",
        "investigation",
        "hypothesis",
    ),
    "evidence": (
        "evidence",
        "source",
        "sources",
        "citation",
        "citations",
        "literature",
        "search",
        "retrieval",
        "curation",
        "curate",
        "mining",
        "miner",
    ),
    "synthesis": (
        "synthesis",
        "synthesizer",
        "summary",
        "summarization",
        "report",
        "draft",
        "answer",
        "critique",
        "critic",
        "fact",
        "check",
        "revision",
        "revise",
        "review",
        "writer",
    ),
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_\-]{1,}")


def _normalize_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        for token in _TOKEN_PATTERN.findall(value.lower()):
            tokens.add(token)
            tokens.update(part for part in re.split(r"[_\-]+", token) if len(part) >= 2)
    return tokens


def _role_family_for_todo(
    todo_id: str,
    capability_requirements: str = "",
    task_name: str = "",
) -> Optional[str]:
    normalized_todo_id = str(todo_id or "").strip().lower()
    if normalized_todo_id in _TODO_ROLE_FAMILIES:
        return _TODO_ROLE_FAMILIES[normalized_todo_id]

    request_tokens = _normalize_tokens([todo_id, capability_requirements, task_name])
    family_scores = {
        role_name: sum(1 for hint in hints if hint in request_tokens)
        for role_name, hints in _ROLE_HINTS.items()
    }
    best_family = max(family_scores, key=family_scores.get, default=None)
    if best_family is None or family_scores.get(best_family, 0) <= 0:
        return None
    return best_family


def _default_supported_agent_id_for_todo(
    todo_id: str,
    capability_requirements: str = "",
    task_name: str = "",
) -> str:
    role_family = _role_family_for_todo(todo_id, capability_requirements, task_name)
    if role_family:
        return _DEFAULT_AGENT_ID_BY_ROLE_FAMILY.get(role_family, "knowledge-synthesizer-001")
    return "knowledge-synthesizer-001"


def _agent_role_families(agent_record: Dict[str, Any]) -> set[str]:
    explicit_families = {
        str(item).strip().lower()
        for item in list(agent_record.get("role_families") or [])
        if str(item).strip()
    }
    if explicit_families:
        return explicit_families

    built_in = get_builtin_research_agent(str(agent_record.get("agent_id") or ""))
    if built_in is not None and built_in.role_families:
        return {family.lower() for family in built_in.role_families}

    blob_tokens = _normalize_tokens(
        [
            str(agent_record.get("agent_id") or ""),
            str(agent_record.get("name") or ""),
            str(agent_record.get("description") or ""),
            *[str(item) for item in (agent_record.get("capabilities") or [])],
        ]
    )
    families: set[str] = set()
    for role_name, signature in _ROLE_SIGNATURES.items():
        if any(token in blob_tokens for token in signature):
            families.add(role_name)
    return families


def _agent_supported_node_strategies(agent_record: Dict[str, Any]) -> set[str]:
    return {
        str(item).strip().lower()
        for item in list(agent_record.get("supported_node_strategies") or [])
        if str(item).strip()
    }


def _agent_contract_version(agent_record: Dict[str, Any]) -> str:
    return str(agent_record.get("research_run_contract_version") or "").strip()


def _agent_supports_role_family(agent_record: Dict[str, Any], required_role_family: Optional[str]) -> bool:
    if not required_role_family:
        return True
    return required_role_family in _agent_role_families(agent_record)


def _agent_supports_research_run_contract(
    agent_record: Dict[str, Any],
    *,
    todo_id: str,
    required_role_family: Optional[str],
) -> bool:
    agent_id = str(agent_record.get("agent_id") or "").strip()
    if is_supported_builtin_research_agent(agent_id):
        return True

    if _agent_contract_version(agent_record) != RESEARCH_RUN_CONTRACT_VERSION:
        return False

    supported_node_strategies = _agent_supported_node_strategies(agent_record)
    normalized_todo_id = str(todo_id or "").strip().lower()
    if supported_node_strategies:
        if "*" in supported_node_strategies or normalized_todo_id in supported_node_strategies:
            return True
        if required_role_family and required_role_family in supported_node_strategies:
            return True
        if required_role_family and f"role:{required_role_family}" in supported_node_strategies:
            return True
        return False

    if not required_role_family:
        return False

    explicit_role_families = {
        str(item).strip().lower()
        for item in list(agent_record.get("role_families") or [])
        if str(item).strip()
    }
    return required_role_family in explicit_role_families


def _agent_role_match_score(
    agent_record: Dict[str, Any],
    request_tokens: set[str],
    *,
    required_role_family: Optional[str] = None,
) -> float:
    blob_tokens = _normalize_tokens(
        [
            agent_record.get("agent_id", ""),
            agent_record.get("name", ""),
            agent_record.get("description", ""),
            *[str(item) for item in (agent_record.get("capabilities") or [])],
        ]
    )
    overlap_score = float(len(blob_tokens & request_tokens) * 8)

    role_bonus = 0.0
    for role_name, hints in _ROLE_HINTS.items():
        if required_role_family and role_name != required_role_family:
            continue
        if not any(hint in request_tokens for hint in hints):
            continue
        if role_name == "planning" and _ROLE_SIGNATURES["planning"] and set(_ROLE_SIGNATURES["planning"]) & blob_tokens:
            role_bonus += 28.0
        elif role_name == "evidence" and _ROLE_SIGNATURES["evidence"] and set(_ROLE_SIGNATURES["evidence"]) & blob_tokens:
            role_bonus += 28.0
        elif role_name == "synthesis" and _ROLE_SIGNATURES["synthesis"] and set(_ROLE_SIGNATURES["synthesis"]) & blob_tokens:
            role_bonus += 28.0

    if required_role_family and required_role_family in _agent_role_families(agent_record):
        role_bonus += 18.0

    price = float(((agent_record.get("pricing") or {}).get("rate") or 0.0))
    reputation = float(agent_record.get("reputation_score") or 0.0)
    return overlap_score + role_bonus + (reputation * 20.0) - (price * 0.35)


def _serialize_agent_row(agent: Agent, reputation_score: float) -> Dict[str, Any]:
    meta = dict(agent.meta or {})
    built_in = get_builtin_research_agent(agent.agent_id)
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": agent.description,
        "capabilities": list(agent.capabilities or []),
        "pricing": dict(meta.get("pricing") or {}),
        "support_tier": meta.get("support_tier") or infer_support_tier(agent.agent_id, agent.agent_type).value,
        "endpoint_url": (
            default_public_research_endpoint(agent.agent_id)
            if is_supported_builtin_research_agent(agent.agent_id)
            else meta.get("endpoint_url")
        ),
        "hedera_account_id": agent.hedera_account_id,
        "reputation_score": reputation_score,
        "role_families": list(meta.get("role_families") or (built_in.role_families if built_in else ())),
        "research_run_contract_version": (
            RESEARCH_RUN_CONTRACT_VERSION
            if is_supported_builtin_research_agent(agent.agent_id)
            else meta.get("research_run_contract_version")
        ),
        "supported_node_strategies": list(meta.get("supported_node_strategies") or []),
    }


def list_supported_research_agents() -> List[Dict[str, Any]]:
    """Return supported research agents from the marketplace, with catalog fallback."""

    session = SessionLocal()
    try:
        agents = (
            session.query(Agent, AgentReputation)
            .outerjoin(AgentReputation, AgentReputation.agent_id == Agent.agent_id)
            .filter(Agent.status == "active")
            .filter(Agent.agent_type == "research")
            .all()
        )
    finally:
        session.close()

    supported: Dict[str, Dict[str, Any]] = {}
    for agent, reputation in agents:
        serialized = _serialize_agent_row(agent, float(reputation.reputation_score or 0.0) if reputation else 0.0)
        if serialized["support_tier"] != SupportTier.SUPPORTED.value:
            continue
        supported[str(serialized["agent_id"])] = serialized

    for agent_id in SUPPORTED_RESEARCH_AGENT_IDS:
        if agent_id in supported:
            if not supported[agent_id].get("role_families"):
                supported[agent_id]["role_families"] = list(
                    (SUPPORTED_AGENT_DETAILS.get(agent_id) or {}).get("role_families") or []
                )
            continue
        details = SUPPORTED_AGENT_DETAILS.get(agent_id) or {}
        supported[agent_id] = {
            "agent_id": agent_id,
            "name": details.get("name", agent_id),
            "description": details.get("description", ""),
            "capabilities": list(details.get("capabilities") or []),
            "pricing": dict(details.get("pricing") or {}),
            "support_tier": SupportTier.SUPPORTED.value,
            "endpoint_url": default_public_research_endpoint(agent_id),
            "hedera_account_id": details.get("hedera_account_id"),
            "reputation_score": 0.8,
            "role_families": list(details.get("role_families") or []),
            "research_run_contract_version": RESEARCH_RUN_CONTRACT_VERSION,
            "supported_node_strategies": [],
        }
    return list(supported.values())


def rank_supported_agents_for_todo(
    todo_id: str,
    capability_requirements: str,
    task_name: str,
    *,
    preferred_agent_id: Optional[str] = None,
    excluded_agent_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    """Rank supported research agents using marketplace metadata instead of a fixed map."""

    excluded = {item for item in (excluded_agent_ids or []) if item}
    request_tokens = _normalize_tokens([todo_id, capability_requirements, task_name])
    required_role_family = _role_family_for_todo(todo_id, capability_requirements, task_name)
    ranked: List[tuple[float, str]] = []
    for agent in list_supported_research_agents():
        agent_id = str(agent.get("agent_id") or "")
        if not agent_id or agent_id in excluded:
            continue
        if not _agent_supports_research_run_contract(
            agent,
            todo_id=todo_id,
            required_role_family=required_role_family,
        ):
            continue
        if not _agent_supports_role_family(agent, required_role_family):
            continue
        score = _agent_role_match_score(
            agent,
            request_tokens,
            required_role_family=required_role_family,
        )
        if preferred_agent_id and preferred_agent_id == agent_id:
            score += 6.0
        ranked.append((score, agent_id))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [agent_id for _, agent_id in ranked]


def default_research_endpoint(agent_id: str) -> str:
    """Return the default research API endpoint for the given agent."""

    base_url = os.getenv("RESEARCH_API_URL", "http://localhost:5001").rstrip("/")
    return f"{base_url}/agents/{agent_id}"


def default_public_research_endpoint(agent_id: str) -> str:
    """Return the public API endpoint exposed for a supported research agent."""

    if is_supported_builtin_research_agent(agent_id):
        return f"/api/research-agent/{agent_id}"
    return default_research_endpoint(agent_id)


def default_public_research_health_url(agent_id: str) -> str | None:
    """Return the public health-check endpoint for a supported research agent."""

    if is_supported_builtin_research_agent(agent_id):
        return f"/api/research-agent/{agent_id}/health"
    return None


def infer_support_tier(agent_id: str, agent_type: str | None = None) -> SupportTier:
    """Infer the support tier for an agent."""

    built_in = get_builtin_research_agent(agent_id)
    if built_in is not None:
        return built_in.support_tier
    if agent_type == "research":
        return SupportTier.EXPERIMENTAL
    return SupportTier.SUPPORTED


def build_phase0_todo_items(description: str) -> List[Dict[str, str]]:
    """Build the fixed literature-review workflow for phase 0."""

    return [
        {
            "id": "todo_0",
            "title": "Frame the research question",
            "description": (
                f"Clarify the user's request into a scoped research question, constraints, "
                f"and searchable literature-review brief.\n\nUser request:\n{description}"
            ),
            "assigned_to": "problem-framer-001",
        },
        {
            "id": "todo_1",
            "title": "Mine supporting literature",
            "description": (
                f"Find relevant papers, sources, and evidence for the framed question.\n\n"
                f"Base request:\n{description}"
            ),
            "assigned_to": "literature-miner-001",
        },
        {
            "id": "todo_2",
            "title": "Synthesize the findings",
            "description": (
                f"Produce a synthesis of the literature review, highlighting key findings, "
                f"uncertainties, and next steps.\n\nBase request:\n{description}"
            ),
            "assigned_to": "knowledge-synthesizer-001",
        },
    ]


def select_supported_agent_for_todo(todo_id: str, capability_requirements: str, task_name: str) -> str:
    """Select the best supported research agent for the current microtask."""

    ranked = rank_supported_agents_for_todo(todo_id, capability_requirements, task_name)
    if ranked:
        return ranked[0]
    return _default_supported_agent_id_for_todo(todo_id, capability_requirements, task_name)
