"""Runtime helpers for payment profiles, notifications, and reconciliation."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

from sqlalchemy.orm import Session

from shared.database import (
    A2AEvent,
    Agent,
    AgentPaymentProfile,
    Payment,
    PaymentNotification,
    PaymentReconciliation,
    PaymentStateTransition,
    SessionLocal,
)
from shared.database.models import PaymentStatus as DBPaymentStatus
from shared.protocols import (
    build_payment_refund_message,
    build_payment_release_message,
    publish_message,
)

HEDERA_ACCOUNT_PATTERN = re.compile(r"^(0\.0\.\d+|0x[a-fA-F0-9]{40})$")


def is_valid_hedera_account_id(value: str | None) -> bool:
    """Return True when the value matches the accepted Hedera account formats."""

    if not value:
        return False
    return bool(HEDERA_ACCOUNT_PATTERN.match(value.strip()))


def upsert_agent_payment_profile(
    session: Session,
    *,
    agent_id: str,
    hedera_account_id: str,
    status: str,
    verification_method: str,
    last_error: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> AgentPaymentProfile:
    """Create or update a payment profile row for an agent."""

    profile = (
        session.query(AgentPaymentProfile)
        .filter(AgentPaymentProfile.agent_id == agent_id)
        .one_or_none()
    )
    now = datetime.utcnow()
    if profile is None:
        profile = AgentPaymentProfile(  # type: ignore[call-arg]
            agent_id=agent_id,
            hedera_account_id=hedera_account_id,
            status=status,
            verification_method=verification_method,
            verified_at=now if status == "verified" else None,
            last_error=last_error,
            meta=metadata or {},
        )
        session.add(profile)
    else:
        profile.hedera_account_id = hedera_account_id
        profile.status = status
        profile.verification_method = verification_method
        profile.verified_at = now if status == "verified" else None
        profile.last_error = last_error
        profile.meta = {**dict(profile.meta or {}), **(metadata or {})}
    session.flush()
    return profile


def sync_verified_payment_profile(
    session: Session,
    *,
    agent: Agent,
    verification_method: str,
) -> AgentPaymentProfile | None:
    """Persist a verified profile for a trusted agent record when possible."""

    hedera_account_id = str(agent.hedera_account_id or "").strip()
    if not is_valid_hedera_account_id(hedera_account_id):
        return None

    return upsert_agent_payment_profile(
        session,
        agent_id=agent.agent_id,
        hedera_account_id=hedera_account_id,
        status="verified",
        verification_method=verification_method,
        last_error=None,
        metadata={"source": verification_method},
    )


def verify_agent_payment_profile(
    *,
    agent_id: str,
    hedera_account_id: str | None = None,
    verification_method: str = "api_verify",
) -> Dict[str, Any]:
    """Verify and persist an agent payment profile against the registered agent record."""

    session = SessionLocal()
    try:
        agent = session.query(Agent).filter(Agent.agent_id == agent_id).one_or_none()
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' not found")

        registered_account = str(agent.hedera_account_id or "").strip()
        candidate = str(hedera_account_id or registered_account).strip()

        if not candidate:
            profile = upsert_agent_payment_profile(
                session,
                agent_id=agent_id,
                hedera_account_id=registered_account or "",
                status="failed",
                verification_method=verification_method,
                last_error="Agent does not have a registered Hedera account",
                metadata={"registered_account": registered_account or None},
            )
            session.commit()
            return serialize_payment_profile(profile, success=False)

        if not is_valid_hedera_account_id(candidate):
            profile = upsert_agent_payment_profile(
                session,
                agent_id=agent_id,
                hedera_account_id=candidate,
                status="failed",
                verification_method=verification_method,
                last_error="Hedera account format is invalid",
                metadata={"registered_account": registered_account or None},
            )
            session.commit()
            return serialize_payment_profile(profile, success=False)

        if registered_account != candidate:
            profile = upsert_agent_payment_profile(
                session,
                agent_id=agent_id,
                hedera_account_id=candidate,
                status="failed",
                verification_method=verification_method,
                last_error="Hedera account does not match the registered agent account",
                metadata={"registered_account": registered_account or None},
            )
            session.commit()
            return serialize_payment_profile(profile, success=False)

        profile = upsert_agent_payment_profile(
            session,
            agent_id=agent_id,
            hedera_account_id=candidate,
            status="verified",
            verification_method=verification_method,
            metadata={"registered_account": registered_account},
        )
        session.commit()
        return serialize_payment_profile(profile, success=True)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_verified_payment_profile(
    session: Session,
    *,
    agent_id: str,
    hedera_account_id: str | None,
) -> AgentPaymentProfile:
    """Ensure a supported agent has a verified payment profile that matches the payee account."""

    profile = (
        session.query(AgentPaymentProfile)
        .filter(AgentPaymentProfile.agent_id == agent_id)
        .one_or_none()
    )
    if profile is None:
        raise ValueError(f"Agent '{agent_id}' is missing a verified payment profile")
    if profile.status != "verified":
        raise ValueError(f"Agent '{agent_id}' does not have a verified payment profile")

    expected_account = str(hedera_account_id or "").strip()
    if expected_account and str(profile.hedera_account_id or "").strip() != expected_account:
        raise ValueError(
            f"Agent '{agent_id}' payment profile does not match Hedera account '{expected_account}'"
        )
    return profile


def serialize_payment_profile(profile: AgentPaymentProfile, *, success: bool) -> Dict[str, Any]:
    """Serialize a payment profile verification result."""

    return {
        "success": success,
        "agent_id": profile.agent_id,
        "hedera_account_id": profile.hedera_account_id,
        "status": profile.status,
        "verification_method": profile.verification_method,
        "verified_at": profile.verified_at.isoformat() if profile.verified_at else None,
        "last_error": profile.last_error,
        "meta": profile.meta or {},
    }


def _notification_role_for_recipient(payment: Payment, recipient_agent_id: str) -> str:
    if recipient_agent_id == payment.from_agent_id:
        return "payer"
    if recipient_agent_id == payment.to_agent_id:
        return "payee"
    return "observer"


def _store_payment_notification(
    session: Session,
    *,
    payment: Payment,
    message: Any,
    notification_type: str,
) -> PaymentNotification:
    existing = (
        session.query(PaymentNotification)
        .filter(PaymentNotification.message_id == message.id)
        .one_or_none()
    )
    payload = message.to_dict()
    delivered_at = datetime.fromisoformat(message.timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
    if existing is None:
        notification = PaymentNotification(  # type: ignore[call-arg]
            payment_id=payment.id,
            task_id=payment.task_id,
            message_id=message.id,
            notification_type=notification_type,
            recipient_agent_id=message.to_agent,
            recipient_role=_notification_role_for_recipient(payment, message.to_agent),
            status="delivered",
            thread_id=message.thid,
            delivered_at=delivered_at,
            payload=payload,
            meta={},
        )
        session.add(notification)
        session.flush()
        return notification

    existing.notification_type = notification_type
    existing.recipient_agent_id = message.to_agent
    existing.recipient_role = _notification_role_for_recipient(payment, message.to_agent)
    existing.status = "delivered"
    existing.thread_id = message.thid
    existing.delivered_at = delivered_at
    existing.payload = payload
    session.flush()
    return existing


def emit_terminal_payment_notifications(
    session: Session,
    *,
    payment: Payment,
    verifier_agent_id: str,
    thread_id: str,
    terminal_action: str,
    transaction_id: str | None,
    verification_notes: str | None = None,
    rejection_reason: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Emit and persist one terminal notification to the payer and one to the payee."""

    notification_type = (
        "payment/released" if terminal_action == "release" else "payment/refunded"
    )
    message_builder = build_payment_release_message if terminal_action == "release" else build_payment_refund_message
    messages: Dict[str, Dict[str, Any]] = {}

    for recipient_role, recipient_agent_id in (
        ("payer", str(payment.from_agent_id)),
        ("payee", str(payment.to_agent_id)),
    ):
        if terminal_action == "release":
            message = message_builder(
                payment_id=str(payment.id),
                task_id=str(payment.task_id),
                amount=Decimal(str(payment.amount)),
                currency=str(payment.currency),
                from_agent=verifier_agent_id,
                to_agent=recipient_agent_id,
                transaction_id=transaction_id or "",
                status=str(payment.status.value),
                verification_notes=verification_notes,
                thread_id=thread_id,
            )
        else:
            message = message_builder(
                payment_id=str(payment.id),
                task_id=str(payment.task_id),
                amount=Decimal(str(payment.amount)),
                currency=str(payment.currency),
                from_agent=verifier_agent_id,
                to_agent=recipient_agent_id,
                transaction_id=transaction_id,
                status=str(payment.status.value),
                rejection_reason=rejection_reason or "Rejected",
                thread_id=thread_id,
            )

        publish_message(message, tags=("payment", terminal_action, recipient_role), session=session)
        _store_payment_notification(
            session,
            payment=payment,
            message=message,
            notification_type=notification_type,
        )
        messages[recipient_role] = message.to_dict()

    return messages


