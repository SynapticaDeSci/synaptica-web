import importlib
import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from api.main import app
from api.main import _upsert_supported_research_agents
from agents.executor.tools import research_api_executor
from agents.negotiator.tools.payment_tools import create_payment_request, authorize_payment
from agents.verifier.tools.payment_tools import reject_and_refund, release_payment
from shared.hedera.utils import hedera_account_to_evm_address
from shared.payments.service import run_idempotent_payment_action
from shared.research.catalog import default_research_endpoint
from shared.runtime import PaymentAction, PaymentActionContext
from shared.database import (
    A2AEvent,
    Agent as AgentModel,
    AgentPaymentProfile,
    AgentReputation,
    AgentsCacheEntry,
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
from shared.database.models import PaymentStatus as DBPaymentStatus, TaskStatus


def _reset_runtime_state():
    research_api_executor._agent_cache.clear()
    session = SessionLocal()
    try:
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
        request_text = payload.get("request", "")
        context = payload.get("context") or {}
        node_strategy = context.get("node_strategy")

        if "problem-framer-001" in endpoint or node_strategy == "plan_query":
            return {
                "success": True,
                "agent_id": "problem-framer-001",
                "result": {
                    "query": context.get("original_description", request_text),
                    "research_question": request_text,
                    "rewritten_research_brief": f"Investigate: {request_text}",
                    "success_criteria": ["Use evidence-grounded claims."],
                    "claim_targets": [
                        {
                            "claim_id": "C1",
                            "claim_target": "Direct answer to the research question.",
                            "lane": "core-answer",
                            "priority": "high",
                        }
                    ],
                    "search_queries": [
                        {
                            "role": "academic-scout",
                            "lane": "core-literature",
                            "query": "autonomous agent payments literature",
                        }
                    ],
                    "keywords": ["desci", "payments", "literature"],
                },
                "metadata": {},
            }
        if "literature-miner-001" in endpoint or node_strategy == "gather_evidence":
            return {
                "success": True,
                "agent_id": "literature-miner-001",
                "result": {
                    "sources": [
                        {
                            "title": "Paper A",
                            "url": "https://example.com/paper-a",
                            "publisher": "arXiv",
                            "published_at": "2025-01-15T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Evidence about agent micropayments.",
                            "display_snippet": "Evidence about agent micropayments.",
                            "relevance_score": 0.94,
                            "quality_flags": [],
                        },
                        {
                            "title": "Paper B",
                            "url": "https://example.com/paper-b",
                            "publisher": "Semantic Scholar",
                            "published_at": "2024-09-03T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Structured review of autonomous marketplaces.",
                            "display_snippet": "Structured review of autonomous marketplaces.",
                            "relevance_score": 0.91,
                            "quality_flags": [],
                        },
                        {
                            "title": "Paper C",
                            "url": "https://example.com/paper-c",
                            "publisher": "Nature",
                            "published_at": "2024-06-11T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Evidence on payment frictions.",
                            "display_snippet": "Evidence on payment frictions.",
                            "relevance_score": 0.89,
                            "quality_flags": [],
                        },
                        {
                            "title": "Paper D",
                            "url": "https://example.com/paper-d",
                            "publisher": "ACM",
                            "published_at": "2023-12-21T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Operational efficiency findings.",
                            "display_snippet": "Operational efficiency findings.",
                            "relevance_score": 0.85,
                            "quality_flags": [],
                        },
                        {
                            "title": "Paper E",
                            "url": "https://example.com/paper-e",
                            "publisher": "IEEE",
                            "published_at": "2023-05-09T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Agent marketplace trust assumptions.",
                            "display_snippet": "Agent marketplace trust assumptions.",
                            "relevance_score": 0.83,
                            "quality_flags": [],
                        },
                        {
                            "title": "Paper F",
                            "url": "https://example.com/paper-f",
                            "publisher": "ScienceDirect",
                            "published_at": "2022-11-30T00:00:00+00:00",
                            "source_type": "academic",
                            "snippet": "Cost and adoption outcomes.",
                            "display_snippet": "Cost and adoption outcomes.",
                            "relevance_score": 0.8,
                            "quality_flags": [],
                        },
                    ],
                    "coverage_summary": {
                        "source_summary": {
                            "total_sources": 6,
                            "academic_or_primary_sources": 6,
                            "fresh_sources": 0,
                            "publishers": ["ACM", "IEEE", "Nature", "ScienceDirect", "Semantic Scholar", "arXiv"],
                            "requirements_met": True,
                        },
                        "source_diversity": {
                            "unique_publishers": 6,
                            "source_types": 1,
                        },
                        "covered_claim_ids": ["C1"],
                        "uncovered_claim_targets": [],
                        "ready_for_synthesis": True,
                    },
                    "uncovered_claim_targets": [],
                    "rounds_completed": {"evidence_rounds": 1, "critique_rounds": 0},
                },
                "metadata": {},
            }
        return {
            "success": True,
            "agent_id": "knowledge-synthesizer-001",
            "result": {
                "answer_markdown": "## Summary\nAgent micropayments improve coordination when paired with trustworthy settlement.\n\n## Evidence\nLiterature points to lower transaction friction and better automation transparency.\n\n## Limitations\nThe evidence base is still emerging.",
                "claims": [
                    {
                        "claim_id": "C1",
                        "claim": "Agent micropayments can reduce transaction friction in autonomous marketplaces.",
                        "supporting_citation_ids": ["S1", "S2"],
                        "confidence": "medium",
                    }
                ],
                "limitations": ["The literature is still early and not universal across domains."],
            },
            "metadata": {},
        }

    async def _mock_quality_score(output, phase, agent_role, phase_validation):
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


def test_execute_happy_path_offline_persists_payments_and_events(client: TestClient):
    response = client.post(
        "/execute",
        json={
            "description": "Review literature on autonomous agent payments in DeSci.",
            "verification_mode": "standard",
            "budget_limit": 25.0,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    status = client.get(f"/api/tasks/{task_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["result"]["workflow"] == (
        "problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001"
    )

    session = SessionLocal()
    try:
        payments = session.query(Payment).filter(Payment.task_id == task_id).all()
        assert len(payments) == 3
        assert all(payment.status.value == "completed" for payment in payments)

        transitions = (
            session.query(PaymentStateTransition)
            .filter(PaymentStateTransition.task_id == task_id)
            .all()
        )
        assert len(transitions) == 9

        notifications = (
            session.query(PaymentNotification)
            .join(Payment, PaymentNotification.payment_id == Payment.id)
            .filter(Payment.task_id == task_id)
            .all()
        )
        assert len(notifications) == 6
        assert {item.recipient_role for item in notifications} == {"payer", "payee"}

        events = session.query(A2AEvent).all()
        assert len(events) == 12
    finally:
        session.close()


def test_payment_routes_expose_notifications_and_reconciliation(client: TestClient):
    response = client.post(
        "/execute",
        json={
            "description": "Review literature on autonomous agent payments in DeSci.",
            "verification_mode": "standard",
            "budget_limit": 25.0,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    session = SessionLocal()
    try:
        payment = (
            session.query(Payment)
            .filter(Payment.task_id == task_id)
            .order_by(Payment.created_at.asc())
            .first()
        )
        assert payment is not None
        payment_id = payment.id
        notification = (
            session.query(PaymentNotification)
            .filter(PaymentNotification.payment_id == payment_id)
            .order_by(PaymentNotification.id.asc())
            .first()
        )
        assert notification is not None
        deleted_message_id = notification.message_id
        session.delete(notification)
        session.commit()
    finally:
        session.close()

    detail_response = client.get(f"/api/payments/{payment_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["payment_profile"]["status"] == "verified"
    assert detail_payload["notification_summary"]["count"] == 1

    events_response = client.get(f"/api/payments/{payment_id}/events")
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert len(events_payload["state_transitions"]) == 3
    assert len(events_payload["notifications"]) == 1
    assert len(events_payload["a2a_events"]) >= 4

    reconcile_response = client.post("/api/payments/reconcile", json={"payment_id": payment_id})
    assert reconcile_response.status_code == 200
    reconciliation = reconcile_response.json()["reconciliations"][0]
    assert reconciliation["status"] == "repaired"
    assert reconciliation["details"]["repaired_notifications"]

    repaired_events = client.get(f"/api/payments/{payment_id}/events")
    assert repaired_events.status_code == 200
    assert len(repaired_events.json()["notifications"]) == 2


def test_execute_requires_verified_payment_profile(client: TestClient):
    session = SessionLocal()
    try:
        profile = (
            session.query(AgentPaymentProfile)
            .filter(AgentPaymentProfile.agent_id == "problem-framer-001")
            .one_or_none()
        )
        assert profile is not None
        session.delete(profile)
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/execute",
        json={
            "description": "Review literature on autonomous agent payments in DeSci.",
            "verification_mode": "standard",
            "budget_limit": 25.0,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    status = client.get(f"/api/tasks/{task_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "failed"
    assert "missing a verified payment profile" in payload["error"]


def test_verify_payment_profile_endpoint_persists_failures_and_success(client: TestClient):
    mismatch = client.post(
        "/api/agents/problem-framer-001/payment-profile/verify",
        json={"hedera_account_id": "0.0.9999"},
    )
    assert mismatch.status_code == 200
    mismatch_payload = mismatch.json()
    assert mismatch_payload["success"] is False
    assert mismatch_payload["status"] == "failed"

    verified = client.post("/api/agents/problem-framer-001/payment-profile/verify", json={})
    assert verified.status_code == 200
    verified_payload = verified.json()
    assert verified_payload["success"] is True
    assert verified_payload["status"] == "verified"

    equivalent = client.post(
        "/api/agents/problem-framer-001/payment-profile/verify",
        json={"hedera_account_id": hedera_account_to_evm_address("0.0.7001").lower()},
    )
    assert equivalent.status_code == 200
    equivalent_payload = equivalent.json()
    assert equivalent_payload["success"] is True
    assert equivalent_payload["status"] == "verified"


def test_verify_payment_profile_endpoint_requires_admin_token_when_configured(client: TestClient, monkeypatch):
    monkeypatch.setenv("AGENT_SUBMIT_ADMIN_TOKEN", "top-secret")

    unauthorized = client.post("/api/agents/problem-framer-001/payment-profile/verify")
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/api/agents/problem-framer-001/payment-profile/verify",
        headers={"X-Admin-Token": "top-secret"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["success"] is True


@pytest.mark.asyncio
async def test_payment_request_fails_closed_without_non_offline_config(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("PAYMENT_MODE", "managed")
    monkeypatch.delenv("HEDERA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("TASK_ESCROW_ADDRESS", raising=False)
    monkeypatch.delenv("TASK_ESCROW_MARKETPLACE_TREASURY", raising=False)
    monkeypatch.delenv("TASK_ESCROW_OPERATOR_PRIVATE_KEY", raising=False)

    with pytest.raises(Exception):
        await create_payment_request(
            task_id="task-fail",
            from_agent_id="orchestrator-agent",
            to_agent_id="problem-framer-001",
            to_hedera_account="0.0.7001",
            amount=5.0,
            description="should fail",
            action_context={"todo_id": "todo_0", "attempt_id": "attempt_0"},
        )

    session = SessionLocal()
    try:
        assert session.query(Payment).count() == 0
    finally:
        session.close()


@pytest.mark.asyncio
async def test_payment_actions_are_idempotent_and_conflicting_terminal_actions_are_blocked(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("PAYMENT_MODE", "offline")

    proposal_ctx = {"todo_id": "todo_0", "attempt_id": "attempt_1"}
    proposal_one = await create_payment_request(
        task_id="task-idempotent",
        from_agent_id="orchestrator-agent",
        to_agent_id="problem-framer-001",
        to_hedera_account="0.0.7001",
        amount=5.0,
        description="idempotent proposal",
        action_context=proposal_ctx,
    )
    proposal_two = await create_payment_request(
        task_id="task-idempotent",
        from_agent_id="orchestrator-agent",
        to_agent_id="problem-framer-001",
        to_hedera_account="0.0.7001",
        amount=5.0,
        description="idempotent proposal",
        action_context=proposal_ctx,
    )
    assert proposal_one["payment_id"] == proposal_two["payment_id"]

    authorize_ctx = {"todo_id": "todo_0", "attempt_id": "attempt_1"}
    auth_one = await authorize_payment(proposal_one["payment_id"], action_context=authorize_ctx)
    auth_two = await authorize_payment(proposal_one["payment_id"], action_context=authorize_ctx)
    assert auth_one["authorization_id"] == auth_two["authorization_id"]

    release_ctx = {"todo_id": "todo_0", "attempt_id": "attempt_1"}
    released = await release_payment(
        proposal_one["payment_id"],
        "verified",
        action_context=release_ctx,
    )
    released_again = await release_payment(
        proposal_one["payment_id"],
        "verified",
        action_context=release_ctx,
    )
    assert released["transaction_id"] == released_again["transaction_id"]

    with pytest.raises(Exception):
        await reject_and_refund(
            proposal_one["payment_id"],
            "too late to refund",
            action_context={"todo_id": "todo_0", "attempt_id": "attempt_1"},
        )


@pytest.mark.asyncio
async def test_sensitive_payment_metadata_is_rejected(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("PAYMENT_MODE", "offline")

    with pytest.raises(Exception):
        await create_payment_request(
            task_id="task-secret",
            from_agent_id="orchestrator-agent",
            to_agent_id="problem-framer-001",
            to_hedera_account="0.0.7001",
            amount=5.0,
            description="secret payload",
            action_context={
                "todo_id": "todo_0",
                "attempt_id": "attempt_1",
                "metadata": {"private_key": "0x" + "a" * 64},
            },
        )


@pytest.mark.asyncio
async def test_create_payment_request_recovers_from_duplicate_proposal_race(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("PAYMENT_MODE", "offline")

    expected = {
        "success": True,
        "payment_id": "existing-payment-id",
        "task_id": "task-proposal-race",
        "status": "pending",
    }

    def _raise_integrity_error(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(
        "agents.negotiator.tools.payment_tools.record_transition",
        _raise_integrity_error,
    )
    monkeypatch.setattr(
        "agents.negotiator.tools.payment_tools.get_completed_transition_result_by_task",
        lambda *args, **kwargs: expected,
    )

    result = await create_payment_request(
        task_id="task-proposal-race",
        from_agent_id="orchestrator-agent",
        to_agent_id="problem-framer-001",
        to_hedera_account="0.0.7001",
        amount=5.0,
        description="proposal race",
        action_context={"todo_id": "todo_0", "attempt_id": "attempt_race"},
    )
    assert result == expected


@pytest.mark.asyncio
async def test_run_idempotent_payment_action_returns_existing_result_after_integrity_race(monkeypatch):
    _reset_runtime_state()
    session = SessionLocal()
    try:
        payment = Payment(  # type: ignore[call-arg]
            id="payment-race",
            task_id="task-race",
            from_agent_id="orchestrator-agent",
            to_agent_id="problem-framer-001",
            amount=5.0,
            currency="HBAR",
            status=DBPaymentStatus.AUTHORIZED,
            meta={},
        )
        session.add(payment)
        session.commit()
    finally:
        session.close()

    expected = {
        "success": True,
        "payment_id": "payment-race",
        "status": "completed",
    }

    def _raise_integrity_error(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(
        "shared.payments.service.record_transition",
        _raise_integrity_error,
    )
    monkeypatch.setattr(
        "shared.payments.service.get_completed_transition_result",
        lambda *args, **kwargs: expected,
    )

    result = await run_idempotent_payment_action(
        payment_id="payment-race",
        context=PaymentActionContext(
            payment_id="payment-race",
            task_id="task-race",
            todo_id="todo_0",
            attempt_id="attempt_race",
            action=PaymentAction.RELEASE,
            idempotency_key="task-race:todo_0:attempt_race:release",
            mode="offline",
        ),
        runner=lambda db: expected,
    )
    assert result == expected


def test_executor_rejects_experimental_agents(client: TestClient):
    session = SessionLocal()
    try:
        agent = session.query(AgentModel).filter(AgentModel.agent_id == "literature-miner-001").one()
        meta = dict(agent.meta or {})
        meta["support_tier"] = "experimental"
        agent.meta = meta
        session.commit()
    finally:
        session.close()
    research_api_executor._agent_cache.clear()

    result = asyncio.run(
        research_api_executor.execute_research_agent(
            agent_domain="literature-miner-001",
            task_description="collect sources",
            context={},
            metadata={"task_id": "task-boundary"},
        )
    )
    assert result["success"] is False
    assert "supported tier" in result["error"]


def test_supported_builtin_agents_ignore_stale_marketplace_endpoint(client: TestClient, monkeypatch):
    session = SessionLocal()
    try:
        agent = session.query(AgentModel).filter(AgentModel.agent_id == "knowledge-synthesizer-001").one()
        meta = dict(agent.meta or {})
        meta["endpoint_url"] = "https://stale.example.test/agents/knowledge-synthesizer-001"
        agent.meta = meta
        session.commit()
    finally:
        session.close()

    research_api_executor._agent_cache.clear()
    captured: dict[str, str] = {}

    async def _capture_endpoint(endpoint, payload):
        del payload
        captured["endpoint"] = endpoint
        return {
            "success": True,
            "agent_id": "knowledge-synthesizer-001",
            "result": {"answer_markdown": "## Summary\n\nok", "claims": [], "limitations": []},
            "metadata": {},
        }

    monkeypatch.setattr(research_api_executor, "_post_agent_request", _capture_endpoint)

    result = asyncio.run(
        research_api_executor.execute_research_agent(
            agent_domain="knowledge-synthesizer-001",
            task_description="Draft the synthesis",
            context={"node_strategy": "draft_synthesis"},
            metadata={"task_id": "task-synthesis-endpoint"},
        )
    )

    assert result["success"] is True
    assert captured["endpoint"] == default_research_endpoint("knowledge-synthesizer-001")


def test_problem_framer_default_execute_returns_current_plan_query_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    problem_framer_module = importlib.import_module(
        "agents.research.phase1_ideation.problem_framer.agent"
    )

    result = asyncio.run(
        problem_framer_module.problem_framer_agent.execute(
            "How do autonomous agent payments affect marketplace adoption?"
        )
    )

    assert result["success"] is True
    payload = result["result"]
    assert payload["research_question"]
    assert payload["rewritten_research_brief"]
    assert payload["success_criteria"]
    assert payload["claim_targets"]
    assert payload["search_queries"]
    assert payload["hypothesis"]
    assert payload["scope"]
    assert payload["domain"]


def test_task_history_uses_persisted_runtime_cancelled_status(client: TestClient):
    session = SessionLocal()
    try:
        task = Task(  # type: ignore[call-arg]
            id="task-cancelled",
            title="Cancelled task",
            description="Task rejected during verification",
            status=TaskStatus.FAILED,
            created_by="orchestrator-agent",
            created_at=datetime.utcnow(),
            meta={
                "runtime": {
                    "status": "cancelled",
                    "progress": [],
                    "progress_snapshot": {},
                }
            },
        )
        session.add(task)
        session.commit()
    finally:
        session.close()

    response = client.get("/api/tasks/history")
    assert response.status_code == 200
    payload = response.json()
    cancelled = next(item for item in payload if item["id"] == "task-cancelled")
    assert cancelled["status"] == "cancelled"


def test_supported_agent_upsert_restores_reputation_floor():
    _reset_runtime_state()
    session = SessionLocal()
    try:
        session.add(
            AgentModel(  # type: ignore[call-arg]
                agent_id="problem-framer-001",
                name="Problem Framer",
                agent_type="research",
                description="Legacy seeded agent",
                capabilities=["problem framing"],
                hedera_account_id="0.0.7001",
                status="active",
                meta={"support_tier": "supported"},
            )
        )
        session.add(
            AgentReputation(  # type: ignore[call-arg]
                agent_id="problem-framer-001",
                reputation_score=0.0,
                total_tasks=1,
                successful_tasks=0,
                failed_tasks=1,
                payment_multiplier=1.0,
            )
        )
        session.commit()
    finally:
        session.close()

    _upsert_supported_research_agents()

    session = SessionLocal()
    try:
        reputation = (
            session.query(AgentReputation)
            .filter(AgentReputation.agent_id == "problem-framer-001")
            .one()
        )
        assert reputation.reputation_score >= 0.8
    finally:
        session.close()


def test_supported_research_agent_server_only_loads_supported_trio(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    research_main = importlib.import_module("agents.research.main")
    research_main.get_agent_registry.cache_clear()

    with TestClient(research_main.app) as client:
        listing = client.get("/agents")
        assert listing.status_code == 200
        payload = listing.json()
        ids = [agent["agent_id"] for agent in payload["agents"]]
        assert ids == [
            "problem-framer-001",
            "literature-miner-001",
            "knowledge-synthesizer-001",
        ]

        detail = client.get("/agents/bias-detector-001")
        assert detail.status_code == 404

    session = SessionLocal()
    try:
        registered_ids = {
            agent.agent_id
            for agent in session.query(AgentModel).order_by(AgentModel.agent_id).all()
        }
        assert registered_ids == {
            "knowledge-synthesizer-001",
            "literature-miner-001",
            "problem-framer-001",
        }
    finally:
        session.close()
