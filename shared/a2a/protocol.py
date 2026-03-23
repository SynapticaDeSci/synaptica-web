"""Helpers for exposing lightweight broker-friendly A2A-compatible routes."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

from .models import AgentCard


def build_agent_card_payload(
    agent_card: AgentCard,
    *,
    rpc_url: str,
) -> Dict[str, Any]:
    """Build a minimal A2A-compatible agent card payload."""

    skills = []
    for capability in agent_card.capabilities:
        capability_id = str(capability.name or "").strip()
        if not capability_id:
            continue
        skills.append(
            {
                "id": capability_id,
                "name": capability_id.replace("-", " ").title(),
                "description": capability.description or capability_id.replace("-", " "),
                "tags": list(agent_card.tags or []),
                "inputModes": ["text"],
                "outputModes": ["text"],
            }
        )

    extras = dict(agent_card.extras or {})
    extras.setdefault("rpc_url", rpc_url)

    return {
        "protocolVersion": "0.3.0",
        "id": agent_card.id,
        "name": agent_card.name,
        "description": agent_card.description,
        "version": agent_card.version,
        "url": rpc_url,
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "skills": skills,
        "tags": list(agent_card.tags or []),
        "extras": extras,
    }


def extract_message_text_and_metadata(payload: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Extract a text prompt and optional metadata from an A2A JSON-RPC payload."""

    if not isinstance(payload, dict):
        return None, {}

    params = payload.get("params")
    if not isinstance(params, dict):
        return None, {}

    metadata = params.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    message = params.get("message")
    if isinstance(message, str):
        cleaned = message.strip()
        return (cleaned or None), metadata

    if not isinstance(message, dict):
        return None, metadata

    message_metadata = message.get("metadata")
    if isinstance(message_metadata, dict):
        metadata = {**metadata, **message_metadata}

    parts = message.get("parts")
    if isinstance(parts, list):
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        if texts:
            return "\n".join(texts), metadata

    fallback_text = message.get("text")
    if isinstance(fallback_text, str) and fallback_text.strip():
        return fallback_text.strip(), metadata

    return None, metadata


def build_completed_task_response(
    *,
    rpc_id: Any,
    text: str,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a compact completed-task JSON-RPC response."""

    message_id = uuid.uuid4().hex
    result: Dict[str, Any] = {
        "id": task_id or message_id,
        "kind": "task",
        "status": {
            "state": "completed",
            "message": {
                "kind": "message",
                "messageId": message_id,
                "role": "agent",
                "parts": [
                    {
                        "kind": "text",
                        "type": "text",
                        "text": text,
                    }
                ],
            },
        },
    }
    if metadata:
        result["metadata"] = dict(metadata)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": result,
    }


def build_error_response(
    *,
    rpc_id: Any,
    code: int,
    message: str,
) -> Dict[str, Any]:
    """Build a JSON-RPC error response."""

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
