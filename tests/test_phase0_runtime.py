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
from shared.payments.service import run_idempotent_payment_action
from shared.runtime import PaymentAction, PaymentActionContext
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
from shared.database.models import PaymentStatus as DBPaymentStatus, TaskStatus


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
                    "scope": "phase0",
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

        events = session.query(A2AEvent).all()
        assert len(events) == 9
    finally:
        session.close()


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
