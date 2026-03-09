import asyncio
import time
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from api.main import app
from agents.executor.tools import research_api_executor
from shared.database import (
    A2AEvent,
    Agent as AgentModel,
    AgentReputation,
    AgentsCacheEntry,
    ExecutionAttempt,
    Payment,
    PaymentStateTransition,
    ResearchRun,
    ResearchRunEdge,
    ResearchRunNode,
    SessionLocal,
    Task,
)
from shared.runtime import load_task_snapshot


ROOT = Path(__file__).resolve().parent.parent


def _reset_runtime_state():
    research_api_executor._agent_cache.clear()
    session = SessionLocal()
    try:
        session.query(ExecutionAttempt).delete()
        session.query(ResearchRunEdge).delete()
        session.query(ResearchRunNode).delete()
        session.query(ResearchRun).delete()
        session.query(PaymentStateTransition).delete()
        session.query(A2AEvent).delete()
        session.query(Payment).delete()
        session.query(Task).delete()
        session.query(AgentsCacheEntry).delete()
        session.query(AgentReputation).delete()
        session.query(AgentModel).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("PAYMENT_MODE", "offline")
    monkeypatch.delenv("X402_OFFLINE", raising=False)
    monkeypatch.setattr("api.main.ensure_registry_cache", lambda: None)
    monkeypatch.setattr("api.routes.agents.ensure_registry_cache", lambda force=False: None)
    monkeypatch.setattr("api.routes.agents.trigger_registry_cache_refresh", lambda: False)
    monkeypatch.setattr("api.routes.agents.get_registry_sync_status", lambda: ("test", None))

    async def _mock_post_agent_request(endpoint, payload):
        request_text = payload.get("request", "")
        if "problem-framer-001" in endpoint:
            return {
                "success": True,
                "agent_id": "problem-framer-001",
                "result": {
                    "research_question": request_text,
                    "keywords": ["desci", "payments", "literature"],
                    "scope": "phase1a",
                },
                "metadata": {},
            }
        if "literature-miner-001" in endpoint:
            return {
                "success": True,
                "agent_id": "literature-miner-001",
                "result": {
                    "papers": [
                        {"title": "Paper A", "source": "arXiv"},
                        {"title": "Paper B", "source": "Semantic Scholar"},
                    ],
                    "sources": ["arXiv", "Semantic Scholar"],
                },
                "metadata": {},
            }
        return {
            "success": True,
            "agent_id": "knowledge-synthesizer-001",
            "result": {
                "summary": "Synthesis complete",
                "key_findings": ["Finding 1", "Finding 2"],
            },
            "metadata": {},
        }

    async def _mock_quality_score(output, phase, agent_role, phase_validation):
        del output, phase, phase_validation
        return {
            "overall_score": 88,
            "dimension_scores": {
                "completeness": 88,
                "correctness": 89,
                "academic_rigor": 86,
                "clarity": 90,
                "innovation": 78,
                "ethics": 92,
            },
            "feedback": f"Verified for {agent_role}",
        }

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _mock_post_agent_request)
    monkeypatch.setattr("agents.orchestrator.tools.agent_tools.calculate_quality_score", _mock_quality_score)

    with TestClient(app) as test_client:
        yield test_client


def _poll_research_run(client: TestClient, research_run_id: str, predicate, timeout: float = 5.0):
    deadline = time.time() + timeout
    last_payload = None
    while time.time() < deadline:
        response = client.get(f"/api/research-runs/{research_run_id}")
        assert response.status_code == 200
        last_payload = response.json()
        if predicate(last_payload):
            return last_payload
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for research run {research_run_id}: {last_payload}")


