"""Data Agent implementation — LLM-powered dataset exploration."""

from agents.data_agent.tools.dataset_tools import (
    get_dataset_content_preview,
    get_dataset_detail,
    list_datasets,
)
from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent

from .system_prompt import DATA_AGENT_SYSTEM_PROMPT


def create_data_agent() -> AsyncStrandsAgent:
    """Create and configure the Data Agent.

    The Data Agent helps users explore and understand datasets in the
    Synaptica Data Vault using natural language.
    """
    tools = [
        list_datasets,
        get_dataset_detail,
        get_dataset_content_preview,
    ]

    return create_strands_openai_agent(
        system_prompt=DATA_AGENT_SYSTEM_PROMPT,
        tools=tools,
        model_env_var="DATA_AGENT_MODEL",
        agent_id="data-agent",
        name="Data Agent",
        description="Helps users explore datasets in the Synaptica Data Vault.",
    )
