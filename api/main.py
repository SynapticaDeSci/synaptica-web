"""FastAPI main application - Orchestrator Agent Entry Point."""

import asyncio
import ipaddress
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shared.agents_cache import rebuild_agents_cache
from shared.database import Agent, AgentReputation, Base, SessionLocal, engine
from shared.database.models import A2AEvent, Task
from shared.payments.runtime import sync_verified_payment_profile
from shared.research.agent_inventory import iter_supported_builtin_research_agents
from shared.research.catalog import (
    build_phase0_todo_items,
    default_research_endpoint,
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
    HolClientError,
    register_agent as hol_register_agent,
    search_agents as hol_search_agents,
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
            "endpoint_url": "/api/data-agent/datasets",
            "health_check_url": "/health",
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
                "endpoint_url": default_research_endpoint(agent_id),
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


def _coerce_pricing_rate(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return False
    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Basic guard against obvious non-public host labels.
        return "." in hostname

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_hol_endpoint_url(
    endpoint_url: Optional[str],
    *,
    endpoint_url_override: Optional[str] = None,
) -> str:
    raw_value = (endpoint_url_override or endpoint_url or "").strip()
    if not raw_value:
        raise HTTPException(status_code=400, detail="Agent endpoint URL is required for HOL registration")

    if _is_public_http_url(raw_value):
        return raw_value

    public_base_url = (os.getenv("HOL_PUBLIC_BASE_URL") or "").strip()
    if not public_base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Agent endpoint URL is not publicly reachable. "
                "Set HOL_PUBLIC_BASE_URL or provide endpoint_url_override."
            ),
        )
    if not _is_public_http_url(public_base_url):
        raise HTTPException(
            status_code=400,
            detail="HOL_PUBLIC_BASE_URL must be a public http(s) URL.",
        )

    parsed = urlparse(raw_value)
    if parsed.scheme in {"http", "https"}:
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
    else:
        path = raw_value if raw_value.startswith("/") else f"/{raw_value}"

    normalized_base = public_base_url.rstrip("/") + "/"
    resolved = urljoin(normalized_base, path.lstrip("/"))
    if not _is_public_http_url(resolved):
        raise HTTPException(
            status_code=400,
            detail="Resolved HOL endpoint URL is not publicly reachable.",
        )
    return resolved


def _resolve_optional_hol_url(value: Any, *, base_url: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    if _is_public_http_url(cleaned):
        return cleaned
    normalized_base = base_url.rstrip("/") + "/"
    candidate = urljoin(normalized_base, cleaned.lstrip("/"))
    if _is_public_http_url(candidate):
        return candidate
    return None


async def _ensure_data_agent_metadata_for_hol(agent: Agent, *, db: Any) -> None:
    if agent.agent_type != "data":
        return

    meta = dict(agent.meta or {})
    existing_metadata_uri = agent.erc8004_metadata_uri or meta.get("metadata_gateway_url")
    if existing_metadata_uri:
        return

    resolved_endpoint_url = _resolve_hol_endpoint_url(meta.get("endpoint_url"))
    pricing = dict(meta.get("pricing") or {})
    categories = meta.get("categories") or []
    parsed_categories = [
        str(category).strip()
        for category in categories
        if isinstance(category, str) and str(category).strip()
    ]
    capabilities = [
        str(capability).strip()
        for capability in (agent.capabilities or [])
        if isinstance(capability, str) and str(capability).strip()
    ]

    metadata_payload = AgentMetadataPayload(
        agent_id=agent.agent_id,
        name=agent.name,
        description=str(agent.description or "").strip() or agent.name,
        endpoint_url=resolved_endpoint_url,
        capabilities=capabilities,
        pricing_rate=_coerce_pricing_rate(pricing.get("rate") or pricing.get("base_rate")),
        pricing_currency=str(pricing.get("currency") or "HBAR"),
        pricing_rate_type=str(pricing.get("rate_type") or "per_task"),
        categories=parsed_categories or ["Data", "Storage"],
        contact_email=meta.get("contact_email"),
        logo_url=meta.get("logo_url"),
        health_check_url=_resolve_optional_hol_url(meta.get("health_check_url"), base_url=resolved_endpoint_url),
        hedera_account=agent.hedera_account_id,
    )
    metadata_document = build_agent_metadata_payload(metadata_payload)

    try:
        upload_result = await publish_agent_metadata(agent.agent_id, metadata_document)
    except PinataCredentialsError as exc:
        raise HTTPException(
            status_code=500,
            detail="Pinata credentials missing; configure PINATA_API_KEY and PINATA_SECRET_KEY.",
        ) from exc
    except PinataUploadError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    updated_meta = dict(meta)
    updated_meta["metadata_cid"] = upload_result.cid
    updated_meta["metadata_gateway_url"] = upload_result.gateway_url
    agent.meta = updated_meta
    agent.erc8004_metadata_uri = upload_result.ipfs_uri
    db.add(agent)


def _build_hol_registration_payload(
    agent: Agent,
    *,
    endpoint_url_override: Optional[str] = None,
    metadata_uri_override: Optional[str] = None,
) -> Dict[str, Any]:
    meta = dict(agent.meta or {})
    pricing = dict(meta.get("pricing") or {})
    categories = meta.get("categories") or []
    endpoint_url = _resolve_hol_endpoint_url(
        str(meta.get("endpoint_url") or "").strip(),
        endpoint_url_override=endpoint_url_override,
    )
    metadata_uri = (
        (metadata_uri_override or "").strip()
        or agent.erc8004_metadata_uri
        or meta.get("metadata_gateway_url")
    )

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

    health_check_url = _resolve_optional_hol_url(meta.get("health_check_url"), base_url=endpoint_url)
    if health_check_url:
        profile["aiAgent"]["health_check_url"] = health_check_url
    if agent.hedera_account_id:
        profile["owner"] = {"account_id": agent.hedera_account_id}

    return {
        # HOL /register expects this HCS-11 profile envelope.
        "profile": profile,
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


class HolAgentsSearchResponse(BaseModel):
    """Response model for HOL agent search."""

    agents: List[HolAgentRecord]
    query: str


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
) -> HolAgentsSearchResponse:
    """
    Search HOL Registry Broker for agents, exposed for the Agent Marketplace UI.

    Currently supports a simple text query and limit. More advanced filtering
    (by registry, transports, or capabilities) can be layered on top of this.
    """
    query = q.strip()
    capped_limit = max(1, min(limit, 25))

    agents = hol_search_agents(query=query, limit=capped_limit)

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
            )
        )

    return HolAgentsSearchResponse(agents=records, query=query)