def test_alembic_upgrade_preserves_phase0_data(tmp_path, monkeypatch):
    db_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    command.upgrade(config, "0bdf6fb7e49d")

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        timestamp = datetime.utcnow()
        conn.execute(
            text(
                "INSERT INTO agents (agent_id, name, agent_type, description, capabilities, "
                "hedera_account_id, status, created_at, meta) "
                "VALUES (:agent_id, :name, :agent_type, :description, :capabilities, "
                ":hedera_account_id, :status, :created_at, :meta)"
            ),
            [
                {
                    "agent_id": "orchestrator-agent",
                    "name": "Orchestrator",
                    "agent_type": "orchestrator",
                    "description": "Coordinates work",
                    "capabilities": '["planning"]',
                    "hedera_account_id": None,
                    "status": "active",
                    "created_at": timestamp,
                    "meta": "{}",
                },
                {
                    "agent_id": "problem-framer-001",
                    "name": "Problem Framer",
                    "agent_type": "research",
                    "description": "Frames the problem",
                    "capabilities": '["problem-framing"]',
                    "hedera_account_id": "0.0.7001",
                    "status": "active",
                    "created_at": timestamp,
                    "meta": '{"support_tier":"supported"}',
                },
            ],
        )
        conn.execute(
            text(
                "INSERT INTO tasks (id, title, description, status, created_by, created_at, updated_at, meta) "
                "VALUES (:id, :title, :description, :status, :created_by, :created_at, :updated_at, :meta)"
            ),
            {
                "id": "task-preexisting",
                "title": "Preexisting Task",
                "description": "Phase 0 task before research runs",
                "status": "completed",
                "created_by": "orchestrator-agent",
                "created_at": timestamp,
                "updated_at": timestamp,
                "meta": '{"runtime":{"status":"completed","progress":[],"progress_snapshot":{}}}',
            },
        )
        conn.execute(
            text(
                "INSERT INTO payments (id, task_id, from_agent_id, to_agent_id, amount, currency, status, created_at, meta) "
                "VALUES (:id, :task_id, :from_agent_id, :to_agent_id, :amount, :currency, :status, :created_at, :meta)"
            ),
            {
                "id": "payment-preexisting",
                "task_id": "task-preexisting",
                "from_agent_id": "orchestrator-agent",
                "to_agent_id": "problem-framer-001",
                "amount": 5.0,
                "currency": "HBAR",
                "status": "completed",
                "created_at": timestamp,
                "meta": "{}",
            },
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "research_runs" in inspector.get_table_names()
    assert "research_run_nodes" in inspector.get_table_names()
    assert "research_run_edges" in inspector.get_table_names()
    assert "execution_attempts" in inspector.get_table_names()

    with engine.connect() as conn:
        task_row = conn.execute(
            text("SELECT id, title, status FROM tasks WHERE id = :task_id"),
            {"task_id": "task-preexisting"},
        ).mappings().one()
        payment_row = conn.execute(
            text("SELECT id, task_id, status FROM payments WHERE id = :payment_id"),
            {"payment_id": "payment-preexisting"},
        ).mappings().one()

    assert task_row["title"] == "Preexisting Task"
    assert payment_row["task_id"] == "task-preexisting"


def test_create_research_run_completes_and_persists_graph(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={
            "description": "Review literature on autonomous agent payments in DeSci.",
            "budget_limit": 25.0,
            "verification_mode": "standard",
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["workflow_template"] == "phase1a_literature_review"
    assert len(payload["nodes"]) == 3
    assert len(payload["edges"]) == 2

    completed = _poll_research_run(
        client,
        payload["id"],
        lambda item: item["status"] == "completed",
    )

    assert completed["workflow"] == (
        "problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001"
    )
    assert completed["result"]["report"]["summary"] == "Synthesis complete"
    assert [node["status"] for node in completed["nodes"]] == [
        "completed",
        "completed",
        "completed",
    ]
    assert all(node["task_id"] for node in completed["nodes"])
    assert all(node["payment_id"] for node in completed["nodes"])


def test_research_run_blocks_downstream_nodes_after_failure(client: TestClient, monkeypatch):
    original_post_agent_request = research_api_executor._post_agent_request

    async def _failing_post_agent_request(endpoint, payload):
        if "literature-miner-001" in endpoint:
            return {
                "success": False,
                "agent_id": "literature-miner-001",
                "error": "literature API unavailable",
            }
        return await original_post_agent_request(endpoint, payload)

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _failing_post_agent_request)

    response = client.post(
        "/api/research-runs",
        json={"description": "Research resilient agentic literature workflows."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    failed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "failed",
    )

    statuses = {node["node_id"]: node["status"] for node in failed["nodes"]}
    assert statuses["problem_framing"] == "completed"
    assert statuses["literature_mining"] == "failed"
    assert statuses["knowledge_synthesis"] == "blocked"


def test_research_run_waits_for_human_review_and_resumes(client: TestClient, monkeypatch):
    async def _review_required_score(output, phase, agent_role, phase_validation):
        del output, phase, phase_validation
        if agent_role == "knowledge-synthesizer-001":
            return {
                "overall_score": 45,
                "dimension_scores": {
                    "completeness": 40,
                    "correctness": 45,
                    "academic_rigor": 42,
                    "clarity": 50,
                    "innovation": 48,
                    "ethics": 90,
                },
                "feedback": "Needs human review",
            }
        return {
            "overall_score": 88,
            "dimension_scores": {
                "completeness": 88,
                "correctness": 89,
                "academic_rigor": 86,
                "clarity": 90,
                "innovation": 78,
                "ethics": 92,
            },
            "feedback": f"Verified for {agent_role}",
        }

    async def _fast_wait_for_human_decision(task_id: str, timeout: int = 3600):
        deadline = time.time() + min(timeout, 5)
        while time.time() < deadline:
            snapshot = load_task_snapshot(task_id)
            if snapshot and snapshot.get("verification_decision"):
                return snapshot["verification_decision"]
            await asyncio.sleep(0.01)
        return {"approved": False, "reason": "Verification timeout"}

    monkeypatch.setattr("agents.orchestrator.tools.agent_tools.calculate_quality_score", _review_required_score)
    monkeypatch.setattr("agents.orchestrator.tools.agent_tools._wait_for_human_decision", _fast_wait_for_human_decision)

    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on reproducible DeSci payment verification."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    waiting = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "waiting_for_review",
        timeout=10.0,
    )

    waiting_node = next(node for node in waiting["nodes"] if node["status"] == "waiting_for_review")
    approve = client.post(f"/api/tasks/{waiting_node['task_id']}/approve_verification")
    assert approve.status_code == 200
    assert approve.json()["success"] is True

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
        timeout=10.0,
    )
    assert completed["result"]["report"]["summary"] == "Synthesis complete"
