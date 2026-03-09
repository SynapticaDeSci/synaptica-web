"""Thin client for the Hashgraph Online (HOL) Registry Broker API.

This module intentionally mirrors the style of other shared helpers like
`shared.registry_sync` and provides just enough surface area for Synaptica to:

- Discover agents in the Universal Agentic Registry.
- Create chat sessions with specific UAIDs.
- Send messages and fetch history for those sessions.
- List sessions for a given identity (for inbox-style workflows).

The implementation uses simple `httpx` calls instead of a heavy SDK so it can
run anywhere the rest of the Python stack does.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class HolClientError(RuntimeError):
    """Raised when the HOL Registry Broker API reports an error."""


class HolClientConfigurationError(HolClientError):
    """Raised when required HOL configuration is missing or invalid."""


def _get_base_url() -> str:
    base_url = os.getenv("REGISTRY_BROKER_API_URL", "https://hol.org/registry/api/v1").strip()
    if not base_url:
        raise HolClientConfigurationError("REGISTRY_BROKER_API_URL is empty")
    return base_url.rstrip("/")


def _get_api_key() -> Optional[str]:
    key = os.getenv("REGISTRY_BROKER_API_KEY")
    return key.strip() if key else None


def _build_client() -> httpx.Client:
    timeout = httpx.Timeout(10.0, connect=5.0)
    limits = httpx.Limits(max_keepalive_connections=4, max_connections=8)
    headers: Dict[str, str] = {
        "Accept": "application/json",
    }
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    return httpx.Client(timeout=timeout, limits=limits, headers=headers, base_url=_get_base_url())


@dataclass
class HolAgentSummary:
    """Lightweight representation of an agent returned from search."""

    uaid: str
    name: str
    description: str
    capabilities: List[str]
    categories: List[str]
    transports: List[str]
    pricing: Dict[str, Any]
    registry: Optional[str] = None


def search_agents(
    query: str,
    *,
    limit: int = 5,
    filters: Optional[Dict[str, Any]] = None,
) -> List[HolAgentSummary]:
    """Search for agents in the Universal Agentic Registry.

    This is a thin wrapper around the Registry Broker `/search` endpoint.
    It intentionally returns a normalized summary subset of the raw payload.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    params: Dict[str, Any] = {"q": query.strip(), "limit": max(1, min(limit, 25))}
    filters = filters or {}
    for key, value in filters.items():
        if value is None:
            continue
        params[key] = value

    with _build_client() as client:
        try:
            response = client.get("/search", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL search request failed: %s", exc)
            raise HolClientError(f"HOL search failed: {exc}") from exc

        data = response.json()

    items = data if isinstance(data, list) else data.get("results") or []
    results: List[HolAgentSummary] = []
    for item in items:
        try:
            uaid = str(item.get("uaid") or item.get("id") or "").strip()
            if not uaid:
                continue
            meta = item.get("metadata") or {}
            name = meta.get("name") or item.get("name") or uaid
            description = meta.get("description") or item.get("description") or ""
            capabilities = _coerce_str_list(
                meta.get("capabilities") or item.get("capabilities")
            )
            categories = _coerce_str_list(
                meta.get("categories") or item.get("categories")
            )
            transports = _coerce_str_list(
                meta.get("transports") or item.get("transports")
            )
            pricing = meta.get("pricing") or item.get("pricing") or {}
            registry = (
                meta.get("registry")
                or item.get("registry")
                or item.get("sourceRegistry")
            )
            results.append(
                HolAgentSummary(
                    uaid=uaid,
                    name=str(name),
                    description=str(description),
                    capabilities=capabilities,
                    categories=categories,
                    transports=transports,
                    pricing=pricing if isinstance(pricing, dict) else {},
                    registry=str(registry) if registry else None,
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to normalize HOL agent entry: %r", item, exc_info=True)
            continue

    return results


def create_session(
    uaid: str,
    *,
    transport: Optional[str] = None,
    as_uaid: Optional[str] = None,
) -> str:
    """Create a chat session with a target UAID."""
    payload: Dict[str, Any] = {"uaid": uaid}
    if transport:
        payload["transport"] = transport
    if as_uaid:
        payload["asUaid"] = as_uaid

    with _build_client() as client:
        try:
            response = client.post("/chat/session", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL create_session failed: %s", exc)
            raise HolClientError(f"HOL create_session failed: {exc}") from exc

        data = response.json()

    session_id = str(data.get("sessionId") or data.get("id") or "").strip()
    if not session_id:
        raise HolClientError(f"Unexpected HOL session response payload: {data!r}")
    return session_id


def send_message(
    session_id: str,
    message: str,
    *,
    as_uaid: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a message into an existing chat session."""
    if not message or not message.strip():
        raise ValueError("message must be a non-empty string")

    payload: Dict[str, Any] = {
        "sessionId": session_id,
        "message": message,
    }
    if as_uaid:
        payload["senderUaid"] = as_uaid

    with _build_client() as client:
        try:
            response = client.post("/chat/message", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL send_message failed: %s", exc)
            raise HolClientError(f"HOL send_message failed: {exc}") from exc

        data = response.json()

    if not isinstance(data, dict):
        raise HolClientError(f"Unexpected HOL message response payload: {data!r}")
    return data


def get_history(session_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent messages for a chat session."""
    params = {"limit": max(1, min(limit, 200))}

    with _build_client() as client:
        try:
            response = client.get(f"/chat/history/{session_id}", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL get_history failed: %s", exc)
            raise HolClientError(f"HOL get_history failed: {exc}") from exc

        data = response.json()

    if isinstance(data, list):
        return data
    return data.get("messages") or []


def list_sessions(*, as_uaid: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List chat sessions that involve the current identity (or a specific UAID)."""
    params: Dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if as_uaid:
        params["asUaid"] = as_uaid

    with _build_client() as client:
        try:
            response = client.get("/chat/sessions", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL list_sessions failed: %s", exc)
            raise HolClientError(f"HOL list_sessions failed: {exc}") from exc

        data = response.json()

    if isinstance(data, list):
        return data
    return data.get("sessions") or []


def _coerce_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple, set)):
        cleaned_list = []
        for item in value:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    cleaned_list.append(s)
        return cleaned_list
    return []

