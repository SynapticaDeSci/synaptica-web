"""Shared HOL usability and verification helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from shared.database import HolAgentVerification, SessionLocal

HOL_VERIFIED_TTL = timedelta(hours=24)
_HARD_FAILURE_PATTERNS = (
    "currently unreachable from the broker",
    "agent card or endpoint check failed",
    "endpoint check failed",
    "cannot be reached from the public broker",
    "configured with a localhost endpoint",
    "localhost endpoint",
)


def _agent_value(agent: Any, field: str, default: Any = None) -> Any:
    if isinstance(agent, dict):
        return agent.get(field, default)
    return getattr(agent, field, default)


def _set_agent_value(agent: Any, field: str, value: Any) -> None:
    if isinstance(agent, dict):
        agent[field] = value
        return
    setattr(agent, field, value)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def is_hol_hard_availability_failure(message: str) -> bool:
    """Return whether the HOL error indicates a definitive reachability failure."""

    normalized = (message or "").strip().lower()
    if not normalized:
        return False
    return any(pattern in normalized for pattern in _HARD_FAILURE_PATTERNS)


def get_hol_agent_verification_map(
    session: Session,
    uaids: Iterable[str],
) -> Dict[str, HolAgentVerification]:
    """Load verification records for the given UAIDs."""

    normalized = sorted({str(uaid).strip() for uaid in uaids if str(uaid).strip()})
    if not normalized:
        return {}

    rows = (
        session.query(HolAgentVerification)
        .filter(HolAgentVerification.uaid.in_(normalized))
        .all()
    )
    return {row.uaid: row for row in rows}


def load_hol_agent_verification_map(
    uaids: Iterable[str],
) -> Dict[str, HolAgentVerification]:
    """Load verification records using a fresh local session."""

    session = SessionLocal()
    try:
        mapping = get_hol_agent_verification_map(session, uaids)
        for row in mapping.values():
            session.expunge(row)
        return mapping
    finally:
        session.close()


def record_hol_agent_success(
    session: Session,
    uaid: str,
    *,
    mode: Optional[str],
    transport: Optional[str] = None,
) -> HolAgentVerification:
    """Persist a successful Synaptica HOL interaction for a UAID."""

    normalized_uaid = str(uaid or "").strip()
    if not normalized_uaid:
        raise ValueError("uaid is required")

    row = session.get(HolAgentVerification, normalized_uaid)
    if row is None:
        row = HolAgentVerification(uaid=normalized_uaid)  # type: ignore[call-arg]
        session.add(row)

    row.last_success_at = _utcnow()
    row.last_success_mode = str(mode).strip() if mode else None
    row.success_count = int(row.success_count or 0) + 1
    if transport and str(transport).strip():
        row.last_transport = str(transport).strip()
    return row


def persist_hol_agent_success(
    uaid: str,
    *,
    mode: Optional[str],
    transport: Optional[str] = None,
) -> HolAgentVerification:
    """Persist a success using a fresh local session and return a detached row."""

    session = SessionLocal()
    try:
        row = record_hol_agent_success(
            session,
            uaid,
            mode=mode,
            transport=transport,
        )
        session.flush()
        session.refresh(row)
        session.expunge(row)
        session.commit()
        return row
    finally:
        session.close()


def record_hol_agent_hard_failure(
    session: Session,
    uaid: str,
    *,
    reason: str,
    transport: Optional[str] = None,
) -> HolAgentVerification:
    """Persist a definitive HOL reachability failure for a UAID."""

    normalized_uaid = str(uaid or "").strip()
    if not normalized_uaid:
        raise ValueError("uaid is required")

    row = session.get(HolAgentVerification, normalized_uaid)
    if row is None:
        row = HolAgentVerification(uaid=normalized_uaid)  # type: ignore[call-arg]
        session.add(row)

    row.last_hard_failure_at = _utcnow()
    row.last_hard_failure_reason = str(reason or "").strip() or None
    row.failure_count = int(row.failure_count or 0) + 1
    if transport and str(transport).strip():
        row.last_transport = str(transport).strip()
    return row


def persist_hol_agent_hard_failure(
    uaid: str,
    *,
    reason: str,
    transport: Optional[str] = None,
) -> HolAgentVerification:
    """Persist a hard failure using a fresh local session and return a detached row."""

    session = SessionLocal()
    try:
        row = record_hol_agent_hard_failure(
            session,
            uaid,
            reason=reason,
            transport=transport,
        )
        session.flush()
        session.refresh(row)
        session.expunge(row)
        session.commit()
        return row
    finally:
        session.close()


def compute_hol_agent_usability_fields(
    agent: Any,
    verification: Optional[HolAgentVerification] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute Synaptica usability metadata for a HOL agent record."""

    current_time = now or _utcnow()
    availability = str(_agent_value(agent, "availability_status", "") or "").strip().lower()
    broker_marked_available = _agent_value(agent, "broker_marked_available", None)
    if broker_marked_available is None:
        broker_marked_available = _agent_value(agent, "available", None)

    last_success_at = getattr(verification, "last_success_at", None)
    last_hard_failure_at = getattr(verification, "last_hard_failure_at", None)
    last_hard_failure_reason = getattr(verification, "last_hard_failure_reason", None)

    verified_is_fresh = bool(
        last_success_at
        and (current_time - last_success_at) <= HOL_VERIFIED_TTL
        and (
            last_hard_failure_at is None
            or last_hard_failure_at <= last_success_at
        )
    )

    if last_hard_failure_at and (
        last_success_at is None or last_hard_failure_at > last_success_at
    ):
        usability_tier = "blocked"
        usability_reason = (
            str(last_hard_failure_reason).strip()
            if last_hard_failure_reason
            else "Synaptica most recently failed to reach this agent."
        )
    elif availability in {"offline", "inactive", "error"}:
        usability_tier = "blocked"
        usability_reason = f"HOL reports this agent as {availability}."
    elif verified_is_fresh:
        mode = str(getattr(verification, "last_success_mode", "") or "").strip() or "session"
        verified_at = _to_iso(last_success_at) or "recently"
        usability_tier = "verified"
        usability_reason = f"Synaptica verified this agent via {mode} on {verified_at}."
    elif broker_marked_available is True:
        usability_tier = "broker_available"
        usability_reason = "HOL currently marks this agent available."
    else:
        usability_tier = "exploratory"
        if availability == "stale":
            usability_reason = "HOL metadata for this agent appears stale; treat this as an exploratory attempt."
        elif availability:
            usability_reason = (
                f"HOL reports availability status {availability}, but this agent is not currently "
                "broker-marked available and not yet verified by Synaptica."
            )
        else:
            usability_reason = (
                "Discoverable in HOL, but not currently broker-marked available and not yet "
                "verified by Synaptica."
            )

    return {
        "broker_marked_available": broker_marked_available,
        "synaptica_verified": verified_is_fresh,
        "synaptica_verified_at": _to_iso(last_success_at),
        "synaptica_verification_mode": (
            str(getattr(verification, "last_success_mode", "") or "").strip() or None
        ),
        "usability_tier": usability_tier,
        "usability_reason": usability_reason,
    }


def apply_hol_agent_usability(
    agent: Any,
    verification: Optional[HolAgentVerification] = None,
    *,
    now: Optional[datetime] = None,
) -> Any:
    """Mutate an agent-like object with computed usability metadata."""

    fields = compute_hol_agent_usability_fields(agent, verification, now=now)
    for key, value in fields.items():
        _set_agent_value(agent, key, value)
    return agent
