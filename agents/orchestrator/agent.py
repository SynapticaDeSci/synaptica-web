"""Orchestrator Agent implementation using OpenAI API."""

from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent

from .system_prompt import ORCHESTRATOR_SYSTEM_PROMPT
from .tools import (
    create_task,
    create_todo_list,
    execute_microtask,
    get_task,
    update_task_status,
    update_todo_item,
)


def create_orchestrator_agent() -> AsyncStrandsAgent:
    """
    Create and configure the Orchestrator agent.

    Returns:
        Configured OpenAI Agent instance
    """
    # Define tools for the orchestrator
    tools = [
        create_task,
        update_task_status,
        get_task,
        create_todo_list,
        update_todo_item,
        execute_microtask,
    ]

    agent = create_strands_openai_agent(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=tools,
        model_env_var="ORCHESTRATOR_MODEL",
        agent_id="orchestrator-agent",
        name="Orchestrator",
        description="Coordinates research tasks and microtask execution.",
    )

    return agent
