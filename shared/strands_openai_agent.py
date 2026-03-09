"""Native Strands OpenAI Responses helpers for the active runtime."""

from __future__ import annotations

import os
from typing import Any, Callable, List, Optional

from strands import Agent as StrandsAgent
from strands.models.model import Model
from strands.models.openai_responses import OpenAIResponsesModel


DEFAULT_OPENAI_MODEL = "gpt-5.4"


class AsyncStrandsAgent:
    """Small compatibility adapter that preserves the repo's async ``run`` interface."""

    def __init__(self, agent: StrandsAgent, *, model: str):
        self._agent = agent
        self.model = model

    async def run(self, request: str) -> str:
        """Execute the agent and normalize the final result to text."""

        result = await self._agent.invoke_async(request)
        return str(result)

    @property
    def agent(self) -> StrandsAgent:
        """Expose the underlying Strands agent for callers that need it."""

        return self._agent


def resolve_openai_model(model: Optional[str] = None, *, env_var: Optional[str] = None) -> str:
    """Resolve the OpenAI model from explicit input, env override, or default."""

    if model:
        return model

    if env_var:
        configured = os.getenv(env_var)
        if configured:
            return configured

    return DEFAULT_OPENAI_MODEL


def create_strands_openai_agent(
    *,
    system_prompt: str,
    tools: Optional[List[Callable[..., Any]]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    model_env_var: Optional[str] = None,
    agent_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    model_provider: Optional[Model] = None,
) -> AsyncStrandsAgent:
    """Create an async-compatible Strands agent backed by OpenAI Responses."""

    resolved_model = resolve_openai_model(model, env_var=model_env_var)
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if model_provider is None and not resolved_api_key:
        raise ValueError("OPENAI_API_KEY not set")

    provider = model_provider or OpenAIResponsesModel(
        client_args={"api_key": resolved_api_key},
        model_id=resolved_model,
    )
    agent = StrandsAgent(
        model=provider,
        tools=tools or [],
        system_prompt=system_prompt,
        agent_id=agent_id,
        name=name,
        description=description,
    )
    return AsyncStrandsAgent(agent, model=resolved_model)
