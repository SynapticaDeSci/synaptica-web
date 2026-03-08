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
        },
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_dataset_success_and_persists_file(client: TestClient):
    response = _upload_dataset(client)
    assert response.status_code == 201

    payload = response.json()
    assert payload["title"] == "Experiment batch A"
    assert payload["lab_name"] == "NeuroLab"
    assert payload["data_classification"] == "failed"
    assert payload["tags"] == ["rna", "failed-run"]
    assert payload["intended_visibility"] == "private"
    assert payload["message"] == "Dataset uploaded successfully."

    session = SessionLocal()
    try:
        row = session.query(DataAsset).filter(DataAsset.id == payload["id"]).one()
        assert row.filename == "trial.csv"
        assert row.size_bytes == len(b"col1,col2\n1,2\n")
        assert Path(row.stored_path).exists()
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


def test_list_datasets_filters_and_pagination(client: TestClient):
    _upload_dataset(
        client,
        title="Protein run 1",
        data_classification="underused",
        tags="proteomics,archive",
        filename="protein.csv",
    )
    _upload_dataset(
        client,
        title="Failed genome scan",
        data_classification="failed",
        tags="genomics,failed-run",
        filename="genome.csv",
    )
    _upload_dataset(
        client,
        title="Behavioral pilot",
        data_classification="underused",
        tags="behavior,pilot",
        filename="behavior.csv",
    )

    listing = client.get("/api/data-agent/datasets", params={"classification": "underused"})
    assert listing.status_code == 200
    underused = listing.json()
    assert underused["total"] == 2

    searched = client.get("/api/data-agent/datasets", params={"q": "genome"})
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["datasets"][0]["title"] == "Failed genome scan"

    tagged = client.get("/api/data-agent/datasets", params={"tag": "pilot"})
    assert tagged.status_code == 200
    assert tagged.json()["total"] == 1
    assert tagged.json()["datasets"][0]["title"] == "Behavioral pilot"

    paged = client.get("/api/data-agent/datasets", params={"limit": 1, "offset": 1})
    assert paged.status_code == 200
    payload = paged.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert len(payload["datasets"]) == 1


def test_dataset_detail_and_download(client: TestClient):
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
