"""Credits routes: balance, Stripe checkout, and webhook handling."""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from shared.database import SessionLocal, UserCredits, StripeTransaction

logger = logging.getLogger(__name__)

router = APIRouter()

# Credit tier → price in USD cents
CREDIT_TIERS: dict[int, int] = {
    10: 1500,
    100: 15000,
    500: 75000,
    1000: 150000,
}

HBAR_PER_CREDIT = float(os.getenv("HBAR_PER_CREDIT", "0.5"))
DEFAULT_USER_ID = "default"


def _get_or_create_user_credits(session, user_id: str = DEFAULT_USER_ID) -> UserCredits:
    record = session.query(UserCredits).filter(UserCredits.user_id == user_id).one_or_none()
    if record is None:
        record = UserCredits(user_id=user_id, credits=50)  # start with 50 demo credits
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


# ── GET /api/credits ──────────────────────────────────────────────────────────

@router.get("")
def get_credits():
    """Return the current credit balance for the default user."""
    session = SessionLocal()
    try:
        record = _get_or_create_user_credits(session)
        return {
            "credits": record.credits,
            "hbar_equivalent": record.credits * HBAR_PER_CREDIT,
        }
    finally:
        session.close()


# ── POST /api/credits/checkout ────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    credits: int
    user_id: Optional[str] = DEFAULT_USER_ID


@router.post("/checkout")
def create_checkout(body: CheckoutRequest):
    """Create a Stripe Checkout session for the selected credit tier."""
    import stripe  # type: ignore

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    amount_cents = CREDIT_TIERS.get(body.credits)
    if amount_cents is None:
        raise HTTPException(status_code=400, detail=f"Invalid credit amount: {body.credits}")

    success_url = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:3000?payment=success")
    cancel_url = os.getenv("STRIPE_CANCEL_URL", "http://localhost:3000")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": f"{body.credits} Synaptica Credits",
                            "description": f"{body.credits} research iterations · HBAR equivalent: {body.credits * HBAR_PER_CREDIT} HBAR",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": body.user_id or DEFAULT_USER_ID,
                "credits": str(body.credits),
            },
        )
    except Exception as exc:
        logger.error("Stripe checkout error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Save pending transaction
    db = SessionLocal()
    try:
        tx = StripeTransaction(
            user_id=body.user_id or DEFAULT_USER_ID,
            stripe_session_id=session.id,
            credits_purchased=body.credits,
            amount_usd_cents=amount_cents,
            status="pending",
        )
        db.add(tx)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save StripeTransaction")
    finally:
        db.close()

    return {"session_url": session.url}


# ── POST /api/credits/webhook ─────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events to fulfil credit purchases."""
    import stripe  # type: ignore

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except Exception as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        stripe_session = event["data"]["object"]
        session_id = stripe_session["id"]
        metadata = stripe_session.get("metadata", {})
        user_id = metadata.get("user_id", DEFAULT_USER_ID)
        credits_str = metadata.get("credits", "0")

        try:
            credits_to_add = int(credits_str)
        except ValueError:
            credits_to_add = 0

        db = SessionLocal()
        try:
            # Update StripeTransaction
            tx = db.query(StripeTransaction).filter(
                StripeTransaction.stripe_session_id == session_id
            ).one_or_none()

            if tx and tx.status != "completed":
                tx.status = "completed"
                tx.completed_at = datetime.utcnow()
                db.commit()

                # Add credits to user
                user_record = _get_or_create_user_credits(db, user_id)
                user_record.credits += credits_to_add
                db.commit()
                logger.info("Credited %d credits to user %s", credits_to_add, user_id)
        except Exception:
            db.rollback()
            logger.exception("Failed to fulfil credits for session %s", session_id)
        finally:
            db.close()

    return {"received": True}
