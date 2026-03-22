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


def _normalize_register_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        return ""
    if normalized.startswith(("http://", "https://")):
        return normalized
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _get_register_paths() -> List[str]:
    # Prefer explicit CSV list when provided.
    paths_csv = (os.getenv("REGISTRY_BROKER_REGISTER_PATHS") or "").strip()
    if paths_csv:
        paths = [_normalize_register_path(item) for item in paths_csv.split(",")]
        cleaned = [path for path in paths if path]
        if not cleaned:
            raise HolClientConfigurationError("REGISTRY_BROKER_REGISTER_PATHS is empty")
        return cleaned

    # Fall back to a single path override.
    single_path = _normalize_register_path(
        os.getenv("REGISTRY_BROKER_REGISTER_PATH", "/register")
    )
    if not single_path:
        raise HolClientConfigurationError("REGISTRY_BROKER_REGISTER_PATH is empty")

    # Conservative built-in fallbacks for broker variations. First item remains
    # the configured/default path to preserve existing behavior.
    fallbacks = [single_path, "/agents/register", "/agent/register", "/skills/publish"]
    deduped: List[str] = []
    for candidate in fallbacks:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _get_quote_paths() -> List[str]:
    """Derive quote endpoints from configured register paths."""
    quote_paths: List[str] = []
    for path in _get_register_paths():
        candidate = path
        if candidate.endswith("/quote"):
            pass
        elif candidate.endswith("/publish"):
            candidate = f"{candidate.rsplit('/publish', 1)[0]}/quote"
        else:
            candidate = f"{candidate.rstrip('/')}/quote"
        if candidate not in quote_paths:
            quote_paths.append(candidate)
    return quote_paths


def _extract_error_detail(response: httpx.Response) -> Optional[str]:
    def _compact(value: str, *, limit: int = 260) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: limit - 3]}..."

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        for key in ("error", "detail", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                credit_keys = ("requiredCredits", "availableCredits", "shortfallCredits")
                credit_parts = [f"{item}={payload[item]}" for item in credit_keys if item in payload]
                if credit_parts:
                    return f"{detail} ({', '.join(credit_parts)})"
                return detail
        return _compact(str(payload))

    if isinstance(payload, list):
        return _compact(str(payload))

    text = response.text.strip()
    if not text:
        return None

    content_type = (response.headers.get("content-type") or "").lower()
    if "text/html" in content_type or "<html" in text.lower():
        return "upstream HOL registry error page"

    return _compact(text)


def _format_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out while waiting for HOL registry response"
    if isinstance(exc, httpx.ConnectError):
        return "failed to connect to HOL registry"

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status = f"{response.status_code} {response.reason_phrase}".strip()
        detail = _extract_error_detail(response)
        return f"{status}: {detail}" if detail else status
    return str(exc)


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


def register_agent(agent_payload: Dict[str, Any], *, mode: str = "register") -> Dict[str, Any]:
    """Register an agent in HOL Registry Broker, or request a quote for registration."""
    normalized_mode = (mode or "register").strip().lower()
    if normalized_mode not in {"quote", "register"}:
        raise ValueError("mode must be either 'quote' or 'register'")

    payload: Dict[str, Any] = dict(agent_payload or {})
    if normalized_mode == "register":
        payload["mode"] = normalized_mode

    attempted_paths: List[str] = []
    last_error: Optional[Exception] = None
    last_error_message: Optional[str] = None
    candidate_paths = _get_quote_paths() if normalized_mode == "quote" else _get_register_paths()

    with _build_client() as client:
        for path in candidate_paths:
            attempted_paths.append(path)
            try:
                response = client.post(path, json=payload)
            except httpx.HTTPError as exc:  # noqa: BLE001
                last_error = exc
                last_error_message = _format_http_error(exc)
                logger.warning("HOL register_agent request failed for %s: %s", path, last_error_message)
                break

            if response.status_code == 404:
                logger.info("HOL register_agent path not found: %s", path)
                last_error = httpx.HTTPStatusError(
                    "404 Not Found",
                    request=response.request,
                    response=response,
                )
                last_error_message = _format_http_error(last_error)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:  # noqa: BLE001
                last_error = exc
                last_error_message = _format_http_error(exc)
                logger.warning("HOL register_agent failed for %s: %s", path, last_error_message)
                break

            data = response.json()
            if not isinstance(data, dict):
                raise HolClientError(f"Unexpected HOL registration response payload: {data!r}")
            return data

    attempted = ", ".join(attempted_paths) or "<none>"
    if isinstance(last_error, httpx.HTTPStatusError) and last_error.response.status_code == 404:
        raise HolClientError(
            "HOL register_agent failed: 404 Not Found on all candidate paths "
            f"({attempted}). Set REGISTRY_BROKER_REGISTER_PATH or "
            "REGISTRY_BROKER_REGISTER_PATHS to the correct endpoint."
        ) from last_error

    raise HolClientError(
        f"HOL register_agent failed after trying paths ({attempted}): "
        f"{last_error_message or last_error}"
    ) from last_error


def get_credit_balance(*, account_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch HOL broker credit balance for the authenticated account."""
    params: Dict[str, Any] = {}
    if account_id:
        params["accountId"] = account_id

    with _build_client() as client:
        try:
            response = client.get("/credits/balance", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("HOL get_credit_balance failed: %s", exc)
            raise HolClientError(f"HOL get_credit_balance failed: {_format_http_error(exc)}") from exc

        data = response.json()
    if not isinstance(data, dict):
        raise HolClientError(f"Unexpected HOL credit balance response payload: {data!r}")
    return data


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
