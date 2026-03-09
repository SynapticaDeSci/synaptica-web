"""Helpers for persisting runtime task state in Task.meta while keeping an in-memory cache."""

from __future__ import annotations

from typing import Any, Dict, Optional

from shared.database import SessionLocal, Task
from shared.runtime.contracts import HandoffContext, TelemetryEnvelope
from shared.runtime.security import redact_sensitive_payload

RUNTIME_META_KEY = "runtime"
_UNSET = object()


def _ensure_runtime_meta(task: Task) -> Dict[str, Any]:
    meta: Dict[str, Any] = dict(task.meta or {})
    runtime: Dict[str, Any] = dict(meta.get(RUNTIME_META_KEY) or {})
    runtime.setdefault("progress", [])
    runtime.setdefault("progress_snapshot", {})
    runtime.setdefault("current_step", None)
    runtime.setdefault("status", "processing")
    runtime.setdefault("verification_pending", False)
    runtime.setdefault("verification_data", None)
    runtime.setdefault("verification_decision", None)
    runtime.setdefault("active_attempt_id", None)
    runtime.setdefault("current_handoff_context", None)
    meta[RUNTIME_META_KEY] = runtime
    task.meta = meta
    return runtime


def initialize_runtime_state(task_id: str, request_meta: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Initialize persisted runtime metadata for a task."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None

        runtime = _ensure_runtime_meta(task)
        if request_meta:
            for key, value in request_meta.items():
                if key not in task.meta:
                    task.meta[key] = redact_sensitive_payload(value)
        runtime["status"] = "processing"
        db.commit()
        db.refresh(task)
        return build_task_snapshot(task)
    finally:
        db.close()


def append_progress_event(
    task_id: str,
    envelope: TelemetryEnvelope,
    *,
    overall_status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a telemetry/progress event and return the latest snapshot."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None

        runtime = _ensure_runtime_meta(task)
        event = envelope.model_dump(mode="json")
        event["data"] = redact_sensitive_payload(event.get("data") or {})
        runtime["progress"].append(event)
        runtime["progress_snapshot"][envelope.step] = event
        runtime["current_step"] = envelope.step

        if overall_status:
            runtime["status"] = overall_status
        elif envelope.step == "orchestrator" and envelope.status in {"completed", "failed"}:
            runtime["status"] = envelope.status

        db.commit()
        db.refresh(task)
        return build_task_snapshot(task)
    finally:
        db.close()


def persist_handoff_context(task_id: str, context: Optional[HandoffContext]) -> Optional[Dict[str, Any]]:
    """Persist the currently active handoff context."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None

        runtime = _ensure_runtime_meta(task)
        runtime["active_attempt_id"] = context.attempt_id if context else None
        runtime["current_handoff_context"] = context.model_dump(mode="json") if context else None
        db.commit()
        db.refresh(task)
        return build_task_snapshot(task)
    finally:
        db.close()


def persist_verification_state(
    task_id: str,
    *,
    pending: bool,
    verification_data: Optional[Dict[str, Any]] = None,
    verification_decision: Any = _UNSET,
) -> Optional[Dict[str, Any]]:
    """Persist verification pending/decision state."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None

        runtime = _ensure_runtime_meta(task)
        runtime["verification_pending"] = pending
        runtime["verification_data"] = redact_sensitive_payload(verification_data)
        if verification_decision is not _UNSET:
            runtime["verification_decision"] = redact_sensitive_payload(verification_decision)
        db.commit()
        db.refresh(task)
        return build_task_snapshot(task)
    finally:
        db.close()


def build_task_snapshot(task: Task) -> Dict[str, Any]:
    """Convert a task row into the task-status response shape."""

    runtime = dict((task.meta or {}).get(RUNTIME_META_KEY) or {})
    snapshot = {
        "task_id": task.id,
        "status": runtime.get("status", "processing"),
        "current_step": runtime.get("current_step"),
        "progress": runtime.get("progress", []),
        "result": task.result,
        "error": runtime.get("error"),
        "verification_pending": runtime.get("verification_pending", False),
        "verification_data": runtime.get("verification_data"),
        "verification_decision": runtime.get("verification_decision"),
        "active_attempt_id": runtime.get("active_attempt_id"),
        "current_handoff_context": runtime.get("current_handoff_context"),
    }
    return snapshot


def load_task_snapshot(task_id: str) -> Optional[Dict[str, Any]]:
    """Load the latest runtime snapshot for a task from the database."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None
        return build_task_snapshot(task)
    finally:
        db.close()


def persist_runtime_error(task_id: str, error: str) -> Optional[Dict[str, Any]]:
    """Persist a task-level runtime error."""

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one_or_none()
        if task is None:
            return None
        runtime = _ensure_runtime_meta(task)
        runtime["error"] = error
        runtime["status"] = "failed"
        db.commit()
        db.refresh(task)
        return build_task_snapshot(task)
    finally:
        db.close()