@app.post("/api/hol/register-agent", response_model=HolRegisterAgentResponse)
async def hol_register_local_agent(request: HolRegisterAgentRequest) -> HolRegisterAgentResponse:
    """Register (or quote registration for) a local marketplace agent in HOL."""
    db = SessionLocal()
    trace_id = uuid.uuid4().hex[:8]
    try:
        agent = db.query(Agent).filter(Agent.agent_id == request.agent_id).one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' not found")

        if agent.agent_type == "data" and not (request.metadata_uri_override or "").strip():
            await _ensure_data_agent_metadata_for_hol(agent, db=db)
            db.commit()
            db.refresh(agent)
            try:
                rebuild_agents_cache()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to rebuild agents cache after metadata auto-publish for %s",
                    agent.agent_id,
                    exc_info=True,
                )

        payload = _build_hol_registration_payload(
            agent,
            endpoint_url_override=request.endpoint_url_override,
            metadata_uri_override=request.metadata_uri_override,
        )
        logger.info(
            "hol_register[%s] start agent_id=%s mode=%s type=%s endpoint=%s metadata_uri=%s",
            trace_id,
            agent.agent_id,
            request.mode,
            agent.agent_type or "unknown",
            payload.get("endpoint_url"),
            payload.get("metadata_uri"),
        )
        current = _extract_hol_meta(agent)
        previous_status = str(current.get("registration_status") or "unregistered")

        if request.mode == "register":
            _set_hol_meta(agent, status="pending", uaid=current.get("uaid"), last_error=None)
            db.commit()
            db.refresh(agent)

        try:
            broker_response = hol_register_agent(payload, mode=request.mode)
        except HolClientError as exc:
            logger.warning(
                "hol_register[%s] broker error agent_id=%s mode=%s detail=%s",
                trace_id,
                agent.agent_id,
                request.mode,
                str(exc),
            )
            if request.mode == "register":
                next_status = _resolve_hol_error_status(previous_status, str(exc))
                _set_hol_meta(
                    agent,
                    status=next_status,
                    uaid=current.get("uaid"),
                    last_error=str(exc),
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
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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
        logger.info(
            "hol_register[%s] success agent_id=%s mode=%s status=%s uaid=%s broker_keys=%s",
            trace_id,
            agent.agent_id,
            request.mode,
            status_meta["registration_status"],
            status_meta["uaid"],
            sorted(list((broker_response or {}).keys())),
        )
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
