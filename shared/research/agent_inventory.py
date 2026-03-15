"""Source-of-truth inventory for built-in research specialist agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

from shared.runtime.contracts import SupportTier


@dataclass(frozen=True)
class BuiltInResearchAgentRecord:
    """Static metadata for a built-in research agent."""

    agent_id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    pricing: Dict[str, Any]
    support_tier: SupportTier
    public_exposure: bool
    active_runtime: bool
    role_families: tuple[str, ...] = ()
    migration_target: Optional[str] = None
    module_path: Optional[str] = None
    instance_name: Optional[str] = None
    hedera_account_id: Optional[str] = None

    def catalog_details(self) -> Dict[str, Any]:
        """Return marketplace-friendly details for fallback catalog use."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "pricing": dict(self.pricing),
            "role_families": list(self.role_families),
            "hedera_account_id": self.hedera_account_id,
        }


BUILT_IN_RESEARCH_AGENTS: Dict[str, BuiltInResearchAgentRecord] = {
    "problem-framer-001": BuiltInResearchAgentRecord(
        agent_id="problem-framer-001",
        name="Problem Framer",
        description="Frames a raw research question into a scoped literature-review brief.",
        capabilities=(
            "problem-framing",
            "research-question-design",
            "scope-definition",
        ),
        pricing={"rate": 5.0, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.SUPPORTED,
        public_exposure=True,
        active_runtime=True,
        role_families=("planning",),
        module_path="agents.research.phase1_ideation.problem_framer.agent",
        instance_name="problem_framer_agent",
        hedera_account_id="0.0.7001",
    ),
    "goal-planner-001": BuiltInResearchAgentRecord(
        agent_id="goal-planner-001",
        name="Research Goal Planner",
        description="Creates structured research plans with objectives, milestones, tasks, and timelines",
        capabilities=(
            "goal-setting",
            "task-decomposition",
            "milestone-planning",
            "resource-allocation",
            "timeline-estimation",
        ),
        pricing={"rate": 0.10, "currency": "HBAR", "rate_type": "per_plan"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "feasibility-analyst-001": BuiltInResearchAgentRecord(
        agent_id="feasibility-analyst-001",
        name="Research Feasibility Analyst",
        description="Evaluates research question feasibility considering resources, data, complexity, and constraints",
        capabilities=(
            "feasibility-analysis",
            "resource-estimation",
            "constraint-identification",
            "risk-assessment",
            "timeline-estimation",
        ),
        pricing={"rate": 0.08, "currency": "HBAR", "rate_type": "per_analysis"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "literature-miner-001": BuiltInResearchAgentRecord(
        agent_id="literature-miner-001",
        name="Literature Miner",
        description="Searches for source papers and extracts evidence for a research topic.",
        capabilities=(
            "literature-mining",
            "evidence-gathering",
            "citation-collection",
        ),
        pricing={"rate": 8.0, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.SUPPORTED,
        public_exposure=True,
        active_runtime=True,
        role_families=("evidence",),
        module_path="agents.research.phase2_knowledge.literature_miner.agent",
        instance_name="literature_miner_agent",
        hedera_account_id="0.0.7002",
    ),
    "knowledge-synthesizer-001": BuiltInResearchAgentRecord(
        agent_id="knowledge-synthesizer-001",
        name="Knowledge Synthesizer",
        description="Synthesizes literature findings into a cohesive research summary.",
        capabilities=(
            "knowledge-synthesis",
            "research-summarization",
            "report-composition",
        ),
        pricing={"rate": 7.0, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.SUPPORTED,
        public_exposure=True,
        active_runtime=True,
        role_families=("synthesis",),
        module_path="agents.research.phase2_knowledge.knowledge_synthesizer.agent",
        instance_name="knowledge_synthesizer_agent",
        hedera_account_id="0.0.7003",
    ),
    "hypothesis-designer-001": BuiltInResearchAgentRecord(
        agent_id="hypothesis-designer-001",
        name="Hypothesis Designer",
        description="Designs testable hypotheses and experiment protocols based on literature synthesis",
        capabilities=(
            "hypothesis-design",
            "experiment-protocol",
            "variable-identification",
            "control-design",
            "metrics-definition",
        ),
        pricing={"rate": 0.12, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "code-generator-001": BuiltInResearchAgentRecord(
        agent_id="code-generator-001",
        name="Code Generator",
        description="Generates experimental code, analysis scripts, and visualization code",
        capabilities=(
            "code-generation",
            "script-writing",
            "data-processing",
            "visualization",
            "testing",
        ),
        pricing={"rate": 0.15, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
        migration_target="replication",
    ),
    "experiment-runner-001": BuiltInResearchAgentRecord(
        agent_id="experiment-runner-001",
        name="Experiment Runner",
        description="Executes experiments, simulations, and data analysis based on experiment protocols",
        capabilities=(
            "experiment-execution",
            "simulation",
            "data-collection",
            "monitoring",
            "error-handling",
        ),
        pricing={"rate": 0.20, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
        migration_target="replication",
    ),
    "insight-generator-001": BuiltInResearchAgentRecord(
        agent_id="insight-generator-001",
        name="Insight Generator",
        description="Generates insights and interpretations from experimental results",
        capabilities=(
            "insight-extraction",
            "pattern-analysis",
            "causal-inference",
            "implication-analysis",
            "conclusion-generation",
        ),
        pricing={"rate": 0.14, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "bias-detector-001": BuiltInResearchAgentRecord(
        agent_id="bias-detector-001",
        name="Bias Detector",
        description="Detects potential biases in research methodology, data, and interpretations",
        capabilities=(
            "bias-detection",
            "fairness-analysis",
            "validity-checking",
            "confounding-identification",
            "mitigation-recommendation",
        ),
        pricing={"rate": 0.11, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
        migration_target="method-critic",
    ),
    "compliance-checker-001": BuiltInResearchAgentRecord(
        agent_id="compliance-checker-001",
        name="Compliance Checker",
        description="Checks research compliance with ethical guidelines, regulations, and standards",
        capabilities=(
            "compliance-checking",
            "ethics-review",
            "regulatory-validation",
            "standards-verification",
            "documentation-review",
        ),
        pricing={"rate": 0.09, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "paper-writer-001": BuiltInResearchAgentRecord(
        agent_id="paper-writer-001",
        name="Research Paper Writer",
        description="Writes research papers in academic format with proper structure and citations",
        capabilities=(
            "paper-writing",
            "academic-formatting",
            "citation-management",
            "figure-generation",
            "abstract-writing",
        ),
        pricing={"rate": 0.25, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
        migration_target="report-composer",
    ),
    "peer-reviewer-001": BuiltInResearchAgentRecord(
        agent_id="peer-reviewer-001",
        name="Peer Reviewer",
        description="Provides peer review feedback on research papers evaluating quality, rigor, and contribution",
        capabilities=(
            "peer-review",
            "quality-assessment",
            "rigor-evaluation",
            "contribution-analysis",
            "feedback-generation",
        ),
        pricing={"rate": 0.18, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
        migration_target="final-review-critic",
    ),
    "reputation-manager-001": BuiltInResearchAgentRecord(
        agent_id="reputation-manager-001",
        name="Reputation Manager",
        description="Updates agent reputations based on research quality and contribution",
        capabilities=(
            "reputation-scoring",
            "contribution-tracking",
            "performance-evaluation",
            "quality-metrics",
            "reputation-updates",
        ),
        pricing={"rate": 0.05, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
    "archiver-001": BuiltInResearchAgentRecord(
        agent_id="archiver-001",
        name="Research Archiver",
        description="Archives research artifacts to IPFS and blockchain for permanent, verifiable storage",
        capabilities=(
            "ipfs-upload",
            "blockchain-recording",
            "metadata-generation",
            "versioning",
            "retrieval",
        ),
        pricing={"rate": 0.07, "currency": "HBAR", "rate_type": "per_task"},
        support_tier=SupportTier.LEGACY,
        public_exposure=False,
        active_runtime=False,
    ),
}


def get_builtin_research_agent(agent_id: str) -> Optional[BuiltInResearchAgentRecord]:
    """Return the built-in research agent record for the given ID."""

    return BUILT_IN_RESEARCH_AGENTS.get(agent_id)


def iter_builtin_research_agents(
    *,
    support_tier: Optional[SupportTier] = None,
    public_exposure: Optional[bool] = None,
    active_runtime: Optional[bool] = None,
) -> Iterator[BuiltInResearchAgentRecord]:
    """Iterate built-in research agents with optional filtering."""

    for record in BUILT_IN_RESEARCH_AGENTS.values():
        if support_tier is not None and record.support_tier != support_tier:
            continue
        if public_exposure is not None and record.public_exposure != public_exposure:
            continue
        if active_runtime is not None and record.active_runtime != active_runtime:
            continue
        yield record


def iter_supported_builtin_research_agents() -> Iterator[BuiltInResearchAgentRecord]:
    """Iterate supported built-in research agents."""

    return iter_builtin_research_agents(
        support_tier=SupportTier.SUPPORTED,
        public_exposure=True,
        active_runtime=True,
    )


def supported_builtin_research_agent_ids() -> tuple[str, ...]:
    """Return the supported built-in research agent IDs."""

    return tuple(record.agent_id for record in iter_supported_builtin_research_agents())


def is_supported_builtin_research_agent(agent_id: str) -> bool:
    """Return whether the ID is a supported built-in research agent."""

    record = get_builtin_research_agent(agent_id)
    return bool(record and record.support_tier == SupportTier.SUPPORTED)


def is_public_builtin_research_agent(agent_id: str) -> bool:
    """Return whether the built-in research agent should be publicly exposed."""

    record = get_builtin_research_agent(agent_id)
    if record is None:
        return True
    return record.public_exposure
