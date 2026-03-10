"""Catalog helpers for support tiers and the phase 0 literature workflow."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from shared.runtime.contracts import SupportTier


SUPPORTED_RESEARCH_AGENT_IDS = (
    "problem-framer-001",
    "literature-miner-001",
    "knowledge-synthesizer-001",
)

SUPPORTED_AGENT_DETAILS: Dict[str, Dict[str, Any]] = {
    "problem-framer-001": {
        "name": "Problem Framer",
        "description": "Frames a raw research question into a scoped literature-review brief.",
        "capabilities": [
            "problem-framing",
            "research-question-design",
            "scope-definition",
        ],
        "pricing": {"rate": 5.0, "currency": "HBAR", "rate_type": "per_task"},
        "hedera_account_id": "0.0.7001",
    },
    "literature-miner-001": {
        "name": "Literature Miner",
        "description": "Searches for source papers and extracts evidence for a research topic.",
        "capabilities": [
            "literature-mining",
            "evidence-gathering",
            "citation-collection",
        ],
        "pricing": {"rate": 8.0, "currency": "HBAR", "rate_type": "per_task"},
        "hedera_account_id": "0.0.7002",
    },
    "knowledge-synthesizer-001": {
        "name": "Knowledge Synthesizer",
        "description": "Synthesizes literature findings into a cohesive research summary.",
        "capabilities": [
            "knowledge-synthesis",
            "research-summarization",
            "report-composition",
        ],
        "pricing": {"rate": 7.0, "currency": "HBAR", "rate_type": "per_task"},
        "hedera_account_id": "0.0.7003",
    },
    "data-agent-001": {
        "name": "Data Agent",
        "description": "Stores and catalogs underused or failed datasets for future reuse.",
        "capabilities": [
            "dataset-upload",
            "dataset-catalog",
            "dataset-retrieval",
            "failed-data-archiving",
            "underused-data-storage",
        ],
        "pricing": {"rate": 0.0, "currency": "HBAR", "rate_type": "per_upload"},
        "hedera_account_id": "0.0.7004",
    },
}


def default_research_endpoint(agent_id: str) -> str:
    """Return the default research API endpoint for the given agent."""

    base_url = os.getenv("RESEARCH_API_URL", "http://localhost:5001").rstrip("/")
    return f"{base_url}/agents/{agent_id}"


def infer_support_tier(agent_id: str, agent_type: str | None = None) -> SupportTier:
    """Infer the support tier for an agent."""

    if agent_id in SUPPORTED_AGENT_DETAILS:
        return SupportTier.SUPPORTED
    if agent_type == "research":
        return SupportTier.EXPERIMENTAL
    return SupportTier.SUPPORTED


def build_phase0_todo_items(description: str) -> List[Dict[str, str]]:
    """Build the fixed literature-review workflow for phase 0."""

    return [
        {
            "id": "todo_0",
            "title": "Frame the research question",
            "description": (
                f"Clarify the user's request into a scoped research question, constraints, "
                f"and searchable literature-review brief.\n\nUser request:\n{description}"
            ),
            "assigned_to": "problem-framer-001",
        },
        {
            "id": "todo_1",
            "title": "Mine supporting literature",
            "description": (
                f"Find relevant papers, sources, and evidence for the framed question.\n\n"
                f"Base request:\n{description}"
            ),
            "assigned_to": "literature-miner-001",
        },
        {
            "id": "todo_2",
            "title": "Synthesize the findings",
            "description": (
                f"Produce a synthesis of the literature review, highlighting key findings, "
                f"uncertainties, and next steps.\n\nBase request:\n{description}"
            ),
            "assigned_to": "knowledge-synthesizer-001",
        },
    ]


def select_supported_agent_for_todo(todo_id: str, capability_requirements: str, task_name: str) -> str:
    """Select one of the supported research agents for the current microtask."""

    normalized = " ".join([todo_id, capability_requirements, task_name]).lower()
    if any(
        token in normalized
        for token in (
            "todo_0",
            "plan_query",
            "frame",
            "question",
            "scope",
            "hypothesis",
            "investigation planning",
        )
    ):
        return "problem-framer-001"
    if any(
        token in normalized
        for token in (
            "draft_synthesis",
            "critique_and_fact_check",
            "revise_final_answer",
            "synthesis",
            "draft",
            "critique",
            "revise",
            "final answer",
            "fact-check",
        )
    ):
        return "knowledge-synthesizer-001"
    if any(
        token in normalized
        for token in (
            "todo_1",
            "gather_evidence",
            "curate_sources",
            "literature",
            "paper",
            "citation",
            "source",
            "evidence",
            "curation",
        )
    ):
        return "literature-miner-001"
    return "knowledge-synthesizer-001"
