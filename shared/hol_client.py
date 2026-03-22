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
DEFAULT_BROKER_BASE_URL = "https://hol.org/registry/api/v1"
DEFAULT_BROKER_TIMEOUT_FALLBACK_URL_2 = "https://registry.hashgraphonline.com/api/v1"


class HolClientError(RuntimeError):
    """Raised when the HOL Registry Broker API reports an error."""


class HolClientConfigurationError(HolClientError):
    """Raised when required HOL configuration is missing or invalid."""


def _get_base_url() -> str:
    base_url = os.getenv("REGISTRY_BROKER_API_URL", DEFAULT_BROKER_BASE_URL).strip()
    if not base_url:
        raise HolClientConfigurationError("REGISTRY_BROKER_API_URL is empty")
    return base_url.rstrip("/")


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    if not normalized.startswith(("http://", "https://")):
        return ""
    return normalized


def _get_base_url_candidates() -> List[str]:
    primary = _normalize_base_url(_get_base_url())
    candidates: List[str] = []
    if primary:
        candidates.append(primary)

    # Optional explicit fallback list for operators.
    csv_fallbacks = (os.getenv("REGISTRY_BROKER_API_URL_FALLBACKS") or "").strip()
    if csv_fallbacks:
        for raw in csv_fallbacks.split(","):
            normalized = _normalize_base_url(raw)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

    # Built-in fallback used only when the primary host repeatedly times out.
    default_fallbacks = [
        # Keep default fallback list conservative and SNI-safe.
        DEFAULT_BROKER_TIMEOUT_FALLBACK_URL_2,
    ]
    for item in default_fallbacks:
        default_fallback = _normalize_base_url(item)
        if default_fallback and default_fallback not in candidates:
            candidates.append(default_fallback)

    if not candidates:
        raise HolClientConfigurationError("No valid Registry Broker base URL candidates configured")
    return candidates


def _get_api_key() -> Optional[str]:
    key = os.getenv("REGISTRY_BROKER_API_KEY")
    return key.strip() if key else None


def _build_client(*, base_url: Optional[str] = None) -> httpx.Client:
    timeout_raw = (os.getenv("REGISTRY_BROKER_TIMEOUT_SECONDS") or "").strip()
    try:
        total_timeout = float(timeout_raw) if timeout_raw else 30.0
    except ValueError:
        total_timeout = 30.0
    total_timeout = max(5.0, min(total_timeout, 300.0))
    connect_timeout = min(max(5.0, total_timeout / 3.0), 20.0)
    timeout = httpx.Timeout(total_timeout, connect=connect_timeout)
    limits = httpx.Limits(max_keepalive_connections=4, max_connections=8)
    headers: Dict[str, str] = {
        "Accept": "application/json",
    }
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    return httpx.Client(
        timeout=timeout,
        limits=limits,
        headers=headers,
        base_url=base_url or _get_base_url(),
    )


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
    # `/skills/publish` is intentionally excluded for this agent-registration
    # client because it belongs to a different publishing flow and can cause
    # long-running incompatible requests.
    fallbacks = [single_path, "/agents/register", "/agent/register"]
    deduped: List[str] = []
    for candidate in fallbacks:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


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
        detail = str(exc).strip()
        if detail:
            return f"failed to connect to HOL registry ({detail})"
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
            detail = _format_http_error(exc)
            logger.warning("HOL search request failed: %s", detail)
            raise HolClientError(f"HOL search failed: {detail}") from exc

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
            detail = _format_http_error(exc)
            logger.warning("HOL create_session failed: %s", detail)
            raise HolClientError(f"HOL create_session failed: {detail}") from exc

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
            detail = _format_http_error(exc)
            logger.warning("HOL send_message failed: %s", detail)
            raise HolClientError(f"HOL send_message failed: {detail}") from exc

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
            detail = _format_http_error(exc)
            logger.warning("HOL get_history failed: %s", detail)
            raise HolClientError(f"HOL get_history failed: {detail}") from exc

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
            detail = _format_http_error(exc)
            logger.warning("HOL list_sessions failed: %s", detail)
            raise HolClientError(f"HOL list_sessions failed: {detail}") from exc

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
    payload["mode"] = normalized_mode

    attempted_paths: List[str] = []
    last_error: Optional[Exception] = None
    last_error_message: Optional[str] = None
    last_http_error_404: Optional[httpx.HTTPStatusError] = None
    last_http_error_non_404: Optional[httpx.HTTPStatusError] = None

    base_urls = _get_base_url_candidates()
    register_paths = _get_register_paths()
    for base_url in base_urls:
        logger.info("HOL register_agent base_url=%s", base_url)
        with _build_client(base_url=base_url) as client:
            for path in register_paths:
                target = path if path.startswith(("http://", "https://")) else f"{base_url}{path}"
                attempted_paths.append(target)
                logger.info(
                    "HOL register_agent attempt mode=%s target=%s",
                    normalized_mode,
                    target,
                )
                try:
                    response = client.post(path, json=payload)
                except httpx.HTTPError as exc:  # noqa: BLE001
                    last_error = exc
                    last_error_message = _format_http_error(exc)
                    logger.warning(
                        "HOL register_agent request failed for %s: %s",
                        target,
                        last_error_message,
                    )
                    # Some brokers/gateways time out on unsupported routes instead of
                    # returning 404/405. Keep trying configured fallback paths.
                    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
                        continue
                    break

                logger.info(
                    "HOL register_agent response mode=%s target=%s status=%s",
                    normalized_mode,
                    target,
                    response.status_code,
                )
                if response.status_code == 404:
                    logger.info("HOL register_agent path not found: %s", target)
                    last_error = httpx.HTTPStatusError(
                        "404 Not Found",
                        request=response.request,
                        response=response,
                    )
                    last_error_message = _format_http_error(last_error)
                    if isinstance(last_error, httpx.HTTPStatusError):
                        last_http_error_404 = last_error
                    continue

                try:
                    response.raise_for_status()
                except httpx.HTTPError as exc:  # noqa: BLE001
                    last_error = exc
                    last_error_message = _format_http_error(exc)
                    if isinstance(exc, httpx.HTTPStatusError):
                        if exc.response.status_code == 404:
                            last_http_error_404 = exc
                        else:
                            last_http_error_non_404 = exc
                    logger.warning(
                        "HOL register_agent failed for %s: %s",
                        target,
                        last_error_message,
                    )
                    break

                data = response.json()
                if not isinstance(data, dict):
                    raise HolClientError(f"Unexpected HOL registration response payload: {data!r}")
                return data

    attempted = ", ".join(attempted_paths) or "<none>"
    if last_http_error_non_404 is not None:
        detail = _format_http_error(last_http_error_non_404)
        raise HolClientError(
            f"HOL register_agent failed after trying paths ({attempted}): {detail}"
        ) from last_http_error_non_404

    if last_http_error_404 is not None:
        raise HolClientError(
            "HOL register_agent failed: 404 Not Found on all candidate paths "
            f"({attempted}). Set REGISTRY_BROKER_REGISTER_PATH or "
            "REGISTRY_BROKER_REGISTER_PATHS to the correct endpoint."
        ) from last_http_error_404

    raise HolClientError(
        f"HOL register_agent failed after trying paths ({attempted}): "
        f"{last_error_message or last_error}"
    ) from last_error


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
