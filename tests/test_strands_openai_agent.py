from __future__ import annotations

import asyncio
from typing import Any

import pytest
from strands.agent.agent_result import AgentResult
from strands.models.model import Model
from strands.telemetry.metrics import EventLoopMetrics

from agents.executor.agent import create_executor_agent
from agents.research.phase1_ideation.problem_framer.agent import ProblemFramerAgent
from shared.strands_openai_agent import create_strands_openai_agent
from strands.models.openai import OpenAIModel


class DummyModel(Model):
    def update_config(self, **model_config: Any) -> None:
        self.config = model_config

    def get_config(self) -> Any:
        return getattr(self, "config", {})

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        if False:
            yield

    async def stream(
        self,
        messages,
        tool_specs=None,
        system_prompt=None,
        *,
        tool_choice=None,
        system_prompt_content=None,
        invocation_state=None,
        **kwargs,
    ):
        if False:
            yield


def _agent_result(text: str) -> AgentResult:
    return AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": text}]},
        metrics=EventLoopMetrics(),
        state={},
    )


@pytest.mark.asyncio
async def test_create_strands_openai_agent_runs_and_returns_text(monkeypatch):
    async def _fake_invoke_async(self, prompt, **kwargs):
        del self, kwargs
        return _agent_result(f"Echo: {prompt}")

    monkeypatch.setattr("shared.strands_openai_agent.StrandsAgent.invoke_async", _fake_invoke_async)

    agent = create_strands_openai_agent(
        system_prompt="You are a test agent.",
        tools=[],
        model="gpt-5.4",
        model_provider=DummyModel(),
    )

    result = await agent.run("hello from strands")

    assert "Echo: hello from strands" in result
    assert agent.model == "gpt-5.4"


def test_create_strands_openai_agent_uses_openai_model_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    agent = create_strands_openai_agent(
        system_prompt="You are a test agent.",
        tools=[],
        model="gpt-5.4",
    )

    assert isinstance(agent.agent.model, OpenAIModel)


@pytest.mark.asyncio
async def test_executor_agent_uses_strands_backed_run(monkeypatch):
    async def _fake_invoke_async(self, prompt, **kwargs):
        del self, kwargs
        return _agent_result(f"Executor handled: {prompt}")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("shared.strands_openai_agent.StrandsAgent.invoke_async", _fake_invoke_async)

    agent = create_executor_agent()
    result = await agent.run("List supported research agents")

    assert "Executor handled: List supported research agents" in result
    assert agent.model == "gpt-5.4"


@pytest.mark.asyncio
async def test_base_research_agent_execute_preserves_response_shape(monkeypatch):
    async def _fake_run(request: str) -> str:
        return '{"research_question":"How do agent payments work?","keywords":["agent","payments","desci"],"hypothesis":"Payments improve coordination.","scope":{"included":["agent markets"]},"feasibility":{"score":0.8},"novelty_assessment":{"score":0.7}}'

    class FakeAgent:
        def __init__(self):
            self.model = "gpt-5.4"

        async def run(self, request: str) -> str:
            return await _fake_run(request)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "agents.research.base_research_agent.create_strands_openai_agent",
        lambda **kwargs: FakeAgent(),
    )

    agent = ProblemFramerAgent()
    result = await agent.execute("Frame a research question about agent payments.")

    assert result["success"] is True
    assert result["agent_id"] == "problem-framer-001"
    assert result["result"]
    assert result["metadata"]["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_base_research_agent_execute_uses_fresh_agent_per_request(monkeypatch):
    class ConcurrentSensitiveAgent:
        def __init__(self, label: str):
            self.model = "gpt-5.4"
            self.label = label
            self._running = False

        async def run(self, request: str) -> str:
            if self._running:
                raise RuntimeError("Agent is already processing a request")
            self._running = True
            try:
                await asyncio.sleep(0.01)
                return f"{self.label}:{request}"
            finally:
                self._running = False

    created_agents: list[ConcurrentSensitiveAgent] = []

    def _build_agent(**kwargs):
        del kwargs
        agent = ConcurrentSensitiveAgent(label=f"agent-{len(created_agents) + 1}")
        created_agents.append(agent)
        return agent

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "agents.research.base_research_agent.create_strands_openai_agent",
        _build_agent,
    )

    agent = ProblemFramerAgent()
    first, second = await asyncio.gather(
        agent.execute("first request"),
        agent.execute("second request"),
    )

    assert first["success"] is True
    assert second["success"] is True
    assert len(created_agents) == 2
    assert first["result"] == "agent-1:first request"
    assert second["result"] == "agent-2:second request"
