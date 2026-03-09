"""Payment settlement tools for the phase 0 verifier/runtime."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, Optional, cast

from shared.hedera import get_hedera_client, hedera_account_to_evm_address
from shared.payments.service import (
    build_idempotency_key,
    coerce_payment_mode,
    get_payment_mode,
    run_idempotent_payment_action,
)
from shared.protocols import (
    PaymentRequest,
    PaymentStatus,
    X402Payment,
    build_payment_refund_message,
    build_payment_release_message,
    new_thread_id,
    publish_message,
)
from shared.database import SessionLocal, Payment
from shared.database.models import PaymentStatus as DBPaymentStatus
from shared.runtime import PaymentAction, PaymentActionContext, PaymentMode


def _build_action_context(
    *,
    payment_id: str,
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
        payload["idempotency_key"] = payload.get("idempotency_key") or build_idempotency_key(
            task_id,
            payload.get("todo_id", "todo_0"),
            payload.get("attempt_id", "attempt_0"),
            action,
        )
        payload["mode"] = mode.value
        return PaymentActionContext.model_validate(payload)
    return PaymentActionContext(
        payment_id=payment_id,
        task_id=task_id,
        todo_id="todo_0",
        attempt_id="attempt_0",
        action=action,
        idempotency_key=build_idempotency_key(task_id, "todo_0", "attempt_0", action),
        mode=mode,
    )


def _build_receipt(
    *,
    payment_id: str,
    payment_row: Any,
    metadata: Dict[str, Any],
    terminal_status: PaymentStatus,
    mode: PaymentMode,
) -> Any:
    if mode == PaymentMode.OFFLINE:
        return SimpleNamespace(
            transaction_id=f"offline-{uuid.uuid4().hex[:12]}",
            status=terminal_status,
            timestamp=datetime.utcnow().isoformat(),
            metadata={"mode": mode.value},
        )

    payment_request = PaymentRequest(
        payment_id=payment_id,
        from_account=os.getenv("HEDERA_ACCOUNT_ID", ""),
        to_account=metadata.get("worker_address", metadata.get("to_hedera_account", "")),
        amount=Decimal(str(payment_row.amount)),
        description=metadata.get("description", ""),
        metadata=metadata,
    )
    hedera_client = get_hedera_client()
    x402 = X402Payment(hedera_client)
    if terminal_status == PaymentStatus.COMPLETED:
        return x402.release_payment(cast(str, payment_row.authorization_id), payment_request)
    return x402.approve_refund(payment_request)


async def release_payment(
    payment_id: str,
    verification_notes: str = "",
    action_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Release an authorized payment after successful verification."""

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
        action=PaymentAction.RELEASE,
        action_context=action_context,
    )

    async def _runner(db: Any) -> Dict[str, Any]:
        payment = db.query(Payment).filter(Payment.id == payment_id).one()
        payment_row: Any = payment
        if payment_row.status != DBPaymentStatus.AUTHORIZED:
            raise ValueError(
                f"Payment not authorized. Current status: {payment_row.status.value}"
            )

        metadata = dict(cast(Dict[str, Any], payment_row.meta or {}))
        worker_address = metadata.get("worker_address") or hedera_account_to_evm_address(
            metadata.get("to_hedera_account", "")
        )
        metadata["worker_address"] = worker_address
        thread_id = metadata.get("a2a_thread_id") or new_thread_id(str(payment_row.task_id), payment_id)
        verifier_agent_id = metadata.get("verifier_agent_id") or os.getenv("VERIFIER_AGENT_ID", "verifier-agent")

        mode = coerce_payment_mode(context.mode)
        receipt = _build_receipt(
            payment_id=payment_id,
            payment_row=payment_row,
            metadata=metadata,
            terminal_status=PaymentStatus.COMPLETED,
            mode=mode,
        )
        if hasattr(receipt, "__await__"):
            receipt = await receipt

        payment_row.status = DBPaymentStatus(receipt.status.value)
        payment_row.transaction_id = receipt.transaction_id
        payment_row.completed_at = datetime.utcnow()

        updated_metadata = dict(metadata)
        updated_metadata["verification_notes"] = verification_notes
        updated_metadata["receipt"] = {
            "transaction_id": receipt.transaction_id,
            "timestamp": receipt.timestamp,
            "details": receipt.metadata,
        }
        updated_metadata["payment_mode"] = mode.value

        release_message = build_payment_release_message(
            payment_id=payment_id,
            task_id=str(payment_row.task_id),
            amount=Decimal(str(payment_row.amount)),
            currency=str(payment_row.currency),
            from_agent=str(verifier_agent_id),
            to_agent=str(payment_row.from_agent_id),
            transaction_id=receipt.transaction_id,
            status=payment_row.status.value,
            verification_notes=verification_notes,
            thread_id=thread_id,
        )
        messages = dict(cast(Dict[str, Any], updated_metadata.get("a2a_messages") or {}))
        messages[release_message.type] = release_message.to_dict()
        updated_metadata["a2a_thread_id"] = thread_id
        updated_metadata["a2a_messages"] = messages
        updated_metadata.setdefault("verifier_agent_id", verifier_agent_id)
        payment_row.meta = updated_metadata

        publish_message(release_message, tags=("payment", "released"), session=db)

        return {
            "success": True,
            "payment_id": payment_id,
            "transaction_id": receipt.transaction_id,
            "status": payment_row.status.value,
            "amount": payment_row.amount,
            "currency": payment_row.currency,
            "mode": mode.value,
            "message": "Payment released successfully",
            "a2a": {
                "thread_id": thread_id,
                "release_message": release_message.to_dict(),
            },
        }

    return await run_idempotent_payment_action(
        payment_id=payment_id,
        context=context,
        runner=_runner,
    )


