"""FastAPI main application - Orchestrator Agent Entry Point."""

import asyncio
import ipaddress
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from functools import lru_cache
from importlib import import_module
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shared.agents_cache import rebuild_agents_cache
from shared.database import Agent, AgentReputation, Base, SessionLocal, engine
from shared.database.models import A2AEvent, Task
from shared.payments.runtime import sync_verified_payment_profile
from shared.a2a.models import AgentCapability, AgentCard, MessagePayload, MessageResponse
from shared.research.agent_inventory import (
    get_builtin_research_agent,
    is_supported_builtin_research_agent,
    iter_supported_builtin_research_agents,
)
from shared.research.catalog import (
    build_phase0_todo_items,
    default_public_research_endpoint,
    default_public_research_health_url,
)
from shared.research_runs.deep_research import (
    assign_citation_ids,
    dedupe_sources,
    filter_sources_for_curation,
    sort_sources,
    validate_source_requirements,
)
from shared.research_runs.planner import SourceRequirements, build_research_run_plan
from shared.registry_sync import (
    RegistrySyncError,
    ensure_registry_cache,
    get_registry_cache_ttl_seconds,
)
from shared.hol_client import (
    HolClientConfigurationError,
    HolClientError,
    check_sidecar_health as hol_check_sidecar_health,
    create_session as hol_create_session,
    get_history as hol_get_history,
    get_credit_balance as hol_get_credit_balance,
    register_agent as hol_register_agent,
    search_agents as hol_search_agents,
    send_message as hol_send_message,
)
from shared.metadata import (
    AgentMetadataPayload,
    PinataCredentialsError,
    PinataUploadError,
    build_agent_metadata_payload,
    publish_agent_metadata,
)
from shared.runtime import (
    TelemetryEnvelope,
    append_progress_event,
    initialize_runtime_state,
    load_task_snapshot,
    persist_verification_state,
    redact_sensitive_payload,
)
import shared.task_progress as task_progress
from agents.orchestrator.tools import create_todo_list, execute_microtask

from .middleware import logging_middleware
from .routes import agents as agents_routes
from .routes import data_agent as data_agent_routes
from .routes import payments as payments_routes
from .routes import research_runs as research_runs_routes
from .routes import credits as credits_routes

# Load environment variables
load_dotenv()

# In-memory task storage for progress tracking
tasks_storage: Dict[str, Dict[str, Any]] = {}
_registry_refresh_task: Optional[asyncio.Task] = None
logger = logging.getLogger(__name__)

BUILT_IN_DATA_AGENT_ID = "data-agent-001"
HOL_DIRECT_SESSION_PREFIX = "hol-direct:"
HOL_DIRECT_SESSION_HISTORY_LIMIT = 50
_hol_direct_chat_sessions: Dict[str, Dict[str, Any]] = {}


@lru_cache(maxsize=8)
def _load_supported_research_runtime_agent(agent_id: str) -> Any:
    """Load a supported built-in research agent instance for the public chat shim."""

    record = get_builtin_research_agent(agent_id)
    if (
        record is None
        or not record.public_exposure
        or not record.active_runtime
        or not record.module_path
        or not record.instance_name
    ):
        raise KeyError(agent_id)

    module = import_module(record.module_path)
    return getattr(module, record.instance_name)


def _get_supported_research_runtime_agent(agent_id: str) -> Any:
    """Return a publicly exposed supported research agent or raise 404."""

    if not is_supported_builtin_research_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Research agent '{agent_id}' is not publicly exposed")

    try:
        return _load_supported_research_runtime_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Research agent '{agent_id}' is not publicly exposed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load supported research agent %s", agent_id)
        raise HTTPException(
            status_code=500,
            detail=f"Research agent '{agent_id}' is unavailable: {exc}",
        ) from exc


