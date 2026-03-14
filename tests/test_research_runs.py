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
from agents.orchestrator.tools.agent_tools import _evaluate_research_quality_contract
from agents.research.phase2_knowledge.literature_miner.agent import LiteratureMinerAgent
from shared.database import (
    A2AEvent,
    Agent as AgentModel,
    AgentPaymentProfile,
    AgentReputation,
    AgentsCacheEntry,
    Base,
    Claim,
    ClaimLink,
    EvidenceArtifact,
    ExecutionAttempt,
    Payment,
    PaymentNotification,
    PaymentReconciliation,
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
        session.query(ClaimLink).delete()
        session.query(Claim).delete()
        session.query(EvidenceArtifact).delete()
        session.query(ExecutionAttempt).delete()
        session.query(ResearchRunEdge).delete()
        session.query(ResearchRunNode).delete()
        session.query(ResearchRun).delete()
        session.query(PaymentReconciliation).delete()
        session.query(PaymentNotification).delete()
        session.query(PaymentStateTransition).delete()
        session.query(A2AEvent).delete()
        session.query(Payment).delete()
        session.query(Task).delete()
        session.query(AgentPaymentProfile).delete()
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
                    "rewritten_research_brief": f"Investigate: {request_text}",
                    "keywords": ["desci", "payments", "literature"],
                    "subquestions": ["What matters?", "Which sources matter most?"],
                    "search_queries": [{"role": "academic-scout", "lane": "core-literature", "query": "query"}],
                    "search_lanes": [
                        {"lane": "core-literature", "objective": "Cover the strongest academic background."}
                    ],
                    "success_criteria": [
                        "Use source-backed claims.",
                        "Highlight uncertainties.",
                    ],
                    "claim_targets": [
                        {
                            "claim_id": "C1",
                            "claim_target": "Direct answer to the research question.",
                            "lane": "core-answer",
                            "priority": "high",
                        },
                        {
                            "claim_id": "C2",
                            "claim_target": "Important limitation or uncertainty.",
                            "lane": "uncertainty",
                            "priority": "high",
                        },
                        {
                            "claim_id": "C3",
                            "claim_target": "Most consistent finding across the strongest literature.",
                            "lane": "core-literature",
                            "priority": "high",
                        },
                    ],
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
                    "search_lanes_used": ["breaking-developments", "official-confirmation", "market-data-confirmation"],
                    "coverage_summary": {
                        "source_summary": {
                            "total_sources": 6,
                            "academic_or_primary_sources": 3,
                            "fresh_sources": 5,
                            "requirements_met": True,
                        },
                        "source_diversity": {
                            "publishers": 6,
                            "source_types": 3,
                        },
                        "covered_claim_ids": ["C1", "C2", "C3"],
                        "uncovered_claim_targets": [],
                        "ready_for_synthesis": True,
                    },
                    "uncovered_claim_targets": [],
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
                            "citation_id": "S1",
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
                            "citation_id": "S2",
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
                            "citation_id": "S3",
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
                            "citation_id": "S4",
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
                            "citation_id": "S5",
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
                            "citation_id": "S6",
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
                            "citation_id": "S1",
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                        },
                        {
                            "citation_id": "S2",
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
                    "coverage_summary": {
                        "source_summary": {
                            "total_sources": 6,
                            "academic_or_primary_sources": 3,
                            "fresh_sources": 5,
                            "requirements_met": True,
                        },
                        "source_diversity": {
                            "publishers": 6,
                            "source_types": 3,
                            "fresh_sources": 5,
                            "academic_or_primary_sources": 3,
                        },
                        "citation_count": 2,
                        "citation_ready": True,
                    },
                    "uncovered_claim_targets": [],
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
                    "answer": (
                        "## Summary\n\nAs of March 9, 2026, the freshest reporting indicates oil prices moved higher as the conflict intensified. [S1][S2]\n\n"
                        "## Evidence\n\nRecent reporting tied the move to immediate risk premia, supply fears, and market volatility. [S1][S2]\n\n"
                        "## Limitations\n\nThe situation is evolving quickly, so the reported impact may change as new evidence emerges. [S1]"
                    ),
                    "answer_markdown": (
                        "## Summary\n\nAs of March 9, 2026, the freshest reporting indicates oil prices moved higher as the conflict intensified. [S1][S2]\n\n"
                        "## Evidence\n\nRecent reporting tied the move to immediate risk premia, supply fears, and market volatility. [S1][S2]\n\n"
                        "## Limitations\n\nThe situation is evolving quickly, so the reported impact may change as new evidence emerges. [S1]"
                    ),
                    "claims": [
                        {
                            "claim_id": "C1",
                            "claim": "Oil prices rose immediately on escalation.",
                            "supporting_citation_ids": ["S1", "S2"],
                            "confidence": "high",
                        },
                        {
                            "claim_id": "C2",
                            "claim": "The evidence base is still evolving quickly.",
                            "supporting_citation_ids": ["S1"],
                            "confidence": "medium",
                        },
                        {
                            "claim_id": "C3",
                            "claim": "Reported market volatility reflects immediate supply-risk pricing.",
                            "supporting_citation_ids": ["S1", "S2"],
                            "confidence": "high",
                        }
                    ],
                    "limitations": ["The situation is evolving quickly."],
                    "citations": [
                        {
                            "citation_id": "S1",
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
                    "quality_summary": {
                        "citation_coverage": 1.0,
                        "uncovered_claims": [],
                        "source_diversity": {
                            "publishers": 6,
                            "source_types": 3,
                        },
                        "verification_notes": [],
                        "strict_live_analysis_checks_passed": True,
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
                    "answer": (
                        "## Summary\n\nAs of March 9, 2026, the available reporting points to a sharp oil-price response driven by immediate supply-risk pricing, while longer-run effects remain uncertain. [S1][S2]\n\n"
                        "## Evidence\n\nRecent reporting described rising crude prices, shipping-risk concerns, and a broader market reaction tied to the conflict. [S1][S2]\n\n"
                        "## Limitations\n\nThe event is still developing, and benchmark-specific price levels may move quickly as new reporting arrives. [S1]"
                    ),
                    "answer_markdown": (
                        "## Summary\n\nAs of March 9, 2026, the available reporting points to a sharp oil-price response driven by immediate supply-risk pricing, while longer-run effects remain uncertain. [S1][S2]\n\n"
                        "## Evidence\n\nRecent reporting described rising crude prices, shipping-risk concerns, and a broader market reaction tied to the conflict. [S1][S2]\n\n"
                        "## Limitations\n\nThe event is still developing, and benchmark-specific price levels may move quickly as new reporting arrives. [S1]"
                    ),
                    "claims": [
                        {
                            "claim_id": "C1",
                            "claim": "Markets priced in immediate supply and shipping risk.",
                            "supporting_citation_ids": ["S1", "S2"],
                            "confidence": "high",
                        },
                        {
                            "claim_id": "C2",
                            "claim": "The answer reflects evidence available on March 9, 2026.",
                            "supporting_citation_ids": ["S1"],
                            "confidence": "medium",
                        },
                        {
                            "claim_id": "C3",
                            "claim": "Longer-run effects remain uncertain while the conflict evolves.",
                            "supporting_citation_ids": ["S1"],
                            "confidence": "medium",
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
                            "citation_id": "S1",
                            "title": "Channel News Asia report",
                            "url": "https://www.channelnewsasia.com/world/example",
                            "publisher": "Channel News Asia",
                            "published_at": "2026-03-09T02:00:00+00:00",
                            "source_type": "news",
                        },
                        {
                            "citation_id": "S2",
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
                    "quality_summary": {
                        "citation_coverage": 1.0,
                        "uncovered_claims": [],
                        "source_diversity": {
                            "publishers": 6,
                            "source_types": 3,
                            "fresh_sources": 5,
                            "academic_or_primary_sources": 3,
                        },
                        "verification_notes": [],
                        "strict_live_analysis_checks_passed": True,
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
    assert "evidence_artifacts" in inspector.get_table_names()
    assert "claims" in inspector.get_table_names()
    assert "claim_links" in inspector.get_table_names()
    assert "agent_payment_profiles" in inspector.get_table_names()
    assert "payment_notifications" in inspector.get_table_names()
    assert "payment_reconciliations" in inspector.get_table_names()

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


def test_alembic_upgrade_is_idempotent_for_precreated_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "migration-precreated.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()
    assert "research_runs" in inspector.get_table_names()
    assert "evidence_artifacts" in inspector.get_table_names()
    assert "claims" in inspector.get_table_names()
    assert "claim_links" in inspector.get_table_names()
    assert "agent_payment_profiles" in inspector.get_table_names()


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
    assert payload["workflow_template"] == "phase1e_literature_standard"
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
    assert completed["result"]["quality_summary"]["citation_coverage"] == 1.0
    assert completed["result"]["quality_summary"]["strict_live_analysis_checks_passed"] is True
    assert all(claim["supporting_citation_ids"] for claim in completed["result"]["claims"])
    assert completed["result"]["source_summary"]["total_sources"] == 6
    assert completed["rounds_completed"] == {"evidence_rounds": 1, "critique_rounds": 1}
    assert all(node["status"] == "completed" for node in completed["nodes"])
    assert all(node["task_id"] for node in completed["nodes"])
    assert all(node["payment_id"] for node in completed["nodes"])


def test_research_run_evidence_and_report_routes(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
    )
    assert completed["status"] == "completed"

    evidence_response = client.get(f"/api/research-runs/{research_run_id}/evidence")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["rewritten_research_brief"].startswith("Investigate:")
    assert len(evidence_payload["sources"]) >= 6
    assert len(evidence_payload["citations"]) >= 2
    assert evidence_payload["coverage_summary"]["ready_for_synthesis"] is True

    report_response = client.get(f"/api/research-runs/{research_run_id}/report")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["answer_markdown"].startswith("## Summary")
    assert len(report_payload["claims"]) >= 3
    assert len(report_payload["critic_findings"]) >= 1
    assert report_payload["quality_summary"]["citation_coverage"] == 1.0


def test_research_run_persists_phase2_evidence_graph_records(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
    )
    assert completed["status"] == "completed"

    session = SessionLocal()
    try:
        artifacts = (
            session.query(EvidenceArtifact)
            .filter(EvidenceArtifact.research_run_id == research_run_id)
            .order_by(EvidenceArtifact.order_index.asc(), EvidenceArtifact.id.asc())
            .all()
        )
        claims = (
            session.query(Claim)
            .filter(Claim.research_run_id == research_run_id)
            .order_by(Claim.claim_order.asc(), Claim.id.asc())
            .all()
        )
        links = (
            session.query(ClaimLink)
            .filter(ClaimLink.research_run_id == research_run_id)
            .order_by(ClaimLink.claim_id.asc(), ClaimLink.link_order.asc(), ClaimLink.id.asc())
            .all()
        )
    finally:
        session.close()

    assert [artifact.artifact_key for artifact in artifacts] == [f"S{index}" for index in range(1, 7)]
    assert [artifact.curation_status for artifact in artifacts] == [
        "cited",
        "cited",
        "selected",
        "selected",
        "selected",
        "selected",
    ]
    assert [claim.claim_id for claim in claims] == ["C1", "C2", "C3"]
    assert [claim.claim for claim in claims] == [
        "Markets priced in immediate supply and shipping risk.",
        "The answer reflects evidence available on March 9, 2026.",
        "Longer-run effects remain uncertain while the conflict evolves.",
    ]
    assert len(links) == 4
    assert [link.artifact_key for link in links if link.claim_id == "C1"] == ["S1", "S2"]


def test_research_run_evidence_graph_and_report_pack_routes(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
    )
    assert completed["status"] == "completed"

    graph_response = client.get(f"/api/research-runs/{research_run_id}/evidence-graph")
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["schema_version"] == "phase2.v1"
    assert graph_payload["summary"] == {
        "artifact_count": 6,
        "cited_artifact_count": 2,
        "filtered_artifact_count": 0,
        "claim_count": 3,
        "link_count": 4,
    }
    assert [artifact["artifact_key"] for artifact in graph_payload["artifacts"]] == [
        f"S{index}" for index in range(1, 7)
    ]
    assert [claim["claim_id"] for claim in graph_payload["claims"]] == ["C1", "C2", "C3"]
    assert graph_payload["claims"][0]["supporting_citation_ids"] == ["S1", "S2"]
    assert graph_payload["claims"][2]["supporting_citation_ids"] == ["S1"]
    assert graph_payload["links"][0] == {
        "claim_id": "C1",
        "artifact_key": "S1",
        "citation_id": "S1",
        "relation_type": "supports",
        "link_order": 1,
    }

    report_pack_response = client.get(f"/api/research-runs/{research_run_id}/report-pack")
    assert report_pack_response.status_code == 200
    report_pack_payload = report_pack_response.json()
    assert report_pack_payload["schema_version"] == "phase2.v1"
    assert report_pack_payload["generated_at"]
    assert report_pack_payload["rewritten_research_brief"].startswith("Investigate:")
    assert report_pack_payload["answer_markdown"].startswith("## Summary")
    assert [claim["claim_id"] for claim in report_pack_payload["claims"]] == ["C1", "C2", "C3"]
    assert [citation["artifact_key"] for citation in report_pack_payload["citations"]] == ["S1", "S2"]
    assert [item["artifact_key"] for item in report_pack_payload["supporting_evidence"]] == ["S1", "S2"]
    assert len(report_pack_payload["claim_lineage"]) == 4
    assert report_pack_payload["quality_summary"]["citation_coverage"] == 1.0


def test_research_run_evidence_graph_uses_persisted_artifacts_before_completion(
    client: TestClient, monkeypatch
):
    original_post_agent_request = research_api_executor._post_agent_request
    gate = asyncio.Event()

    async def _slow_draft_node(endpoint, payload):
        context = payload.get("context") or {}
        if context.get("node_strategy") == "draft_synthesis":
            await gate.wait()
        return await original_post_agent_request(endpoint, payload)

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _slow_draft_node)

    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    in_flight = _poll_research_run(
        client,
        research_run_id,
        lambda item: any(
            node["node_id"] == "draft_synthesis" and node["status"] == "running"
            for node in item["nodes"]
        ),
        timeout=10.0,
    )
    assert in_flight["status"] == "running"

    graph_response = client.get(f"/api/research-runs/{research_run_id}/evidence-graph")
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["status"] == "running"
    assert graph_payload["summary"]["artifact_count"] == 6
    assert graph_payload["summary"]["claim_count"] == 0
    assert graph_payload["summary"]["link_count"] == 0
    assert graph_payload["artifacts"][0]["artifact_key"] == "S1"

    gate.set()

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
        timeout=10.0,
    )
    assert completed["status"] == "completed"


def test_phase2_graph_routes_return_409_for_legacy_runs_without_backfill(client: TestClient):
    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
    )
    assert completed["status"] == "completed"

    session = SessionLocal()
    try:
        run_record = session.query(ResearchRun).filter(ResearchRun.id == research_run_id).one()
        run_meta = dict(run_record.meta or {})
        run_meta.pop("evidence_graph_schema_version", None)
        run_record.meta = run_meta
        session.query(ClaimLink).filter(ClaimLink.research_run_id == research_run_id).delete(
            synchronize_session=False
        )
        session.query(Claim).filter(Claim.research_run_id == research_run_id).delete(
            synchronize_session=False
        )
        session.query(EvidenceArtifact).filter(
            EvidenceArtifact.research_run_id == research_run_id
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()

    evidence_response = client.get(f"/api/research-runs/{research_run_id}/evidence")
    assert evidence_response.status_code == 200
    report_response = client.get(f"/api/research-runs/{research_run_id}/report")
    assert report_response.status_code == 200

    graph_response = client.get(f"/api/research-runs/{research_run_id}/evidence-graph")
    assert graph_response.status_code == 409
    assert "Rerun the research job" in graph_response.json()["detail"]

    report_pack_response = client.get(f"/api/research-runs/{research_run_id}/report-pack")
    assert report_pack_response.status_code == 409
    assert "Rerun the research job" in report_pack_response.json()["detail"]


def test_research_run_pause_and_resume(client: TestClient, monkeypatch):
    original_post_agent_request = research_api_executor._post_agent_request
    gate = asyncio.Event()

    async def _slow_first_node(endpoint, payload):
        context = payload.get("context") or {}
        if context.get("node_strategy") == "plan_query":
            await gate.wait()
        return await original_post_agent_request(endpoint, payload)

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _slow_first_node)

    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    running = _poll_research_run(
        client,
        research_run_id,
        lambda item: any(node["status"] == "running" for node in item["nodes"]),
    )
    assert running["status"] == "running"

    pause_response = client.post(f"/api/research-runs/{research_run_id}/pause")
    assert pause_response.status_code == 200
    paused_request = pause_response.json()
    assert paused_request["status"] in {"running", "paused"}

    gate.set()

    paused = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "paused",
        timeout=10.0,
    )
    paused_statuses = {node["node_id"]: node["status"] for node in paused["nodes"]}
    assert paused_statuses["plan_query"] == "completed"
    assert paused_statuses["gather_evidence"] == "pending"

    resume_response = client.post(f"/api/research-runs/{research_run_id}/resume")
    assert resume_response.status_code == 200

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
        timeout=10.0,
    )
    assert completed["status"] == "completed"


def test_research_run_evidence_payload_uses_node_results_before_completion(client: TestClient, monkeypatch):
    original_post_agent_request = research_api_executor._post_agent_request
    gate = asyncio.Event()

    async def _slow_draft_node(endpoint, payload):
        context = payload.get("context") or {}
        if context.get("node_strategy") == "draft_synthesis":
            await gate.wait()
        return await original_post_agent_request(endpoint, payload)

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _slow_draft_node)

    response = client.post(
        "/api/research-runs",
        json={"description": "Review literature on autonomous agent payments in DeSci."},
    )
    assert response.status_code == 202
    research_run_id = response.json()["id"]

    in_flight = _poll_research_run(
        client,
        research_run_id,
        lambda item: any(
            node["node_id"] == "draft_synthesis" and node["status"] == "running"
            for node in item["nodes"]
        ),
        timeout=10.0,
    )
    assert in_flight["rounds_completed"] == {"evidence_rounds": 1, "critique_rounds": 0}

    evidence_response = client.get(f"/api/research-runs/{research_run_id}/evidence")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["rewritten_research_brief"].startswith("Investigate:")
    assert len(evidence_payload["sources"]) >= 6
    assert len(evidence_payload["citations"]) >= 2
    assert evidence_payload["coverage_summary"]["ready_for_synthesis"] is True

    gate.set()

    completed = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "completed",
        timeout=10.0,
    )
    assert completed["status"] == "completed"


