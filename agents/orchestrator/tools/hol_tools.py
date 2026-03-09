"""HOL (Hashgraph Online) discovery and hiring tools for the Orchestrator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from strands import tool

from shared.hol_client import (
    HolAgentSummary,
    HolClientError,
    search_agents,
    create_session,
    send_message,
    get_history,
)


def _agent_summary_to_dict(agent: HolAgentSummary) -> Dict[str, Any]:
    return {
        "uaid": agent.uaid,
        "name": agent.name,
        "description": agent.description,
        "capabilities": agent.capabilities,
        "categories": agent.categories,
        "transports": agent.transports,
        "pricing": agent.pricing,
        "registry": agent.registry,
    }


@tool
async def hol_discover_agents(
    task_description: str,
    required_capabilities: Optional[List[str]] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Discover candidate agents from the HOL Universal Agentic Registry for a given task.

    Args:
        task_description: Natural language description of the microtask to delegate.
        required_capabilities: Optional list of capability keywords to bias discovery
            (for example: ["literature review", "data analysis", "solidity audit"]).
        limit: Maximum number of agents to return (default 5).

    Returns:
        Dictionary with a list of candidate agents and the query used.
    """
    query_parts = [task_description.strip()]
    if required_capabilities:
        query_parts.extend(required_capabilities)
    query = " ".join(part for part in query_parts if part)

    try:
        agents = search_agents(query=query, limit=limit)
    except HolClientError as exc:
        return {
            "success": False,
            "error": str(exc),
            "agents": [],
            "query": query,
        }

    return {
        "success": True,
        "query": query,
        "agents": [_agent_summary_to_dict(agent) for agent in agents],
    }


@tool
async def hol_hire_agent(
    uaid: str,
    instructions: str,
    context: Optional[Dict[str, Any]] = None,
    transport: Optional[str] = None,
    as_uaid: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Hire a specific HOL agent by UAID for a well-scoped microtask.

    This helper:
        - Creates (or reuses) a chat session with the target UAID.
        - Sends a structured instruction message including optional context.

    Args:
        uaid: Target Universal Agent Identifier for the agent to hire.
        instructions: Natural language description of the task to perform.
        context: Optional structured context (inputs, constraints, budget, etc.).
        transport: Optional transport hint (e.g. "xmtp", "a2a", "http").
        as_uaid: Optional UAID to send messages as (when Synaptica has a verified UAID).

    Returns:
        Dictionary containing session_id, delivery status, and raw broker response.
    """
    context = context or {}

    # Build a compact, tool-friendly message for the target agent.
    message_payload: Dict[str, Any] = {
        "role": "user",
        "type": "synaptica_microtask",
        "instructions": instructions,
        "context": context,
    }

    try:
        session_id = create_session(uaid=uaid, transport=transport, as_uaid=as_uaid)
        response = send_message(
            session_id=session_id,
            message=str(message_payload),
            as_uaid=as_uaid,
        )
    except HolClientError as exc:
        return {
            "success": False,
            "error": str(exc),
            "session_id": None,
            "uaid": uaid,
        }

    return {
        "success": True,
        "uaid": uaid,
        "session_id": session_id,
        "broker_response": response,
    }


@tool
async def hol_get_session_summary(session_id: str, limit: int = 50) -> Dict[str, Any]:
    """
    Fetch recent history for a HOL chat session and return a compact summary.

    Note:
        This does not perform heavy summarization itself; instead it returns
        a small window of messages so the Orchestrator can summarize them
        inside the model context if needed.

    Args:
        session_id: HOL chat session identifier.
        limit: Maximum number of recent messages to retrieve.

    Returns:
        Dictionary with raw messages and a lightweight textual summary.
    """
    try:
        messages = get_history(session_id=session_id, limit=limit)
    except HolClientError as exc:
        return {
            "success": False,
            "error": str(exc),
            "messages": [],
            "session_id": session_id,
        }

    # Build a single concatenated summary string based on roles and content.
    summary_lines: List[str] = []
    for msg in messages:
        role = msg.get("role") or msg.get("sender") or "unknown"
        content = msg.get("message") or msg.get("content") or ""
        if not content:
            continue
        summary_lines.append(f"[{role}] {content}")

    return {
        "success": True,
        "session_id": session_id,
        "messages": messages,
        "summary": "\n".join(summary_lines),
    }

