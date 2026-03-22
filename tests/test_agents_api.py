from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from shared.database import (
    Agent as AgentModel,
    AgentReputation,
    AgentsCacheEntry,
    SessionLocal,
)
from shared.metadata.publisher import PinataUploadResult


def _clear_agents():
    session = SessionLocal()
    try:
        session.query(AgentsCacheEntry).delete()
        session.query(AgentReputation).delete()
        session.query(AgentModel).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch):
    _clear_agents()

    monkeypatch.setattr("api.routes.agents.ensure_registry_cache", lambda force=False: None)
    monkeypatch.setattr("api.routes.agents.trigger_registry_cache_refresh", lambda: False)
    monkeypatch.setattr("api.routes.agents.get_registry_sync_status", lambda: ("test", None))
    monkeypatch.setattr("api.routes.agents._trigger_registry_registration", lambda agent_id: None)

    mock_publish = AsyncMock(
        return_value=PinataUploadResult(
            cid="bafy-test",
            ipfs_uri="ipfs://bafy-test",
            gateway_url="https://gateway.pinata.cloud/ipfs/bafy-test",
            pinata_url="https://app.pinata.cloud/pinmanager?search=bafy-test",
        )
    )
    monkeypatch.setattr("api.routes.agents.publish_agent_metadata", mock_publish)
    return TestClient(app)


def _sample_payload():
    return {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "Performs useful tests for integration.",
        "capabilities": ["testing", "validation"],
        "categories": ["Quality"],
        "endpoint_url": "https://example.com/agents/test",
        "base_rate": 1.5,
        "currency": "HBAR",
        "rate_type": "per_task",
        "contact_email": "qa@example.com",
    }


def test_register_agent_creates_record(client: TestClient):
    response = client.post("/api/agents", json=_sample_payload())
    assert response.status_code == 201

    data = response.json()
    assert data["agent_id"] == "test-agent"
    assert data["pricing"]["rate"] == 1.5
    assert data["metadata_cid"] == "bafy-test"
    assert data["erc8004_metadata_uri"] == "ipfs://bafy-test"
    assert data["reputation_score"] == 0.5
    assert data["registry_status"] == "pending"
    assert data["registry_agent_id"] is None
    assert data["registry_last_error"] is None
    assert "operator_checklist" in data

    session = SessionLocal()
    try:
        agent = session.query(AgentModel).filter(AgentModel.agent_id == "test-agent").one()
        assert agent.meta["metadata_cid"] == "bafy-test"
        assert agent.erc8004_metadata_uri == "ipfs://bafy-test"
        assert agent.meta["registry"]["status"] == "pending"
    finally:
        session.close()


def test_duplicate_agent_id_returns_conflict(client: TestClient):
    payload = _sample_payload()
    assert client.post("/api/agents", json=payload).status_code == 201
    conflict = client.post("/api/agents", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["detail"].startswith("Agent 'test-agent' already exists")


def test_list_agents_returns_created_agent(client: TestClient):
    client.post("/api/agents", json=_sample_payload())
    listing = client.get("/api/agents")
    assert listing.status_code == 200
    data = listing.json()
    assert data["sync_status"] == "test"
    assert data["total"] >= 1
    created = next((agent for agent in data["agents"] if agent["agent_id"] == "test-agent"), None)
    assert created is not None
    assert created["agent_type"] == "http"
    assert created["pricing"]["rate"] == 1.5
    assert created["reputation_score"] == 0.5
    assert created["registry_status"] == "pending"


def test_legacy_builtin_research_agents_are_hidden_from_directory(client: TestClient):
    session = SessionLocal()
    try:
        session.add(
            AgentModel(  # type: ignore[call-arg]
                agent_id="bias-detector-001",
                name="Bias Detector",
                agent_type="research",
                description="Legacy built-in specialist",
                capabilities=["bias-detection"],
                status="active",
                meta={
                    "support_tier": "legacy",
                    "endpoint_url": "http://localhost:5001/agents/bias-detector-001",
                },
            )
        )
        session.add(
            AgentReputation(
                agent_id="bias-detector-001",
                reputation_score=0.25,
                payment_multiplier=1.0,
            )
        )
        session.query(AgentsCacheEntry).delete()
        session.commit()
    finally:
        session.close()

    listing = client.get("/api/agents")
    assert listing.status_code == 200
    ids = [agent["agent_id"] for agent in listing.json()["agents"]]
    assert "bias-detector-001" not in ids

    detail = client.get("/api/agents/bias-detector-001")
    assert detail.status_code == 404
