"""Dynamic planning for deep research runs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


SUPPORTED_RESEARCH_RUN_WORKFLOW = (
    "plan_query -> gather_evidence -> curate_sources -> draft_synthesis -> "
    "critique_and_fact_check -> revise_final_answer"
)

_LIVE_QUERY_HINTS = {
    "today",
    "current",
    "currently",
    "latest",
    "recent",
    "breaking",
    "news",
    "live",
    "market",
    "markets",
    "war",
    "ceasefire",
    "election",
    "tariff",
    "sanctions",
    "price",
    "prices",
    "stocks",
    "oil",
    "conflict",
}

_LITERATURE_QUERY_HINTS = {
    "literature",
    "paper",
    "papers",
    "review",
    "survey",
    "academic",
    "study",
    "studies",
    "journal",
    "evidence",
    "citation",
    "citations",
    "meta-analysis",
}

_SCENARIO_HINTS = {
    "scenario",
    "forecast",
    "predict",
    "projection",
    "hypothetical",
    "would happen",
    "what if",
}

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "their",
    "there",
    "about",
    "what",
    "when",
    "where",
    "which",
    "while",
    "would",
    "should",
    "could",
    "these",
    "those",
    "them",
    "they",
    "been",
    "being",
    "have",
    "has",
    "had",
    "were",
    "was",
    "does",
    "did",
    "how",
}


class ResearchMode(str, Enum):
    AUTO = "auto"
    LITERATURE = "literature"
    LIVE_ANALYSIS = "live_analysis"
    HYBRID = "hybrid"


class DepthMode(str, Enum):
    STANDARD = "standard"
    DEEP = "deep"


class SourceRequirements(BaseModel):
    """Evidence collection thresholds for a research run."""

    total_sources: int
    min_academic_or_primary: int = 0
    min_fresh_sources: int = 0
    freshness_window_days: int | None = None


class RoundsPlan(BaseModel):
    """Planned scout/critic loop counts."""

    evidence_rounds: int
    critique_rounds: int


class ResearchRunProfile(BaseModel):
    """Planner metadata shared across all nodes in the run."""

    requested_mode: ResearchMode
    classified_mode: ResearchMode
    depth_mode: DepthMode
    freshness_required: bool
    source_requirements: SourceRequirements
    rounds_planned: RoundsPlan
    scenario_analysis_requested: bool = False
    planner_notes: List[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


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
    """Planned research-run graph plus execution profile."""

    workflow_template: str
    workflow: str
    profile: ResearchRunProfile
    nodes: List[ResearchRunPlanNode]
    edges: List[ResearchRunPlanEdge]


def _normalized_query(description: str) -> str:
    return re.sub(r"\s+", " ", description).strip().lower()


def _contains_current_year(description: str) -> bool:
    current_year = datetime.now(UTC).year
    return str(current_year) in description


def _score_matches(description: str, hints: set[str]) -> int:
    normalized = _normalized_query(description)
    return sum(1 for hint in hints if hint in normalized)


def _extract_keywords(description: str, limit: int = 10) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", description.lower())
    keywords: List[str] = []
    for token in tokens:
        if token in _STOP_WORDS or token.isdigit():
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _coerce_research_mode(value: ResearchMode | str) -> ResearchMode:
    if isinstance(value, ResearchMode):
        return value
    return ResearchMode(value)


def _coerce_depth_mode(value: DepthMode | str) -> DepthMode:
    if isinstance(value, DepthMode):
        return value
    return DepthMode(value)


def _build_source_requirements(
    classified_mode: ResearchMode,
    depth_mode: DepthMode,
) -> SourceRequirements:
    if classified_mode == ResearchMode.LITERATURE:
        if depth_mode == DepthMode.DEEP:
            return SourceRequirements(total_sources=12, min_academic_or_primary=6)
        return SourceRequirements(total_sources=6, min_academic_or_primary=3)

    if classified_mode == ResearchMode.LIVE_ANALYSIS:
        if depth_mode == DepthMode.DEEP:
            return SourceRequirements(
                total_sources=12,
                min_fresh_sources=5,
                freshness_window_days=7,
            )
        return SourceRequirements(
            total_sources=8,
            min_fresh_sources=3,
            freshness_window_days=7,
        )

    if depth_mode == DepthMode.DEEP:
        return SourceRequirements(
            total_sources=14,
            min_academic_or_primary=5,
            min_fresh_sources=4,
            freshness_window_days=7,
        )
    return SourceRequirements(
        total_sources=10,
        min_academic_or_primary=3,
        min_fresh_sources=2,
        freshness_window_days=7,
    )


def _build_rounds_plan(depth_mode: DepthMode) -> RoundsPlan:
    if depth_mode == DepthMode.DEEP:
        return RoundsPlan(evidence_rounds=2, critique_rounds=2)
    return RoundsPlan(evidence_rounds=1, critique_rounds=1)


def classify_research_mode(
    description: str,
    requested_mode: ResearchMode | str = ResearchMode.AUTO,
) -> ResearchMode:
    """Classify the user query into literature, live analysis, or hybrid mode."""

    requested_mode = _coerce_research_mode(requested_mode)
    if requested_mode != ResearchMode.AUTO:
        return requested_mode

    normalized = _normalized_query(description)
    live_score = _score_matches(description, _LIVE_QUERY_HINTS)
    literature_score = _score_matches(description, _LITERATURE_QUERY_HINTS)

    if _contains_current_year(description) and any(
        token in normalized for token in ("war", "latest", "current", "today", "market", "price", "conflict")
    ):
        live_score += 2

    if any(phrase in normalized for phrase in ("as of", "what happened", "why did", "how did")):
        live_score += 1

    if live_score >= 2 and literature_score >= 1:
        return ResearchMode.HYBRID
    if live_score >= 2:
        return ResearchMode.LIVE_ANALYSIS
    return ResearchMode.LITERATURE


def build_research_run_profile(
    description: str,
    *,
    research_mode: ResearchMode | str = ResearchMode.AUTO,
    depth_mode: DepthMode | str = DepthMode.STANDARD,
) -> ResearchRunProfile:
    """Build the run-level research profile used by the planner and UI."""

    research_mode = _coerce_research_mode(research_mode)
    depth_mode = _coerce_depth_mode(depth_mode)
    classified_mode = classify_research_mode(description, research_mode)
    scenario_requested = any(phrase in _normalized_query(description) for phrase in _SCENARIO_HINTS)
    source_requirements = _build_source_requirements(classified_mode, depth_mode)
    freshness_required = source_requirements.min_fresh_sources > 0
    notes = [
        f"Requested mode: {research_mode.value}",
        f"Classified mode: {classified_mode.value}",
        f"Depth mode: {depth_mode.value}",
    ]
    if scenario_requested:
        notes.append("Scenario-analysis language detected in the user prompt.")
    if freshness_required:
        notes.append(
            f"Fresh evidence required within {source_requirements.freshness_window_days} days."
        )

    return ResearchRunProfile(
        requested_mode=research_mode,
        classified_mode=classified_mode,
        depth_mode=depth_mode,
        freshness_required=freshness_required,
        source_requirements=source_requirements,
        rounds_planned=_build_rounds_plan(depth_mode),
        scenario_analysis_requested=scenario_requested,
        planner_notes=notes,
    )


def build_research_run_plan(
    description: str,
    *,
    research_mode: ResearchMode | str = ResearchMode.AUTO,
    depth_mode: DepthMode | str = DepthMode.STANDARD,
) -> ResearchRunPlan:
    """Build the Phase 1C deep-research graph used by research runs."""

    profile = build_research_run_profile(
        description,
        research_mode=research_mode,
        depth_mode=depth_mode,
    )
    keywords = _extract_keywords(description)
    shared_parameters = {
        "research_mode": profile.requested_mode.value,
        "classified_mode": profile.classified_mode.value,
        "depth_mode": profile.depth_mode.value,
        "freshness_required": profile.freshness_required,
        "source_requirements": profile.source_requirements.model_dump(),
        "rounds_planned": profile.rounds_planned.model_dump(),
        "scenario_analysis_requested": profile.scenario_analysis_requested,
        "query_keywords": keywords,
        "original_description": description,
    }

    return ResearchRunPlan(
        workflow_template=f"phase1c_{profile.classified_mode.value}_{profile.depth_mode.value}",
        workflow=SUPPORTED_RESEARCH_RUN_WORKFLOW,
        profile=profile,
        nodes=[
            ResearchRunPlanNode(
                node_id="plan_query",
                title="Plan the investigation",
                description=(
                    "Classify the request, define the investigation plan, extract durable keywords, "
                    "and decide how much freshness is required.\n\n"
                    f"User request:\n{description}"
                ),
                capability_requirements="problem framing, investigation planning, scope definition",
                assigned_agent_id="problem-framer-001",
                execution_order=0,
                execution_parameters={
                    **shared_parameters,
                    "phase": "ideation",
                    "node_strategy": "plan_query",
                },
            ),
            ResearchRunPlanNode(
                node_id="gather_evidence",
                title="Gather evidence",
                description=(
                    "Run bounded scout searches across the web and research sources, collecting "
                    "source cards for the question and its sub-questions."
                ),
                capability_requirements="evidence gathering, source discovery, fresh web research",
                assigned_agent_id="literature-miner-001",
                execution_order=1,
                execution_parameters={
                    **shared_parameters,
                    "phase": "knowledge_retrieval",
                    "node_strategy": "gather_evidence",
                },
                input_bindings={"query_plan": "plan_query"},
            ),
            ResearchRunPlanNode(
                node_id="curate_sources",
                title="Curate the sources",
                description=(
                    "Deduplicate gathered evidence, score source quality, and enforce freshness/citation thresholds."
                ),
                capability_requirements="source curation, citation validation, evidence quality control",
                assigned_agent_id="literature-miner-001",
                execution_order=2,
                execution_parameters={
                    **shared_parameters,
                    "phase": "knowledge_retrieval",
                    "node_strategy": "curate_sources",
                },
                input_bindings={
                    "query_plan": "plan_query",
                    "gathered_evidence": "gather_evidence",
                },
            ),
            ResearchRunPlanNode(
                node_id="draft_synthesis",
                title="Draft the synthesis",
                description=(
                    "Synthesize the curated evidence into a structured answer with explicit claims, citations, "
                    "dated context, and known limitations."
                ),
                capability_requirements="knowledge synthesis, multi-source reasoning, citation-aware writing",
                assigned_agent_id="knowledge-synthesizer-001",
                execution_order=3,
                execution_parameters={
                    **shared_parameters,
                    "phase": "knowledge_retrieval",
                    "node_strategy": "draft_synthesis",
                },
                input_bindings={
                    "query_plan": "plan_query",
                    "curated_sources": "curate_sources",
                },
            ),
            ResearchRunPlanNode(
                node_id="critique_and_fact_check",
                title="Critique and fact-check",
                description=(
                    "Review the draft for unsupported claims, weak sourcing, freshness gaps, and missing caveats."
                ),
                capability_requirements="fact checking, critic review, source verification",
                assigned_agent_id="knowledge-synthesizer-001",
                execution_order=4,
                execution_parameters={
                    **shared_parameters,
                    "phase": "knowledge_retrieval",
                    "node_strategy": "critique_and_fact_check",
                },
                input_bindings={
                    "query_plan": "plan_query",
                    "curated_sources": "curate_sources",
                    "draft_synthesis": "draft_synthesis",
                },
            ),
            ResearchRunPlanNode(
                node_id="revise_final_answer",
                title="Revise the final answer",
                description=(
                    "Incorporate critique findings into the final answer, preserving citations, evidence quality, "
                    "and dated limitations."
                ),
                capability_requirements="revision, source-grounded synthesis, final answer composition",
                assigned_agent_id="knowledge-synthesizer-001",
                execution_order=5,
                execution_parameters={
                    **shared_parameters,
                    "phase": "knowledge_retrieval",
                    "node_strategy": "revise_final_answer",
                },
                input_bindings={
                    "query_plan": "plan_query",
                    "curated_sources": "curate_sources",
                    "draft_synthesis": "draft_synthesis",
                    "critic_review": "critique_and_fact_check",
                },
            ),
        ],
        edges=[
            ResearchRunPlanEdge(from_node_id="plan_query", to_node_id="gather_evidence"),
            ResearchRunPlanEdge(from_node_id="gather_evidence", to_node_id="curate_sources"),
            ResearchRunPlanEdge(from_node_id="curate_sources", to_node_id="draft_synthesis"),
            ResearchRunPlanEdge(from_node_id="draft_synthesis", to_node_id="critique_and_fact_check"),
            ResearchRunPlanEdge(from_node_id="critique_and_fact_check", to_node_id="revise_final_answer"),
        ],
    )
