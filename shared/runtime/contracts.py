"""Typed contracts for the live phase 0 runtime."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class SupportTier(str, Enum):
    """Support tier assigned to an agent."""

    SUPPORTED = "supported"
    EXPERIMENTAL = "experimental"
    LEGACY = "legacy"


class PaymentMode(str, Enum):
    """Explicit payment execution modes."""

    MANAGED = "managed"
    DEV_ENV = "dev_env"
    OFFLINE = "offline"


class PaymentAction(str, Enum):
    """Payment lifecycle actions tracked for idempotency."""

    PROPOSAL = "proposal"
    AUTHORIZE = "authorize"
    RELEASE = "release"
    REFUND = "refund"


class HandoffContext(BaseModel):
    """Context shared across negotiator, executor, verifier, and payment steps."""

    model_config = ConfigDict(use_enum_values=True)

    task_id: str
    todo_id: str
    attempt_id: str
    research_run_id: Optional[str] = None
    node_id: Optional[str] = None
    payment_id: Optional[str] = None
    agent_id: Optional[str] = None
    budget_remaining: Optional[float] = None
    verification_mode: str = "standard"
    idempotency_key: Optional[str] = None


class TelemetryEnvelope(BaseModel):
    """Typed progress/telemetry event persisted with the task."""

    model_config = ConfigDict(use_enum_values=True)

    task_id: str
    step: str
    status: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    handoff_context: Optional[HandoffContext] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class AgentSelectionResult(BaseModel):
    """Structured result from the negotiator step."""

    model_config = ConfigDict(use_enum_values=True)

    success: bool
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    description: Optional[str] = None
    endpoint_url: Optional[str] = None
    hedera_account_id: Optional[str] = None
    pricing: Dict[str, Any] = Field(default_factory=dict)
    support_tier: SupportTier = SupportTier.EXPERIMENTAL
    payment_id: Optional[str] = None
    payment_thread_id: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    handoff_context: Optional[HandoffContext] = None


class ExecutionRequest(BaseModel):
    """Typed request for executor dispatch."""

    agent_id: str
    task_description: str
    context: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    handoff_context: HandoffContext


class ExecutionResult(BaseModel):
    """Typed response from the executor step."""

    success: bool
    agent_id: str
    result: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    handoff_context: Optional[HandoffContext] = None


class VerificationRequest(BaseModel):
    """Typed request for verification."""

    task_id: str
    payment_id: str
    task_result: Dict[str, Any]
    verification_criteria: Dict[str, Any] = Field(default_factory=dict)
    verification_mode: str = "standard"
    handoff_context: HandoffContext


class VerificationResult(BaseModel):
    """Typed verification outcome."""

    success: bool
    verification_passed: bool
    overall_score: float = 0.0
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    feedback: str = ""
    decision: str = "review_required"
    error: Optional[str] = None
    handoff_context: Optional[HandoffContext] = None


class PaymentActionContext(BaseModel):
    """Context used for payment mutations and idempotency."""

    payment_id: Optional[str] = None
    task_id: str
    todo_id: str
    attempt_id: str
    action: PaymentAction
    idempotency_key: str
    mode: PaymentMode
    thread_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
