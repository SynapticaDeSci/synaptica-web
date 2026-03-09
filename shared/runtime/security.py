"""Security guardrails for runtime payloads and logs."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable


SECRET_KEY_NAMES = {
    "private_key",
    "funding_private_key",
    "verifier_private_key",
    "task_escrow_operator_private_key",
    "secret",
    "api_key",
}

HEX_PRIVATE_KEY_PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")
BASE58_LIKE_KEY_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{48,}$")


class SensitivePayloadError(ValueError):
    """Raised when a runtime payload contains forbidden secret material."""


def _looks_like_secret_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    stripped = value.strip()
    if not stripped:
        return False

    return bool(
        HEX_PRIVATE_KEY_PATTERN.match(stripped)
        or BASE58_LIKE_KEY_PATTERN.match(stripped)
    )


def _iter_items(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key), value
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield str(index), value


def assert_no_sensitive_payload(payload: Any, *, path: str = "payload") -> None:
    """Reject payloads that contain likely secret material."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = str(key).lower()
            current_path = f"{path}.{key}"

            if key_lower in SECRET_KEY_NAMES or key_lower.endswith("_private_key"):
                raise SensitivePayloadError(f"Sensitive field '{current_path}' is not allowed")

            if _looks_like_secret_key(value):
                raise SensitivePayloadError(f"Sensitive value detected at '{current_path}'")

            assert_no_sensitive_payload(value, path=current_path)
        return

    if isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_no_sensitive_payload(value, path=f"{path}[{index}]")
        return

    if _looks_like_secret_key(payload):
        raise SensitivePayloadError(f"Sensitive value detected at '{path}'")


def redact_sensitive_payload(payload: Any) -> Any:
    """Return a deep copy of the payload with secret-like values redacted."""

    if isinstance(payload, dict):
        redacted: Dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            if key_lower in SECRET_KEY_NAMES or key_lower.endswith("_private_key"):
                redacted[key] = "[REDACTED]"
                continue
            redacted[key] = redact_sensitive_payload(value)
        return redacted

    if isinstance(payload, list):
        return [redact_sensitive_payload(item) for item in payload]

    if _looks_like_secret_key(payload):
        return "[REDACTED]"

    return payload

