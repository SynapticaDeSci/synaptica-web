"""Helpers for working with Agent ORM objects."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from shared.database.models import Agent
from shared.research.agent_inventory import is_supported_builtin_research_agent
from shared.research.catalog import default_research_endpoint, infer_support_tier


def _coerce_rate(value: Any) -> float:
    """Attempt to convert a stored rate into a float."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"([0-9]*\.?[0-9]+)", value)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
    return 0.0


def _extract_pricing(meta: Dict[str, Any]) -> Dict[str, Any]:
    pricing_dict = meta.get("pricing") or {}
    if not isinstance(pricing_dict, dict):
        pricing_dict = {}

    rate = pricing_dict.get("rate") or pricing_dict.get("base_rate")
    currency = pricing_dict.get("currency") or pricing_dict.get("currency_code") or "HBAR"
    rate_type = (
        pricing_dict.get("rate_type")
        or pricing_dict.get("rateType")
        or pricing_dict.get("unit")
        or "per_task"
    )

    return {
        "rate": _coerce_rate(rate),
        "currency": currency,
        "rate_type": rate_type,
    }


def _normalize_reputation_score(value: Any) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def is_registry_managed(agent: Agent) -> bool:
    meta: Dict[str, Any] = agent.meta or {}
    return bool(meta.get("registry_managed"))


def serialize_agent(agent: Agent, reputation_score: Optional[float] = None) -> Dict[str, Any]:
    """Convert an Agent model into a serializable dict."""

    meta: Dict[str, Any] = agent.meta or {}
    metadata_cid = meta.get("metadata_cid")

    score = reputation_score
    if score is None:
        registry_rep = meta.get("registry_reputation") or {}
        score = _normalize_reputation_score(registry_rep.get("reputationScore"))

    registry_meta: Dict[str, Any] = meta.get("registry") or {}
    endpoint_url = (
        default_research_endpoint(agent.agent_id)
        if is_supported_builtin_research_agent(agent.agent_id)
        else meta.get("endpoint_url")
    )
    hol_meta: Dict[str, Any] = meta.get("hol") or {}

    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": agent.description,
        "capabilities": agent.capabilities or [],
        "categories": meta.get("categories") or [],
        "status": agent.status or "inactive",
        "endpoint_url": endpoint_url,
        "health_check_url": meta.get("health_check_url"),
        "pricing": _extract_pricing(meta),
        "contact_email": meta.get("contact_email"),
        "logo_url": meta.get("logo_url"),
        "erc8004_metadata_uri": agent.erc8004_metadata_uri,
        "metadata_cid": metadata_cid,
        "metadata_gateway_url": meta.get("metadata_gateway_url")
        or (f"https://gateway.pinata.cloud/ipfs/{metadata_cid}" if metadata_cid else None),
        "hedera_account_id": agent.hedera_account_id,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "reputation_score": score,
        "registry_status": registry_meta.get("status"),
        "registry_agent_id": registry_meta.get("agent_id"),
        "registry_tx_hash": registry_meta.get("tx_hash"),
        "registry_last_error": registry_meta.get("last_error"),
        "registry_updated_at": registry_meta.get("updated_at"),
        "support_tier": meta.get("support_tier")
        or infer_support_tier(agent.agent_id, agent.agent_type).value,
        "hol_uaid": hol_meta.get("uaid"),
        "hol_registration_status": hol_meta.get("registration_status"),
        "hol_last_error": hol_meta.get("last_error"),
    }
