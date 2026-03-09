"""Payment helpers for explicit payment modes and idempotent state transitions."""

from __future__ import annotations

import inspect
import os
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.database import SessionLocal
from shared.database.models import Payment, PaymentStatus, PaymentStateTransition
from shared.runtime import (
    PaymentAction,
    PaymentActionContext,
    PaymentMode,
    SensitivePayloadError,
    assert_no_sensitive_payload,
    redact_sensitive_payload,
)

T = TypeVar("T")

NON_TERMINAL_ACTIONS = {PaymentAction.PROPOSAL, PaymentAction.AUTHORIZE}
TERMINAL_ACTION_TO_STATUS = {
    PaymentAction.RELEASE: PaymentStatus.COMPLETED,
    PaymentAction.REFUND: PaymentStatus.REFUNDED,
}


class PaymentModeError(RuntimeError):
    """Raised when payment mode/configuration is invalid."""


class PaymentConflictError(RuntimeError):
    """Raised when a duplicate or conflicting payment transition is attempted."""


def _completed_transition_result(
    transition: Optional[PaymentStateTransition],
) -> Optional[Dict[str, Any]]:
    """Return the stored result for a completed transition, if available."""

    if transition and transition.state == "completed" and isinstance(transition.result, dict):
        return transition.result
    return None


def get_payment_mode() -> PaymentMode:
    """Return the explicit payment mode, preserving X402_OFFLINE compatibility."""

    configured = os.getenv("PAYMENT_MODE", "").strip().lower()
    if not configured and os.getenv("X402_OFFLINE", "").strip():
        configured = PaymentMode.OFFLINE.value
    if not configured:
        configured = PaymentMode.MANAGED.value
    return PaymentMode(configured)


def coerce_payment_mode(mode: PaymentMode | str) -> PaymentMode:
    """Normalize enum-or-string payment modes."""

    if isinstance(mode, PaymentMode):
        return mode
    return PaymentMode(mode)


def coerce_payment_action(action: PaymentAction | str) -> PaymentAction:
    """Normalize enum-or-string payment actions."""

    if isinstance(action, PaymentAction):
        return action
    return PaymentAction(action)


def build_idempotency_key(
    task_id: str,
    todo_id: str,
    attempt_id: str,
    action: PaymentAction | str,
) -> str:
    """Build the shared idempotency key format used across payment actions."""

    action = coerce_payment_action(action)
    return f"{task_id}:{todo_id}:{attempt_id}:{action.value}"


def validate_payment_mode(mode: PaymentMode | str) -> None:
    """Validate that the configured payment mode has the required config."""

    mode = coerce_payment_mode(mode)
    if mode == PaymentMode.OFFLINE:
        return

    required_env = [
        "TASK_ESCROW_ADDRESS",
        "TASK_ESCROW_MARKETPLACE_TREASURY",
        "TASK_ESCROW_OPERATOR_PRIVATE_KEY",
    ]
    missing = [name for name in required_env if not os.getenv(name)]
    if missing:
        raise PaymentModeError(
            f"Payment mode '{mode.value}' requires missing environment variables: {', '.join(missing)}"
        )


def ensure_payment_action_context(context: PaymentActionContext) -> None:
    """Reject unsafe metadata before it reaches persistence or logs."""

    assert_no_sensitive_payload(context.model_dump(mode="json"))


def get_existing_transition(
    db: Session,
    *,
    payment_id: str,
    action: PaymentAction | str,
    idempotency_key: str,
) -> Optional[PaymentStateTransition]:
    """Fetch an existing state transition for the action/idempotency key."""

    action = coerce_payment_action(action)
    return (
        db.query(PaymentStateTransition)
        .filter(PaymentStateTransition.payment_id == payment_id)
        .filter(PaymentStateTransition.action == action.value)
        .filter(PaymentStateTransition.idempotency_key == idempotency_key)
        .one_or_none()
    )


