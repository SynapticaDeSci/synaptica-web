"""Legacy task-management routes kept for reference only.

These routes are not mounted by ``api.main`` in the active phase 0 runtime.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.database import get_db, Task
from shared.database.models import TaskStatus
from agents.orchestrator import create_orchestrator_agent

router = APIRouter()


class TaskCreate(BaseModel):
    """Task creation request."""

    title: str
    description: str
    metadata: Optional[dict] = None


class TaskResponse(BaseModel):
    """Task response."""

    id: str
    title: str
    description: str
    status: str
    created_by: str
    assigned_to: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post("/", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Create a new task."""
    agent = create_orchestrator_agent()

    # Use orchestrator to create task
    request = f"""
    Create a new task:
    Title: {task.title}
    Description: {task.description}
    """

    result = await agent.run(request)

    # Get the created task from database
    db_task = db.query(Task).order_by(Task.created_at.desc()).first()

    return TaskResponse(
        id=db_task.id,
        title=db_task.title,
        description=db_task.description,
        status=db_task.status.value,
        created_by=db_task.created_by,
        assigned_to=db_task.assigned_to,
        created_at=db_task.created_at.isoformat(),
        updated_at=db_task.updated_at.isoformat(),
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get task by ID."""
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        created_by=task.created_by,
        assigned_to=task.assigned_to,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)
):
    """List tasks with optional filtering."""
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == TaskStatus(status))

    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()

    return [
        TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            status=task.status.value,
            created_by=task.created_by,
            assigned_to=task.assigned_to,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat(),
        )
        for task in tasks
    ]
