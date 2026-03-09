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
from shared.research_runs.planner import (
    ResearchMode,
    build_research_run_profile,
    classify_research_mode,
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
        context = payload.get("context") or {}
        request_text = payload.get("request", "")
        node_strategy = context.get("node_strategy")

        if "problem-framer-001" in endpoint or node_strategy == "plan_query":
            return {
                "success": True,
                "agent_id": "problem-framer-001",
                "result": {
                    "query": context.get("original_description", request_text),
                    "research_question": request_text,
                    "keywords": ["desci", "payments", "literature"],
                    "subquestions": ["What matters?", "Which sources matter most?"],
                    "search_queries": [{"role": "academic-scout", "query": "query"}],
                    "source_requirements": context.get("source_requirements") or {},
                    "rounds_planned": context.get("rounds_planned") or {},
                },
                "metadata": {},
            }

        if "literature-miner-001" in endpoint and node_strategy == "gather_evidence":
            evidence_rounds = int((context.get("rounds_planned") or {}).get("evidence_rounds", 1) or 1)
            return {
                "success": True,
                "agent_id": "literature-miner-001",
                "result": {
                    "sources": [
                        {
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                            "snippet": "Oil prices jumped on escalation.",
                            "display_snippet": "Oil prices jumped on escalation.",
                            "relevance_score": 0.94,
                            "quality_flags": [],
                        },
                        {
                            "title": "Reuters report",
                            "url": "https://www.reuters.com/world/example",
                            "publisher": "Reuters",
                            "published_at": "2026-03-09T01:00:00+00:00",
                            "source_type": "primary",
                            "snippet": "Market reaction to the conflict.",
                            "display_snippet": "Market reaction to the conflict.",
                            "relevance_score": 0.93,
                            "quality_flags": [],
                        },
                        {
                            "title": "AP report",
                            "url": "https://apnews.com/example",
                            "publisher": "AP",
                            "published_at": "2026-03-08T23:30:00+00:00",
                            "source_type": "news",
                            "snippet": "Regional escalation drives risk premium.",
                            "display_snippet": "Regional escalation drives risk premium.",
                            "relevance_score": 0.91,
                            "quality_flags": [],
                        },
                        {
                            "title": "OPEC market note",
                            "url": "https://www.opec.org/example",
                            "publisher": "OPEC",
                            "published_at": "2026-03-08T20:00:00+00:00",
                            "source_type": "primary",
                            "snippet": "Supply and spare-capacity commentary.",
                            "display_snippet": "Supply and spare-capacity commentary.",
                            "relevance_score": 0.88,
                            "quality_flags": [],
                        },
                        {
                            "title": "Academic context paper",
                            "url": "https://doi.org/10.1234/example",
                            "publisher": "doi.org",
                            "published_at": "2024-05-11T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Historical evidence on geopolitical oil shocks.",
                            "display_snippet": "Historical evidence on geopolitical oil shocks.",
                            "relevance_score": 0.82,
                            "quality_flags": [],
                        },
                        {
                            "title": "FT market analysis",
                            "url": "https://www.ft.com/example",
                            "publisher": "Financial Times",
                            "published_at": "2026-03-09T03:00:00+00:00",
                            "source_type": "news",
                            "snippet": "Asian markets reacted sharply.",
                            "display_snippet": "Asian markets reacted sharply.",
                            "relevance_score": 0.87,
                            "quality_flags": [],
                        },
                    ],
                    "rounds_completed": {
                        "evidence_rounds": evidence_rounds,
                        "critique_rounds": 0,
                    },
                },
                "metadata": {},
            }

        if "literature-miner-001" in endpoint and node_strategy == "curate_sources":
            return {
                "success": True,
                "agent_id": "literature-miner-001",
                "result": {
                    "sources": [
                        {
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                            "snippet": "Oil prices jumped on escalation.",
                            "display_snippet": "Oil prices jumped on escalation.",
                            "relevance_score": 0.94,
                            "quality_flags": [],
                        },
                        {
                            "title": "Reuters report",
                            "url": "https://www.reuters.com/world/example",
                            "publisher": "Reuters",
                            "published_at": "2026-03-09T01:00:00+00:00",
                            "source_type": "primary",
                            "snippet": "Market reaction to the conflict.",
                            "display_snippet": "Market reaction to the conflict.",
                            "relevance_score": 0.93,
                            "quality_flags": [],
                        },
                        {
                            "title": "Academic context paper",
                            "url": "https://doi.org/10.1234/example",
                            "publisher": "doi.org",
                            "published_at": "2024-05-11T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Historical evidence on geopolitical oil shocks.",
                            "display_snippet": "Historical evidence on geopolitical oil shocks.",
                            "relevance_score": 0.82,
                            "quality_flags": [],
                        },
                        {
                            "title": "FT market analysis",
                            "url": "https://www.ft.com/example",
                            "publisher": "Financial Times",
                            "published_at": "2026-03-09T03:00:00+00:00",
                            "source_type": "news",
                            "snippet": "Asian markets reacted sharply.",
                            "display_snippet": "Asian markets reacted sharply.",
                            "relevance_score": 0.87,
                            "quality_flags": [],
                        },
                        {
                            "title": "AP report",
                            "url": "https://apnews.com/example",
                            "publisher": "AP",
                            "published_at": "2026-03-08T23:30:00+00:00",
                            "source_type": "news",
                            "snippet": "Regional escalation drives risk premium.",
                            "display_snippet": "Regional escalation drives risk premium.",
                            "relevance_score": 0.91,
                            "quality_flags": [],
                        },
                        {
                            "title": "OPEC market note",
                            "url": "https://www.opec.org/example",
                            "publisher": "OPEC",
                            "published_at": "2026-03-08T20:00:00+00:00",
                            "source_type": "primary",
                            "snippet": "Supply and spare-capacity commentary.",
                            "display_snippet": "Supply and spare-capacity commentary.",
                            "relevance_score": 0.88,
                            "quality_flags": [],
                        },
                    ],
                    "citations": [
                        {
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                        },
                        {
                            "title": "Reuters report",
                            "url": "https://www.reuters.com/world/example",
                            "publisher": "Reuters",
                            "published_at": "2026-03-09T01:00:00+00:00",
                            "source_type": "primary",
                        },
                    ],
                    "source_summary": {
                        "total_sources": 6,
                        "academic_or_primary_sources": 3,
                        "fresh_sources": 5,
                        "requirements_met": True,
                    },
                    "freshness_summary": {
                        "required": bool(context.get("freshness_required")),
                        "window_days": 7,
                        "minimum_fresh_sources": (context.get("source_requirements") or {}).get("min_fresh_sources", 0),
                        "fresh_sources": 5,
                        "requirements_met": True,
                        "issues": [],
                    },
                    "rounds_completed": {
                        "evidence_rounds": int((context.get("rounds_planned") or {}).get("evidence_rounds", 1) or 1),
                        "critique_rounds": 0,
                    },
                    "filtered_sources": [],
                },
                "metadata": {},
            }

        if "knowledge-synthesizer-001" in endpoint and node_strategy == "draft_synthesis":
            return {
                "success": True,
                "agent_id": "knowledge-synthesizer-001",
                "result": {
                    "answer": "## Summary\n\nAs of March 9, 2026, the freshest reporting indicates the conflict pushed oil prices higher through immediate risk premia and supply fears.",
                    "answer_markdown": "## Summary\n\nAs of March 9, 2026, the freshest reporting indicates the conflict pushed oil prices higher through immediate risk premia and supply fears.",
                    "claims": [
                        {
                            "claim": "Oil prices rose immediately on escalation.",
                            "supporting_citations": ["Channel News Asia report", "Reuters report"],
                            "confidence": "high",
                        }
                    ],
                    "limitations": ["The situation is evolving quickly."],
                    "citations": [
                        {
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                        }
                    ],
                    "source_summary": {
                        "total_sources": 6,
                        "academic_or_primary_sources": 3,
                        "fresh_sources": 5,
                        "requirements_met": True,
                    },
                    "freshness_summary": {
                        "required": bool(context.get("freshness_required")),
                        "window_days": 7,
                        "minimum_fresh_sources": (context.get("source_requirements") or {}).get("min_fresh_sources", 0),
                        "fresh_sources": 5,
                        "requirements_met": True,
                        "issues": [],
                    },
                    "sources": context.get("curated_sources", {}).get("sources", []),
                    "rounds_completed": {
                        "evidence_rounds": int((context.get("rounds_planned") or {}).get("evidence_rounds", 1) or 1),
                        "critique_rounds": 0,
                    },
                },
                "metadata": {},
            }

        if "knowledge-synthesizer-001" in endpoint and node_strategy == "critique_and_fact_check":
            return {
                "success": True,
                "agent_id": "knowledge-synthesizer-001",
                "result": {
                    "critic_findings": [
                        {
                            "issue": "Add a stronger caveat about continuing volatility.",
                            "severity": "medium",
                            "recommendation": "Make the live uncertainty explicit in the lead paragraph.",
                        }
                    ],
                    "rounds_completed": {
                        "evidence_rounds": int((context.get("rounds_planned") or {}).get("evidence_rounds", 1) or 1),
                        "critique_rounds": int((context.get("rounds_planned") or {}).get("critique_rounds", 1) or 1),
                    },
                },
                "metadata": {},
            }

        return {
            "success": True,
            "agent_id": "knowledge-synthesizer-001",
                "result": {
                "answer": "## Summary\n\nAs of March 9, 2026, the available reporting points to a sharp oil-price response driven by immediate supply-risk pricing, while longer-run effects remain uncertain.",
                "answer_markdown": "## Summary\n\nAs of March 9, 2026, the available reporting points to a sharp oil-price response driven by immediate supply-risk pricing, while longer-run effects remain uncertain.",
                "claims": [
                    {
                        "claim": "Markets priced in immediate supply and shipping risk.",
                        "supporting_citations": ["Channel News Asia report", "Reuters report"],
                        "confidence": "high",
                    }
                ],
                "limitations": ["The event is still developing and numbers may move quickly."],
                "critic_findings": [
                    {
                        "issue": "Add a stronger uncertainty caveat.",
                        "severity": "medium",
                        "recommendation": "State that the answer is current only as of March 9, 2026.",
                    }
                ],
                "citations": [
                    {
                        "title": "Channel News Asia report",
                        "url": "https://www.channelnewsasia.com/world/example",
                        "publisher": "Channel News Asia",
                        "published_at": "2026-03-09T02:00:00+00:00",
                        "source_type": "news",
                    },
                    {
                        "title": "Reuters report",
                        "url": "https://www.reuters.com/world/example",
                        "publisher": "Reuters",
                        "published_at": "2026-03-09T01:00:00+00:00",
                        "source_type": "primary",
                    },
                ],
                "source_summary": {
                    "total_sources": 6,
                    "academic_or_primary_sources": 3,
                    "fresh_sources": 5,
                    "requirements_met": True,
                },
                "freshness_summary": {
                    "required": bool(context.get("freshness_required")),
                    "window_days": 7,
                    "minimum_fresh_sources": (context.get("source_requirements") or {}).get("min_fresh_sources", 0),
                    "fresh_sources": 5,
                    "requirements_met": True,
                    "issues": [],
                },
                "sources": context.get("curated_sources", {}).get("sources", []),
                "rounds_completed": {
                    "evidence_rounds": int((context.get("rounds_planned") or {}).get("evidence_rounds", 1) or 1),
                    "critique_rounds": int((context.get("rounds_planned") or {}).get("critique_rounds", 1) or 1),
                },
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
    assert payload["workflow_template"] == "phase1c_literature_standard"
    assert payload["classified_mode"] == "literature"
    assert payload["depth_mode"] == "standard"
    assert payload["rounds_planned"] == {"evidence_rounds": 1, "critique_rounds": 1}
    assert len(payload["nodes"]) == 6
    assert len(payload["edges"]) == 5

    completed = _poll_research_run(
        client,
        payload["id"],
        lambda item: item["status"] == "completed",
    )

    assert completed["workflow"] == (
        "plan_query -> gather_evidence -> curate_sources -> draft_synthesis -> "
        "critique_and_fact_check -> revise_final_answer"
    )
    assert "As of March 9, 2026" in completed["result"]["answer"]
    assert completed["result"]["answer_markdown"].startswith("## Summary")
    assert len(completed["result"]["citations"]) >= 2
    assert completed["result"]["source_summary"]["total_sources"] == 6
    assert completed["rounds_completed"] == {"evidence_rounds": 1, "critique_rounds": 1}
    assert all(node["status"] == "completed" for node in completed["nodes"])
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
    assert statuses["plan_query"] == "completed"
    assert statuses["gather_evidence"] == "failed"
    assert statuses["curate_sources"] == "blocked"
    assert statuses["revise_final_answer"] == "blocked"


def test_research_run_waits_for_human_review_and_resumes(client: TestClient, monkeypatch):
    score_calls = {"knowledge": 0}

    async def _review_required_score(output, phase, agent_role, phase_validation):
        del output, phase, phase_validation
        if agent_role == "knowledge-synthesizer-001":
            score_calls["knowledge"] += 1
            if score_calls["knowledge"] > 1:
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
                    "feedback": "Recovered after human review",
                }
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
    assert "As of March 9, 2026" in completed["result"]["answer"]


def test_query_classifier_detects_live_and_hybrid_modes():
    assert classify_research_mode(
        "What is the impact of the 2026 Iran war on oil prices today?"
    ) == ResearchMode.LIVE_ANALYSIS
    assert classify_research_mode(
        "Review the literature on autonomous agent payments in DeSci."
    ) == ResearchMode.LITERATURE
    assert classify_research_mode(
        "Compare current tariffs news with the historical literature on supply-chain policy."
    ) == ResearchMode.HYBRID


def test_build_research_run_profile_accepts_string_modes():
    profile = build_research_run_profile(
        "What is the impact of the 2026 Iran war on oil prices today?",
        research_mode="auto",
        depth_mode="deep",
    )

    assert profile.requested_mode == ResearchMode.AUTO
    assert profile.classified_mode == ResearchMode.LIVE_ANALYSIS
    assert profile.depth_mode.value == "deep"
    assert profile.freshness_required is True


def test_deep_research_run_tracks_extra_rounds(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={
            "description": "Review literature on autonomous agent payments in DeSci.",
            "depth_mode": "deep",
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["depth_mode"] == "deep"
    assert payload["rounds_planned"] == {"evidence_rounds": 2, "critique_rounds": 2}

    completed = _poll_research_run(
        client,
        payload["id"],
        lambda item: item["status"] == "completed",
    )
    assert completed["rounds_completed"] == {"evidence_rounds": 2, "critique_rounds": 2}
    gather_node = next(node for node in completed["nodes"] if node["node_id"] == "gather_evidence")
    assert gather_node["result"]["rounds_completed"]["evidence_rounds"] == 2


def test_live_analysis_fails_when_fresh_evidence_is_missing(client: TestClient, monkeypatch):
    original_post_agent_request = research_api_executor._post_agent_request

    async def _stale_live_post_agent_request(endpoint, payload):
        context = payload.get("context") or {}
        if context.get("classified_mode") == "live_analysis" and context.get("node_strategy") == "curate_sources":
            return {
                "success": False,
                "agent_id": "literature-miner-001",
                "error": "insufficient_fresh_evidence",
            }
        return await original_post_agent_request(endpoint, payload)

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _stale_live_post_agent_request)

    response = client.post(
        "/api/research-runs",
        json={
            "description": "What is the impact of the 2026 Iran war on oil prices today?",
            "research_mode": "auto",
        },
    )
    assert response.status_code == 202

    failed = _poll_research_run(
        client,
        response.json()["id"],
        lambda item: item["status"] == "failed",
    )
    assert failed["classified_mode"] == "live_analysis"
    assert "insufficient_fresh_evidence" in (failed["error"] or "")