def get_existing_transition_by_task(
    db: Session,
    *,
    task_id: str,
    action: PaymentAction | str,
    idempotency_key: str,
) -> Optional[PaymentStateTransition]:
    """Fetch an existing transition by task/action/idempotency key."""

    action = coerce_payment_action(action)
    return (
        db.query(PaymentStateTransition)
        .filter(PaymentStateTransition.task_id == task_id)
        .filter(PaymentStateTransition.action == action.value)
        .filter(PaymentStateTransition.idempotency_key == idempotency_key)
        .order_by(PaymentStateTransition.id.desc())
        .one_or_none()
    )


def get_completed_transition_result(
    db: Session,
    *,
    payment_id: str,
    action: PaymentAction | str,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the completed transition result for a payment/action/idempotency key."""

    transition = get_existing_transition(
        db,
        payment_id=payment_id,
        action=action,
        idempotency_key=idempotency_key,
    )
    return _completed_transition_result(transition)


def get_completed_transition_result_by_task(
    db: Session,
    *,
    task_id: str,
    action: PaymentAction | str,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the completed transition result for a task/action/idempotency key."""

    transition = get_existing_transition_by_task(
        db,
        task_id=task_id,
        action=action,
        idempotency_key=idempotency_key,
    )
    return _completed_transition_result(transition)


def record_transition(
    db: Session,
    *,
    payment_id: str,
    task_id: str,
    action: PaymentAction | str,
    idempotency_key: str,
    state: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> PaymentStateTransition:
    """Persist a payment state transition."""

    action = coerce_payment_action(action)
    payload = redact_sensitive_payload(result or {})
    transition = get_existing_transition(
        db,
        payment_id=payment_id,
        action=action,
        idempotency_key=idempotency_key,
    )
    if transition is None:
        transition = PaymentStateTransition(
            payment_id=payment_id,
            task_id=task_id,
            action=action.value,
            idempotency_key=idempotency_key,
            state=state,
            result=payload,
            error=error,
        )
        db.add(transition)
    else:
        transition.state = state
        transition.result = payload
        transition.error = error
    db.flush()
    return transition


def ensure_no_terminal_conflict(
    db: Session,
    payment: Payment,
    action: PaymentAction | str,
) -> None:
    """Reject duplicate conflicting terminal settlement actions."""

    action = coerce_payment_action(action)
    current_status = payment.status
    if action in NON_TERMINAL_ACTIONS:
        return

    expected_status = TERMINAL_ACTION_TO_STATUS[action]
    if current_status in {PaymentStatus.COMPLETED, PaymentStatus.REFUNDED} and current_status != expected_status:
        raise PaymentConflictError(
            f"Payment {payment.id} already reached terminal status '{current_status.value}'"
        )


async def run_idempotent_payment_action(
    *,
    payment_id: str,
    context: PaymentActionContext,
    runner: Callable[[Session], T | Awaitable[T]],
) -> T:
    """Run a payment mutation once for a given idempotency key."""

    context.action = coerce_payment_action(context.action)
    context.mode = coerce_payment_mode(context.mode)
    ensure_payment_action_context(context)
    validate_payment_mode(context.mode)

    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is None:
            raise PaymentConflictError(f"Payment {payment_id} not found")

        existing_result = get_completed_transition_result(
            db,
            payment_id=payment_id,
            action=context.action,
            idempotency_key=context.idempotency_key,
        )
        if existing_result is not None:
            return existing_result  # type: ignore[return-value]

        ensure_no_terminal_conflict(db, payment, context.action)

        result = runner(db)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise PaymentConflictError("Payment runner must return a serializable dict result")

        record_transition(
            db,
            payment_id=payment_id,
            task_id=context.task_id,
            action=context.action,
            idempotency_key=context.idempotency_key,
            state="completed",
            result=result,
        )
        db.commit()
        return result  # type: ignore[return-value]
    except IntegrityError:
        db.rollback()
        existing_result = get_completed_transition_result(
            db,
            payment_id=payment_id,
            action=context.action,
            idempotency_key=context.idempotency_key,
        )
        if existing_result is not None:
            return existing_result  # type: ignore[return-value]
        raise
    except Exception as exc:
        db.rollback()
        payment = db.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is not None:
            record_transition(
                db,
                payment_id=payment_id,
                task_id=context.task_id,
                action=context.action,
                idempotency_key=context.idempotency_key,
                state="failed",
                error=str(exc),
            )
            db.commit()
        raise
    finally:
        db.close()
