"""Bridge client for the Hashgraph Online (HOL) Standards SDK sidecar.

The Python application remains the system-of-record API, but HOL broker traffic
now goes through the official HOL Standards SDK running in a small Node sidecar.
This module preserves the Python helper surface used by the rest of Synaptica:

- Discover agents in the Universal Agentic Registry.
- Create chat sessions with specific UAIDs.
- Send messages and fetch session history.
- Register local agents on HOL or request registration quotes.

`get_credit_balance()` remains on the direct REST path as a temporary fallback
because the current SDK surface used here does not provide a clean equivalent.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class HolClientError(RuntimeError):
    """Raised when the HOL Registry Broker API reports an error."""


class HolClientConfigurationError(HolClientError):
    """Raised when required HOL configuration is missing or invalid."""


def _get_env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %.2f", name, raw, default)
        return default
    if value < minimum:
        logger.warning(
            "Invalid %s=%r (must be >= %.2f); using default %.2f",
            name,
            raw,
            minimum,
            default,
        )
        return default
    return value


def _get_env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning(
            "Invalid %s=%r (must be >= %d); using default %d",
            name,
            raw,
            minimum,
            default,
        )
        return default
    return value


def _get_sidecar_url() -> str:
    base_url = os.getenv("HOL_SDK_SIDECAR_URL", "http://127.0.0.1:8040").strip()
    if not base_url:
        raise HolClientConfigurationError("HOL_SDK_SIDECAR_URL is empty")
    return base_url.rstrip("/")


def _get_base_url() -> str:
    base_url = os.getenv("REGISTRY_BROKER_API_URL", "https://hol.org/registry/api/v1").strip()
    if not base_url:
        raise HolClientConfigurationError("REGISTRY_BROKER_API_URL is empty")
    return base_url.rstrip("/")


def _get_api_key() -> Optional[str]:
    key = os.getenv("REGISTRY_BROKER_API_KEY")
    return key.strip() if key else None


def _get_sidecar_timeout_seconds() -> float:
    # HOL register can exceed short defaults during broker cold starts or load.
    return _get_env_float("HOL_SDK_SIDECAR_TIMEOUT_SECONDS", 60.0, minimum=1.0)


def _get_sidecar_connect_timeout_seconds() -> float:
    return _get_env_float("HOL_SDK_SIDECAR_CONNECT_TIMEOUT_SECONDS", 5.0, minimum=0.1)


def _get_sidecar_create_session_timeout_seconds() -> float:
    return _get_env_float(
        "HOL_SDK_SIDECAR_CREATE_SESSION_TIMEOUT_SECONDS",
        120.0,
        minimum=1.0,
    )


def _get_sidecar_create_session_retries() -> int:
    # Retries apply to create-session timeouts and transient upstream 5xx.
    return _get_env_int("HOL_SDK_SIDECAR_CREATE_SESSION_RETRIES", 2, minimum=0)


def _get_sidecar_create_session_retry_backoff_seconds() -> float:
    return _get_env_float(
        "HOL_SDK_SIDECAR_CREATE_SESSION_RETRY_BACKOFF_SECONDS",
        2.0,
        minimum=0.0,
    )


def _retry_backoff_delay_seconds(attempt: int) -> float:
    base_delay = _get_sidecar_create_session_retry_backoff_seconds()
    if base_delay <= 0:
        return 0.0
    # Exponential backoff with a conservative cap to avoid runaway waits.
    return min(base_delay * (2 ** max(0, attempt - 1)), 15.0)


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


def _build_sidecar_client() -> httpx.Client:
    timeout = httpx.Timeout(
        _get_sidecar_timeout_seconds(),
        connect=_get_sidecar_connect_timeout_seconds(),
    )
    limits = httpx.Limits(max_keepalive_connections=4, max_connections=8)
    headers: Dict[str, str] = {
        "Accept": "application/json",
    }
    return httpx.Client(
        timeout=timeout,
        limits=limits,
        headers=headers,
        base_url=_get_sidecar_url(),
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


def _format_sidecar_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out while waiting for HOL SDK sidecar response"
    if isinstance(exc, httpx.ConnectError):
        return (
            f"HOL SDK sidecar unavailable at {_get_sidecar_url()}. "
            "Start `npm --prefix frontend run hol-sidecar` and ensure "
            "HOL_SDK_SIDECAR_URL is reachable."
        )

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status = f"{response.status_code} {response.reason_phrase}".strip()
        detail = _extract_error_detail(response)
        return f"{status}: {detail}" if detail else status
    return str(exc)


def check_sidecar_health() -> Dict[str, Any]:
    """Verify the HOL SDK sidecar is reachable before broker operations."""
    with _build_sidecar_client() as client:
        try:
            response = client.get("/health")
            response.raise_for_status()
        except httpx.ConnectError as exc:
            detail = _format_sidecar_error(exc)
            raise HolClientConfigurationError(detail) from exc
        except httpx.HTTPError as exc:  # noqa: BLE001
            detail = _format_sidecar_error(exc)
            raise HolClientError(f"HOL sidecar health check failed: {detail}") from exc

        data = response.json()

    if not isinstance(data, dict):
        raise HolClientError(f"Unexpected HOL sidecar health response payload: {data!r}")
    return data


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
    available: Optional[bool] = None
    availability_status: Optional[str] = None
    source_url: Optional[str] = None
    adapter: Optional[str] = None
    protocol: Optional[str] = None


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

    filters = filters or {}

    payload: Dict[str, Any] = {
        "query": query.strip(),
        "limit": max(1, min(limit, 100)),
        "filters": filters or {},
    }

    with _build_sidecar_client() as client:
        try:
            response = client.post("/search", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            detail = _format_sidecar_error(exc)
            logger.warning("HOL sidecar search request failed: %s", detail)
            raise HolClientConfigurationError(detail) from exc
        except httpx.HTTPError as exc:  # noqa: BLE001
            detail = _format_sidecar_error(exc)
            logger.warning("HOL search request via sidecar failed: %s", detail)
            raise HolClientError(f"HOL search failed: {detail}") from exc

        data = response.json()

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Broker variants have returned any of these keys in practice.
        items = (
            data.get("results")
            or data.get("hits")
            or data.get("agents")
            or data.get("items")
            or []
        )
    else:
        items = []

    if not isinstance(items, list):
        items = []

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
            available = item.get("available")
            if available is None:
                available = meta.get("available")
            availability_status = (
                item.get("availabilityStatus")
                or meta.get("availabilityStatus")
                or meta.get("status")
            )
            source_url = (
                meta.get("url")
                or item.get("url")
                or ((item.get("endpoints") or {}).get("primary") if isinstance(item.get("endpoints"), dict) else None)
                or ((item.get("endpoints") or {}).get("api") if isinstance(item.get("endpoints"), dict) else None)
            )
            adapter = meta.get("adapter") or item.get("adapter")
            protocol = meta.get("protocol") or item.get("protocol")
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
                    available=bool(available) if available is not None else None,
                    availability_status=str(availability_status) if availability_status else None,
                    source_url=str(source_url) if source_url else None,
                    adapter=str(adapter) if adapter else None,
                    protocol=str(protocol) if protocol else None,
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

    attempts = _get_sidecar_create_session_retries() + 1
    request_timeout = httpx.Timeout(
        _get_sidecar_create_session_timeout_seconds(),
        connect=_get_sidecar_connect_timeout_seconds(),
    )

    with _build_sidecar_client() as client:
        response: Optional[httpx.Response] = None
        for attempt in range(1, attempts + 1):
            try:
                response = client.post(
                    "/chat/session",
                    json=payload,
                    timeout=request_timeout,
                )
                response.raise_for_status()
                break
            except httpx.TimeoutException as exc:
                detail = _format_sidecar_error(exc)
                if attempt < attempts:
                    delay = _retry_backoff_delay_seconds(attempt)
                    logger.warning(
                        "HOL create_session timed out (%s). Retrying attempt %d/%d in %.1fs...",
                        detail,
                        attempt + 1,
                        attempts,
                        delay,
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                logger.warning("HOL create_session failed: %s", detail)
                raise HolClientError(f"HOL create_session failed: {detail}") from exc
            except httpx.ConnectError as exc:
                detail = _format_sidecar_error(exc)
                logger.warning("HOL sidecar create_session failed: %s", detail)
                raise HolClientConfigurationError(detail) from exc
            except httpx.HTTPStatusError as exc:
                detail = _format_sidecar_error(exc)
                status = exc.response.status_code
                if status in {502, 503, 504} and attempt < attempts:
                    delay = _retry_backoff_delay_seconds(attempt)
                    logger.warning(
                        "HOL create_session got transient upstream status %d (%s). "
                        "Retrying attempt %d/%d in %.1fs...",
                        status,
                        detail,
                        attempt + 1,
                        attempts,
                        delay,
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                logger.warning("HOL create_session failed: %s", detail)
                raise HolClientError(f"HOL create_session failed: {detail}") from exc
            except httpx.HTTPError as exc:  # noqa: BLE001
                detail = _format_sidecar_error(exc)
                logger.warning("HOL create_session failed: %s", detail)
                raise HolClientError(f"HOL create_session failed: {detail}") from exc

        if response is None:
            raise HolClientError("HOL create_session failed: no response from HOL SDK sidecar")
        data = response.json()

    session_id = str(data.get("sessionId") or data.get("id") or "").strip()
    if not session_id:
        raise HolClientError(f"Unexpected HOL session response payload: {data!r}")
    return session_id


def send_message(
    session_id: Optional[str],
    message: str,
    *,
    uaid: Optional[str] = None,
    as_uaid: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a message into an existing chat session (or directly by UAID)."""
    if not message or not message.strip():
        raise ValueError("message must be a non-empty string")
    normalized_session_id = (session_id or "").strip()
    normalized_uaid = (uaid or "").strip()
    if not normalized_session_id and not normalized_uaid:
        raise ValueError("session_id or uaid is required")

    payload: Dict[str, Any] = {"message": message}
    if normalized_session_id:
        payload["sessionId"] = normalized_session_id
    if normalized_uaid:
        payload["uaid"] = normalized_uaid
    if as_uaid:
        payload["senderUaid"] = as_uaid

    with _build_sidecar_client() as client:
        try:
            response = client.post("/chat/message", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            detail = _format_sidecar_error(exc)
            logger.warning("HOL sidecar send_message failed: %s", detail)
            raise HolClientConfigurationError(detail) from exc
        except httpx.HTTPError as exc:  # noqa: BLE001
            detail = _format_sidecar_error(exc)
            logger.warning("HOL send_message failed: %s", detail)
            raise HolClientError(f"HOL send_message failed: {detail}") from exc

        data = response.json()

    if not isinstance(data, dict):
        raise HolClientError(f"Unexpected HOL message response payload: {data!r}")
    return data


def get_history(session_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent messages for a chat session."""
    params = {"limit": max(1, min(limit, 200))}

    with _build_sidecar_client() as client:
        try:
            response = client.get(f"/chat/history/{session_id}", params=params)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            detail = _format_sidecar_error(exc)
            logger.warning("HOL sidecar get_history failed: %s", detail)
            raise HolClientConfigurationError(detail) from exc
        except httpx.HTTPError as exc:  # noqa: BLE001
            detail = _format_sidecar_error(exc)
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

    payload: Dict[str, Any] = {
        "agent_payload": dict(agent_payload or {}),
        "mode": normalized_mode,
    }

    with _build_sidecar_client() as client:
        try:
            response = client.post("/register", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            detail = _format_sidecar_error(exc)
            logger.warning("HOL sidecar register_agent failed: %s", detail)
            raise HolClientConfigurationError(detail) from exc
        except httpx.HTTPError as exc:  # noqa: BLE001
            detail = _format_sidecar_error(exc)
            raise HolClientError(f"HOL register_agent failed: {detail}") from exc

        data = response.json()
    if not isinstance(data, dict):
        raise HolClientError(f"Unexpected HOL registration response payload: {data!r}")
    return data


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