async def reject_and_refund(
    payment_id: str,
    rejection_reason: str,
    action_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Reject task results and refund the payment."""

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
        action=PaymentAction.REFUND,
        action_context=action_context,
    )

    async def _runner(db: Any) -> Dict[str, Any]:
        payment = db.query(Payment).filter(Payment.id == payment_id).one()
        payment_row: Any = payment
        metadata = dict(cast(Dict[str, Any], payment_row.meta or {}))
        worker_address = metadata.get("worker_address") or hedera_account_to_evm_address(
            metadata.get("to_hedera_account", "")
        )
        metadata["worker_address"] = worker_address
        thread_id = metadata.get("a2a_thread_id") or new_thread_id(str(payment_row.task_id), payment_id)
        verifier_agent_id = metadata.get("verifier_agent_id") or os.getenv("VERIFIER_AGENT_ID", "verifier-agent")

        mode = coerce_payment_mode(context.mode)
        receipt = _build_receipt(
            payment_id=payment_id,
            payment_row=payment_row,
            metadata=metadata,
            terminal_status=PaymentStatus.REFUNDED,
            mode=mode,
        )
        if hasattr(receipt, "__await__"):
            receipt = await receipt

        payment_row.status = DBPaymentStatus(receipt.status.value)
        payment_row.transaction_id = receipt.transaction_id
        payment_row.completed_at = datetime.utcnow()

        updated_metadata = dict(metadata)
        updated_metadata["rejection_reason"] = rejection_reason
        updated_metadata["rejected_at"] = datetime.utcnow().isoformat()
        updated_metadata["refund_receipt"] = {
            "transaction_id": receipt.transaction_id,
            "timestamp": receipt.timestamp,
            "details": receipt.metadata,
        }
        updated_metadata["payment_mode"] = mode.value

        refund_message = build_payment_refund_message(
            payment_id=payment_id,
            task_id=str(payment_row.task_id),
            amount=Decimal(str(payment_row.amount)),
            currency=str(payment_row.currency),
            from_agent=str(verifier_agent_id),
            to_agent=str(payment_row.from_agent_id),
            transaction_id=receipt.transaction_id,
            status=payment_row.status.value,
            rejection_reason=rejection_reason,
            thread_id=thread_id,
        )
        messages = dict(cast(Dict[str, Any], updated_metadata.get("a2a_messages") or {}))
        messages[refund_message.type] = refund_message.to_dict()
        updated_metadata["a2a_thread_id"] = thread_id
        updated_metadata["a2a_messages"] = messages
        updated_metadata.setdefault("verifier_agent_id", verifier_agent_id)
        payment_row.meta = updated_metadata

        publish_message(refund_message, tags=("payment", "refunded"), session=db)

        return {
            "success": receipt.status == PaymentStatus.REFUNDED,
            "payment_id": payment_id,
            "status": payment_row.status.value,
            "rejection_reason": rejection_reason,
            "mode": mode.value,
            "message": "Refund approved on-chain" if receipt.status == PaymentStatus.REFUNDED else "Refund approval recorded",
            "a2a": {
                "thread_id": thread_id,
                "refund_message": refund_message.to_dict(),
            },
        }

    return await run_idempotent_payment_action(
        payment_id=payment_id,
        context=context,
        runner=_runner,
    )