def _coerce_research_chat_response(result: Any) -> str:
    """Normalize a research agent execution result into a chat-friendly response string."""

    if isinstance(result, str):
        return result
    if result is None:
        return ""
    if not isinstance(result, dict):
        return str(result)

    success = bool(result.get("success"))
    if not success:
        error = str(result.get("error") or "Unknown agent error").strip()
        return f"Synaptica Research Agent error: {error}"

    payload = result.get("result")
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in (
            "answer_markdown",
            "summary",
            "executive_summary",
            "report_markdown",
            "response",
            "text",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(payload, ensure_ascii=True)[:4000]
    if isinstance(payload, list):
        return json.dumps(payload, ensure_ascii=True)[:4000]

    return str(payload)


def _upsert_builtin_data_agent() -> None:
    """Ensure the built-in Data Agent is available in the marketplace."""

    session = SessionLocal()
    try:
        agent = (
            session.query(Agent)
            .filter(Agent.agent_id == BUILT_IN_DATA_AGENT_ID)
            .one_or_none()
        )

        data_agent_meta = {
            "endpoint_url": "/api/data-agent/agent",
            "health_check_url": "/api/data-agent/agent/health",
            "pricing": {
                "rate": 0.0,
                "currency": "HBAR",
                "rate_type": "per_upload",
            },
            "categories": ["Data", "Storage", "DeSci"],
            "always_listed": True,
            "data_agent": {
                "built_in": True,
                "public_access": True,
            },
            "support_tier": "supported",
        }

        capabilities = [
            "dataset-upload",
            "dataset-catalog",
            "dataset-retrieval",
            "failed-data-archiving",
            "underused-data-storage",
        ]

        if agent is None:
            agent = Agent(  # type: ignore[call-arg]
                agent_id=BUILT_IN_DATA_AGENT_ID,
                name="Data Agent",
                agent_type="data",
                description=(
                    "Stores and catalogs underused or failed lab datasets for future reuse."
                ),
                capabilities=capabilities,
                status="active",
                meta=data_agent_meta,
            )
            session.add(agent)
        else:
            merged_meta = dict(agent.meta or {})
            merged_meta.update(data_agent_meta)
            agent.name = "Data Agent"
            agent.agent_type = "data"
            agent.description = (
                "Stores and catalogs underused or failed lab datasets for future reuse."
            )
            agent.capabilities = capabilities
            agent.status = "active"
            agent.meta = merged_meta

        reputation = (
            session.query(AgentReputation)
            .filter(AgentReputation.agent_id == BUILT_IN_DATA_AGENT_ID)
            .one_or_none()
        )
        if reputation is None:
            session.add(
                AgentReputation(  # type: ignore[call-arg]
                    agent_id=BUILT_IN_DATA_AGENT_ID,
                    reputation_score=0.8,
                    total_tasks=0,
                    successful_tasks=0,
                    failed_tasks=0,
                    payment_multiplier=1.0,
                )
            )
        else:
            reputation.reputation_score = max(float(reputation.reputation_score or 0.0), 0.8)

        session.commit()
        rebuild_agents_cache(session=session)
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert built-in Data Agent")
    finally:
        session.close()


def _upsert_supported_research_agents() -> None:
    """Ensure the supported phase 0 research agents exist in the marketplace cache."""

    session = SessionLocal()
    try:
        for record in iter_supported_builtin_research_agents():
            agent_id = record.agent_id
            agent = (
                session.query(Agent)
                .filter(Agent.agent_id == agent_id)
                .one_or_none()
            )
            meta = {
                "endpoint_url": default_public_research_endpoint(agent_id),
                "health_check_url": default_public_research_health_url(agent_id),
                "pricing": dict(record.pricing),
                "categories": ["Research", "DeSci"],
                "support_tier": record.support_tier.value,
                "always_listed": True,
            }

            if agent is None:
                agent = Agent(  # type: ignore[call-arg]
                    agent_id=agent_id,
                    name=record.name,
                    agent_type="research",
                    description=record.description,
                    capabilities=list(record.capabilities),
                    hedera_account_id=record.hedera_account_id,
                    status="active",
                    meta=meta,
                )
                session.add(agent)
            else:
                merged_meta = dict(agent.meta or {})
                merged_meta.update(meta)
                agent.name = record.name
                agent.agent_type = "research"
                agent.description = record.description
                agent.capabilities = list(record.capabilities)
                agent.hedera_account_id = record.hedera_account_id
                agent.status = "active"
                agent.meta = merged_meta

            reputation = (
                session.query(AgentReputation)
                .filter(AgentReputation.agent_id == agent_id)
                .one_or_none()
            )
            if reputation is None:
                session.add(
                    AgentReputation(  # type: ignore[call-arg]
                        agent_id=agent_id,
                        reputation_score=0.8,
                        total_tasks=0,
                        successful_tasks=0,
                        failed_tasks=0,
                        payment_multiplier=1.0,
                    )
                )
            else:
                reputation.reputation_score = max(float(reputation.reputation_score or 0.0), 0.8)

            sync_verified_payment_profile(
                session,
                agent=agent,
                verification_method="supported_catalog_sync",
            )

        session.commit()
        rebuild_agents_cache(session=session)
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert supported research agents")
    finally:
        session.close()


def _sync_task_cache(task_id: str, snapshot: Optional[Dict[str, Any]]) -> None:
    if snapshot is not None:
        tasks_storage[task_id] = snapshot


def update_task_progress(task_id: str, step: str, status: str, data: Optional[Dict] = None):
    """Update task progress for frontend polling."""
    overall_status = None
    if step == "orchestrator" and status in {"completed", "failed"}:
        overall_status = status
    elif status == "cancelled":
        overall_status = "CANCELLED"

    envelope = TelemetryEnvelope(
        task_id=task_id,
        step=step,
        status=status,
        data=redact_sensitive_payload(data or {}),
    )
    snapshot = append_progress_event(task_id, envelope, overall_status=overall_status)
    if snapshot is not None:
        _sync_task_cache(task_id, snapshot)
        return

    # Fallback for events emitted before the DB task row exists.
    existing = tasks_storage.setdefault(
        task_id,
        {
            "task_id": task_id,
            "status": "processing",
            "progress": [],
            "current_step": step,
        },
    )
    existing.setdefault("progress", []).append(envelope.model_dump(mode="json"))
    existing["current_step"] = step


def _build_phase0_curated_sources(
    *,
    gathered_evidence: Dict[str, Any],
    execution_parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """Inline source curation for the three-step phase 0 workflow."""

    requirements = SourceRequirements.model_validate(
        execution_parameters.get("source_requirements") or {}
    )
    filtered_payload = filter_sources_for_curation(
        dedupe_sources(gathered_evidence.get("sources") or []),
        requirements=requirements,
        classified_mode=str(execution_parameters.get("classified_mode") or "literature"),
    )
    curated_sources = sort_sources(filtered_payload["selected_sources"])
    curated_sources, citations = assign_citation_ids(
        curated_sources,
        limit=requirements.total_sources,
    )
    validation = validate_source_requirements(curated_sources, requirements=requirements)
    source_summary = validation["summary"]
    freshness_summary = {
        "required": requirements.min_fresh_sources > 0,
        "window_days": requirements.freshness_window_days,
        "minimum_fresh_sources": requirements.min_fresh_sources,
        "fresh_sources": source_summary["fresh_sources"],
        "requirements_met": validation["passed"],
        "issues": validation["issues"],
    }
    return {
        "sources": curated_sources,
        "citations": citations,
        "source_summary": source_summary,
        "freshness_summary": freshness_summary,
        "coverage_summary": dict(gathered_evidence.get("coverage_summary") or {}),
        "uncovered_claim_targets": list(gathered_evidence.get("uncovered_claim_targets") or []),
        "rounds_completed": dict(
            gathered_evidence.get("rounds_completed")
            or {"evidence_rounds": 0, "critique_rounds": 0}
        ),
        "filtered_sources": list(filtered_payload.get("filtered_sources") or []),
    }


def _extract_hol_meta(agent: Agent) -> Dict[str, Any]:
    meta = dict(agent.meta or {})
    hol_meta = dict(meta.get("hol") or {})
    return {
        "uaid": hol_meta.get("uaid"),
        "registration_status": hol_meta.get("registration_status") or "unregistered",
        "last_error": hol_meta.get("last_error"),
        "updated_at": hol_meta.get("updated_at"),
    }


def _set_hol_meta(
    agent: Agent,
    *,
    status: str,
    uaid: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    meta = dict(agent.meta or {})
    hol_meta = dict(meta.get("hol") or {})
    hol_meta["registration_status"] = status
    hol_meta["updated_at"] = datetime.utcnow().isoformat()
    if uaid is not None:
        hol_meta["uaid"] = uaid
    if last_error is None and status in {"registered", "pending"}:
        hol_meta["last_error"] = None
    else:
        hol_meta["last_error"] = last_error
    meta["hol"] = hol_meta
    agent.meta = meta


def _is_transient_hol_error(message: str) -> bool:
    text = (message or "").lower()
    transient_markers = (
        "timed out",
        "timeout",
        "failed to connect to hol registry",
        "connect error",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "upstream hol registry error page",
        "temporary",
    )
    return any(marker in text for marker in transient_markers)


def _resolve_hol_error_status(previous_status: str, message: str) -> str:
    normalized_prev = (previous_status or "unregistered").strip().lower()
    if _is_transient_hol_error(message):
        # Keep previously successful registrations as-is; otherwise reset to unregistered.
        if normalized_prev in {"registered", "ok"}:
            return "registered"
        return "unregistered"
    return "error"


def _is_hol_insufficient_credits_error(message: str) -> bool:
    return "insufficient_credits" in (message or "").lower()


def _is_relative_or_non_public_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return True
    if parsed.scheme.lower() not in {"http", "https"}:
        return False

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return True
    if hostname in {"localhost", "0.0.0.0", "127.0.0.1", "::1", "host.docker.internal"}:
        return True
    if hostname.endswith(".local"):
        return True

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _rewrite_hol_public_url(url: str) -> str:
    raw = (url or "").strip()
    base = (os.getenv("HOL_PUBLIC_BASE_URL") or "").strip()
    if not base:
        raise HTTPException(
            status_code=400,
            detail=(
                "HOL_PUBLIC_BASE_URL is required when registering data agents with "
                "relative or private endpoints"
            ),
        )

    parsed_base = urlparse(base)
    if parsed_base.scheme.lower() not in {"http", "https"} or not parsed_base.netloc:
        raise HTTPException(
            status_code=400,
            detail="HOL_PUBLIC_BASE_URL must be an absolute http(s) URL",
        )

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        path = parsed.path or "/"
        if parsed.params:
            path = f"{path};{parsed.params}"
        query = f"?{parsed.query}" if parsed.query else ""
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"{base.rstrip('/')}{path}{query}{fragment}"

    normalized_path = raw if raw.startswith("/") else f"/{raw}"
    return urljoin(f"{base.rstrip('/')}/", normalized_path.lstrip("/"))


def _coerce_string_list(values: Any) -> List[str]:
    output: List[str] = []
    if not isinstance(values, list):
        return output
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                output.append(cleaned)
    return output


async def _publish_missing_data_agent_metadata(
    agent: Agent,
    *,
    endpoint_url: str,
    health_check_url: Optional[str],
) -> None:
    meta = dict(agent.meta or {})
    pricing = dict(meta.get("pricing") or {})
    metadata_payload = AgentMetadataPayload(
        agent_id=agent.agent_id,
        name=agent.name,
        description=str(agent.description or "").strip(),
        endpoint_url=endpoint_url,
        capabilities=_coerce_string_list(agent.capabilities),
        pricing_rate=float(pricing.get("rate") or 0.0),
        pricing_currency=str(pricing.get("currency") or "HBAR"),
        pricing_rate_type=str(pricing.get("rate_type") or "per_task"),
        categories=_coerce_string_list(meta.get("categories") or []),
        contact_email=str(meta.get("contact_email") or "").strip() or None,
        logo_url=str(meta.get("logo_url") or "").strip() or None,
        health_check_url=health_check_url,
        hedera_account=agent.hedera_account_id,
    )
    metadata = build_agent_metadata_payload(metadata_payload)
    try:
        upload_result = await publish_agent_metadata(agent.agent_id, metadata)
    except PinataCredentialsError as exc:
        raise HTTPException(
            status_code=500,
            detail="Pinata credentials missing; configure PINATA_API_KEY and PINATA_SECRET_KEY.",
        ) from exc
    except PinataUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    meta["metadata_cid"] = upload_result.cid
    meta["metadata_gateway_url"] = upload_result.gateway_url
    agent.meta = meta
    agent.erc8004_metadata_uri = upload_result.ipfs_uri


async def _prepare_hol_registration_payload(
    agent: Agent,
    *,
    endpoint_url_override: Optional[str] = None,
    metadata_uri_override: Optional[str] = None,
) -> Dict[str, Any]:
    meta = dict(agent.meta or {})
    endpoint_url = str(
        endpoint_url_override if endpoint_url_override is not None else (meta.get("endpoint_url") or "")
    ).strip()
    health_check_url = str(meta.get("health_check_url") or "").strip() or None
    metadata_uri = str(
        metadata_uri_override
        if metadata_uri_override is not None
        else (agent.erc8004_metadata_uri or meta.get("metadata_gateway_url") or "")
    ).strip() or None

    if agent.agent_type == "data":
        if endpoint_url and _is_relative_or_non_public_url(endpoint_url):
            endpoint_url = _rewrite_hol_public_url(endpoint_url)
        if health_check_url and _is_relative_or_non_public_url(health_check_url):
            health_check_url = _rewrite_hol_public_url(health_check_url)
        if not metadata_uri:
            await _publish_missing_data_agent_metadata(
                agent,
                endpoint_url=endpoint_url,
                health_check_url=health_check_url,
            )
            refreshed_meta = dict(agent.meta or {})
            metadata_uri = str(
                agent.erc8004_metadata_uri or refreshed_meta.get("metadata_gateway_url") or ""
            ).strip() or None

    return _build_hol_registration_payload(
        agent,
        endpoint_url_override=endpoint_url or None,
        metadata_uri_override=metadata_uri,
        health_check_url_override=health_check_url,
    )


def _build_hol_registration_payload(
    agent: Agent,
    *,
    endpoint_url_override: Optional[str] = None,
    metadata_uri_override: Optional[str] = None,
    health_check_url_override: Optional[str] = None,
) -> Dict[str, Any]:
    meta = dict(agent.meta or {})
    pricing = dict(meta.get("pricing") or {})
    categories = meta.get("categories") or []
    endpoint_url = str(
        endpoint_url_override if endpoint_url_override is not None else (meta.get("endpoint_url") or "")
    ).strip()
    metadata_uri = (
        metadata_uri_override
        if metadata_uri_override is not None
        else agent.erc8004_metadata_uri or meta.get("metadata_gateway_url")
    )

    if not endpoint_url:
        raise HTTPException(status_code=400, detail="Agent endpoint URL is required for HOL registration")
    if not metadata_uri:
        raise HTTPException(
            status_code=400,
            detail="Agent metadata URI is required for HOL registration",
        )

    category_tags: List[str] = []
    if isinstance(categories, list):
        for category in categories:
            if isinstance(category, str):
                cleaned = category.strip()
                if cleaned:
                    category_tags.append(cleaned)

    capabilities: List[str] = []
    if isinstance(agent.capabilities, list):
        for capability in agent.capabilities:
            if isinstance(capability, str):
                cleaned = capability.strip()
                if cleaned:
                    capabilities.append(cleaned)

    description = str(agent.description or "").strip()
    short_description = " ".join(description.split())[:160] if description else agent.name
    profile: Dict[str, Any] = {
        "version": "1.0",
        "type": 1,  # AI_AGENT (required by HOL HCS-11 validator)
        "display_name": agent.name,
        "description": description,
        "short_description": short_description,
        "url": endpoint_url,
        "tags": category_tags,
        "aiAgent": {
            "capabilities": capabilities,
            "metadata_uri": metadata_uri,
            "pricing": pricing if isinstance(pricing, dict) else {},
        },
    }

    health_check_url = (
        health_check_url_override
        if health_check_url_override is not None
        else meta.get("health_check_url")
    )
    if isinstance(health_check_url, str) and health_check_url.strip():
        profile["aiAgent"]["health_check_url"] = health_check_url.strip()
    if agent.hedera_account_id:
        profile["owner"] = {"account_id": agent.hedera_account_id}

    # HOL defaults to paid base registration unless additional registries are
    # explicitly controlled. Keep local marketplace registration on free tier
    # by default and allow opt-in paid fan-out via env override.
    additional_registries_env = (os.getenv("HOL_REGISTER_ADDITIONAL_REGISTRIES") or "").strip()
    additional_registries: List[str] = []
    if additional_registries_env:
        additional_registries = [
            item.strip() for item in additional_registries_env.split(",") if item.strip()
        ]

    return {
        # HOL /register expects this HCS-11 profile envelope.
        "profile": profile,
        # Explicitly pass additionalRegistries to avoid broker-side paid defaults.
        "additionalRegistries": additional_registries,
        # Keep the legacy flat shape for compatibility with any alternate broker paths.
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": description,
        "capabilities": capabilities,
        "categories": category_tags,
        "endpoint_url": endpoint_url,
        "health_check_url": health_check_url,
        "pricing": pricing if isinstance(pricing, dict) else {},
        "metadata_uri": metadata_uri,
        "hedera_account_id": agent.hedera_account_id,
    }


def _extract_hol_uaid(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("uaid", "agent_uaid", "agentUaid", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for section_key in ("data", "result", "registration", "agent"):
        section = payload.get(section_key)
        if not isinstance(section, dict):
            continue
        for key in ("uaid", "agent_uaid", "agentUaid", "id"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _extract_estimated_credits(payload: Dict[str, Any]) -> Optional[float]:
    candidates: List[Any] = [
        payload.get("estimated_credits"),
        payload.get("estimatedCredits"),
        payload.get("credits"),
    ]
    quote = payload.get("quote")
    if isinstance(quote, dict):
        candidates.extend(
            [
                quote.get("estimated_credits"),
                quote.get("estimatedCredits"),
                quote.get("credits"),
            ]
        )

    for value in candidates:
        try:
            if value is None:
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


# Pydantic models for API requests/responses
class TaskRequest(BaseModel):
    """Request model for creating a task."""

    description: str
    capability_requirements: Optional[str] = None
    budget_limit: Optional[float] = None
    min_reputation_score: Optional[float] = 0.7
    verification_mode: Optional[str] = "standard"


class TaskResponse(BaseModel):
    """Response model for task execution."""

    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class A2AEventResponse(BaseModel):
    """Response model for emitted A2A messages."""

    message_id: str
    protocol: str
    message_type: str
    from_agent: str
    to_agent: str
    thread_id: str
    timestamp: datetime
    tags: Optional[List[str]] = None
    body: Dict[str, Any]


class HolAgentRecord(BaseModel):
    """Normalized HOL agent representation for the frontend marketplace."""

    uaid: str
    name: str
    description: str
    capabilities: List[str]
    categories: List[str]
    transports: List[str]
    pricing: Dict[str, Any]
    registry: Optional[str] = None
    available: Optional[bool] = None
    availability_status: Optional[str] = None
    trust_score: Optional[float] = None
    trust_scores: Optional[Dict[str, float]] = None
    source_url: Optional[str] = None
    adapter: Optional[str] = None
    protocol: Optional[str] = None


class HolAgentsSearchResponse(BaseModel):
    """Response model for HOL agent search."""

    agents: List[HolAgentRecord]
    query: str


class HolChatSessionRequest(BaseModel):
    """Request payload for starting a HOL chat session."""

    uaid: str
    transport: Optional[str] = None
    as_uaid: Optional[str] = None


class HolChatSendRequest(BaseModel):
    """Request payload for sending a HOL chat message."""

    session_id: str
    message: str
    as_uaid: Optional[str] = None


class HolChatMessageRecord(BaseModel):
    """Normalized HOL chat message for frontend display."""

    role: str
    content: str
    timestamp: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class HolChatSessionResponse(BaseModel):
    """Response payload for HOL chat session operations."""

    success: bool
    session_id: str
    uaid: Optional[str] = None
    broker_response: Dict[str, Any] = Field(default_factory=dict)
    history: List[HolChatMessageRecord] = Field(default_factory=list)


class HolRegisterAgentRequest(BaseModel):
    """Request payload for quoting/registering a local agent into HOL."""

    agent_id: str
    mode: Literal["quote", "register"] = "register"
    endpoint_url_override: Optional[str] = None
    metadata_uri_override: Optional[str] = None


class HolRegisterAgentResponse(BaseModel):
    """Response payload for HOL registration operations."""

    success: bool
    agent_id: str
    mode: Literal["quote", "register"]
    hol_registration_status: str
    hol_uaid: Optional[str] = None
    hol_last_error: Optional[str] = None
    estimated_credits: Optional[float] = None
    broker_response: Dict[str, Any] = Field(default_factory=dict)


class HolRegisterAgentStatusResponse(BaseModel):
    """Current persisted HOL registration status for a local agent."""

    agent_id: str
    hol_registration_status: str
    hol_uaid: Optional[str] = None
    hol_last_error: Optional[str] = None
    updated_at: Optional[str] = None


def _extract_hol_chat_message_content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("content", "message", "text", "reply", "response"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _extract_hol_chat_message_content(value)
                if nested:
                    return nested
        parts = payload.get("parts")
        if isinstance(parts, list):
            chunks: List[str] = []
            for part in parts:
                nested = _extract_hol_chat_message_content(part)
                if nested:
                    chunks.append(nested)
            if chunks:
                return "\n".join(chunks)
    return ""


def _normalize_hol_chat_history(messages: List[Dict[str, Any]]) -> List[HolChatMessageRecord]:
    normalized: List[HolChatMessageRecord] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(
            item.get("role")
            or item.get("senderRole")
            or item.get("type")
            or "assistant"
        ).strip().lower()
        if role not in {"user", "assistant", "system"}:
            sender = str(item.get("sender") or item.get("from") or "").strip().lower()
            role = "assistant" if sender not in {"user", "human"} else "user"
        content = _extract_hol_chat_message_content(item)
        if not content:
            content = json.dumps(item, ensure_ascii=True)[:1200]
        timestamp_value = item.get("timestamp") or item.get("createdAt") or item.get("sentAt")
        normalized.append(
            HolChatMessageRecord(
                role=role,
                content=content,
                timestamp=str(timestamp_value) if timestamp_value else None,
                raw=item,
            )
        )
    return normalized


def _should_use_hol_direct_chat_fallback(error: HolClientError) -> bool:
    if isinstance(error, HolClientConfigurationError):
        # Sidecar not reachable/configured is a local setup problem, not a broker timeout.
        return False
    message = str(error).lower()
    if "create_session failed" not in message:
        return False
    return any(
        marker in message
        for marker in (
            "timed out",
            "timeout",
            "gateway timeout",
            "504",
            "503",
            "502",
            "registry broker request failed",
        )
    )


def _create_hol_direct_chat_session(uaid: str) -> str:
    session_id = f"{HOL_DIRECT_SESSION_PREFIX}{uuid.uuid4()}"
    _hol_direct_chat_sessions[session_id] = {"uaid": uaid, "history": []}
    return session_id


def _is_hol_direct_chat_session(session_id: str) -> bool:
    return session_id.startswith(HOL_DIRECT_SESSION_PREFIX)


def _get_hol_direct_chat_session(session_id: str) -> Optional[Dict[str, Any]]:
    return _hol_direct_chat_sessions.get(session_id)


def _append_hol_direct_chat_history(
    session_id: str,
    records: List[HolChatMessageRecord],
) -> List[HolChatMessageRecord]:
    session = _hol_direct_chat_sessions.get(session_id)
    if session is None:
        return []

    history = session.setdefault("history", [])
    if not isinstance(history, list):
        history = []
    history.extend(records)
    if len(history) > HOL_DIRECT_SESSION_HISTORY_LIMIT:
        history = history[-HOL_DIRECT_SESSION_HISTORY_LIMIT:]
    session["history"] = history
    return list(history)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global _registry_refresh_task

    # Startup: Create database tables
    Base.metadata.create_all(bind=engine)
    _upsert_builtin_data_agent()
    _upsert_supported_research_agents()
    # Register progress callback for task updates
    task_progress.set_progress_callback(update_task_progress)
    print("Database initialized")
    print("Orchestrator agent ready")

    loop = asyncio.get_running_loop()

    def _prime_registry() -> Optional[str]:
        try:
            result = ensure_registry_cache()
            if result:
                return f"Primed registry cache with {result.synced} agents"
            return "Registry cache already warm"
        except RegistrySyncError as exc:
            logger.warning("Initial registry sync failed: %s", exc)
            return None

    prime_message = await loop.run_in_executor(None, _prime_registry)
    if prime_message:
        logger.info(prime_message)

    _registry_refresh_task = loop.create_task(_periodic_registry_refresh())
    yield
    # Shutdown
    if _registry_refresh_task:
        _registry_refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await _registry_refresh_task
        _registry_refresh_task = None
    print("Shutting down...")


async def _periodic_registry_refresh() -> None:
    """Run registry cache refreshes on the configured TTL."""

    while True:
        interval = max(60, get_registry_cache_ttl_seconds())
        await asyncio.sleep(interval)
        loop = asyncio.get_running_loop()

        def _refresh() -> Optional[str]:
            result = ensure_registry_cache()
            if result:
                return f"Periodic registry sync refreshed {result.synced} agents"
            return None

        try:
            message = await loop.run_in_executor(None, _refresh)
            if message:
                logger.debug(message)
        except RegistrySyncError as exc:
            logger.warning("Periodic registry sync failed: %s", exc)


# Create FastAPI app
app = FastAPI(
    title="ProvidAI Orchestrator",
    description="Orchestrator agent that discovers, negotiates with, and executes tasks using marketplace agents",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware
app.middleware("http")(logging_middleware)

# Include routers
app.include_router(agents_routes.router, prefix="/api/agents", tags=["agents"])
app.include_router(data_agent_routes.router, prefix="/api/data-agent", tags=["data-agent"])
app.include_router(payments_routes.router, prefix="/api/payments", tags=["payments"])
app.include_router(research_runs_routes.router, prefix="/api/research-runs", tags=["research-runs"])
app.include_router(credits_routes.router, prefix="/api/credits", tags=["credits"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "ProvidAI Orchestrator",
        "version": "0.1.0",
        "description": "Orchestrator agent for discovering and coordinating marketplace agents",
        "workflow": [
            "1. Frame the research question",
            "2. Mine supporting literature with a supported research agent",
            "3. Synthesize findings and verify before releasing payment",
            "4. Return the literature-review report and payment trail",
        ],
        "endpoints": {
            "/execute": "POST - Execute a task using marketplace agents",
            "/api/research-runs": "POST - Create and start a graph-backed research run",
            "/api/research-runs/{id}": "GET - Inspect research run status, nodes, and attempts",
            "/api/research-runs/{id}/pause": "POST - Cooperatively pause a research run",
            "/api/research-runs/{id}/resume": "POST - Resume a paused research run",
            "/api/research-runs/{id}/cancel": "POST - Cancel a research run and downstream scheduling",
            "/api/research-runs/{id}/evidence": "GET - Read the shaped evidence payload",
            "/api/research-runs/{id}/evidence-graph": "GET - Read the persisted Phase 2 evidence graph",
            "/api/research-runs/{id}/report": "GET - Read the shaped final report payload",
            "/api/research-runs/{id}/report-pack": "GET - Read the persisted Phase 2 JSON report pack",
            "/api/payments/{payment_id}": "GET - Inspect payment detail and notification summary",
            "/api/payments/{payment_id}/events": "GET - Inspect payment transitions, notifications, and A2A events",
            "/api/payments/reconcile": "POST - Reconcile payment state against terminal notifications",
            "/api/agents/{agent_id}/payment-profile/verify": "POST - Verify a payee payment profile",
            "/health": "GET - Health check",
            "/api/tasks/{task_id}": "GET - Poll task status and progress",
            "/api/tasks/history": "GET - Retrieve task history with payments",
            "/a2a/events": "GET - View A2A message events",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "orchestrator"}


@app.get("/api/research-agent/{agent_id}")
async def research_agent_public_metadata(agent_id: str) -> Dict[str, Any]:
    """Describe the public broker-chatable surface for a supported research agent."""

    agent = _get_supported_research_runtime_agent(agent_id)
    return {
        "agent_id": agent_id,
        "name": getattr(agent, "name", agent_id),
        "description": getattr(agent, "description", ""),
        "message_endpoint": f"/api/research-agent/{agent_id}/a2a/v1/messages",
        "card_endpoint": f"/api/research-agent/{agent_id}/.well-known/agent.json",
        "health_endpoint": f"/api/research-agent/{agent_id}/health",
    }


@app.get("/api/research-agent/{agent_id}/.well-known/agent.json", response_model=AgentCard)
async def research_agent_public_card(agent_id: str) -> AgentCard:
    """Expose a supported research agent as a minimal A2A-compatible card."""

    agent = _get_supported_research_runtime_agent(agent_id)
    capabilities = [
        AgentCapability(name=str(capability), description=None)
        for capability in list(getattr(agent, "capabilities", []) or [])
        if str(capability).strip()
    ]
    return AgentCard(
        id=agent_id,
        name=str(getattr(agent, "name", agent_id)),
        description=str(getattr(agent, "description", "") or ""),
        version="0.1.0",
        capabilities=capabilities,
        tags=["research", "desci", "a2a", "synaptica"],
        extras={"message_endpoint": f"/api/research-agent/{agent_id}/a2a/v1/messages"},
    )


@app.get("/api/research-agent/{agent_id}/health")
async def research_agent_public_health(agent_id: str) -> Dict[str, Any]:
    """Health endpoint for the supported research-agent public A2A surface."""

    agent = _get_supported_research_runtime_agent(agent_id)
    return {
        "status": "ok",
        "agent_id": agent_id,
        "service": "synaptica-research-agent",
        "name": getattr(agent, "name", agent_id),
    }


@app.post("/api/research-agent/{agent_id}/a2a/v1/messages", response_model=MessageResponse)
async def research_agent_public_message(
    agent_id: str,
    payload: MessagePayload,
) -> MessageResponse:
    """Respond to broker/A2A-style chat messages for supported research agents."""

    agent = _get_supported_research_runtime_agent(agent_id)
    context = dict(payload.metadata or {})
    result = await agent.execute(payload.message, context=context)
    response = _coerce_research_chat_response(result)
    return MessageResponse(
        message_id=uuid.uuid4().hex,
        response=response,
        metadata=payload.metadata,
    )


class SubTaskResponse(BaseModel):
    """Response model for subtask (payment) details."""
    id: str
    description: str
    agent_used: str
    agent_reputation: float
    cost: float
    status: str
    timestamp: datetime


class TaskHistoryResponse(BaseModel):
    """Response model for task history."""
    id: str
    research_query: str
    total_cost: float
    status: str
    created_at: datetime
    sub_tasks: List[SubTaskResponse]


@app.get("/api/tasks/history", response_model=List[TaskHistoryResponse])
def get_task_history(limit: int = 50) -> List[TaskHistoryResponse]:
    """
    Retrieve task history with associated payments (microtransactions).

    Returns tasks ordered by creation date (newest first) with their
    associated payment details representing agent microtransactions.
    """
    from shared.database.models import Agent, Payment, Task

    session = SessionLocal()
    try:
        capped_limit = max(1, min(limit, 200))

        # Query tasks with their payments
        tasks = (
            session.query(Task)
            .order_by(Task.created_at.desc())
            .limit(capped_limit)
            .all()
        )

        responses = []
        for task in tasks:
            # Get all payments for this task
            payments = (
                session.query(Payment)
                .filter(Payment.task_id == task.id)
                .order_by(Payment.created_at.asc())
                .all()
            )

            # Build subtasks from payments
            sub_tasks = []
            total_cost = 0.0

            for payment in payments:
                # Get agent details
                agent = session.query(Agent).filter(Agent.agent_id == payment.to_agent_id).first()
                agent_name = agent.name if agent else payment.to_agent_id

                # Get agent reputation (default to 0.0 if not found)
                from shared.database.models import AgentReputation
                reputation_record = session.query(AgentReputation).filter(
                    AgentReputation.agent_id == payment.to_agent_id
                ).first()
                reputation_score = reputation_record.reputation_score if reputation_record else 0.0

                # Extract description from payment metadata
                description = "Agent task execution"
                if payment.meta and isinstance(payment.meta, dict):
                    description = payment.meta.get("description", description)

                sub_tasks.append(SubTaskResponse(
                    id=payment.id,
                    description=description,
                    agent_used=agent_name,
                    agent_reputation=reputation_score,
                    cost=payment.amount,
                    status=payment.status.value,
                    timestamp=payment.created_at
                ))

                total_cost += payment.amount

            runtime_meta = {}
            if task.meta and isinstance(task.meta, dict):
                runtime_meta = dict(task.meta.get("runtime") or {})
            persisted_runtime_status = str(runtime_meta.get("status") or "").lower()

            # Map task status to frontend format
            status_mapping = {
                "pending": "in_progress",
                "assigned": "in_progress",
                "in_progress": "in_progress",
                "completed": "completed",
                "failed": "failed",
                "cancelled": "cancelled",
            }
            frontend_status = status_mapping.get(
                persisted_runtime_status or task.status.value,
                "in_progress",
            )

            responses.append(TaskHistoryResponse(
                id=task.id,
                research_query=task.title or task.description or "Unknown task",
                total_cost=total_cost,
                status=frontend_status,
                created_at=task.created_at,
                sub_tasks=sub_tasks
            ))

        return responses
    finally:
        session.close()


@app.get("/api/hol/agents/search", response_model=HolAgentsSearchResponse)
async def hol_agents_search(
    q: str,
    limit: int = 12,
    only_available: bool = False,
) -> HolAgentsSearchResponse:
    """
    Search HOL Registry Broker for agents, exposed for the Agent Marketplace UI.

    Currently supports a simple text query and limit. More advanced filtering
    (by registry, transports, or capabilities) can be layered on top of this.
    """
    query = q.strip()
    capped_limit = max(1, min(limit, 25))
    broker_limit = min(100, max(capped_limit, capped_limit * 5)) if only_available else capped_limit

    try:
        await run_in_threadpool(hol_check_sidecar_health)
        agents = await run_in_threadpool(hol_search_agents, query, limit=broker_limit)
    except HolClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if only_available:
        agents = [agent for agent in agents if agent.available is True][:capped_limit]

    records: List[HolAgentRecord] = []
    for agent in agents:
        records.append(
            HolAgentRecord(
                uaid=agent.uaid,
                name=agent.name,
                description=agent.description,
                capabilities=agent.capabilities,
                categories=agent.categories,
                transports=agent.transports,
                pricing=agent.pricing,
                registry=agent.registry,
                available=agent.available,
                availability_status=agent.availability_status,
                trust_score=getattr(agent, "trust_score", None),
                trust_scores=getattr(agent, "trust_scores", None),
                source_url=getattr(agent, "source_url", None),
                adapter=getattr(agent, "adapter", None),
                protocol=getattr(agent, "protocol", None),
            )
        )

    return HolAgentsSearchResponse(agents=records, query=query)


@app.post("/api/hol/chat/session", response_model=HolChatSessionResponse)
async def hol_chat_create_session(request: HolChatSessionRequest) -> HolChatSessionResponse:
    """Create a HOL broker chat session for a selected external agent."""
    uaid = request.uaid.strip()
    if not uaid:
        raise HTTPException(status_code=400, detail="uaid is required")

    try:
        await run_in_threadpool(hol_check_sidecar_health)
        session_id = await run_in_threadpool(
            hol_create_session,
            uaid,
            transport=request.transport,
            as_uaid=request.as_uaid,
        )
    except HolClientError as exc:
        if _should_use_hol_direct_chat_fallback(exc):
            logger.warning(
                "HOL create_session failed for %s, enabling direct chat fallback: %s",
                uaid,
                exc,
            )
            fallback_session_id = _create_hol_direct_chat_session(uaid)
            return HolChatSessionResponse(
                success=True,
                session_id=fallback_session_id,
                uaid=uaid,
                broker_response={
                    "mode": "direct",
                    "fallback_reason": str(exc),
                },
                history=[],
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        history = await run_in_threadpool(hol_get_history, session_id, limit=50)
    except HolClientError as exc:
        logger.warning("HOL get_history after create_session failed for %s: %s", uaid, exc)
        history = []

    return HolChatSessionResponse(
        success=True,
        session_id=session_id,
        uaid=uaid,
        history=_normalize_hol_chat_history(history),
    )


@app.post("/api/hol/chat/message", response_model=HolChatSessionResponse)
async def hol_chat_send_message(request: HolChatSendRequest) -> HolChatSessionResponse:
    """Send a message to an existing HOL broker chat session and return refreshed history."""
    session_id = request.session_id.strip()
    message = request.message.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    if _is_hol_direct_chat_session(session_id):
        direct_session = _get_hol_direct_chat_session(session_id)
        if direct_session is None:
            raise HTTPException(status_code=404, detail="HOL direct chat session not found")
        uaid = str(direct_session.get("uaid") or "").strip()
        if not uaid:
            raise HTTPException(status_code=500, detail="HOL direct chat session is missing UAID")

        try:
            await run_in_threadpool(hol_check_sidecar_health)
            broker_response = await run_in_threadpool(
                hol_send_message,
                None,
                message,
                uaid=uaid,
                as_uaid=request.as_uaid,
            )
        except HolClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        assistant_content = _extract_hol_chat_message_content(broker_response) or json.dumps(
            broker_response,
            ensure_ascii=True,
        )[:1200]
        history = _append_hol_direct_chat_history(
            session_id,
            [
                HolChatMessageRecord(role="user", content=message, raw={}),
                HolChatMessageRecord(
                    role="assistant",
                    content=assistant_content,
                    raw=broker_response if isinstance(broker_response, dict) else {},
                ),
            ],
        )
        return HolChatSessionResponse(
            success=True,
            session_id=session_id,
            uaid=uaid,
            broker_response=broker_response if isinstance(broker_response, dict) else {},
            history=history,
        )

    try:
        await run_in_threadpool(hol_check_sidecar_health)
        broker_response = await run_in_threadpool(
            hol_send_message,
            session_id,
            message,
            as_uaid=request.as_uaid,
        )
    except HolClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        history = await run_in_threadpool(hol_get_history, session_id, limit=50)
    except HolClientError as exc:
        logger.warning("HOL get_history after send_message failed for %s: %s", session_id, exc)
        history = []

    normalized_history = _normalize_hol_chat_history(history)
    if not normalized_history:
        content = _extract_hol_chat_message_content(broker_response) or json.dumps(
            broker_response,
            ensure_ascii=True,
        )[:1200]
        normalized_history = [
            HolChatMessageRecord(role="user", content=message, raw={}),
            HolChatMessageRecord(role="assistant", content=content, raw=broker_response),
        ]

    return HolChatSessionResponse(
        success=True,
        session_id=session_id,
        broker_response=broker_response,
        history=normalized_history,
    )


@app.post("/api/hol/register-agent", response_model=HolRegisterAgentResponse)
async def hol_register_local_agent(request: HolRegisterAgentRequest) -> HolRegisterAgentResponse:
    """Register (or quote registration for) a local marketplace agent in HOL."""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.agent_id == request.agent_id).one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' not found")

        try:
            await run_in_threadpool(hol_check_sidecar_health)
        except HolClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        payload = await _prepare_hol_registration_payload(
            agent,
            endpoint_url_override=request.endpoint_url_override,
            metadata_uri_override=request.metadata_uri_override,
        )
        db.commit()
        db.refresh(agent)
        current = _extract_hol_meta(agent)
        previous_status = str(current.get("registration_status") or "unregistered")

        if request.mode == "register":
            _set_hol_meta(agent, status="pending", uaid=current.get("uaid"), last_error=None)
            db.commit()
            db.refresh(agent)

        try:
            broker_response = hol_register_agent(payload, mode=request.mode)
        except HolClientError as exc:
            error_message = str(exc)
            if request.mode == "register" and _is_hol_insufficient_credits_error(error_message):
                diagnostics: List[str] = []

                try:
                    quote_response = hol_register_agent(payload, mode="quote")
                    diagnostics.append(
                        "quote requiredCredits="
                        f"{quote_response.get('requiredCredits')}, "
                        "availableCredits="
                        f"{quote_response.get('availableCredits')}"
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("HOL quote diagnostic failed", exc_info=True)

                try:
                    balance_payload = hol_get_credit_balance()
                    diagnostics.append(
                        "balance accountId="
                        f"{balance_payload.get('accountId')}, "
                        "balance="
                        f"{balance_payload.get('balance')}"
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("HOL balance diagnostic failed", exc_info=True)

                if diagnostics:
                    error_message = (
                        f"{error_message}. HOL diagnostics: {'; '.join(diagnostics)}"
                    )

            if request.mode == "register":
                next_status = _resolve_hol_error_status(previous_status, error_message)
                _set_hol_meta(
                    agent,
                    status=next_status,
                    uaid=current.get("uaid"),
                    last_error=error_message,
                )
                db.commit()
                db.refresh(agent)
                try:
                    rebuild_agents_cache()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to rebuild agents cache after HOL registration error for %s",
                        agent.agent_id,
                        exc_info=True,
                    )
            raise HTTPException(status_code=502, detail=error_message) from exc

        extracted_uaid = _extract_hol_uaid(broker_response)
        estimated_credits = _extract_estimated_credits(broker_response)

        if request.mode == "register":
            next_status = "registered" if extracted_uaid else "pending"
            _set_hol_meta(
                agent,
                status=next_status,
                uaid=extracted_uaid or current.get("uaid"),
                last_error=None,
            )
            db.commit()
            db.refresh(agent)

            try:
                rebuild_agents_cache()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to rebuild agents cache after HOL registration for %s",
                    agent.agent_id,
                    exc_info=True,
                )

        status_meta = _extract_hol_meta(agent)
        return HolRegisterAgentResponse(
            success=True,
            agent_id=agent.agent_id,
            mode=request.mode,
            hol_registration_status=status_meta["registration_status"],
            hol_uaid=status_meta["uaid"],
            hol_last_error=status_meta["last_error"],
            estimated_credits=estimated_credits,
            broker_response=broker_response,
        )
    finally:
        db.close()


@app.get(
    "/api/hol/register-agent/{agent_id}/status",
    response_model=HolRegisterAgentStatusResponse,
)
async def hol_register_agent_status(agent_id: str) -> HolRegisterAgentStatusResponse:
    """Get persisted HOL registration status for a local marketplace agent."""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        hol_meta = _extract_hol_meta(agent)
        return HolRegisterAgentStatusResponse(
            agent_id=agent.agent_id,
            hol_registration_status=hol_meta["registration_status"],
            hol_uaid=hol_meta["uaid"],
            hol_last_error=hol_meta["last_error"],
            updated_at=hol_meta["updated_at"],
        )
    finally:
        db.close()


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get task status and progress for frontend polling."""
    if task_id not in tasks_storage:
        snapshot = load_task_snapshot(task_id)
        if snapshot:
            _sync_task_cache(task_id, snapshot)
        else:
            return {
                "task_id": task_id,
                "status": "not_found",
                "error": "Task not found"
            }

    return tasks_storage[task_id]


@app.post("/api/tasks/{task_id}/approve_verification")
async def approve_verification(task_id: str):
    """Approve verification for a task requiring human review."""
    snapshot = tasks_storage.get(task_id) or load_task_snapshot(task_id)
    if snapshot is None:
        return {
            "success": False,
            "error": "Task not found"
        }
    _sync_task_cache(task_id, snapshot)

    if not snapshot.get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    decision = {
        "approved": True,
        "timestamp": datetime.now().isoformat()
    }
    persist_verification_state(
        task_id,
        pending=False,
        verification_data=None,
        verification_decision=decision,
    )
    _sync_task_cache(task_id, load_task_snapshot(task_id))

    # Update progress
    verification_data = snapshot.get("verification_data", {})
    todo_id = verification_data.get("todo_id", "unknown")

    update_task_progress(task_id, f"verification_{todo_id}", "completed", {
        "message": "✓ Approved by human reviewer",
        "human_approved": True,
        "quality_score": verification_data.get("quality_score", 0)
    })

    return {
        "success": True,
        "message": "Verification approved",
        "task_id": task_id
    }


@app.post("/api/tasks/{task_id}/reject_verification")
async def reject_verification(task_id: str, reason: str = "Rejected by reviewer"):
    """Reject verification for a task requiring human review."""
    import logging
    logger = logging.getLogger(__name__)

    snapshot = tasks_storage.get(task_id) or load_task_snapshot(task_id)
    if snapshot is None:
        return {
            "success": False,
            "error": "Task not found"
        }
    _sync_task_cache(task_id, snapshot)

    if not snapshot.get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    decision = {
        "approved": False,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }
    persist_verification_state(
        task_id,
        pending=False,
        verification_data=None,
        verification_decision=decision,
    )
    refreshed_snapshot = load_task_snapshot(task_id) or snapshot
    refreshed_snapshot["status"] = "CANCELLED"
    tasks_storage[task_id] = refreshed_snapshot

    # Update progress
    verification_data = snapshot.get("verification_data", {})
    todo_id = verification_data.get("todo_id", "unknown")

    update_task_progress(task_id, f"verification_{todo_id}", "failed", {
        "message": f"✗ Rejected by human reviewer: {reason}",
        "human_rejected": True,
        "quality_score": verification_data.get("quality_score", 0),
        "rejection_reason": reason
    })

    # Add prominent cancellation card to progress logs
    update_task_progress(task_id, "cancellation", "cancelled", {
        "message": f"🚫 TASK CANCELLED - All execution stopped",
        "reason": reason,
        "cancelled_at": datetime.now().isoformat(),
        "cancelled_by": "user"
    })

    # Log cancellation details
    logger.info(f"[reject_verification] Task {task_id} cancelled by user. Reason: {reason}")

    return {
        "success": True,
        "message": "Verification rejected and task execution cancelled",
        "task_id": task_id,
        "reason": reason
    }


@app.get("/a2a/events", response_model=List[A2AEventResponse])
def list_a2a_events(limit: int = 50) -> List[A2AEventResponse]:
    """Return recent A2A events emitted by the system."""

    session = SessionLocal()
    try:
        capped_limit = max(1, min(limit, 200))
        records = (
            session.query(A2AEvent)
            .order_by(A2AEvent.timestamp.desc(), A2AEvent.id.desc())
            .limit(capped_limit)
            .all()
        )

        responses = []
        for record in records:
            responses.append(
                A2AEventResponse(
                    message_id=record.message_id,
                    protocol=record.protocol,
                    message_type=record.message_type,
                    from_agent=record.from_agent,
                    to_agent=record.to_agent,
                    thread_id=record.thread_id,
                    timestamp=record.timestamp,
                    tags=record.tags or None,
                    body=record.body or {},
                )
            )

        return responses
    finally:
        session.close()


async def run_orchestrator_task(task_id: str, request: TaskRequest):
    """Background task to run the deterministic phase 0 literature workflow."""
    try:
        db = SessionLocal()
        try:
            task = Task(
                id=task_id,
                title=f"Research: {request.description[:50]}...",
                description=request.description,
                status="in_progress",
                created_at=datetime.utcnow(),
                meta={
                    "budget_limit": request.budget_limit,
                    "min_reputation_score": request.min_reputation_score,
                    "verification_mode": request.verification_mode,
                    "capability_requirements": request.capability_requirements,
                    "workflow_type": "phase0_literature_review",
                }
            )
            db.add(task)
            db.commit()
            logger.info(f"Created Task record in database: {task_id}")
        finally:
            db.close()
        initialize_runtime_state(
            task_id,
            request_meta={
                "budget_limit": request.budget_limit,
                "min_reputation_score": request.min_reputation_score,
                "verification_mode": request.verification_mode,
                "capability_requirements": request.capability_requirements,
            },
        )
        _sync_task_cache(task_id, load_task_snapshot(task_id))

        # Update progress - initialization
        update_task_progress(task_id, "initialization", "started", {
            "message": "Starting task execution",
            "description": request.description
        })
        update_task_progress(task_id, "orchestrator_analysis", "running", {
            "message": "Preparing the phase 0 literature-review workflow"
        })
        research_plan = build_research_run_plan(request.description)
        node_lookup = {node.node_id: node for node in research_plan.nodes}
        todo_items = build_phase0_todo_items(request.description)
        todo_result = await create_todo_list(
            task_id,
            [
                {
                    "title": item["title"],
                    "description": item["description"],
                    "assigned_to": item["assigned_to"],
                }
                for item in todo_items
            ],
        )
        todo_list = todo_result["todo_list"]

        result_0 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_0",
            task_name=todo_items[0]["title"],
            task_description=todo_items[0]["description"],
            capability_requirements="problem framing, research question design, scope definition",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters=dict(node_lookup["plan_query"].execution_parameters),
            todo_list=todo_list,
        )
        if not result_0.get("success"):
            raise RuntimeError(result_0.get("error", "Problem framing failed"))
        query_plan = dict(result_0.get("result") or {})

        result_1 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_1",
            task_name=todo_items[1]["title"],
            task_description=todo_items[1]["description"],
            capability_requirements="literature mining, source collection, evidence gathering",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters={
                **dict(node_lookup["gather_evidence"].execution_parameters),
                "query_plan": query_plan,
            },
            todo_list=todo_list,
        )
        if not result_1.get("success"):
            raise RuntimeError(result_1.get("error", "Literature mining failed"))
        gathered_evidence = dict(result_1.get("result") or {})
        curated_sources = _build_phase0_curated_sources(
            gathered_evidence=gathered_evidence,
            execution_parameters=dict(node_lookup["curate_sources"].execution_parameters),
        )

        result_2 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_2",
            task_name=todo_items[2]["title"],
            task_description=todo_items[2]["description"],
            capability_requirements="knowledge synthesis, research summarization, report composition",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters={
                **dict(node_lookup["draft_synthesis"].execution_parameters),
                "query_plan": query_plan,
                "curated_sources": curated_sources,
            },
            todo_list=todo_list,
        )
        if not result_2.get("success"):
            raise RuntimeError(result_2.get("error", "Knowledge synthesis failed"))

        result = {
            "workflow": "problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001",
            "steps": [result_0, result_1, result_2],
            "report": result_2.get("result"),
            "framing": result_0.get("result"),
            "evidence": result_1.get("result"),
        }

        # Update final status
        update_task_progress(task_id, "orchestrator", "completed", {
            "message": "Generated research output successfully",
            "result": redact_sensitive_payload(result),
        })

        snapshot = load_task_snapshot(task_id) or {"task_id": task_id, "status": "completed"}
        snapshot["status"] = "completed"
        snapshot["result"] = result
        tasks_storage[task_id] = snapshot

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "completed"
                task.result = result
                db.commit()
                logger.info(f"Updated Task status to completed: {task_id}")
        finally:
            db.close()

    except Exception as e:
        # Update error status
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        update_task_progress(task_id, "orchestrator", "failed", {
            "error": str(e)
        })
        snapshot = load_task_snapshot(task_id) or {"task_id": task_id}
        snapshot["status"] = "failed"
        snapshot["error"] = str(e)
        tasks_storage[task_id] = snapshot

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "failed"
                task.result = {"error": str(e)}
                db.commit()
                logger.info(f"Updated Task status to failed: {task_id}")
        finally:
            db.close()


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest, background_tasks: BackgroundTasks) -> TaskResponse:
    """
    Execute a task using the orchestrator agent.

    The orchestrator will:
    1. Decompose the task into specialized microtasks
    2. For each microtask: discover agents → authorize payment → execute
    3. Aggregate results from all microtasks
    4. Return complete output

    Args:
        request: Task request with description and optional parameters

    Returns:
        TaskResponse with task ID - execution happens in background
    """
    task_id = str(uuid.uuid4())

    # Initialize task in storage
    tasks_storage[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": [],
        "current_step": "initializing"
    }

    # Run orchestrator in background
    background_tasks.add_task(run_orchestrator_task, task_id, request)

    # Return immediately with task_id
    return TaskResponse(
        task_id=task_id,
        status="processing",
        result={
            "message": "Task started, poll /api/tasks/{task_id} for progress"
        }
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    uvicorn.run("api.main:app", host=host, port=port, reload=True)
