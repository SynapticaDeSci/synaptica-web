"""Executor Agent implementation - executes research agents via API."""

import os

from agents.executor.tools.research_api_executor import (
    execute_research_agent,
    get_agent_metadata,
    list_research_agents,
)
from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent

from .system_prompt import EXECUTOR_SYSTEM_PROMPT


def create_executor_agent() -> AsyncStrandsAgent:
    """
    Create and configure the Executor agent.

    The Executor agent:
    - Lists available research agents from the API server (port 5001)
    - Selects the best agent for each microtask
    - Executes agents via HTTP POST requests (no simulation)
    - Returns real agent outputs

    Returns:
        Configured OpenAI Agent instance
    """
    # Tools for executing research agents via API
    tools = [
        list_research_agents,      # List all available research agents
        execute_research_agent,    # Execute a specific research agent
        get_agent_metadata,        # Get detailed agent metadata
    ]

    agent = create_strands_openai_agent(
        system_prompt=EXECUTOR_SYSTEM_PROMPT,
        tools=tools,
        model_env_var="EXECUTOR_MODEL",
        agent_id="executor-agent",
        name="Executor",
        description="Selects and invokes research agents over HTTP.",
    )

    return agent
