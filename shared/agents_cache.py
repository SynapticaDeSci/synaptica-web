"""Utilities for caching serialized agent listings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from shared.agent_utils import is_registry_managed, serialize_agent
from shared.database import SessionLocal
from shared.database.models import Agent, AgentReputation, AgentsCacheEntry

CACHE_KEY_DEFAULT = "default"


def _get_session(session: Optional[Session] = None) -> tuple[Session, bool]:
    if session is not None:
        return session, False
    new_session = SessionLocal()
    return new_session, True


def build_agents_payload(session: Optional[Session] = None) -> Dict[str, Any]:
    db, should_close = _get_session(session)
    try:
        agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
        registry_agents = [agent for agent in agents if is_registry_managed(agent)]
        always_listed = [agent for agent in agents if (agent.meta or {}).get("always_listed")]
        if registry_agents:
            source = list(registry_agents)
            seen = {agent.agent_id for agent in source}
            for agent in always_listed:
                if agent.agent_id not in seen:
                    source.append(agent)
        else:
            source = agents

        reputation_map: Dict[str, float] = {}
        agent_ids = [agent.agent_id for agent in source]
        if agent_ids:
            records = (
                db.query(AgentReputation)
                .filter(AgentReputation.agent_id.in_(agent_ids))
                .all()
            )
            reputation_map = {record.agent_id: record.reputation_score for record in records}

        serialized = [serialize_agent(agent, reputation_map.get(agent.agent_id)) for agent in source]
        return {"total": len(serialized), "agents": serialized}
    finally:
        if should_close:
            db.close()


def get_cached_agents_payload(session: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    db, should_close = _get_session(session)
    try:
        entry = db.query(AgentsCacheEntry).filter(AgentsCacheEntry.key == CACHE_KEY_DEFAULT).one_or_none()
        if not entry:
            return None
        payload = dict(entry.payload or {})
        if entry.synced_at and not payload.get("synced_at"):
            payload["synced_at"] = entry.synced_at.isoformat()
        return payload
    finally:
        if should_close:
            db.close()


def rebuild_agents_cache(
    session: Optional[Session] = None,
    *,
    synced_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    payload = build_agents_payload(session)
    payload["synced_at"] = synced_at.isoformat() if synced_at else payload.get("synced_at")

    db, should_close = _get_session(session)
    try:
        entry = db.query(AgentsCacheEntry).filter(AgentsCacheEntry.key == CACHE_KEY_DEFAULT).one_or_none()
        if entry is None:
            entry = AgentsCacheEntry(key=CACHE_KEY_DEFAULT, payload=payload, synced_at=synced_at)
            db.add(entry)
        else:
            entry.payload = payload
            entry.synced_at = synced_at
        db.commit()
    finally:
        if should_close:
            db.close()
    return payload
