"""Credits management: Stripe checkout + Hedera HBAR transfer."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.database import SessionLocal, UserCredits, StripeTransaction
from shared.hedera.client import HEDERA_SDK_AVAILABLE

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_USER_ID = "default"
DEFAULT_CREDITS = 50

# credits -> price in cents
CREDIT_TIERS: Dict[int, int] = {
    10: 100,
    50: 400,
    100: 700,
    500: 3000,
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _stripe_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key or key.startswith("sk_test_YOUR"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured — set STRIPE_SECRET_KEY in .env",
        )
    return key


def _webhook_secret() -> str:
    s = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not s or s.startswith("whsec_YOUR"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret not configured",
        )
    return s


# ── GET /balance ─────────────────────────────────────────────────────────────

class BalanceResponse(BaseModel):
    user_id: str
    balance: int


@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    user_id: str = DEFAULT_USER_ID,
    db: Session = Depends(get_db),
) -> BalanceResponse:
    row = db.query(UserCredits).filter(UserCredits.user_id == user_id).one_or_none()
    if row is None:
        row = UserCredits(user_id=user_id, balance=DEFAULT_CREDITS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return BalanceResponse(user_id=row.user_id, balance=row.balance)


# ── POST /checkout ────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    credits: int
    user_id: str = DEFAULT_USER_ID


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(body: CheckoutRequest, db: Session = Depends(get_db)) -> CheckoutResponse:
    stripe.api_key = _stripe_key()

    price_cents = CREDIT_TIERS.get(body.credits)
    if price_cents is None:
        raise HTTPException(status_code=400, detail=f"Invalid credit tier: {body.credits}. Valid: {list(CREDIT_TIERS)}")

    success_url = os.environ.get("STRIPE_SUCCESS_URL", "http://localhost:3000/?payment=success")
    cancel_url = os.environ.get("STRIPE_CANCEL_URL", "http://localhost:3000/")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{body.credits} Synaptica Credits"},
                "unit_amount": price_cents,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": body.user_id,
            "credits": str(body.credits),
        },
    )

    return CheckoutResponse(checkout_url=session.url)


# ── POST /webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    stripe.api_key = _stripe_key()
    secret = _webhook_secret()

    # Must read raw bytes BEFORE any JSON parsing or signature check fails
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature or "",
            secret=secret,
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as exc:
        logger.error("Webhook payload error: %s", exc)
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    if event["type"] != "checkout.session.completed":
        return {"received": True}

    session_obj = event["data"]["object"]
    session_id = session_obj["id"]
    metadata = session_obj.get("metadata", {})
    user_id = metadata.get("user_id", DEFAULT_USER_ID)
    credits = int(metadata.get("credits", 0))
    amount_cents = session_obj.get("amount_total", 0)
    payment_intent = session_obj.get("payment_intent")

    if credits <= 0:
        logger.warning("Webhook session %s has 0 credits in metadata", session_id)
        return {"received": True}

    # Idempotency: skip if already processed
    existing = (
        db.query(StripeTransaction)
        .filter(StripeTransaction.stripe_session_id == session_id)
        .one_or_none()
    )
    if existing is not None:
        logger.info("Already processed webhook for session %s", session_id)
        return {"received": True}

    # Write transaction + credit user atomically
    tx_row = StripeTransaction(
        user_id=user_id,
        stripe_session_id=session_id,
        stripe_payment_intent_id=payment_intent,
        credits_granted=credits,
        amount_cents=amount_cents,
        status="pending",
    )
    db.add(tx_row)

    credits_row = db.query(UserCredits).filter(UserCredits.user_id == user_id).one_or_none()
    if credits_row is None:
        credits_row = UserCredits(user_id=user_id, balance=credits)
        db.add(credits_row)
    else:
        credits_row.balance += credits

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("DB commit failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Database error")

    db.refresh(tx_row)

    # Hedera HBAR transfer — best-effort; credits are already saved
    hedera_tx_id: Optional[str] = None
    try:
        hedera_tx_id = await _transfer_hbar(user_id=user_id, credits=credits)
        tx_row.hedera_tx_id = hedera_tx_id
        tx_row.status = "completed"
        tx_row.completed_at = datetime.utcnow()
        db.commit()
        logger.info("HBAR transfer complete for session %s: tx=%s", session_id, hedera_tx_id)
    except Exception as exc:
        logger.error("Hedera transfer failed for session %s: %s", session_id, exc)
        tx_row.status = "completed"
        tx_row.meta = {"hedera_error": str(exc)}
        tx_row.completed_at = datetime.utcnow()
        db.commit()

    return {"received": True}


# ── Hedera transfer ───────────────────────────────────────────────────────────

async def _transfer_hbar(user_id: str, credits: int) -> str:
    """Transfer testnet HBAR to the user's wallet. Returns Hedera transaction ID."""
    hbar_per_credit = float(os.environ.get("HBAR_PER_CREDIT", "0.5"))
    hbar_amount = credits * hbar_per_credit

    if not HEDERA_SDK_AVAILABLE:
        logger.info(
            "[Hedera stub] Would transfer %.2f HBAR (%d credits) to user %s",
            hbar_amount, credits, user_id,
        )
        return "stub-tx-id"

    operator_id = os.environ.get("HEDERA_OPERATOR_ACCOUNT_ID")
    operator_key = os.environ.get("HEDERA_OPERATOR_PRIVATE_KEY")
    user_wallet = os.environ.get("HEDERA_USER_WALLET_ADDRESS")

    if not all([operator_id, operator_key, user_wallet]):
        raise RuntimeError(
            "Missing Hedera env vars: HEDERA_OPERATOR_ACCOUNT_ID, "
            "HEDERA_OPERATOR_PRIVATE_KEY, HEDERA_USER_WALLET_ADDRESS"
        )

    from hedera import AccountId, PrivateKey, TransferTransaction, Hbar, Client  # type: ignore

    network = os.environ.get("HEDERA_NETWORK", "testnet")
    client: Client
    if network == "testnet":
        for name in ("for_testnet", "forTestnet", "forTestNet"):
            if hasattr(Client, name):
                client = getattr(Client, name)()
                break
        else:
            raise RuntimeError("Cannot find Hedera Client testnet factory method")
    else:
        for name in ("for_mainnet", "forMainnet", "forMainNet"):
            if hasattr(Client, name):
                client = getattr(Client, name)()
                break
        else:
            raise RuntimeError("Cannot find Hedera Client mainnet factory method")

    # Resolve AccountId.from_string variant
    def _account_id(val: str) -> "AccountId":
        for name in ("from_string", "fromString"):
            if hasattr(AccountId, name):
                return getattr(AccountId, name)(val)
        raise RuntimeError("Cannot resolve AccountId factory")

    def _private_key(val: str) -> "PrivateKey":
        for name in ("from_string", "fromString"):
            if hasattr(PrivateKey, name):
                return getattr(PrivateKey, name)(val)
        raise RuntimeError("Cannot resolve PrivateKey factory")

    op_id = _account_id(operator_id)
    op_key = _private_key(operator_key)
    client.set_operator(op_id, op_key)

    hbar = Hbar(hbar_amount)

    tx_response = await (
        TransferTransaction()
        .add_hbar_transfer(op_id, hbar.negated())
        .add_hbar_transfer(_account_id(user_wallet), hbar)
        .execute(client)
    )
    receipt = await tx_response.get_receipt(client)
    return str(receipt.transaction_id)
