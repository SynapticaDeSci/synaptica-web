"""Round progress payload for research runs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class RoundsCompletedPayload(BaseModel):
    """Completed scout/critic loop counters."""

    model_config = ConfigDict(extra="ignore")

    evidence_rounds: int = 0
    critique_rounds: int = 0

    @field_validator("evidence_rounds", "critique_rounds", mode="before")
    @classmethod
    def _coerce_rounds(cls, value: Any) -> int:
        if value is None or value == "":
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def from_payload(cls, payload: Any) -> "RoundsCompletedPayload":
        if isinstance(payload, cls):
            return payload
        if isinstance(payload, dict):
            rounds_payload = payload.get("rounds_completed")
            if isinstance(rounds_payload, dict):
                return cls.model_validate(rounds_payload)
            return cls.model_validate(payload)
        return cls()
