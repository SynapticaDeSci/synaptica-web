"""Agent management routes for the marketplace and onboarding flow."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.database import Agent, AgentReputation, SessionLocal, get_db
from shared.agent_utils import serialize_agent
from shared.agents_cache import (
    build_agents_payload,
    get_cached_agents_payload,
    rebuild_agents_cache,
)
from shared.registry_sync import (
    ensure_registry_cache as _ensure_registry_cache,
    get_registry_sync_status,
    trigger_registry_cache_refresh,
)
from shared.metadata import (
    AgentMetadataPayload,
    PinataCredentialsError,
    PinataUploadError,
    build_agent_metadata_payload,
    publish_agent_metadata,
)
from shared.payments.runtime import verify_agent_payment_profile
from shared.registry import (
    AgentRegistryConfigError,
    AgentRegistryRegistrationError,
    get_registry_client,
)

router = APIRouter()

# Maintain backwards compatibility for callers/tests that patch ensure_registry_cache directly.
ensure_registry_cache = _ensure_registry_cache

logger = logging.getLogger(__name__)
AUDIT_LOGGER = logging.getLogger("agent_registration")

AGENT_ID_PATTERN = re.compile(r"^[a-z0-9-]{3,50}$")
HEDERA_ACCOUNT_PATTERN = re.compile(r"^(0\.0\.\d+|0x[a-fA-F0-9]{40})$")
ALLOW_INSECURE_ENDPOINTS = os.getenv("AGENT_SUBMIT_ALLOW_HTTP", "1").lower() in {"1", "true", "yes"}


class AgentPricing(BaseModel):
    """Pricing information for an agent."""

    rate: float = Field(..., ge=0)
    currency: str = Field("HBAR", min_length=1, max_length=10)
    rate_type: str = Field("per_task", min_length=3, max_length=32)


class AgentResponse(BaseModel):
    """Shape of agent responses for the marketplace."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    description: Optional[str] = None
    capabilities: List[str]
    categories: List[str]
    status: str
    endpoint_url: Optional[str] = None
    health_check_url: Optional[str] = None
    pricing: AgentPricing
    contact_email: Optional[str] = None
    logo_url: Optional[str] = None
    erc8004_metadata_uri: Optional[str] = None
    metadata_cid: Optional[str] = None
    metadata_gateway_url: Optional[str] = None
    hedera_account_id: Optional[str] = None
    created_at: Optional[str] = None
    reputation_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    registry_status: Optional[str] = None
    registry_agent_id: Optional[int] = None
    registry_tx_hash: Optional[str] = None
    registry_last_error: Optional[str] = None
    registry_updated_at: Optional[str] = None
    support_tier: str


class AgentsListResponse(BaseModel):
    """List response for agents."""

    total: int
    agents: List[AgentResponse]
    sync_status: Optional[str] = None
    synced_at: Optional[str] = None


