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
from shared.database.models import A2AEvent
from shared.registry_sync import (
    RegistrySyncError,
    ensure_registry_cache,
    get_registry_cache_ttl_seconds,
)
import shared.task_progress as task_progress
from agents.orchestrator.agent import create_orchestrator_agent

from .middleware import logging_middleware
from .routes import agents as agents_routes
from .routes import data_agent as data_agent_routes

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

        session.commit()
        rebuild_agents_cache(session=session)
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert built-in Data Agent")
    finally:
        session.close()


def update_task_progress(task_id: str, step: str, status: str, data: Optional[Dict] = None):
    """Update task progress for frontend polling."""
    if task_id not in tasks_storage:
        tasks_storage[task_id] = {
            "task_id": task_id,
            "status": "processing",
            "progress": [],
            "current_step": step
        }

    if "progress" not in tasks_storage[task_id]:
        tasks_storage[task_id]["progress"] = []

    tasks_storage[task_id]["progress"].append({
        "step": step,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data or {}
    })

    tasks_storage[task_id]["current_step"] = step

    # Only update overall task status when orchestrator completes/fails
    # Intermediate steps (planning, negotiator, executor) shouldn't affect overall status
    if step == "orchestrator" and status in ["completed", "failed"]:
        tasks_storage[task_id]["status"] = status
    elif tasks_storage[task_id]["status"] not in ["completed", "failed"]:
        # Keep as "processing" for all intermediate steps
        tasks_storage[task_id]["status"] = "processing"


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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "ProvidAI Orchestrator",
        "version": "0.1.0",
        "description": "Orchestrator agent for discovering and coordinating marketplace agents",
        "workflow": [
            "1. Analyze request and decompose into specialized microtasks",
            "2. For each microtask: discover agents (negotiator) → authorize payment → execute task",
            "3. Aggregate results from all microtasks",
            "4. Return complete output",
        ],
        "endpoints": {
            "/execute": "POST - Execute a task using marketplace agents",
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

            # Map task status to frontend format
            status_mapping = {
                "pending": "in_progress",
                "assigned": "in_progress",
                "in_progress": "in_progress",
                "completed": "completed",
                "failed": "failed"
            }
            frontend_status = status_mapping.get(task.status.value, "in_progress")

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
        return {
            "task_id": task_id,
            "status": "not_found",
            "error": "Task not found"
        }

    return tasks_storage[task_id]


@app.post("/api/tasks/{task_id}/approve_verification")
async def approve_verification(task_id: str):
    """Approve verification for a task requiring human review."""
    if task_id not in tasks_storage:
        return {
            "success": False,
            "error": "Task not found"
        }

    if not tasks_storage[task_id].get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    # Store approval decision
    tasks_storage[task_id]["verification_decision"] = {
        "approved": True,
        "timestamp": datetime.now().isoformat()
    }
    tasks_storage[task_id]["verification_pending"] = False

    # Update progress
    verification_data = tasks_storage[task_id].get("verification_data", {})
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

    if task_id not in tasks_storage:
        return {
            "success": False,
            "error": "Task not found"
        }

    if not tasks_storage[task_id].get("verification_pending"):
        return {
            "success": False,
            "error": "No verification pending for this task"
        }

    # Store rejection decision
    tasks_storage[task_id]["verification_decision"] = {
        "approved": False,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }
    tasks_storage[task_id]["verification_pending"] = False

    # CRITICAL: Set cancellation flag to stop all ongoing execution
    tasks_storage[task_id]["cancelled"] = True
    tasks_storage[task_id]["status"] = "CANCELLED"

    # Update progress
    verification_data = tasks_storage[task_id].get("verification_data", {})
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
    """Background task to run the orchestrator agent."""
    try:
        # Create Task record in database for transaction history
        from datetime import datetime

        from shared.database import SessionLocal
        from shared.database.models import Task

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
                }
            )
            db.add(task)
            db.commit()
            logger.info(f"Created Task record in database: {task_id}")
        finally:
            db.close()

        # Update progress - initialization
        update_task_progress(task_id, "initialization", "started", {
            "message": "Starting task execution",
            "description": request.description
        })

        # Create orchestrator agent
        orchestrator = create_orchestrator_agent()

        # Build the orchestrator query
        query = f"""
        Task ID: {task_id}

        User Request:
        {request.description}

        Configuration:
        - Budget Limit: {request.budget_limit or "No specific limit"}
        - Minimum Reputation Score: {request.min_reputation_score}
        - Verification Mode: {request.verification_mode}
        - Initial Capability Hint: {request.capability_requirements or "Analyze the task to determine"}

        Execute your standard workflow to completion. Remember to:
        - Break complex requests into specialized microtasks when beneficial
        - Define specific, detailed capability requirements for each agent
        - Actually call all agent tools (negotiator, authorize_payment, executor)
        - Aggregate results and return a complete summary
        """

        # Run the orchestrator agent
        update_task_progress(task_id, "orchestrator_analysis", "running", {
            "message": "Orchestrator analyzing task and coordinating agents"
        })

        result = await orchestrator.run(query)

        # Log the full orchestrator response
        logger.info("========== ORCHESTRATOR RESPONSE START ==========")
        logger.info(f"{result}")
        logger.info("========== ORCHESTRATOR RESPONSE END ==========")

        # Update final status
        update_task_progress(task_id, "orchestrator", "completed", {
            "message": "Generated research output successfully",
            "result": str(result)
        })

        tasks_storage[task_id]["status"] = "completed"
        tasks_storage[task_id]["result"] = {
            "orchestrator_response": str(result),
            "workflow": "Task decomposition → Per microtask: (negotiator → authorize → executor) → Aggregation",
        }

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "completed"
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

        tasks_storage[task_id]["status"] = "failed"
        tasks_storage[task_id]["error"] = str(e)

        # Update Task status in database
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "failed"
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