def test_research_run_cancel_from_waiting_review(client: TestClient, monkeypatch):
    score_calls = {"knowledge": 0}

    async def _review_required_score(output, phase, agent_role, phase_validation):
        del output, phase, phase_validation
        if agent_role == "knowledge-synthesizer-001":
            score_calls["knowledge"] += 1
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

    cancel_response = client.post(f"/api/research-runs/{research_run_id}/cancel")
    assert cancel_response.status_code == 200

    cancelled = _poll_research_run(
        client,
        research_run_id,
        lambda item: item["status"] == "cancelled",
        timeout=10.0,
    )
    statuses = {node["node_id"]: node["status"] for node in cancelled["nodes"]}
    assert statuses["revise_final_answer"] == "cancelled"
    assert cancelled["error"] == "Cancelled by user"

    waiting_task = client.get(f"/api/tasks/{waiting_node['task_id']}")
    assert waiting_task.status_code == 200
    assert waiting_task.json()["status"] == "cancelled"


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


@pytest.mark.asyncio
async def test_hybrid_source_curation_fails_when_requirements_are_not_met(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    agent = LiteratureMinerAgent()

    result = await agent._execute_curate_sources(
        "Curate hybrid evidence",
        {
            "classified_mode": "hybrid",
            "scenario_analysis_requested": False,
            "source_requirements": {
                "total_sources": 2,
                "min_academic_or_primary": 1,
                "min_fresh_sources": 1,
                "freshness_window_days": 7,
            },
            "gathered_evidence": {
                "sources": [
                    {
                        "title": "Old analysis 1",
                        "url": "https://example.com/old-1",
                        "publisher": "Example",
                        "published_at": "2020-01-01T00:00:00+00:00",
                        "source_type": "analysis",
                        "snippet": "stale evidence",
                        "quality_flags": [],
                    },
                    {
                        "title": "Old analysis 2",
                        "url": "https://example.com/old-2",
                        "publisher": "Example 2",
                        "published_at": "2020-01-02T00:00:00+00:00",
                        "source_type": "analysis",
                        "snippet": "stale evidence",
                        "quality_flags": [],
                    },
                ],
                "coverage_summary": {},
                "uncovered_claim_targets": [],
                "rounds_completed": {"evidence_rounds": 1, "critique_rounds": 0},
            },
        },
    )

    assert result["success"] is False
    assert result["error"] == "insufficient_curated_evidence"
    assert "Not enough fresh sources" in " ".join(result["details"]["issues"])


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


def test_research_quality_contract_flags_missing_citations_and_live_checks():
    result = _evaluate_research_quality_contract(
        {
            "answer_markdown": (
                "## Summary\n\nOil prices rose sharply.\n\n"
                "## Evidence\n\nReports described conflict-linked volatility.\n\n"
                "## Limitations\n\nNumbers may keep changing."
            ),
            "claims": [
                {
                    "claim_id": "C1",
                    "claim": "Oil prices rose sharply.",
                    "supporting_citation_ids": [],
                }
            ],
            "citations": [
                {
                    "citation_id": "S1",
                    "title": "Reuters report",
                    "url": "https://www.reuters.com/example",
                }
            ],
            "source_summary": {
                "fresh_sources": 1,
                "academic_or_primary_sources": 1,
            },
        },
        {
            "node_strategy": "revise_final_answer",
            "classified_mode": "live_analysis",
            "expected_format": {"required": ["answer_markdown", "claims", "limitations"]},
            "quality_requirements": {
                "min_claim_count": 1,
                "min_citation_coverage": 1.0,
                "require_inline_citations": True,
                "required_sections": ["Summary", "Evidence", "Limitations"],
                "require_absolute_dates": True,
                "require_uncertainty_language": True,
                "strict_live_analysis": True,
            },
        },
    )

    assert any("supporting citation" in issue.lower() for issue in result["issues"])
    assert any("inline citation" in issue.lower() for issue in result["issues"])
    assert any("absolute date" in issue.lower() for issue in result["issues"])
    assert result["quality_summary"]["strict_live_analysis_checks_passed"] is False


def test_research_quality_contract_is_noop_for_non_final_nodes():
    result = _evaluate_research_quality_contract(
        {"research_question": "What matters?", "search_queries": [{"query": "test"}]},
        {
            "node_strategy": "plan_query",
            "expected_format": {"required": ["research_question", "search_queries"]},
            "quality_requirements": {"require_inline_citations": True},
        },
    )

    assert result["issues"] == []


def test_research_quality_contract_accepts_lowercase_absolute_month_dates():
    result = _evaluate_research_quality_contract(
        {
            "answer_markdown": (
                "## Summary\n\nAs of march 9, 2026, oil prices appear elevated.[S1]\n\n"
                "## Evidence\n\nReuters reported a conflict-linked risk premium.[S1]\n\n"
                "## Limitations\n\nThe situation may keep changing."
            ),
            "claims": [
                {
                    "claim_id": "C1",
                    "claim": "Oil prices appear elevated.",
                    "supporting_citation_ids": ["S1"],
                }
            ],
            "citations": [
                {
                    "citation_id": "S1",
                    "title": "Reuters report",
                    "url": "https://www.reuters.com/example",
                }
            ],
            "limitations": ["The situation may keep changing."],
            "source_summary": {
                "fresh_sources": 1,
                "academic_or_primary_sources": 1,
            },
        },
        {
            "node_strategy": "revise_final_answer",
            "classified_mode": "live_analysis",
            "expected_format": {"required": ["answer_markdown", "claims", "limitations"]},
            "quality_requirements": {
                "min_claim_count": 1,
                "min_citation_coverage": 1.0,
                "require_inline_citations": True,
                "required_sections": ["Summary", "Evidence", "Limitations"],
                "require_absolute_dates": True,
                "require_uncertainty_language": True,
                "strict_live_analysis": True,
            },
        },
    )

    assert not any("absolute date" in issue.lower() for issue in result["issues"])
    assert result["quality_summary"]["strict_live_analysis_checks_passed"] is True