class AgentSubmissionRequest(BaseModel):
    """Payload for registering a new agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=1_000)
    capabilities: List[str] = Field(..., min_length=1)
    categories: Optional[List[str]] = None
    endpoint_url: str
    health_check_url: Optional[str] = None
    base_rate: float = Field(..., gt=0)
    currency: str = Field("HBAR", min_length=1, max_length=10)
    rate_type: str = Field("per_task", min_length=3, max_length=32)
    hedera_account: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[EmailStr] = None

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: str) -> str:
        """Ensure agent_id is a slug as required."""
        if not AGENT_ID_PATTERN.match(value):
            raise ValueError(
                "agent_id must be 3-50 characters of lowercase letters, numbers, or dashes"
            )
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: List[str]) -> List[str]:
        """Ensure capability list is sane and trimmed."""
        cleaned = [cap.strip() for cap in value if cap.strip()]
        if not cleaned:
            raise ValueError("At least one capability is required")
        return cleaned

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: Optional[List[str]]) -> List[str]:
        """Normalize categories list."""
        if not value:
            return []
        return [item.strip() for item in value if item.strip()]

    @field_validator("endpoint_url", "health_check_url")
    @classmethod
    def validate_endpoint(cls, value: Optional[str], _info) -> Optional[str]:
        """Ensure endpoints use HTTPS unless explicitly allowed."""
        if value is None:
            return value
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if (not value.startswith("https://")) and not ALLOW_INSECURE_ENDPOINTS:
            raise ValueError("URL must use HTTPS")
        return value

    @field_validator("hedera_account")
    @classmethod
    def validate_hedera_account(cls, value: Optional[str]) -> Optional[str]:
        """Validate Hedera account formatting."""
        if value is None or value.strip() == "":
            return None
        if not HEDERA_ACCOUNT_PATTERN.match(value.strip()):
            raise ValueError("Hedera account must match 0.0.x or 0x followed by 40 hex characters")
        return value.strip()

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: Optional[str]) -> Optional[str]:
        """Basic validation for logo URL."""
        if value is None:
            return value
        if not value.startswith(("http://", "https://")):
            raise ValueError("Logo URL must start with http:// or https://")
        return value


class AgentSubmissionResponse(AgentResponse):
    """Extended response for agent creation."""

    metadata_gateway_url: Optional[str] = None
    metadata_cid: Optional[str] = None
    operator_checklist: List[str]
    message: str


class PaymentProfileVerifyRequest(BaseModel):
    """Optional override payload for verifying a payment profile."""

    hedera_account_id: Optional[str] = None


class PaymentProfileVerifyResponse(BaseModel):
    """Serialized payment profile verification result."""

    success: bool
    agent_id: str
    hedera_account_id: str
    status: str
    verification_method: Optional[str] = None
    verified_at: Optional[str] = None
    last_error: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


def _require_admin_token(provided: Optional[str]) -> None:
    """Enforce optional admin header."""
    required = os.getenv("AGENT_SUBMIT_ADMIN_TOKEN")
    if not required:
        return
    if provided != required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )


@router.post("/{agent_id}/payment-profile/verify", response_model=PaymentProfileVerifyResponse)
async def verify_payment_profile_route(
    agent_id: str,
    request: PaymentProfileVerifyRequest,
) -> PaymentProfileVerifyResponse:
    """Verify and persist an agent payment profile against the registered account."""

    try:
        payload = verify_agent_payment_profile(
            agent_id=agent_id,
            hedera_account_id=request.hedera_account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return PaymentProfileVerifyResponse.model_validate(payload)


def _set_registry_status(
    agent: Agent,
    *,
    status: str,
    agent_id: Optional[int] = None,
    tx_hash: Optional[str] = None,
    metadata_uri: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Persist registry status metadata on the agent."""

    meta: Dict[str, Any] = dict(agent.meta or {})
    registry_meta: Dict[str, Any] = dict(meta.get("registry") or {})
    registry_meta["status"] = status
    registry_meta["updated_at"] = datetime.utcnow().isoformat()
    if agent_id is not None:
        registry_meta["agent_id"] = agent_id
    if tx_hash is not None:
        registry_meta["tx_hash"] = tx_hash
    if metadata_uri is not None:
        registry_meta["metadata_uri"] = metadata_uri
    registry_meta["last_error"] = error
    meta["registry"] = registry_meta
    agent.meta = meta


def _trigger_registry_registration(agent_id: str) -> None:
    """Background task entrypoint for on-chain registration."""

    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).one_or_none()
        if not agent:
            logger.warning("Registry trigger skipped; agent %s not found", agent_id)
            return

        meta: Dict[str, Any] = agent.meta or {}
        metadata_uri = agent.erc8004_metadata_uri or meta.get("metadata_gateway_url")
        if not metadata_uri:
            _set_registry_status(
                agent,
                status="failed",
                error="Missing metadata URI for on-chain registration",
            )
            db.commit()
            return

        registry_meta = meta.get("registry") or {}
        registry_agent_id = registry_meta.get("agent_id")
        try:
            registry_agent_id = int(registry_agent_id) if registry_agent_id is not None else None
        except (TypeError, ValueError):
            registry_agent_id = None

        try:
            client = get_registry_client()
            result = client.register_agent(
                agent.agent_id,
                metadata_uri=metadata_uri,
                registry_agent_id=registry_agent_id,
            )
            _set_registry_status(
                agent,
                status=result.status,
                agent_id=result.agent_id,
                tx_hash=result.tx_hash,
                metadata_uri=result.metadata_uri,
                error=None,
            )
            db.commit()
        except (AgentRegistryConfigError, AgentRegistryRegistrationError) as exc:
            logger.warning("Agent %s registry registration failed: %s", agent_id, exc)
            _set_registry_status(agent, status="failed", error=str(exc))
            db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error while registering agent %s", agent_id)
            _set_registry_status(agent, status="failed", error="Unexpected error; see API logs")
            db.commit()
    finally:
        db.close()


