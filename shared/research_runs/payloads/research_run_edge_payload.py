"""Serialized edge payload for research-run graphs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResearchRunEdgePayload(BaseModel):
    """Directed edge between two research-run nodes."""

    model_config = ConfigDict(extra="ignore")

    from_node_id: str
    to_node_id: str
