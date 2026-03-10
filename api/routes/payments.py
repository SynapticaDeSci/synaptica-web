"""Active deterministic payment routes for the research-run runtime."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.payments.runtime import (
    get_payment_detail,
    get_payment_events,
    reconcile_payment,
    reconcile_recent_payments,
)

router = APIRouter()


class PaymentDetailResponse(BaseModel):
    """Serialized payment detail."""

    id: str
    task_id: str
    from_agent_id: str
    to_agent_id: str
    amount: float
    currency: str
    status: str
    transaction_id: Optional[str] = None
    authorization_id: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    a2a_thread_id: Optional[str] = None
    payment_mode: Optional[str] = None
    worker_account_id: Optional[str] = None
    verification_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    payment_profile: Optional[Dict[str, Any]] = None
    notification_summary: Dict[str, int] = Field(default_factory=dict)


class PaymentEventResponse(BaseModel):
    """Serialized payment activity timeline."""

    payment: PaymentDetailResponse
    state_transitions: List[Dict[str, Any]] = Field(default_factory=list)
    notifications: List[Dict[str, Any]] = Field(default_factory=list)
    a2a_events: List[Dict[str, Any]] = Field(default_factory=list)
    reconciliations: List[Dict[str, Any]] = Field(default_factory=list)


class PaymentReconcileRequest(BaseModel):
    """Request payload for payment reconciliation."""

    payment_id: Optional[str] = None
    repair: bool = True
    limit: int = Field(default=25, ge=1, le=100)


class PaymentReconcileResponse(BaseModel):
    """Response payload for payment reconciliation."""

    reconciliations: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/reconcile", response_model=PaymentReconcileResponse)
async def reconcile_payments_route(request: PaymentReconcileRequest) -> PaymentReconcileResponse:
    """Reconcile one payment or a bounded set of recent payments."""

    if request.payment_id:
        payload = reconcile_payment(request.payment_id, repair=request.repair)
        if payload is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        return PaymentReconcileResponse(reconciliations=[payload])

    return PaymentReconcileResponse(
        reconciliations=reconcile_recent_payments(limit=request.limit, repair=request.repair)
    )


@router.get("/{payment_id}", response_model=PaymentDetailResponse)
async def get_payment_route(payment_id: str) -> PaymentDetailResponse:
    """Return payment detail plus notification/profile summary."""

    payload = get_payment_detail(payment_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentDetailResponse.model_validate(payload)


@router.get("/{payment_id}/events", response_model=PaymentEventResponse)
async def get_payment_events_route(payment_id: str) -> PaymentEventResponse:
    """Return transitions, terminal notifications, and A2A events for a payment."""

    payload = get_payment_events(payment_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentEventResponse.model_validate(payload)