@router.get("/", response_model=AgentsListResponse)
async def list_agents() -> AgentsListResponse:
    """List all registered agents."""
    sync_status = "unknown"
    synced_at = None
    try:
        if trigger_registry_cache_refresh():
            logger.debug("Background registry sync triggered for stale cache")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to trigger registry sync: %s", exc)

    status_value, synced_dt = get_registry_sync_status()
    sync_status = status_value
    if synced_dt:
        synced_at = synced_dt.isoformat()

    payload = get_cached_agents_payload()
    if payload is None:
        try:
            payload = rebuild_agents_cache(synced_at=synced_dt)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to rebuild agents cache on demand; falling back to live query")
            payload = build_agents_payload()
        if synced_dt and not payload.get("synced_at"):
            payload["synced_at"] = synced_dt.isoformat()

    payload_synced_at = payload.get("synced_at") or synced_at
    agents_payload = payload.get("agents", [])
    responses = [AgentResponse(**item) for item in agents_payload]

    return AgentsListResponse(
        total=payload.get("total", len(responses)),
        agents=responses,
        sync_status=sync_status,
        synced_at=payload_synced_at,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, db: Session = Depends(get_db)) -> AgentResponse:
    """Retrieve a single agent."""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    reputation = (
        db.query(AgentReputation)
        .filter(AgentReputation.agent_id == agent_id)
        .one_or_none()
    )
    score = reputation.reputation_score if reputation else None
    return AgentResponse(**serialize_agent(agent, score))


@router.post("/", response_model=AgentSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    payload: AgentSubmissionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> AgentSubmissionResponse:
    """Register a new HTTP agent and publish its metadata."""
    _require_admin_token(x_admin_token)

    existing = db.query(Agent).filter(Agent.agent_id == payload.agent_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent '{payload.agent_id}' already exists",
        )

    meta: Dict[str, Any] = {
        "endpoint_url": payload.endpoint_url,
        "health_check_url": payload.health_check_url,
        "pricing": {
            "rate": payload.base_rate,
            "currency": payload.currency,
            "rate_type": payload.rate_type,
        },
        "categories": payload.categories or [],
        "contact_email": payload.contact_email,
        "logo_url": payload.logo_url,
        "support_tier": "supported",
    }

    agent = Agent(  # type: ignore[call-arg]
        agent_id=payload.agent_id,
        name=payload.name,
        agent_type="http",
        description=payload.description,
        capabilities=payload.capabilities,
        hedera_account_id=payload.hedera_account,
        status="active",
        meta=meta,
    )

    reputation = AgentReputation(
        agent_id=payload.agent_id,
        reputation_score=0.5,
        total_tasks=0,
        successful_tasks=0,
        failed_tasks=0,
        payment_multiplier=1.0,
    )

    db.add(agent)
    db.add(reputation)

    try:
        db.flush()
    except IntegrityError as exc:  # pragma: no cover - defensive
        db.rollback()
        logger.exception("Integrity error while registering agent %s", payload.agent_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    metadata_payload = AgentMetadataPayload(
        agent_id=payload.agent_id,
        name=payload.name,
        description=payload.description,
        endpoint_url=payload.endpoint_url,
        capabilities=payload.capabilities,
        pricing_rate=payload.base_rate,
        pricing_currency=payload.currency,
        pricing_rate_type=payload.rate_type,
        categories=payload.categories,
        contact_email=payload.contact_email,
        logo_url=payload.logo_url,
        health_check_url=payload.health_check_url,
        hedera_account=payload.hedera_account,
    )
    metadata = build_agent_metadata_payload(metadata_payload)

    try:
        upload_result = await publish_agent_metadata(payload.agent_id, metadata)
    except PinataCredentialsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pinata credentials missing; configure PINATA_API_KEY and PINATA_SECRET_KEY.",
        ) from exc
    except PinataUploadError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    agent.erc8004_metadata_uri = upload_result.ipfs_uri
    updated_meta = dict(meta)
    updated_meta["metadata_cid"] = upload_result.cid
    updated_meta["metadata_gateway_url"] = upload_result.gateway_url
    agent.meta = updated_meta

    _set_registry_status(
        agent,
        status="pending",
        metadata_uri=agent.erc8004_metadata_uri,
        error=None,
    )

    db.commit()
    db.refresh(agent)

    background_tasks.add_task(_trigger_registry_registration, agent.agent_id)

    response = serialize_agent(agent, reputation_score=reputation.reputation_score)
    operator_checklist = [
        "Review metadata JSON via provided gateway link.",
        "Registry registration is running in the background; monitor `registry_status`/`registry_last_error`.",
        "Verify endpoint responds to orchestrator/executor probes.",
    ]

    payload_summary = {
        "agent_id": payload.agent_id,
        "endpoint_url": payload.endpoint_url,
        "metadata_cid": upload_result.cid,
        "metadata_gateway_url": upload_result.gateway_url,
        "hedera_account": payload.hedera_account,
    }
    AUDIT_LOGGER.info("agent_registration", extra={"payload": payload_summary})

    try:
        rebuild_agents_cache()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to rebuild agents cache after registering %s", agent.agent_id, exc_info=True)

    response_payload = {
        **response,
        "metadata_gateway_url": upload_result.gateway_url,
        "metadata_cid": upload_result.cid,
        "operator_checklist": operator_checklist,
        "message": "Agent registered successfully.",
    }
    return AgentSubmissionResponse(**response_payload)
