"""Research API executor - calls research agents via FastAPI server on port 5001."""

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from strands import tool

from shared.agent_utils import serialize_agent
from shared.database import Agent as AgentModel
from shared.database import AgentReputation, SessionLocal
from shared.task_progress import update_progress

logger = logging.getLogger(__name__)

# Research agents API base URL
RESEARCH_API_BASE_URL = os.getenv("RESEARCH_API_URL", "http://localhost:5001")
MARKETPLACE_API_BASE_URL = (
    os.getenv("MARKETPLACE_API_URL")
    or os.getenv("BACKEND_API_URL")
    or os.getenv("ORCHESTRATOR_API_URL")
    or "http://localhost:8000"
)

AGENT_DIRECTORY_BASE_URL = f"{MARKETPLACE_API_BASE_URL.rstrip('/')}/api/agents"
AGENT_DIRECTORY_LIST_URL = f"{AGENT_DIRECTORY_BASE_URL}/"

# Simple in-memory cache for agent records to avoid repeated lookups
_agent_cache: Dict[str, Dict[str, Any]] = {}


def _legacy_agent_endpoint(agent_domain: str) -> str:
    """Fallback endpoint pointing at the legacy research API server."""
    return f"{RESEARCH_API_BASE_URL.rstrip('/')}/agents/{agent_domain}"


def _load_local_agent_record(agent_id: str) -> Optional[Dict[str, Any]]:
    """Load agent metadata directly from the local marketplace database."""

    session = SessionLocal()
    try:
        agent = session.query(AgentModel).filter(AgentModel.agent_id == agent_id).one_or_none()
        if agent is None:
            return None

        reputation = (
            session.query(AgentReputation)
            .filter(AgentReputation.agent_id == agent_id)
            .one_or_none()
        )
        score = reputation.reputation_score if reputation else None
        return serialize_agent(agent, reputation_score=score)
    finally:
        session.close()


