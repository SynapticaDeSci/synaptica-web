"""x402 payment tools for the phase 0 negotiator/runtime."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, cast

from shared.hedera import get_hedera_client, hedera_account_to_evm_address
from shared.payments.service import (
    PaymentModeError,
    build_idempotency_key,
    coerce_payment_mode,
    get_existing_transition_by_task,
    get_payment_mode,
    record_transition,
    run_idempotent_payment_action,
    validate_payment_mode,
)
from shared.protocols import (
    PaymentRequest,
    X402Payment,
    build_payment_authorized_message,
    build_payment_proposal_message,
    new_thread_id,
    publish_message,
)
from shared.database import SessionLocal, Payment
from shared.database.models import PaymentStatus as DBPaymentStatus
from shared.runtime import PaymentAction, PaymentActionContext, PaymentMode, assert_no_sensitive_payload

logger = logging.getLogger(__name__)


def _normalize_verifier_addresses() -> tuple[List[str], Optional[str]]:
    verifier_addresses: List[str] = []
    default_verifiers = os.getenv("TASK_ESCROW_DEFAULT_VERIFIERS", "").strip()
    marketplace_treasury = os.getenv("TASK_ESCROW_MARKETPLACE_TREASURY", "").strip()

    for addr in (item.strip() for item in default_verifiers.split(",") if item.strip()):
        verifier_addresses.append(hedera_account_to_evm_address(addr))

    treasury_address: Optional[str] = None
    if marketplace_treasury:
        treasury_address = hedera_account_to_evm_address(marketplace_treasury)

    if not verifier_addresses and treasury_address:
        verifier_addresses.append(treasury_address)
    return verifier_addresses, treasury_address


def _build_action_context(
    *,
    payment_id: Optional[str],
    task_id: str,
    action: PaymentAction,
    action_context: Optional[Dict[str, Any]],
) -> PaymentActionContext:
    mode = get_payment_mode()
    if action_context:
        payload = dict(action_context)
        payload["payment_id"] = payment_id
        payload["task_id"] = task_id
        payload["action"] = action.value
        payload["idempotency_key"] = build_idempotency_key(
            task_id,
            payload.get("todo_id", "todo_0"),
            payload.get("attempt_id", "attempt_0"),
            action,
        )
        payload["mode"] = mode.value
        context = PaymentActionContext.model_validate(payload)
    else:
        context = PaymentActionContext(
            payment_id=payment_id,
            task_id=task_id,
            todo_id="todo_0",
            attempt_id="attempt_0",
            action=action,
            idempotency_key=build_idempotency_key(task_id, "todo_0", "attempt_0", action),
            mode=mode,
        )
    assert_no_sensitive_payload(context.model_dump(mode="json"))
    return context


async def create_payment_request(
    task_id: str,
    from_agent_id: str,
    to_agent_id: str,
    to_hedera_account: str,
    amount: float,
    description: str = "",
    action_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a payment proposal and persist the initial transition."""

    context = _build_action_context(
        payment_id=None,
        task_id=task_id,
        action=PaymentAction.PROPOSAL,
        action_context=action_context,
    )

    db = SessionLocal()
    try:
        existing = get_existing_transition_by_task(
            db,
            task_id=task_id,
            action=PaymentAction.PROPOSAL,
            idempotency_key=context.idempotency_key,
        )
        if existing and isinstance(existing.result, dict):
            return cast(Dict[str, Any], existing.result)

        from_account = os.getenv("HEDERA_ACCOUNT_ID", "").strip()
        mode = coerce_payment_mode(context.mode)
        validate_payment_mode(mode)
        if mode != PaymentMode.OFFLINE and not from_account:
            raise PaymentModeError("Missing HEDERA_ACCOUNT_ID for non-offline payment mode")

        if not to_hedera_account or not to_hedera_account.strip():
            raise ValueError("Payee Hedera account is required")

        worker_address = hedera_account_to_evm_address(to_hedera_account)
        verifier_addresses, treasury_address = _normalize_verifier_addresses()
        approvals_required = int(os.getenv("TASK_ESCROW_DEFAULT_APPROVALS", "1") or 1)
        if approvals_required > len(verifier_addresses) and verifier_addresses:
            approvals_required = len(verifier_addresses)

        payment_id = str(uuid.uuid4())
        thread_id = new_thread_id(task_id, payment_id)

        metadata: Dict[str, Any] = {
            "task_id": task_id,
            "description": description,
            "to_hedera_account": to_hedera_account,
            "worker_account_id": to_hedera_account,
            "worker_address": worker_address,
            "verifier_addresses": verifier_addresses,
            "approvals_required": approvals_required,
            "marketplace_fee_bps": int(os.getenv("TASK_ESCROW_MARKETPLACE_FEE_BPS", "0") or 0),
            "verifier_fee_bps": int(os.getenv("TASK_ESCROW_VERIFIER_FEE_BPS", "0") or 0),
            "a2a_thread_id": thread_id,
            "payment_mode": mode.value,
            "support_tier": "supported",
            "proposal_idempotency_key": context.idempotency_key,
            "attempt_id": context.attempt_id,
            "todo_id": context.todo_id,
        }
        if treasury_address:
            metadata["marketplace_treasury"] = treasury_address

        proposal_message = build_payment_proposal_message(
            payment_id=payment_id,
            task_id=task_id,
            amount=Decimal(str(amount)),
            currency="HBAR",
            from_agent=from_agent_id,
            to_agent=to_agent_id,
            verifier_addresses=verifier_addresses,
            approvals_required=approvals_required or 1,
            marketplace_fee_bps=metadata["marketplace_fee_bps"],
            verifier_fee_bps=metadata["verifier_fee_bps"],
            thread_id=thread_id,
        )
        metadata["a2a_messages"] = {proposal_message.type: proposal_message.to_dict()}

        payment = Payment(  # type: ignore[call-arg]
            id=payment_id,
            task_id=task_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            amount=amount,
            currency="HBAR",
            status=DBPaymentStatus.PENDING,
            meta=metadata,
        )
        db.add(payment)
        db.flush()

        result = {
            "success": True,
            "payment_id": payment_id,
            "task_id": task_id,
            "from_agent": from_agent_id,
            "to_agent": to_agent_id,
            "amount": amount,
            "currency": "HBAR",
            "status": "pending",
            "description": description,
            "mode": mode.value,
            "a2a": {
                "thread_id": thread_id,
                "proposal_message": proposal_message.to_dict(),
            },
        }

        record_transition(
            db,
            payment_id=payment_id,
            task_id=task_id,
            action=PaymentAction.PROPOSAL,
            idempotency_key=context.idempotency_key,
            state="completed",
            result=result,
        )

        publish_message(proposal_message, tags=("payment", "proposal"), session=db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def authorize_payment(
    payment_id: str,
    action_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Authorize a payment proposal using explicit payment modes and idempotency."""

    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if payment is None:
            raise ValueError(f"Payment {payment_id} not found")
        task_id = str(payment.task_id)
    finally:
        db.close()

    context = _build_action_context(
        payment_id=payment_id,
        task_id=task_id,
        action=PaymentAction.AUTHORIZE,
        action_context=action_context,
    )

    async def _runner(db: Any) -> Dict[str, Any]:
        payment = db.query(Payment).filter(Payment.id == payment_id).one()
        payment_row: Any = payment
        metadata = dict(cast(Dict[str, Any], payment_row.meta or {}))
        thread_id = metadata.get("a2a_thread_id") or new_thread_id(str(payment_row.task_id), payment_id)

        worker_address = metadata.get("worker_address") or hedera_account_to_evm_address(
            metadata.get("to_hedera_account", "")
        )
        metadata["worker_address"] = worker_address

        payment_request = PaymentRequest(
            payment_id=payment_id,
            from_account=os.getenv("HEDERA_ACCOUNT_ID", ""),
            to_account=worker_address,
            amount=Decimal(str(payment_row.amount)),
            description=metadata.get("description", ""),
            metadata=metadata,
        )

        mode = coerce_payment_mode(context.mode)
        if mode == PaymentMode.OFFLINE:
            auth_id = f"offline-{uuid.uuid4().hex[:12]}"
        else:
            hedera_client = get_hedera_client()
            x402 = X402Payment(hedera_client)
            auth_id = await x402.authorize_payment(payment_request)

        payment_row.authorization_id = auth_id
        payment_row.transaction_id = auth_id
        payment_row.status = DBPaymentStatus.AUTHORIZED
        metadata["payment_mode"] = mode.value

        authorized_message = build_payment_authorized_message(
            payment_id=payment_id,
            task_id=str(payment_row.task_id),
            amount=Decimal(str(payment_row.amount)),
            currency=str(payment_row.currency),
            from_agent=str(payment_row.from_agent_id),
            to_agent=str(payment_row.to_agent_id),
            transaction_id=auth_id,
            thread_id=thread_id,
        )
        messages = dict(cast(Dict[str, Any], metadata.get("a2a_messages") or {}))
        messages[authorized_message.type] = authorized_message.to_dict()
        metadata["a2a_thread_id"] = thread_id
        metadata["a2a_messages"] = messages
        payment_row.meta = metadata

        publish_message(authorized_message, tags=("payment", "authorized"), session=db)

        return {
            "success": True,
            "payment_id": payment_id,
            "authorization_id": auth_id,
            "status": "authorized",
            "mode": mode.value,
            "message": "Payment authorized. Waiting for verification to release funds.",
            "a2a": {
                "thread_id": thread_id,
                "authorized_message": authorized_message.to_dict(),
            },
        }

    return await run_idempotent_payment_action(
        payment_id=payment_id,
        context=context,
        runner=_runner,
    )


async def get_payment_status(payment_id: str) -> Dict[str, Any]:
    """Get the current payment status and transition metadata."""

    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        payment_row: Any = payment
        metadata = dict(cast(Dict[str, Any], payment_row.meta or {}))
        completed_at_value = payment_row.completed_at

        return {
            "payment_id": str(payment_row.id),
            "task_id": str(payment_row.task_id),
            "status": payment_row.status.value,
            "amount": float(payment_row.amount),
            "currency": str(payment_row.currency),
            "transaction_id": payment_row.transaction_id,
            "authorization_id": payment_row.authorization_id,
            "created_at": payment_row.created_at.isoformat(),
            "completed_at": completed_at_value.isoformat() if completed_at_value else None,
            "a2a": {
                "thread_id": metadata.get("a2a_thread_id"),
                "messages": metadata.get("a2a_messages", {}),
            },
            "mode": metadata.get("payment_mode", get_payment_mode().value),
        }
    finally:
        db.close()
