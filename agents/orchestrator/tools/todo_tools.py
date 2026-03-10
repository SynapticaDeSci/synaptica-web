"""TODO management tools for Orchestrator."""

from typing import List, Dict, Any, Optional

from strands import tool
from shared.task_progress import update_progress

@tool
async def create_todo_list(task_id: str, items: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Create a structured TODO list for a task.

    Args:
        task_id: Task ID
        items: List of TODO items, each with 'title', 'description', 'assigned_to'

    Returns:
        Created TODO list information

    Example:
        items = [
            {
                "title": "Discover marketplace agents",
                "description": "Use ERC-8004 to find agents with 'data-analysis' capability",
                "assigned_to": "negotiator"
            },
            {
                "title": "Create custom integration tool",
                "description": "Generate dynamic tool for discovered agent API",
                "assigned_to": "executor"
            }
        ]
    """
    from shared.database import SessionLocal, Task

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            # Task might not be in database yet (in-memory only), so just send progress update
            pass
        else:
            # Store TODO list in task metadata
            if task.meta is None:
                task.meta = {}

            task.meta["todo_list"] = [
                {
                    "id": item.get("id", f"todo_{i}"),
                    "status": "pending",
                    **item,
                }
                for i, item in enumerate(items)
            ]

            db.commit()
            db.refresh(task)

        # Send progress update to frontend with TODO list
        todo_list = [
            {
                "id": item.get("id", f"todo_{i}"),
                "status": "pending",
                **item,
            }
            for i, item in enumerate(items)
        ]

        # Mark initialization and orchestrator analysis as completed when planning finishes
        update_progress(task_id, "initialization", "completed", {
            "message": "Task initialization completed"
        })

        # The initial "orchestrator running" step should complete here
        # (The final orchestrator step will complete when the entire workflow finishes)
        update_progress(task_id, "orchestrator_analysis", "completed", {
            "message": "Task analysis completed"
        })

        update_progress(task_id, "planning", "completed", {
            "message": "Created task plan with TODO list",
            "todo_list": todo_list
        })

        return {
            "task_id": task_id,
            "todo_count": len(items),
            "todo_list": todo_list,
        }
    finally:
        db.close()

@tool
async def update_todo_item(task_id: str, todo_id: str, status: str, todo_list: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Update TODO item status and emit progress update to frontend.

    CRITICAL: Call this function to mark each microtask as in_progress when starting
    and completed when finished!

    Args:
        task_id: Task ID
        todo_id: TODO item ID (e.g., "todo_0", "todo_1")
        status: New status (pending, in_progress, completed, failed)
        todo_list: Optional TODO list to use if task not in database yet

    Returns:
        Updated TODO item information

    Example Usage:
        # When starting first microtask
        update_todo_item(task_id, "todo_0", "in_progress")

        # After completing negotiation + execution for first microtask
        update_todo_item(task_id, "todo_0", "completed")

        # Start second microtask
        update_todo_item(task_id, "todo_1", "in_progress")
    """
    from shared.database import SessionLocal, Task
    import logging

    logger = logging.getLogger(__name__)

    db = SessionLocal()
    try:
        # Initialize defaults
        found = False
        todo_title = "Unknown task"
        todo_description = ""
        todo_assigned_to = None

        # First try to get from database
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.meta and "todo_list" in task.meta:
            for item in task.meta["todo_list"]:
                if isinstance(item, dict) and item.get("id") == todo_id:
                    todo_title = item.get("title", "Unknown task")
                    todo_description = item.get("description", "")
                    todo_assigned_to = item.get("assigned_to", None)
                    found = True
                    logger.info(f"[update_todo_item] Found TODO in database: id={todo_id}, title={todo_title}")

                    # Update status in database
                    item["status"] = status
                    db.commit()
                    break

        # If not found in database and todo_list provided, check there
        if not found and todo_list is not None:
            logger.info(f"[update_todo_item] Checking provided todo_list: type={type(todo_list)}, length={len(todo_list) if isinstance(todo_list, list) else 'N/A'}")

            # Handle case where todo_list might be passed as JSON string
            if isinstance(todo_list, str):
                import json
                try:
                    todo_list = json.loads(todo_list)
                    logger.info("[update_todo_item] Parsed todo_list from JSON string")
                except json.JSONDecodeError:
                    logger.error(f"[update_todo_item] Failed to parse todo_list JSON string: {todo_list[:100]}")
                    todo_list = None

            if isinstance(todo_list, list):
                for item in todo_list:
                    if isinstance(item, dict) and item.get("id") == todo_id:
                        todo_title = item.get("title", "Unknown task")
                        todo_description = item.get("description", "")
                        todo_assigned_to = item.get("assigned_to", None)
                        found = True
                        logger.info(f"[update_todo_item] Found TODO in provided list: id={todo_id}, title={todo_title}")
                        break
                    elif not isinstance(item, dict):
                        logger.warning(f"[update_todo_item] Invalid todo_list item type: {type(item)}, value: {item}")

        if not found:
            logger.warning(f"[update_todo_item] Could not find TODO {todo_id} in database or provided list")

        # Emit progress update to frontend based on status
        # Note: We don't emit "in_progress" updates here because negotiator already shows "Agent selected for: {task}"
        # We only emit completion/failure updates
        if status == "completed":
            # Emit completion for this specific microtask
            update_progress(task_id, f"microtask_{todo_id}", "completed", {
                "message": f"✓ Completed: {todo_title}",
                "todo_id": todo_id,
                "assigned_to": todo_assigned_to,
                "description": todo_description
            })
        elif status == "failed":
            update_progress(task_id, f"microtask_{todo_id}", "failed", {
                "message": f"✗ Failed: {todo_title}",
                "todo_id": todo_id,
                "assigned_to": todo_assigned_to,
                "error": "Microtask failed"
            })

        return {
            "task_id": task_id,
            "todo_id": todo_id,
            "status": status,
            "title": todo_title,
            "message": f"TODO item '{todo_title}' marked as {status}"
        }
    finally:
        db.close()
