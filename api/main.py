"""FastAPI main application - Orchestrator Agent Entry Point."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shared.agents_cache import rebuild_agents_cache
from shared.database import Agent, AgentReputation, Base, SessionLocal, engine
from shared.database.models import A2AEvent, Task
from shared.research.catalog import (
    SUPPORTED_AGENT_DETAILS,
    build_phase0_todo_items,
    default_research_endpoint,
)
from shared.registry_sync import (
    RegistrySyncError,
    ensure_registry_cache,
    get_registry_cache_ttl_seconds,
)
from shared.runtime import (
    TelemetryEnvelope,
    append_progress_event,
    initialize_runtime_state,
    load_task_snapshot,
    persist_verification_state,
    redact_sensitive_payload,
)
import shared.task_progress as task_progress
from agents.orchestrator.tools import create_todo_list, execute_microtask

from .middleware import logging_middleware
from .routes import agents as agents_routes
from .routes import data_agent as data_agent_routes
from .routes import research_runs as research_runs_routes

# Load environment variables
load_dotenv()

# In-memory task storage for progress tracking
tasks_storage: Dict[str, Dict[str, Any]] = {}
_registry_refresh_task: Optional[asyncio.Task] = None
logger = logging.getLogger(__name__)

BUILT_IN_DATA_AGENT_ID = "data-agent-001"


def _upsert_builtin_data_agent() -> None:
    """Ensure the built-in Data Agent is available in the marketplace."""

    session = SessionLocal()
    try:
        agent = (
            session.query(Agent)
            .filter(Agent.agent_id == BUILT_IN_DATA_AGENT_ID)
            .one_or_none()
        )

        data_agent_meta = {
            "endpoint_url": "/api/data-agent/datasets",
            "health_check_url": "/health",
            "pricing": {
                "rate": 0.0,
                "currency": "HBAR",
                "rate_type": "per_upload",
            },
            "categories": ["Data", "Storage", "DeSci"],
            "always_listed": True,
            "data_agent": {
                "built_in": True,
                "public_access": True,
            },
            "support_tier": "supported",
        }

        capabilities = [
            "dataset-upload",
            "dataset-catalog",
            "dataset-retrieval",
            "failed-data-archiving",
            "underused-data-storage",
        ]

        if agent is None:
            agent = Agent(  # type: ignore[call-arg]
                agent_id=BUILT_IN_DATA_AGENT_ID,
                name="Data Agent",
                agent_type="data",
                description=(
                    "Stores and catalogs underused or failed lab datasets for future reuse."
                ),
                capabilities=capabilities,
                status="active",
                meta=data_agent_meta,
            )
            session.add(agent)
        else:
            merged_meta = dict(agent.meta or {})
            merged_meta.update(data_agent_meta)
            agent.name = "Data Agent"
            agent.agent_type = "data"
            agent.description = (
                "Stores and catalogs underused or failed lab datasets for future reuse."
            )
            agent.capabilities = capabilities
            agent.status = "active"
            agent.meta = merged_meta

        reputation = (
            session.query(AgentReputation)
            .filter(AgentReputation.agent_id == BUILT_IN_DATA_AGENT_ID)
            .one_or_none()
        )
        if reputation is None:
            session.add(
                AgentReputation(  # type: ignore[call-arg]
                    agent_id=BUILT_IN_DATA_AGENT_ID,
                    reputation_score=0.8,
                    total_tasks=0,
                    successful_tasks=0,
                    failed_tasks=0,
                    payment_multiplier=1.0,
                )
            )
        else:
            reputation.reputation_score = max(float(reputation.reputation_score or 0.0), 0.8)

        session.commit()
        rebuild_agents_cache(session=session)
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert built-in Data Agent")
    finally:
        session.close()


def _upsert_supported_research_agents() -> None:
    """Ensure the supported phase 0 research agents exist in the marketplace cache."""

    session = SessionLocal()
    try:
        for agent_id, details in SUPPORTED_AGENT_DETAILS.items():
            if agent_id == BUILT_IN_DATA_AGENT_ID:
                continue

            agent = (
                session.query(Agent)
                .filter(Agent.agent_id == agent_id)
                .one_or_none()
            )
            meta = {
                "endpoint_url": default_research_endpoint(agent_id),
                "pricing": details["pricing"],
                "categories": ["Research", "DeSci"],
                "support_tier": "supported",
                "always_listed": True,
            }

            if agent is None:
                session.add(
                    Agent(  # type: ignore[call-arg]
                        agent_id=agent_id,
                        name=details["name"],
                        agent_type="research",
                        description=details["description"],
                        capabilities=details["capabilities"],
                        hedera_account_id=details["hedera_account_id"],
                        status="active",
                        meta=meta,
                    )
                )
            else:
                merged_meta = dict(agent.meta or {})
                merged_meta.update(meta)
                agent.name = details["name"]
                agent.agent_type = "research"
                agent.description = details["description"]
                agent.capabilities = details["capabilities"]
                agent.hedera_account_id = details["hedera_account_id"]
                agent.status = "active"
                agent.meta = merged_meta

            reputation = (
                session.query(AgentReputation)
                .filter(AgentReputation.agent_id == agent_id)
                .one_or_none()
            )
            if reputation is None:
                session.add(
                    AgentReputation(  # type: ignore[call-arg]
                        agent_id=agent_id,
                        reputation_score=0.8,
                        total_tasks=0,
                        successful_tasks=0,
                        failed_tasks=0,
                        payment_multiplier=1.0,
                    )
                )
            else:
                reputation.reputation_score = max(float(reputation.reputation_score or 0.0), 0.8)

        session.commit()
        rebuild_agents_cache(session=session)
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert supported research agents")
    finally:
        session.close()


def _sync_task_cache(task_id: str, snapshot: Optional[Dict[str, Any]]) -> None:
    if snapshot is not None:
        tasks_storage[task_id] = snapshot


def update_task_progress(task_id: str, step: str, status: str, data: Optional[Dict] = None):
    """Update task progress for frontend polling."""
    overall_status = None
    if step == "orchestrator" and status in {"completed", "failed"}:
        overall_status = status
    elif status == "cancelled":
        overall_status = "CANCELLED"

    envelope = TelemetryEnvelope(
        task_id=task_id,
        step=step,
        status=status,
        data=redact_sensitive_payload(data or {}),
    )
    snapshot = append_progress_event(task_id, envelope, overall_status=overall_status)
    if snapshot is not None:
        _sync_task_cache(task_id, snapshot)
        return

    # Fallback for events emitted before the DB task row exists.
    existing = tasks_storage.setdefault(
        task_id,
        {
            "task_id": task_id,
            "status": "processing",
            "progress": [],
            "current_step": step,
        },
    )
    existing.setdefault("progress", []).append(envelope.model_dump(mode="json"))
    existing["current_step"] = step


# Pydantic models for API requests/responses
class TaskRequest(BaseModel):
    """Request model for creating a task."""

    description: str
    capability_requirements: Optional[str] = None
    budget_limit: Optional[float] = None
    min_reputation_score: Optional[float] = 0.7
    verification_mode: Optional[str] = "standard"


class TaskResponse(BaseModel):
    """Response model for task execution."""

    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class A2AEventResponse(BaseModel):
    """Response model for emitted A2A messages."""

    message_id: str
    protocol: str
    message_type: str
    from_agent: str
    to_agent: str
    thread_id: str
    timestamp: datetime
    tags: Optional[List[str]] = None
    body: Dict[str, Any]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global _registry_refresh_task

    # Startup: Create database tables
    Base.metadata.create_all(bind=engine)
    _upsert_builtin_data_agent()
    _upsert_supported_research_agents()
    # Register progress callback for task updates
    task_progress.set_progress_callback(update_task_progress)
    print("Database initialized")
    print("Orchestrator agent ready")

    loop = asyncio.get_running_loop()

    def _prime_registry() -> Optional[str]:
        try:
            result = ensure_registry_cache()
            if result:
                return f"Primed registry cache with {result.synced} agents"
            return "Registry cache already warm"
        except RegistrySyncError as exc:
            logger.warning("Initial registry sync failed: %s", exc)
            return None

    prime_message = await loop.run_in_executor(None, _prime_registry)
    if prime_message:
        logger.info(prime_message)

    _registry_refresh_task = loop.create_task(_periodic_registry_refresh())
    yield
    # Shutdown
    if _registry_refresh_task:
        _registry_refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await _registry_refresh_task
        _registry_refresh_task = None
    print("Shutting down...")


async def _periodic_registry_refresh() -> None:
    """Run registry cache refreshes on the configured TTL."""

    while True:
        interval = max(60, get_registry_cache_ttl_seconds())
        await asyncio.sleep(interval)
        loop = asyncio.get_running_loop()

        def _refresh() -> Optional[str]:
            result = ensure_registry_cache()
            if result:
                return f"Periodic registry sync refreshed {result.synced} agents"
            return None

        try:
            message = await loop.run_in_executor(None, _refresh)
            if message:
                logger.debug(message)
        except RegistrySyncError as exc:
            logger.warning("Periodic registry sync failed: %s", exc)


# Create FastAPI app
app = FastAPI(
    title="ProvidAI Orchestrator",
    description="Orchestrator agent that discovers, negotiates with, and executes tasks using marketplace agents",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware
app.middleware("http")(logging_middleware)

# Include routers
app.include_router(agents_routes.router, prefix="/api/agents", tags=["agents"])
app.include_router(data_agent_routes.router, prefix="/api/data-agent", tags=["data-agent"])
app.include_router(research_runs_routes.router, prefix="/api/research-runs", tags=["research-runs"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "ProvidAI Orchestrator",
        "version": "0.1.0",
        "description": "Orchestrator agent for discovering and coordinating marketplace agents",
        "workflow": [
            "1. Frame the research question",
            "2. Mine supporting literature with a supported research agent",
            "3. Synthesize findings and verify before releasing payment",
            "4. Return the literature-review report and payment trail",
        ],
        "endpoints": {
            "/execute": "POST - Execute a task using marketplace agents",
            "/api/research-runs": "POST - Create and start a graph-backed research run",
            "/api/research-runs/{id}": "GET - Inspect research run status, nodes, and attempts",
            "/health": "GET - Health check",
            "/api/tasks/{task_id}": "GET - Poll task status and progress",
            "/api/tasks/history": "GET - Retrieve task history with payments",
            "/a2a/events": "GET - View A2A message events",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "orchestrator"}


class SubTaskResponse(BaseModel):
    """Response model for subtask (payment) details."""
    id: str
    description: str
    agent_used: str
    agent_reputation: float
    cost: float
    status: str
    timestamp: datetime


class TaskHistoryResponse(BaseModel):
    """Response model for task history."""
    id: str
    research_query: str
    total_cost: float
    status: str
    created_at: datetime
    sub_tasks: List[SubTaskResponse]


@app.get("/api/tasks/history", response_model=List[TaskHistoryResponse])
def get_task_history(limit: int = 50) -> List[TaskHistoryResponse]:
    """
    Retrieve task history with associated payments (microtransactions).

    Returns tasks ordered by creation date (newest first) with their
    associated payment details representing agent microtransactions.
    """
    from shared.database.models import Agent, Payment, Task

    session = SessionLocal()
    try:
        capped_limit = max(1, min(limit, 200))

        # Query tasks with their payments
        tasks = (
            session.query(Task)
            .order_by(Task.created_at.desc())
            .limit(capped_limit)
            .all()
        )

        responses = []
        for task in tasks:
            # Get all payments for this task
            payments = (
                session.query(Payment)
                .filter(Payment.task_id == task.id)
                .order_by(Payment.created_at.asc())
                .all()
            )

            # Build subtasks from payments
            sub_tasks = []
            total_cost = 0.0

            for payment in payments:
                # Get agent details
                agent = session.query(Agent).filter(Agent.agent_id == payment.to_agent_id).first()
                agent_name = agent.name if agent else payment.to_agent_id

                # Get agent reputation (default to 0.0 if not found)
                from shared.database.models import AgentReputation
                reputation_record = session.query(AgentReputation).filter(
                    AgentReputation.agent_id == payment.to_agent_id
                ).first()
                reputation_score = reputation_record.reputation_score if reputation_record else 0.0

                # Extract description from payment metadata
                description = "Agent task execution"
                if payment.meta and isinstance(payment.meta, dict):
                    description = payment.meta.get("description", description)

                sub_tasks.append(SubTaskResponse(
                    id=payment.id,
                    description=description,
                    agent_used=agent_name,
                    agent_reputation=reputation_score,
                    cost=payment.amount,
                    status=payment.status.value,
                    timestamp=payment.created_at
                ))

                total_cost += payment.amount

            runtime_meta = {}
            if task.meta and isinstance(task.meta, dict):
                runtime_meta = dict(task.meta.get("runtime") or {})
            persisted_runtime_status = str(runtime_meta.get("status") or "").lower()

            # Map task status to frontend format
            status_mapping = {
                "pending": "in_progress",
                "assigned": "in_progress",
                "in_progress": "in_progress",
                "completed": "completed",
                "failed": "failed",
                "cancelled": "cancelled",
            }
            frontend_status = status_mapping.get(
                persisted_runtime_status or task.status.value,
                "in_progress",
            )

            responses.append(TaskHistoryResponse(
                id=task.id,
                research_query=task.title or task.description or "Unknown task",
                total_cost=total_cost,
                status=frontend_status,
                created_at=task.created_at,
                sub_tasks=sub_tasks
            ))

        return responses
    finally:
        session.close()


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get task status and progress for frontend polling."""
    if task_id not in tasks_storage:
        snapshot = load_task_snapshot(task_id)
        if snapshot:
            _sync_task_cache(task_id, snapshot)
        else:
            return {
                "task_id": task_id,
                "status": "not_found",
                "error": "Task not found"
            }

    return tasks_storage[task_id]