async def _fetch_agent_record(agent_id: str) -> Optional[Dict[str, Any]]:
    """Fetch agent metadata from the marketplace API with caching."""
    if agent_id in _agent_cache:
        return _agent_cache[agent_id]

    record = _load_local_agent_record(agent_id)
    if record:
        _agent_cache[agent_id] = record
        return record

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AGENT_DIRECTORY_BASE_URL}/{agent_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                _agent_cache[agent_id] = data
                return data
    except Exception as error:
        logger.debug("[fetch_agent_record] Failed to fetch agent %s: %s", agent_id, error)

    return None


async def _resolve_agent_endpoint(agent_domain: str, explicit_endpoint: Optional[str]) -> str:
    """
    Determine the best endpoint for executing the agent.

    Preference order:
    1. Explicit endpoint supplied via tool argument.
    2. Stored endpoint from marketplace metadata.
    3. Legacy research API fallback.
    """
    if explicit_endpoint:
        return explicit_endpoint

    record = await _fetch_agent_record(agent_domain)
    if record:
        endpoint_url = record.get("endpoint_url")
        if endpoint_url:
            return endpoint_url

    logger.debug(
        "[resolve_agent_endpoint] Falling back to legacy endpoint for %s", agent_domain
    )
    return _legacy_agent_endpoint(agent_domain)


async def _post_agent_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a POST request to the agent endpoint and return parsed JSON data."""
    logger.debug("[_post_agent_request] POST %s", endpoint)

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()

    try:
        data = response.json()
    except json.JSONDecodeError as error:
        logger.error(
            "[_post_agent_request] Invalid JSON response from %s: %s",
            endpoint,
            error,
        )
        raise ValueError(
            f"Agent response from {endpoint} was not valid JSON."
        ) from error

    if not isinstance(data, dict):
        raise ValueError(
            f"Agent response from {endpoint} must be a JSON object."
        )

    return data


@tool
async def list_research_agents() -> Dict[str, Any]:
    """
    List all available research agents from the marketplace API.

    Returns:
        Dict with list of available agents, their capabilities, and pricing:
        {
            "success": bool,
            "total_agents": int,
            "agents": [
                {
                    "agent_id": str,
                    "name": str,
                    "description": str,
                    "capabilities": List[str],
                    "pricing": dict,
                    "endpoint": str,
                    "reputation_score": float
                }
            ]
        }
    """
    logger.info(
        "[list_research_agents] Fetching agents from %s", AGENT_DIRECTORY_LIST_URL
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(AGENT_DIRECTORY_LIST_URL)
            response.raise_for_status()
            data = response.json()

        agents = [
            agent
            for agent in data.get("agents", [])
            if agent.get("support_tier", "supported") == "supported"
        ]
        for agent in agents:
            agent_id = agent.get("agent_id")
            if agent_id:
                _agent_cache[agent_id] = agent

        total = data.get("total", len(agents))
        logger.info("[list_research_agents] Found %s agents", total)

        return {
            "success": True,
            "total_agents": total,
            "agents": agents,
        }

    except Exception as primary_error:
        logger.warning(
            "[list_research_agents] Marketplace API unavailable (%s). Falling back to %s.",
            primary_error,
            RESEARCH_API_BASE_URL,
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{RESEARCH_API_BASE_URL.rstrip('/')}/agents")
                response.raise_for_status()
                data = response.json()

            agents = data.get("agents", [])
            for agent in agents:
                agent_id = agent.get("agent_id")
                if agent_id and agent_id not in _agent_cache:
                    _agent_cache[agent_id] = agent

            return {
                "success": True,
                "total_agents": data.get("total_agents", len(agents)),
                "agents": agents,
                "source": "legacy",
            }

        except httpx.HTTPError as e:
            logger.error(f"[list_research_agents] HTTP error: {e}")
            return {
                "success": False,
                "error": f"Failed to connect to research agents API: {str(e)}",
                "suggestion": "Make sure the research agents server is running on port 5001"
            }
        except Exception as e:
            logger.error(f"[list_research_agents] Error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


@tool
async def execute_research_agent(
    agent_domain: str,
    task_description: str,
    context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    endpoint_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a research agent via its published HTTP endpoint.

    This function makes a real HTTP POST request to the research agents API
    running on port 5001. No simulation - actual agent execution.

    Args:
        agent_domain: The agent domain (e.g., "feasibility-analyst-001", "literature-miner-001")
        task_description: Description of the task to execute
        context: Optional context dict with additional parameters (budget, timeline, etc.)
        metadata: Optional metadata (task_id, user_id, etc.)
        endpoint_url: Optional explicit endpoint override for the agent

    Returns:
        Dict with execution results:
        {
            "success": bool,
            "agent_id": str,
            "result": Any,  # The actual agent output
            "error": str (if failed),
            "metadata": dict
        }

    Example:
        result = await execute_research_agent(
            agent_id="feasibility-analyst-001",
            task_description="Analyze feasibility of building a blockchain analytics platform",
            context={"budget": "5000 HBAR", "timeline": "3 months"},
            metadata={"task_id": "task-123"}
        )
    """
    try:
        logger.info(f"[execute_research_agent] Executing agent: {agent_domain}")
        logger.info(f"[execute_research_agent] Task: {task_description[:100]}...")

        if isinstance(context, str):
            try:
                context = json.loads(context)
            except json.JSONDecodeError:
                raise ValueError(f"context string is not valid JSON: {context}")

        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                raise ValueError(f"metadata string is not valid JSON: {metadata}")

        # Construct request payload
        payload = {
            "request": task_description,
            "context": context or {},
            "metadata": metadata or {},
        }
        logger.info(f"[execute_research_agent] Payload: {payload}")

        record = await _fetch_agent_record(agent_domain)
        if record and record.get("support_tier", "supported") != "supported":
            return {
                "success": False,
                "agent_id": agent_domain,
                "error": f"Agent '{agent_domain}' is not in the supported tier.",
            }

        endpoint = await _resolve_agent_endpoint(
            agent_domain,
            endpoint_url or (record.get("endpoint_url") if record else None),
        )
        logger.info(f"[execute_research_agent] Calling {endpoint}")

        # Emit web_search progress if this is a literature/web search agent and we have a task_id
        web_search_started = False
        try:
            task_id = (metadata or {}).get("task_id")
            if task_id and any(
                k in (agent_domain or "") for k in ("literature", "miner", "knowledge", "paper", "search")
            ):
                update_progress(
                    task_id,
                    "web_search",
                    "running",
                    {
                        "message": "Searching the web for relevant sources",
                        "agent_domain": agent_domain,
                    },
                )
                web_search_started = True
        except Exception:
            # Non-fatal; continue execution
            pass

        try:
            data = await _post_agent_request(endpoint, payload)
        except httpx.RequestError as connection_error:
            fallback_endpoint = _legacy_agent_endpoint(agent_domain)
            if endpoint != fallback_endpoint:
                logger.warning(
                    "[execute_research_agent] Primary endpoint %s unreachable (%s). Falling back to %s",
                    endpoint,
                    connection_error,
                    fallback_endpoint,
                )
                try:
                    data = await _post_agent_request(fallback_endpoint, payload)
                except Exception as fallback_exception:  # noqa: BLE001
                    logger.error(
                        "[execute_research_agent] Fallback endpoint %s also failed: %s",
                        fallback_endpoint,
                        fallback_exception,
                    )
                    raise fallback_exception
            else:
                raise connection_error

        if not data.get("success"):
            logger.error(f"[execute_research_agent] Agent returned error: {data.get('error')}")

        # Close web_search phase if it was opened
        if web_search_started:
            try:
                task_id = (metadata or {}).get("task_id")
                update_progress(
                    task_id,
                    "web_search",
                    "completed",
                    {
                        "message": "✓ Web search results retrieved",
                        "agent_domain": agent_domain,
                    },
                )
            except Exception:
                pass

        return data

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 404:
            logger.error(f"[execute_research_agent] Agent not found: {agent_domain}")
            return {
                "success": False,
                "agent_id": agent_domain,
                "error": f"Agent '{agent_domain}' not found or endpoint returned 404.",
            }
        logger.error(f"[execute_research_agent] HTTP {status_code}: {exc}")
        return {
            "success": False,
            "agent_id": agent_domain,
            "error": f"HTTP error {status_code}: {exc.response.text}",
        }

    except httpx.TimeoutException:
        logger.error(f"[execute_research_agent] Request timed out for agent: {agent_domain}")
        return {
            "success": False,
            "agent_id": agent_domain,
            "error": "Agent execution timed out (120s limit). The task may be too complex or the endpoint is overloaded.",
        }

    except httpx.HTTPError as exc:
        logger.error(f"[execute_research_agent] HTTP error: {exc}")
        return {
            "success": False,
            "agent_id": agent_domain,
            "error": f"Failed to connect to research agents API: {str(exc)}",
            "suggestion": "Make sure the research agents server is running on port 5001",
        }

    except Exception as exc:  # noqa: BLE001
        logger.error(f"[execute_research_agent] Unexpected error: {exc}", exc_info=True)
        return {
            "success": False,
            "agent_id": agent_domain,
            "error": f"Unexpected error: {str(exc)}",
        }


@tool
async def get_agent_metadata(agent_id: str) -> Dict[str, Any]:
    """
    Get detailed metadata for a specific research agent.

    Args:
        agent_id: The agent ID (e.g., "feasibility-analyst-001")

    Returns:
        Dict with agent metadata including capabilities, pricing, API spec, etc.
    """
    try:
        logger.info(f"[get_agent_metadata] Fetching metadata for: {agent_id}")

        record = await _fetch_agent_record(agent_id)
        if record:
            return {
                "success": True,
                **record,
            }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_legacy_agent_endpoint(agent_id))
            response.raise_for_status()
            data = response.json()
            logger.info(f"[get_agent_metadata] Retrieved metadata for {agent_id} via legacy API")
            return {
                "success": True,
                **data,
                "source": "legacy",
            }

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 404:
            return {
                "success": False,
                "error": f"Agent '{agent_id}' not found",
            }
        return {
            "success": False,
            "error": f"HTTP error {status_code}: {exc.response.text}",
        }

    except Exception as error:
        logger.error(f"[get_agent_metadata] Error: {error}", exc_info=True)
        return {
            "success": False,
            "error": str(error),
        }