def serialize_payment_detail(payment: Payment) -> Dict[str, Any]:
    """Serialize a payment row for the active payment API."""

    meta = dict(cast(Dict[str, Any], payment.meta or {}))
    return {
        "id": payment.id,
        "task_id": payment.task_id,
        "from_agent_id": payment.from_agent_id,
        "to_agent_id": payment.to_agent_id,
        "amount": float(payment.amount),
        "currency": payment.currency,
        "status": payment.status.value,
        "transaction_id": payment.transaction_id,
        "authorization_id": payment.authorization_id,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "completed_at": payment.completed_at.isoformat() if payment.completed_at else None,
        "a2a_thread_id": meta.get("a2a_thread_id"),
        "payment_mode": meta.get("payment_mode"),
        "worker_account_id": meta.get("worker_account_id") or meta.get("to_hedera_account"),
        "verification_notes": meta.get("verification_notes"),
        "rejection_reason": meta.get("rejection_reason"),
    }


def get_payment_detail(payment_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a serialized payment detail payload."""

    session = SessionLocal()
    try:
        payment = session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is None:
            return None
        profile = (
            session.query(AgentPaymentProfile)
            .filter(AgentPaymentProfile.agent_id == payment.to_agent_id)
            .one_or_none()
        )
        payload = serialize_payment_detail(payment)
        payload["payment_profile"] = (
            serialize_payment_profile(profile, success=profile.status == "verified")
            if profile is not None
            else None
        )
        payload["notification_summary"] = {
            "count": len(payment.notifications),
            "reconciliations": len(payment.reconciliations),
        }
        return payload
    finally:
        session.close()


def _serialize_state_transition(transition: PaymentStateTransition) -> Dict[str, Any]:
    return {
        "id": transition.id,
        "action": transition.action,
        "idempotency_key": transition.idempotency_key,
        "state": transition.state,
        "result": transition.result,
        "error": transition.error,
        "created_at": transition.created_at.isoformat() if transition.created_at else None,
    }


def _serialize_payment_notification(notification: PaymentNotification) -> Dict[str, Any]:
    return {
        "id": notification.id,
        "payment_id": notification.payment_id,
        "task_id": notification.task_id,
        "message_id": notification.message_id,
        "notification_type": notification.notification_type,
        "recipient_agent_id": notification.recipient_agent_id,
        "recipient_role": notification.recipient_role,
        "status": notification.status,
        "thread_id": notification.thread_id,
        "delivered_at": notification.delivered_at.isoformat() if notification.delivered_at else None,
        "last_error": notification.last_error,
        "payload": notification.payload,
    }


def _serialize_a2a_event(event: A2AEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "message_id": event.message_id,
        "protocol": event.protocol,
        "message_type": event.message_type,
        "from_agent": event.from_agent,
        "to_agent": event.to_agent,
        "thread_id": event.thread_id,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "tags": event.tags or [],
        "body": event.body or {},
    }


def _serialize_payment_reconciliation(reconciliation: PaymentReconciliation) -> Dict[str, Any]:
    return {
        "id": reconciliation.id,
        "payment_id": reconciliation.payment_id,
        "task_id": reconciliation.task_id,
        "status": reconciliation.status,
        "mismatch_count": reconciliation.mismatch_count,
        "details": reconciliation.details or {},
        "created_at": reconciliation.created_at.isoformat() if reconciliation.created_at else None,
        "resolved_at": reconciliation.resolved_at.isoformat() if reconciliation.resolved_at else None,
    }


def get_payment_events(payment_id: str) -> Optional[Dict[str, Any]]:
    """Return transitions, notifications, and A2A events for a payment."""

    session = SessionLocal()
    try:
        payment = session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is None:
            return None
        thread_id = str((payment.meta or {}).get("a2a_thread_id") or "")
        a2a_events = (
            session.query(A2AEvent)
            .filter(A2AEvent.thread_id == thread_id)
            .order_by(A2AEvent.timestamp.asc(), A2AEvent.id.asc())
            .all()
            if thread_id
            else []
        )
        return {
            "payment": serialize_payment_detail(payment),
            "state_transitions": [
                _serialize_state_transition(item)
                for item in sorted(payment.state_transitions, key=lambda entry: entry.id)
            ],
            "notifications": [
                _serialize_payment_notification(item)
                for item in sorted(payment.notifications, key=lambda entry: entry.id)
            ],
            "a2a_events": [_serialize_a2a_event(item) for item in a2a_events],
            "reconciliations": [
                _serialize_payment_reconciliation(item)
                for item in sorted(payment.reconciliations, key=lambda entry: entry.id)
            ],
        }
    finally:
        session.close()


def _expected_terminal_notification_type(payment: Payment) -> str | None:
    if payment.status == DBPaymentStatus.COMPLETED:
        return "payment/released"
    if payment.status == DBPaymentStatus.REFUNDED:
        return "payment/refunded"
    return None


def _rebuild_notification_from_event(
    session: Session,
    *,
    payment: Payment,
    event: A2AEvent,
) -> PaymentNotification:
    notification = PaymentNotification(  # type: ignore[call-arg]
        payment_id=payment.id,
        task_id=payment.task_id,
        message_id=event.message_id,
        notification_type=event.message_type,
        recipient_agent_id=event.to_agent,
        recipient_role=_notification_role_for_recipient(payment, event.to_agent),
        status="delivered",
        thread_id=event.thread_id,
        delivered_at=event.timestamp,
        payload=event.body,
        meta={"repaired_from_a2a_event": True},
    )
    session.add(notification)
    session.flush()
    return notification


def reconcile_payment(payment_id: str, *, repair: bool = True) -> Optional[Dict[str, Any]]:
    """Reconcile one payment row against transitions and terminal notifications."""

    session = SessionLocal()
    try:
        payment = session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is None:
            return None

        terminal_notification_type = _expected_terminal_notification_type(payment)
        issues: List[str] = []
        repaired_notifications: List[str] = []
        thread_id = str((payment.meta or {}).get("a2a_thread_id") or "")
        a2a_events: Sequence[A2AEvent] = (
            session.query(A2AEvent)
            .filter(A2AEvent.thread_id == thread_id)
            .order_by(A2AEvent.timestamp.asc(), A2AEvent.id.asc())
            .all()
            if thread_id
            else []
        )

        if payment.status == DBPaymentStatus.COMPLETED and not any(
            transition.action == "release" and transition.state == "completed"
            for transition in payment.state_transitions
        ):
            issues.append("Terminal payment is missing a completed release transition.")
        if payment.status == DBPaymentStatus.REFUNDED and not any(
            transition.action == "refund" and transition.state == "completed"
            for transition in payment.state_transitions
        ):
            issues.append("Refunded payment is missing a completed refund transition.")

        if terminal_notification_type:
            existing_by_recipient = {
                (item.recipient_agent_id, item.notification_type): item
                for item in payment.notifications
            }
            for recipient_agent_id in (payment.from_agent_id, payment.to_agent_id):
                key = (recipient_agent_id, terminal_notification_type)
                if key in existing_by_recipient:
                    continue

                matching_event = next(
                    (
                        event
                        for event in a2a_events
                        if event.message_type == terminal_notification_type
                        and event.to_agent == recipient_agent_id
                    ),
                    None,
                )
                if repair and matching_event is not None:
                    _rebuild_notification_from_event(session, payment=payment, event=matching_event)
                    repaired_notifications.append(recipient_agent_id)
                    continue
                issues.append(
                    f"Missing terminal notification for recipient '{recipient_agent_id}'."
                )
        elif payment.notifications:
            issues.append("Non-terminal payment has terminal notifications persisted.")

        if issues and repaired_notifications:
            status = "manual_review"
        elif issues:
            status = "mismatch"
        elif repaired_notifications:
            status = "repaired"
        else:
            status = "matched"

        reconciliation = PaymentReconciliation(  # type: ignore[call-arg]
            payment_id=payment.id,
            task_id=payment.task_id,
            status=status,
            mismatch_count=len(issues),
            details={
                "issues": issues,
                "repaired_notifications": repaired_notifications,
                "expected_terminal_notification_type": terminal_notification_type,
            },
            resolved_at=datetime.utcnow() if status in {"matched", "repaired"} else None,
        )
        session.add(reconciliation)
        session.commit()
        return _serialize_payment_reconciliation(reconciliation)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reconcile_recent_payments(*, limit: int = 25, repair: bool = True) -> List[Dict[str, Any]]:
    """Reconcile recent unresolved payments."""

    session = SessionLocal()
    try:
        payments = (
            session.query(Payment)
            .order_by(Payment.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        payment_ids = [payment.id for payment in payments]
    finally:
        session.close()

    reconciled: List[Dict[str, Any]] = []
    for payment_id in payment_ids:
        payload = reconcile_payment(payment_id, repair=repair)
        if payload is not None:
            reconciled.append(payload)
    return reconciled


__all__ = [
    "emit_terminal_payment_notifications",
    "get_payment_detail",
    "get_payment_events",
    "is_valid_hedera_account_id",
    "reconcile_payment",
    "reconcile_recent_payments",
    "require_verified_payment_profile",
    "serialize_payment_profile",
    "sync_verified_payment_profile",
    "verify_agent_payment_profile",
]