@app.post("/api/tasks/{task_id}/approve_verification")
async def approve_verification(task_id: str):
    """Approve verification for a task requiring human review."""
    snapshot = tasks_storage.get(task_id) or load_task_snapshot(task_id)
    if snapshot is None:
        return {
            "success": False,
            "error": "Task not found"
        }
    _sync_task_cache(task_id, snapshot)

    if not snapshot.get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    decision = {
        "approved": True,
        "timestamp": datetime.now().isoformat()
    }
    persist_verification_state(
        task_id,
        pending=False,
        verification_data=None,
        verification_decision=decision,
    )
    _sync_task_cache(task_id, load_task_snapshot(task_id))

    # Update progress
    verification_data = snapshot.get("verification_data", {})
    todo_id = verification_data.get("todo_id", "unknown")

    update_task_progress(task_id, f"verification_{todo_id}", "completed", {
        "message": "✓ Approved by human reviewer",
        "human_approved": True,
        "quality_score": verification_data.get("quality_score", 0)
    })

    return {
        "success": True,
        "message": "Verification approved",
        "task_id": task_id
    }


@app.post("/api/tasks/{task_id}/reject_verification")
async def reject_verification(task_id: str, reason: str = "Rejected by reviewer"):
    """Reject verification for a task requiring human review."""
    import logging
    logger = logging.getLogger(__name__)

    snapshot = tasks_storage.get(task_id) or load_task_snapshot(task_id)
    if snapshot is None:
        return {
            "success": False,
            "error": "Task not found"
        }
    _sync_task_cache(task_id, snapshot)

    if not snapshot.get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    decision = {
        "approved": False,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }
    persist_verification_state(
        task_id,
        pending=False,
        verification_data=None,
        verification_decision=decision,
    )
    refreshed_snapshot = load_task_snapshot(task_id) or snapshot
    refreshed_snapshot["status"] = "CANCELLED"
    tasks_storage[task_id] = refreshed_snapshot

    # Update progress
    verification_data = snapshot.get("verification_data", {})
    todo_id = verification_data.get("todo_id", "unknown")

    update_task_progress(task_id, f"verification_{todo_id}", "failed", {
        "message": f"✗ Rejected by human reviewer: {reason}",
        "human_rejected": True,
        "quality_score": verification_data.get("quality_score", 0),
        "rejection_reason": reason
    })

    # Add prominent cancellation card to progress logs
    update_task_progress(task_id, "cancellation", "cancelled", {
        "message": f"🚫 TASK CANCELLED - All execution stopped",
        "reason": reason,
        "cancelled_at": datetime.now().isoformat(),
        "cancelled_by": "user"
    })

    # Log cancellation details
    logger.info(f"[reject_verification] Task {task_id} cancelled by user. Reason: {reason}")

    return {
        "success": True,
        "message": "Verification rejected and task execution cancelled",
        "task_id": task_id,
        "reason": reason
    }


