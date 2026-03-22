from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from shared.database import (
    Agent as AgentModel,
    AgentReputation,
    AgentsCacheEntry,
    DataAsset,
    SessionLocal,
)


def _reset_state():
    session = SessionLocal()
    try:
        session.query(DataAsset).delete()
        session.query(AgentsCacheEntry).delete()
        session.query(AgentReputation).delete()
        session.query(AgentModel).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch, tmp_path):
    _reset_state()
    monkeypatch.setenv("DATA_AGENT_STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr("api.main.ensure_registry_cache", lambda: None)
    monkeypatch.setattr("api.routes.agents.trigger_registry_cache_refresh", lambda: False)
    monkeypatch.setattr("api.routes.agents.get_registry_sync_status", lambda: ("test", None))
    monkeypatch.setattr("api.routes.data_agent.hol_check_sidecar_health", lambda: {"ok": True})
    with TestClient(app) as test_client:
        yield test_client


def _upload_dataset(
    client: TestClient,
    *,
    title: str = "Experiment batch A",
    description: str = "Negative result from trial run.",
    lab_name: str = "NeuroLab",
    data_classification: str = "failed",
    tags: str = "rna,failed-run",
    failed_reason: str = "No significant signal",
    reuse_domains: str = "meta-analysis,benchmarking",
    filename: str = "trial.csv",
    content: bytes = b"col1,col2\n1,2\n",
):
    return client.post(
        "/api/data-agent/datasets",
        data={
            "title": title,
            "description": description,
            "lab_name": lab_name,
            "data_classification": data_classification,
            "tags": tags,
            "failed_reason": failed_reason,
            "reuse_domains": reuse_domains,
        },
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_creates_dataset_with_verification(client: TestClient):
    response = _upload_dataset(client)
    assert response.status_code == 201

    payload = response.json()
    assert payload["title"] == "Experiment batch A"
    assert payload["lab_name"] == "NeuroLab"
    assert payload["data_classification"] == "failed"
    assert payload["tags"] == ["rna", "failed-run"]
    assert payload["intended_visibility"] == "private"
    assert payload["verification_status"] in {"passed", "failed"}
    assert payload["proof_status"] in {"unanchored", "failed", "manifest_pinned", "anchored"}
    assert payload["failed_reason"] == "No significant signal"
    assert payload["reuse_domains"] == ["meta-analysis", "benchmarking"]

    session = SessionLocal()
    try:
        row = session.query(DataAsset).filter(DataAsset.id == payload["id"]).one()
        assert row.filename == "trial.csv"
        assert row.size_bytes == len(b"col1,col2\n1,2\n")
        assert Path(row.stored_path).exists()
        meta = row.meta or {}
        assert "verification_report" in meta
        assert "verification_status" in meta
    finally:
        session.close()


def test_upload_rejects_unsupported_extension(client: TestClient):
    response = _upload_dataset(client, filename="results.exe", content=b"binary")
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_rejects_file_larger_than_25mb(client: TestClient):
    oversized = b"x" * (25 * 1024 * 1024 + 1)
    response = _upload_dataset(client, filename="huge.csv", content=oversized)
    assert response.status_code == 413
    assert "25MB" in response.json()["detail"]


def test_verify_endpoint_returns_report(client: TestClient):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    verified = client.post(f"/api/data-agent/datasets/{dataset_id}/verify")
    assert verified.status_code == 200
    payload = verified.json()
    assert payload["id"] == dataset_id
    assert payload["verification_status"] in {"passed", "failed"}
    assert isinstance(payload["verification_report"], dict)
    assert "checks" in payload["verification_report"]


def test_anchor_and_proof_and_citation_endpoints(client: TestClient, monkeypatch):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    async def _mock_pin(asset, manifest):
        return "bafy-manifest", "https://gateway.pinata.cloud/ipfs/bafy-manifest"

    async def _mock_submit(payload):
        return "0.0.123456", "SUCCESS"

    monkeypatch.setattr("api.routes.data_agent._pin_manifest_to_pinata", _mock_pin)
    monkeypatch.setattr("api.routes.data_agent._submit_anchor_message", _mock_submit)

    anchored = client.post(f"/api/data-agent/datasets/{dataset_id}/anchor")
    assert anchored.status_code == 200
    anchored_payload = anchored.json()
    assert anchored_payload["manifest_cid"] == "bafy-manifest"
    assert anchored_payload["hcs_topic_id"] == "0.0.123456"
    assert anchored_payload["proof_status"] == "anchored"

    proof = client.get(f"/api/data-agent/datasets/{dataset_id}/proof")
    assert proof.status_code == 200
    proof_payload = proof.json()
    assert proof_payload["dataset_id"] == dataset_id
    assert proof_payload["manifest_cid"] == "bafy-manifest"

    citation = client.get(f"/api/data-agent/datasets/{dataset_id}/citation")
    assert citation.status_code == 200
    citation_payload = citation.json()["citation"]
    assert citation_payload["dataset_id"] == dataset_id
    assert citation_payload["identifiers"]["manifest_cid"] == "bafy-manifest"

    anchored_filter = client.get("/api/data-agent/datasets", params={"proof_status": "anchored"})
    assert anchored_filter.status_code == 200
    assert anchored_filter.json()["total"] == 1
    assert anchored_filter.json()["datasets"][0]["id"] == dataset_id

    verified_filter = client.get("/api/data-agent/datasets", params={"verification_status": "passed"})
    assert verified_filter.status_code == 200
    assert verified_filter.json()["total"] == 1
    assert verified_filter.json()["datasets"][0]["id"] == dataset_id


def test_list_filters_and_reuse_events(client: TestClient):
    first = _upload_dataset(
        client,
        title="Protein run 1",
        data_classification="underused",
        tags="proteomics,archive",
        reuse_domains="benchmarks",
        filename="protein.csv",
    ).json()
    second = _upload_dataset(
        client,
        title="Failed genome scan",
        data_classification="failed",
        tags="genomics,failed-run",
        lab_name="GenomeLab",
        reuse_domains="replication",
        filename="genome.csv",
    ).json()

    listing = client.get("/api/data-agent/datasets", params={"classification": "failed"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["datasets"][0]["title"] == "Failed genome scan"

    lab_filtered = client.get("/api/data-agent/datasets", params={"lab_name": "Genome"})
    assert lab_filtered.status_code == 200
    assert lab_filtered.json()["total"] == 1
    assert lab_filtered.json()["datasets"][0]["id"] == second["id"]

    reuse = client.post(f"/api/data-agent/datasets/{second['id']}/reuse-events")
    assert reuse.status_code == 200
    assert reuse.json()["reuse_count"] == 1

    refetched = client.get(f"/api/data-agent/datasets/{second['id']}")
    assert refetched.status_code == 200
    assert refetched.json()["reuse_count"] == 1
    assert refetched.json()["last_reused_at"] is not None
    assert isinstance(refetched.json()["similar_datasets"], list)

    paged = client.get("/api/data-agent/datasets", params={"limit": 1, "offset": 1})
    assert paged.status_code == 200
    payload = paged.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert len(payload["datasets"]) == 1

    _ = first


def test_dataset_download_and_missing_download(client: TestClient):
    upload = _upload_dataset(client, filename="detail.csv")
    dataset_id = upload.json()["id"]

    detail = client.get(f"/api/data-agent/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == dataset_id
    assert detail.json()["filename"] == "detail.csv"

    download = client.get(f"/api/data-agent/datasets/{dataset_id}/download")
    assert download.status_code == 200
    assert download.content == b"col1,col2\n1,2\n"
    assert "attachment; filename=\"detail.csv\"" in download.headers.get("content-disposition", "")

    missing_download = client.get("/api/data-agent/datasets/missing-id/download")
    assert missing_download.status_code == 404


def test_built_in_data_agent_is_listed(client: TestClient):
    listing = client.get("/api/agents")
    assert listing.status_code == 200
    payload = listing.json()
    ids = [agent["agent_id"] for agent in payload["agents"]]
    assert "data-agent-001" in ids


def test_dataset_hol_use_autodiscovery_persists_session_trace(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    class _Agent:
        uaid = "uaid:aid:hol-data"
        name = "HOL Data Agent"
        description = "Remote data specialist"
        capabilities = ["data", "analysis"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {"rate": 0}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://example.com/hol-data"
        adapter = "http-adapter"
        protocol = "http"

    monkeypatch.setattr("api.routes.data_agent.hol_search_agents", lambda query, limit=5: [_Agent()])
    monkeypatch.setattr("api.routes.data_agent.hol_create_session", lambda uaid, transport=None, as_uaid=None: "session-123")
    monkeypatch.setattr(
        "api.routes.data_agent.hol_send_message",
        lambda session_id, message, as_uaid=None: {"reply": "analysis ready", "sessionId": session_id},
    )

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["selected_agent"]["uaid"] == "uaid:aid:hol-data"
    assert payload["session_id"] == "session-123"

    detail = client.get(f"/api/data-agent/datasets/{dataset_id}")
    assert detail.status_code == 200
    hol_sessions = detail.json()["hol_sessions"]
    assert len(hol_sessions) == 1
    assert hol_sessions[0]["session_id"] == "session-123"
    assert hol_sessions[0]["selected_agent"]["uaid"] == "uaid:aid:hol-data"


def test_dataset_hol_use_autodiscovery_skips_broken_adapter_candidate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    class _BrokenAgent:
        uaid = "uaid:aid:broken"
        name = "Broken Agent"
        description = "First candidate fails on broker adapter"
        capabilities = ["data", "analysis"]
        categories = ["Data"]
        transports = []
        pricing = {"rate": 0}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://broken.example.com"
        adapter = "broken-adapter"
        protocol = "broken"

    class _WorkingAgent:
        uaid = "uaid:aid:working"
        name = "Working Agent"
        description = "Second candidate succeeds"
        capabilities = ["data", "analysis"]
        categories = ["Data"]
        transports = []
        pricing = {"rate": 0}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://working.example.com"
        adapter = "working-adapter"
        protocol = "http"

    monkeypatch.setattr(
        "api.routes.data_agent.hol_search_agents",
        lambda query, limit=5: [_BrokenAgent(), _WorkingAgent()],
    )

    def _mock_create_session(uaid, transport=None, as_uaid=None):
        if uaid == "uaid:aid:broken":
            return "session-broken"
        return "session-working"

    def _mock_send_message(session_id, message, as_uaid=None):
        if session_id == "session-broken":
            from shared.hol_client import HolClientError

            raise HolClientError("HOL send_message failed: 500 Internal Server Error: No adapter found for broken-adapter")
        return {"reply": "usable", "sessionId": session_id}

    monkeypatch.setattr("api.routes.data_agent.hol_create_session", _mock_create_session)
    monkeypatch.setattr("api.routes.data_agent.hol_send_message", _mock_send_message)

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_agent"]["uaid"] == "uaid:aid:working"
    assert payload["session_id"] == "session-working"


def test_dataset_hol_use_explicit_uaid_skips_discovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    def _unexpected_search(query, limit=5):
        raise AssertionError("HOL search should be skipped when uaid is explicitly provided")

    monkeypatch.setattr("api.routes.data_agent.hol_search_agents", _unexpected_search)
    monkeypatch.setattr("api.routes.data_agent.hol_create_session", lambda uaid, transport=None, as_uaid=None: "session-explicit")
    monkeypatch.setattr(
        "api.routes.data_agent.hol_send_message",
        lambda session_id, message, as_uaid=None: {"reply": "ok", "sessionId": session_id},
    )

    response = client.post(
        f"/api/data-agent/datasets/{dataset_id}/hol-use",
        json={"uaid": "uaid:aid:explicit"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_agent"]["uaid"] == "uaid:aid:explicit"
    assert payload["session_id"] == "session-explicit"


def test_dataset_hol_use_returns_404_when_no_candidates_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    monkeypatch.setattr("api.routes.data_agent.hol_search_agents", lambda query, limit=5: [])

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "No HOL agents found" in detail["message"]
    assert detail["search_queries"]


def test_dataset_hol_use_filters_non_broker_chatable_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    class _A2AAgent:
        uaid = "uaid:aid:a2a"
        name = "A2A Agent"
        description = "Looks discoverable but not broker-chatable"
        capabilities = ["data"]
        categories = ["Data"]
        transports = []
        pricing = {}
        registry = "broker"
        protocol = "a2a"
        adapter = "a2a-registry-adapter"
        source_url = "https://example.com/a2a"
        available = True
        availability_status = "online"

    class _UAgent:
        uaid = "uaid:aid:uagent"
        name = "UAgent"
        description = "Agentverse style candidate"
        capabilities = ["data"]
        categories = ["Data"]
        transports = []
        pricing = {}
        registry = "broker"
        protocol = "uagent"
        adapter = "agentverse-adapter"
        source_url = "https://example.com/uagent"
        available = True
        availability_status = "online"

    monkeypatch.setattr(
        "api.routes.data_agent.hol_search_agents",
        lambda query, limit=5: [_A2AAgent(), _UAgent()],
    )

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "No broker-chatable HOL agents found" in detail["message"]
    assert len(detail["rejected_candidates"]) == 2


def test_dataset_hol_use_filters_unavailable_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    class _UnavailableAgent:
        uaid = "uaid:aid:unavailable"
        name = "Unavailable Agent"
        description = "Found by search but not marked available"
        capabilities = ["data", "analysis"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = False
        availability_status = "offline"
        source_url = "https://example.com/unavailable"
        adapter = "http-adapter"
        protocol = "http"

    monkeypatch.setattr(
        "api.routes.data_agent.hol_search_agents",
        lambda query, limit=10: [_UnavailableAgent()],
    )

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "No broker-chatable HOL agents found" in detail["message"]
    assert detail["rejected_candidates"][0]["uaid"] == "uaid:aid:unavailable"
    assert "not marked available" in detail["rejected_candidates"][0]["reason"]


def test_dataset_hol_use_returns_502_for_hol_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    upload = _upload_dataset(client)
    dataset_id = upload.json()["id"]

    class _Agent:
        uaid = "uaid:aid:hol-data"
        name = "HOL Data Agent"
        description = "Remote data specialist"
        capabilities = ["data", "analysis"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {"rate": 0}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://example.com/hol-data"
        adapter = "http-adapter"
        protocol = "http"

    monkeypatch.setattr("api.routes.data_agent.hol_search_agents", lambda query, limit=5: [_Agent()])

    def _failing_create_session(uaid, transport=None, as_uaid=None):
        from shared.hol_client import HolClientError

        raise HolClientError("HOL create_session failed: 502 Bad Gateway: upstream HOL registry error page")

    monkeypatch.setattr("api.routes.data_agent.hol_create_session", _failing_create_session)

    response = client.post(f"/api/data-agent/datasets/{dataset_id}/hol-use", json={})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "HOL create_session failed" in detail["message"]
    assert detail["attempted_errors"]


def test_built_in_data_agent_a2a_endpoints_respond(client: TestClient):
    _upload_dataset(client)

    card = client.get("/api/data-agent/agent/.well-known/agent.json")
    assert card.status_code == 200
    assert card.json()["id"] == "data-agent-001"

    message = client.post(
        "/api/data-agent/agent/a2a/v1/messages",
        json={"message": "show me recent failed datasets", "metadata": {"source": "test"}},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["message_id"]
    assert "Synaptica Data Agent dataset summary" in payload["response"]
