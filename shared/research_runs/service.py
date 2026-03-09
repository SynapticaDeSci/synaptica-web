"""Persistence and execution helpers for research runs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from strands.agent.agent_result import AgentResult
from strands._async import run_async
from strands.multiagent.graph import GraphBuilder
from strands.telemetry.metrics import EventLoopMetrics

from agents.orchestrator.tools import create_todo_list, execute_microtask
from shared.database import (
    ExecutionAttempt,
    ResearchRun,
    ResearchRunEdge,
    ResearchRunNode,
    ResearchRunNodeStatus,
    ResearchRunStatus,
    SessionLocal,
    Task,
)
from shared.database.models import TaskStatus
from shared.runtime import HandoffContext, initialize_runtime_state, load_task_snapshot, redact_sensitive_payload

from .planner import SUPPORTED_RESEARCH_RUN_WORKFLOW, ResearchRunPlan, build_research_run_plan

logger = logging.getLogger(__name__)

DEFAULT_MIN_REPUTATION_SCORE = 0.7


class _ResearchRunGraphNodeExecutor:
    """Minimal AgentBase-compatible wrapper for a persisted research-run node."""

    def __init__(self, node_id: str):
        self.node_id = node_id

    async def invoke_async(self, prompt: Any = None, **kwargs: Any) -> Any:
        del prompt
        invocation_state = kwargs.get("invocation_state") or {}
        runner: ResearchRunExecutor = invocation_state["runner"]
        result = await runner.execute_node(self.node_id)
        return AgentResult(
            stop_reason="end_turn",
            message={
                "role": "assistant",
                "content": [{"text": json.dumps(result, default=str)}],
            },
            metrics=EventLoopMetrics(),
            state=result,
        )

    async def stream_async(self, prompt: Any = None, **kwargs: Any):
        result = await self.invoke_async(prompt, **kwargs)
        yield {"result": result}

    def __call__(self, prompt: Any = None, **kwargs: Any) -> Any:
        return run_async(lambda: self.invoke_async(prompt, **kwargs))


def _utcnow() -> datetime:
    return datetime.utcnow()


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _build_research_run_title(description: str) -> str:
    snippet = " ".join(description.split())
    snippet = snippet[:57].rstrip()
    return f"Research Run: {snippet}..." if len(snippet) == 57 else f"Research Run: {snippet}"


def create_research_run(
    *,
    description: str,
    budget_limit: Optional[float],
    verification_mode: str,
) -> str:
    """Persist a research run plus its template graph."""

    plan = build_research_run_plan(description)
    research_run_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
        record = ResearchRun(  # type: ignore[call-arg]
            id=research_run_id,
            title=_build_research_run_title(description),
            description=description,
            status=ResearchRunStatus.PENDING,
            workflow_template=plan.workflow_template,
            budget_limit=budget_limit,
            verification_mode=verification_mode,
            meta={"workflow": plan.workflow},
        )
        db.add(record)

        for node in plan.nodes:
            db.add(
                ResearchRunNode(  # type: ignore[call-arg]
                    research_run_id=research_run_id,
                    node_id=node.node_id,
                    title=node.title,
                    description=node.description,
                    capability_requirements=node.capability_requirements,
                    assigned_agent_id=node.assigned_agent_id,
                    execution_order=node.execution_order,
                    status=ResearchRunNodeStatus.PENDING,
                    meta={
                        "execution_parameters": node.execution_parameters,
                        "input_bindings": node.input_bindings,
                    },
                )
            )

        for edge in plan.edges:
            db.add(
                ResearchRunEdge(  # type: ignore[call-arg]
                    research_run_id=research_run_id,
                    from_node_id=edge.from_node_id,
                    to_node_id=edge.to_node_id,
                )
            )

        db.commit()
        return research_run_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _load_plan_for_run(research_run_id: str) -> ResearchRunPlan:
    db = SessionLocal()
    try:
        run_record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one()
        nodes = (
            db.query(ResearchRunNode)
            .filter(ResearchRunNode.research_run_id == research_run_id)
            .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
            .all()
        )
        edges = (
            db.query(ResearchRunEdge)
            .filter(ResearchRunEdge.research_run_id == research_run_id)
            .order_by(ResearchRunEdge.id.asc())
            .all()
        )
        return ResearchRunPlan(
            workflow_template=run_record.workflow_template,
            workflow=(run_record.meta or {}).get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
            nodes=[
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "description": node.description,
                    "capability_requirements": node.capability_requirements,
                    "assigned_agent_id": node.assigned_agent_id,
                    "execution_order": node.execution_order,
                    "execution_parameters": dict((node.meta or {}).get("execution_parameters") or {}),
                    "input_bindings": dict((node.meta or {}).get("input_bindings") or {}),
                }
                for node in nodes
            ],
            edges=[
                {
                    "from_node_id": edge.from_node_id,
                    "to_node_id": edge.to_node_id,
                }
                for edge in edges
            ],
        )
    finally:
        db.close()


class ResearchRunExecutor:
    """Execute a persisted research run through a Strands graph."""

    def __init__(self, research_run_id: str):
        self.research_run_id = research_run_id

    async def run(self) -> None:
        """Execute the full research run and persist terminal state."""

        self._mark_started()
        graph = self._build_graph()

        try:
            await graph.invoke_async(
                f"Execute research run {self.research_run_id}",
                invocation_state={"runner": self},
            )
            self._mark_completed()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Research run %s failed", self.research_run_id)
            self._mark_failed(str(exc))
            self._block_pending_descendants()

    async def execute_node(self, node_id: str) -> Dict[str, Any]:
        """Execute one node by creating a backing task and reusing the phase 0 microtask flow."""

        attempt_id, task_id, node_title = self._create_attempt(node_id)
        await self._initialize_attempt_runtime(node_id=node_id, attempt_id=attempt_id, task_id=task_id)

        try:
            context = self._build_handoff_context(
                node_id=node_id,
                attempt_id=attempt_id,
                task_id=task_id,
            )
            node_record = self._get_node(node_id)
            execution_parameters = self._resolve_execution_parameters(node_record)

            result = await execute_microtask(
                task_id=task_id,
                todo_id=node_id,
                task_name=node_title,
                task_description=node_record.description,
                capability_requirements=node_record.capability_requirements,
                budget_limit=self._get_research_run().budget_limit,
                min_reputation_score=DEFAULT_MIN_REPUTATION_SCORE,
                execution_parameters=execution_parameters,
                todo_list=[
                    {
                        "id": node_id,
                        "title": node_record.title,
                        "description": node_record.description,
                        "assigned_to": node_record.assigned_agent_id,
                        "status": "pending",
                    }
                ],
                handoff_context=context.model_dump(mode="json"),
            )

            snapshot = load_task_snapshot(task_id)
            self._finalize_attempt(
                node_id=node_id,
                attempt_id=attempt_id,
                task_id=task_id,
                result=result,
                snapshot=snapshot,
            )

            if not result.get("success"):
                raise RuntimeError(result.get("error", f"Research run node '{node_id}' failed"))

            return result
        except Exception as exc:  # noqa: BLE001
            self._record_attempt_failure(
                node_id=node_id,
                attempt_id=attempt_id,
                task_id=task_id,
                error=str(exc),
            )
            raise

    def _build_graph(self):
        plan = _load_plan_for_run(self.research_run_id)
        builder = GraphBuilder()
        builder.set_graph_id(f"research_run:{self.research_run_id}")
        builder.set_execution_timeout(3600)
        builder.set_max_node_executions(max(len(plan.nodes), 1))

        for node in sorted(plan.nodes, key=lambda item: item.execution_order):
            builder.add_node(_ResearchRunGraphNodeExecutor(node.node_id), node_id=node.node_id)
        for edge in plan.edges:
            builder.add_edge(edge.from_node_id, edge.to_node_id)
        return builder.build()

    def _get_research_run(self) -> ResearchRun:
        db = SessionLocal()
        try:
            return db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
        finally:
            db.close()

    def _get_node(self, node_id: str) -> ResearchRunNode:
        db = SessionLocal()
        try:
            return (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
        finally:
            db.close()

    def _mark_started(self) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            record.status = ResearchRunStatus.RUNNING
            record.started_at = record.started_at or _utcnow()
            db.commit()
        finally:
            db.close()

    def _mark_completed(self) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            nodes = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
                .all()
            )
            node_payloads = [
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "status": _enum_value(node.status),
                    "assigned_agent_id": node.assigned_agent_id,
                    "task_id": node.latest_task_id,
                    "payment_id": node.latest_payment_id,
                    "result": node.result,
                }
                for node in nodes
            ]
            result = {
                "research_run_id": record.id,
                "workflow": (record.meta or {}).get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
                "template": record.workflow_template,
                "steps": node_payloads,
                "framing": next((item["result"] for item in node_payloads if item["node_id"] == "problem_framing"), None),
                "evidence": next((item["result"] for item in node_payloads if item["node_id"] == "literature_mining"), None),
                "report": next((item["result"] for item in node_payloads if item["node_id"] == "knowledge_synthesis"), None),
            }
            record.status = ResearchRunStatus.COMPLETED
            record.completed_at = _utcnow()
            record.result = redact_sensitive_payload(result)
            record.error = None
            db.commit()
        finally:
            db.close()

    def _mark_failed(self, error: str) -> None:
        db = SessionLocal()
        try:
            record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            record.status = ResearchRunStatus.FAILED
            record.completed_at = _utcnow()
            record.error = error
            if record.result is None:
                record.result = {"error": error}
            db.commit()
        finally:
            db.close()

    def _create_attempt(self, node_id: str) -> tuple[str, str, str]:
        db = SessionLocal()
        try:
            run_record = db.query(ResearchRun).filter(ResearchRun.id == self.research_run_id).one()
            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
            existing_attempts = (
                db.query(ExecutionAttempt)
                .filter(ExecutionAttempt.research_run_id == self.research_run_id)
                .filter(ExecutionAttempt.node_id == node_id)
                .count()
            )
            attempt_number = existing_attempts + 1
            attempt_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())

            task = Task(  # type: ignore[call-arg]
                id=task_id,
                title=f"{run_record.title} - {node_record.title}",
                description=node_record.description,
                status=TaskStatus.IN_PROGRESS,
                created_by="research-run-runner",
                assigned_to=node_record.assigned_agent_id,
                created_at=_utcnow(),
                meta={
                    "research_run_id": self.research_run_id,
                    "node_id": node_id,
                    "attempt_id": attempt_id,
                    "workflow_type": "research_run_node",
                    "budget_limit": run_record.budget_limit,
                    "verification_mode": run_record.verification_mode,
                },
            )
            db.add(task)

            attempt = ExecutionAttempt(  # type: ignore[call-arg]
                id=attempt_id,
                research_run_id=self.research_run_id,
                node_id=node_id,
                attempt_number=attempt_number,
                status=ResearchRunNodeStatus.RUNNING,
                task_id=task_id,
                agent_id=node_record.assigned_agent_id,
                created_at=_utcnow(),
                started_at=_utcnow(),
            )
            db.add(attempt)

            node_record.status = ResearchRunNodeStatus.RUNNING
            node_record.started_at = node_record.started_at or _utcnow()
            node_record.latest_task_id = task_id
            node_record.error = None
            run_record.status = ResearchRunStatus.RUNNING
            run_record.started_at = run_record.started_at or _utcnow()
            db.commit()
            return attempt_id, task_id, node_record.title
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _initialize_attempt_runtime(self, *, node_id: str, attempt_id: str, task_id: str) -> None:
        node_record = self._get_node(node_id)
        run_record = self._get_research_run()

        initialize_runtime_state(
            task_id,
            request_meta={
                "research_run_id": self.research_run_id,
                "node_id": node_id,
                "attempt_id": attempt_id,
                "budget_limit": run_record.budget_limit,
                "verification_mode": run_record.verification_mode,
                "assigned_agent_id": node_record.assigned_agent_id,
            },
        )

        await create_todo_list(
            task_id,
            [
                {
                    "id": node_id,
                    "title": node_record.title,
                    "description": node_record.description,
                    "assigned_to": node_record.assigned_agent_id,
                }
            ],
        )

    def _build_handoff_context(self, *, node_id: str, attempt_id: str, task_id: str) -> HandoffContext:
        run_record = self._get_research_run()
        node_record = self._get_node(node_id)
        return HandoffContext(
            task_id=task_id,
            todo_id=node_id,
            attempt_id=attempt_id,
            research_run_id=self.research_run_id,
            node_id=node_id,
            agent_id=node_record.assigned_agent_id,
            budget_remaining=run_record.budget_limit,
            verification_mode=run_record.verification_mode,
        )

    def _resolve_execution_parameters(self, node_record: ResearchRunNode) -> Dict[str, Any]:
        parameters = dict((node_record.meta or {}).get("execution_parameters") or {})
        input_bindings = dict((node_record.meta or {}).get("input_bindings") or {})
        if not input_bindings:
            return parameters

        db = SessionLocal()
        try:
            for param_name, source_node_id in input_bindings.items():
                source_node = (
                    db.query(ResearchRunNode)
                    .filter(ResearchRunNode.research_run_id == self.research_run_id)
                    .filter(ResearchRunNode.node_id == source_node_id)
                    .one()
                )
                parameters[param_name] = source_node.result
            return parameters
        finally:
            db.close()

    def _extract_payment_id(self, result: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
        selection = result.get("selected_agent")
        if isinstance(selection, dict) and selection.get("payment_id"):
            return str(selection["payment_id"])

        handoff_context = (snapshot or {}).get("current_handoff_context") or {}
        if isinstance(handoff_context, dict) and handoff_context.get("payment_id"):
            return str(handoff_context["payment_id"])
        return None

    def _extract_agent_id(self, result: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
        if result.get("agent_used"):
            return str(result["agent_used"])

        selection = result.get("selected_agent")
        if isinstance(selection, dict) and selection.get("agent_id"):
            return str(selection["agent_id"])

        handoff_context = (snapshot or {}).get("current_handoff_context") or {}
        if isinstance(handoff_context, dict) and handoff_context.get("agent_id"):
            return str(handoff_context["agent_id"])
        return None

    def _finalize_attempt(
        self,
        *,
        node_id: str,
        attempt_id: str,
        task_id: str,
        result: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
    ) -> None:
        success = bool(result.get("success"))
        payment_id = self._extract_payment_id(result, snapshot)
        agent_id = self._extract_agent_id(result, snapshot)
        task_status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        attempt_status = ResearchRunNodeStatus.COMPLETED if success else ResearchRunNodeStatus.FAILED
        node_status = ResearchRunNodeStatus.COMPLETED if success else ResearchRunNodeStatus.FAILED
        task_result = (
            redact_sensitive_payload(result.get("result"))
            if success
            else {"error": result.get("error", "Research run node failed")}
        )

        db = SessionLocal()
        try:
            attempt = db.query(ExecutionAttempt).filter(ExecutionAttempt.id == attempt_id).one()
            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one()
            )
            task = db.query(Task).filter(Task.id == task_id).one()

            attempt.status = attempt_status
            attempt.payment_id = payment_id
            attempt.agent_id = agent_id or node_record.assigned_agent_id
            attempt.verification_score = result.get("verification_score")
            attempt.completed_at = _utcnow()
            attempt.result = redact_sensitive_payload(result)
            attempt.error = None if success else result.get("error")

            node_record.status = node_status
            node_record.latest_payment_id = payment_id
            node_record.completed_at = _utcnow()
            node_record.result = redact_sensitive_payload(result.get("result")) if success else None
            node_record.error = None if success else result.get("error")

            task.status = task_status
            task.result = task_result
            if success:
                task.completed_at = _utcnow()

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _record_attempt_failure(self, *, node_id: str, attempt_id: str, task_id: str, error: str) -> None:
        db = SessionLocal()
        try:
            attempt = db.query(ExecutionAttempt).filter(ExecutionAttempt.id == attempt_id).one_or_none()
            if attempt is not None and _enum_value(attempt.status) == ResearchRunNodeStatus.RUNNING.value:
                attempt.status = ResearchRunNodeStatus.FAILED
                attempt.completed_at = _utcnow()
                attempt.error = error
                attempt.result = {"error": error}

            node_record = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.node_id == node_id)
                .one_or_none()
            )
            if node_record is not None and _enum_value(node_record.status) == ResearchRunNodeStatus.RUNNING.value:
                node_record.status = ResearchRunNodeStatus.FAILED
                node_record.completed_at = _utcnow()
                node_record.error = error

            task = db.query(Task).filter(Task.id == task_id).one_or_none()
            if task is not None and _enum_value(task.status) == TaskStatus.IN_PROGRESS.value:
                task.status = TaskStatus.FAILED
                task.result = {"error": error}

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _block_pending_descendants(self) -> None:
        db = SessionLocal()
        try:
            pending_nodes = (
                db.query(ResearchRunNode)
                .filter(ResearchRunNode.research_run_id == self.research_run_id)
                .filter(ResearchRunNode.status == ResearchRunNodeStatus.PENDING)
                .all()
            )
            for node in pending_nodes:
                node.status = ResearchRunNodeStatus.BLOCKED
                node.error = "Blocked by an upstream node failure"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _derive_attempt_status(attempt: ExecutionAttempt) -> str:
    status = _enum_value(attempt.status)
    if attempt.task_id:
        snapshot = load_task_snapshot(str(attempt.task_id))
        if snapshot and snapshot.get("verification_pending"):
            return ResearchRunNodeStatus.WAITING_FOR_REVIEW.value
        snapshot_status = str((snapshot or {}).get("status", "")).lower()
        if snapshot_status == "cancelled":
            return ResearchRunNodeStatus.FAILED.value
    return status


def get_research_run_payload(research_run_id: str) -> Optional[Dict[str, Any]]:
    """Serialize a research run for API responses."""

    db = SessionLocal()
    try:
        record = db.query(ResearchRun).filter(ResearchRun.id == research_run_id).one_or_none()
        if record is None:
            return None

        nodes = (
            db.query(ResearchRunNode)
            .filter(ResearchRunNode.research_run_id == research_run_id)
            .order_by(ResearchRunNode.execution_order.asc(), ResearchRunNode.id.asc())
            .all()
        )
        edges = (
            db.query(ResearchRunEdge)
            .filter(ResearchRunEdge.research_run_id == research_run_id)
            .order_by(ResearchRunEdge.id.asc())
            .all()
        )
        attempts = (
            db.query(ExecutionAttempt)
            .filter(ExecutionAttempt.research_run_id == research_run_id)
            .order_by(ExecutionAttempt.attempt_number.asc(), ExecutionAttempt.created_at.asc())
            .all()
        )
    finally:
        db.close()

    attempts_by_node: Dict[str, List[ExecutionAttempt]] = {}
    for attempt in attempts:
        attempts_by_node.setdefault(attempt.node_id, []).append(attempt)

    any_waiting_for_review = False
    nodes_payload: List[Dict[str, Any]] = []
    for node in nodes:
        attempt_payloads = []
        latest_attempt_status = None
        for attempt in attempts_by_node.get(node.node_id, []):
            derived_status = _derive_attempt_status(attempt)
            any_waiting_for_review = any_waiting_for_review or (
                derived_status == ResearchRunNodeStatus.WAITING_FOR_REVIEW.value
            )
            latest_attempt_status = derived_status
            attempt_payloads.append(
                {
                    "attempt_id": attempt.id,
                    "attempt_number": attempt.attempt_number,
                    "status": derived_status,
                    "task_id": attempt.task_id,
                    "payment_id": attempt.payment_id,
                    "agent_id": attempt.agent_id,
                    "verification_score": attempt.verification_score,
                    "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
                    "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                    "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
                    "result": attempt.result,
                    "error": attempt.error,
                }
            )

        node_status = _enum_value(node.status)
        if node_status in {
            ResearchRunNodeStatus.PENDING.value,
            ResearchRunNodeStatus.RUNNING.value,
        } and latest_attempt_status == ResearchRunNodeStatus.WAITING_FOR_REVIEW.value:
            node_status = ResearchRunNodeStatus.WAITING_FOR_REVIEW.value

        nodes_payload.append(
            {
                "node_id": node.node_id,
                "title": node.title,
                "description": node.description,
                "capability_requirements": node.capability_requirements,
                "assigned_agent_id": node.assigned_agent_id,
                "execution_order": node.execution_order,
                "status": node_status,
                "task_id": node.latest_task_id,
                "payment_id": node.latest_payment_id,
                "created_at": node.created_at.isoformat() if node.created_at else None,
                "started_at": node.started_at.isoformat() if node.started_at else None,
                "completed_at": node.completed_at.isoformat() if node.completed_at else None,
                "result": node.result,
                "error": node.error,
                "attempts": attempt_payloads,
            }
        )

    run_status = _enum_value(record.status)
    if run_status == ResearchRunStatus.RUNNING.value and any_waiting_for_review:
        run_status = ResearchRunStatus.WAITING_FOR_REVIEW.value

    return {
        "id": record.id,
        "title": record.title,
        "description": record.description,
        "status": run_status,
        "workflow_template": record.workflow_template,
        "workflow": (record.meta or {}).get("workflow", SUPPORTED_RESEARCH_RUN_WORKFLOW),
        "budget_limit": record.budget_limit,
        "verification_mode": record.verification_mode,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "result": record.result,
        "error": record.error,
        "nodes": nodes_payload,
        "edges": [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
            }
            for edge in edges
        ],
    }