@app.get("/a2a/events", response_model=List[A2AEventResponse])
def list_a2a_events(limit: int = 50) -> List[A2AEventResponse]:
    """Return recent A2A events emitted by the system."""

    session = SessionLocal()
    try:
        capped_limit = max(1, min(limit, 200))
        records = (
            session.query(A2AEvent)
            .order_by(A2AEvent.timestamp.desc(), A2AEvent.id.desc())
            .limit(capped_limit)
            .all()
        )

        responses = []
        for record in records:
            responses.append(
                A2AEventResponse(
                    message_id=record.message_id,
                    protocol=record.protocol,
                    message_type=record.message_type,
                    from_agent=record.from_agent,
                    to_agent=record.to_agent,
                    thread_id=record.thread_id,
                    timestamp=record.timestamp,
                    tags=record.tags or None,
                    body=record.body or {},
                )
            )

        return responses
    finally:
        session.close()


async def run_orchestrator_task(task_id: str, request: TaskRequest):
    """Background task to run the deterministic phase 0 literature workflow."""
    try:
        db = SessionLocal()
        try:
            task = Task(
                id=task_id,
                title=f"Research: {request.description[:50]}...",
                description=request.description,
                status="in_progress",
                created_at=datetime.utcnow(),
                meta={
                    "budget_limit": request.budget_limit,
                    "min_reputation_score": request.min_reputation_score,
                    "verification_mode": request.verification_mode,
                    "capability_requirements": request.capability_requirements,
                    "workflow_type": "phase0_literature_review",
                }
            )
            db.add(task)
            db.commit()
            logger.info(f"Created Task record in database: {task_id}")
        finally:
            db.close()
        initialize_runtime_state(
            task_id,
            request_meta={
                "budget_limit": request.budget_limit,
                "min_reputation_score": request.min_reputation_score,
                "verification_mode": request.verification_mode,
                "capability_requirements": request.capability_requirements,
            },
        )
        _sync_task_cache(task_id, load_task_snapshot(task_id))

        # Update progress - initialization
        update_task_progress(task_id, "initialization", "started", {
            "message": "Starting task execution",
            "description": request.description
        })
        update_task_progress(task_id, "orchestrator_analysis", "running", {
            "message": "Preparing the phase 0 literature-review workflow"
        })
        todo_items = build_phase0_todo_items(request.description)
        todo_result = await create_todo_list(
            task_id,
            [
                {
                    "title": item["title"],
                    "description": item["description"],
                    "assigned_to": item["assigned_to"],
                }
                for item in todo_items
            ],
        )
        todo_list = todo_result["todo_list"]

        result_0 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_0",
            task_name=todo_items[0]["title"],
            task_description=todo_items[0]["description"],
            capability_requirements="problem framing, research question design, scope definition",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters={"phase": "ideation"},
            todo_list=todo_list,
        )
        if not result_0.get("success"):
            raise RuntimeError(result_0.get("error", "Problem framing failed"))

        result_1 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_1",
            task_name=todo_items[1]["title"],
            task_description=todo_items[1]["description"],
            capability_requirements="literature mining, source collection, evidence gathering",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters={
                "phase": "knowledge_retrieval",
                "framed_question": result_0.get("result"),
            },
            todo_list=todo_list,
        )
        if not result_1.get("success"):
            raise RuntimeError(result_1.get("error", "Literature mining failed"))

        result_2 = await execute_microtask(
            task_id=task_id,
            todo_id="todo_2",
            task_name=todo_items[2]["title"],
            task_description=todo_items[2]["description"],
            capability_requirements="knowledge synthesis, research summarization, report composition",
            budget_limit=request.budget_limit,
            min_reputation_score=request.min_reputation_score,
            execution_parameters={
                "phase": "knowledge_retrieval",
                "framed_question": result_0.get("result"),
                "literature_findings": result_1.get("result"),
            },
            todo_list=todo_list,
        )
        if not result_2.get("success"):
            raise RuntimeError(result_2.get("error", "Knowledge synthesis failed"))

        result = {
            "workflow": "problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001",
            "steps": [result_0, result_1, result_2],
            "report": result_2.get("result"),
            "framing": result_0.get("result"),
            "evidence": result_1.get("result"),
        }

        # Update final status
        update_task_progress(task_id, "orchestrator", "completed", {
            "message": "Generated research output successfully",
            "result": redact_sensitive_payload(result),
        })

        snapshot = load_task_snapshot(task_id) or {"task_id": task_id, "status": "completed"}
        snapshot["status"] = "completed"
        snapshot["result"] = result
        tasks_storage[task_id] = snapshot

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "completed"
                task.result = result
                db.commit()
                logger.info(f"Updated Task status to completed: {task_id}")
        finally:
            db.close()

    except Exception as e:
        # Update error status
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        update_task_progress(task_id, "orchestrator", "failed", {
            "error": str(e)
        })
        snapshot = load_task_snapshot(task_id) or {"task_id": task_id}
        snapshot["status"] = "failed"
        snapshot["error"] = str(e)
        tasks_storage[task_id] = snapshot

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "failed"
                task.result = {"error": str(e)}
                db.commit()
                logger.info(f"Updated Task status to failed: {task_id}")
        finally:
            db.close()


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest, background_tasks: BackgroundTasks) -> TaskResponse:
    """
    Execute a task using the orchestrator agent.

    The orchestrator will:
    1. Decompose the task into specialized microtasks
    2. For each microtask: discover agents → authorize payment → execute
    3. Aggregate results from all microtasks
    4. Return complete output

    Args:
        request: Task request with description and optional parameters

    Returns:
        TaskResponse with task ID - execution happens in background
    """
    task_id = str(uuid.uuid4())

    # Initialize task in storage
    tasks_storage[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": [],
        "current_step": "initializing"
    }

    # Run orchestrator in background
    background_tasks.add_task(run_orchestrator_task, task_id, request)

    # Return immediately with task_id
    return TaskResponse(
        task_id=task_id,
        status="processing",
        result={
            "message": "Task started, poll /api/tasks/{task_id} for progress"
        }
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    uvicorn.run("api.main:app", host=host, port=port, reload=True)
