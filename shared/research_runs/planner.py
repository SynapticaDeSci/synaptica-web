"""Template planning for research-run execution graphs."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


SUPPORTED_RESEARCH_RUN_WORKFLOW = (
    "problem-framer-001 -> literature-miner-001 -> knowledge-synthesizer-001"
)


class ResearchRunPlanNode(BaseModel):
    """Single node within a research-run plan."""

    node_id: str
    title: str
    description: str
    capability_requirements: str
    assigned_agent_id: str
    execution_order: int
    execution_parameters: Dict[str, Any] = Field(default_factory=dict)
    input_bindings: Dict[str, str] = Field(default_factory=dict)


class ResearchRunPlanEdge(BaseModel):
    """Directed dependency edge between research-run nodes."""

    from_node_id: str
    to_node_id: str


class ResearchRunPlan(BaseModel):
    """Template research-run plan."""

    workflow_template: str
    workflow: str
    nodes: List[ResearchRunPlanNode]
    edges: List[ResearchRunPlanEdge]


def build_research_run_plan(description: str) -> ResearchRunPlan:
    """Build the fixed literature-review graph used by the Phase 1A research run."""

    return ResearchRunPlan(
        workflow_template="phase1a_literature_review",
        workflow=SUPPORTED_RESEARCH_RUN_WORKFLOW,
        nodes=[
            ResearchRunPlanNode(
                node_id="problem_framing",
                title="Frame the research question",
                description=(
                    "Clarify the user's request into a scoped research question, constraints, "
                    "and searchable literature-review brief.\n\n"
                    f"User request:\n{description}"
                ),
                capability_requirements="problem framing, research question design, scope definition",
                assigned_agent_id="problem-framer-001",
                execution_order=0,
                execution_parameters={"phase": "ideation"},
            ),
            ResearchRunPlanNode(
                node_id="literature_mining",
                title="Mine supporting literature",
                description=(
                    "Find relevant papers, sources, and evidence for the framed question.\n\n"
                    f"Base request:\n{description}"
                ),
                capability_requirements="literature mining, source collection, evidence gathering",
                assigned_agent_id="literature-miner-001",
                execution_order=1,
                execution_parameters={"phase": "knowledge_retrieval"},
                input_bindings={"framed_question": "problem_framing"},
            ),
            ResearchRunPlanNode(
                node_id="knowledge_synthesis",
                title="Synthesize the findings",
                description=(
                    "Produce a synthesis of the literature review, highlighting key findings, "
                    "uncertainties, and next steps.\n\n"
                    f"Base request:\n{description}"
                ),
                capability_requirements="knowledge synthesis, research summarization, report composition",
                assigned_agent_id="knowledge-synthesizer-001",
                execution_order=2,
                execution_parameters={"phase": "knowledge_retrieval"},
                input_bindings={
                    "framed_question": "problem_framing",
                    "literature_findings": "literature_mining",
                },
            ),
        ],
        edges=[
            ResearchRunPlanEdge(from_node_id="problem_framing", to_node_id="literature_mining"),
            ResearchRunPlanEdge(from_node_id="literature_mining", to_node_id="knowledge_synthesis"),
        ],
    )
