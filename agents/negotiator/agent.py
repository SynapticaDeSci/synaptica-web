"""Negotiator Agent implementation using OpenAI API."""

from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent

from .system_prompt import NEGOTIATOR_SYSTEM_PROMPT
from .tools import (
    find_agents,
    resolve_agent_by_domain,
    compare_agent_scores,
    create_payment_request,
    get_payment_status,
)


def create_negotiator_agent() -> AsyncStrandsAgent:
    """
    Create and configure the Negotiator agent.

    Returns:
        Configured OpenAI Agent instance
    """
    tools = [
        find_agents,
        resolve_agent_by_domain,
        compare_agent_scores,
        create_payment_request,
        get_payment_status,
    ]

    agent = create_strands_openai_agent(
        system_prompt=NEGOTIATOR_SYSTEM_PROMPT,
        tools=tools,
        model_env_var="NEGOTIATOR_MODEL",
        agent_id="negotiator-agent",
        name="Negotiator",
        description="Finds supported agents and prepares payment proposals.",
    )

    return agent
