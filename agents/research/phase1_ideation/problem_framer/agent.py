"""Problem Framer Agent implementation."""

import json
import re
from datetime import UTC, datetime
from typing import Dict, Any, List, Optional
from agents.research.base_research_agent import BaseResearchAgent
from .system_prompt import PROBLEM_FRAMER_SYSTEM_PROMPT
from .tools import (
    parse_research_query,
    generate_hypothesis,
    scope_research_problem,
    check_research_novelty,
    assess_feasibility,
    extract_keywords,
)
from shared.research.validators import validate_problem_statement


class ProblemFramerAgent(BaseResearchAgent):
    """
    Problem Framer Agent for converting research queries into formal problems.

    This agent:
    - Converts vague queries into formal research questions
    - Generates testable hypotheses
    - Defines research scope and boundaries
    - Extracts keywords for literature search
    - Assesses feasibility and novelty
    """

    def __init__(self):
        """Initialize Problem Framer Agent."""
        super().__init__(
            agent_id="problem-framer-001",
            name="Research Problem Framer",
            description="Converts vague research queries into formal research questions with hypotheses and scope",
            capabilities=[
                "research-framing",
                "hypothesis-generation",
                "domain-taxonomy",
                "scope-definition",
                "keyword-extraction",
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.1 HBAR",
                "unit": "per_framing"
            }
        )

    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return PROBLEM_FRAMER_SYSTEM_PROMPT

    def get_tools(self) -> List:
        """Get the tools for this agent."""
        return [
            parse_research_query,
            generate_hypothesis,
            scope_research_problem,
            check_research_novelty,
            assess_feasibility,
            extract_keywords,
        ]

    async def execute(self, request: str, **kwargs) -> Dict[str, Any]:
        context = kwargs.get("context") or {}
        if context.get("node_strategy") == "plan_query":
            return await self._execute_query_plan(request, context)

        # The supported problem framer is now a research-run planner first.
        # Fall back to the same structured contract even when older callers do
        # not pass an explicit node strategy, so the active runtime cannot drift
        # back into the legacy problem-statement schema.
        return await self._execute_query_plan(request, context)

    async def _execute_query_plan(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        description = str(context.get("original_description") or request).strip()
        classified_mode = str(context.get("classified_mode") or "literature")
        depth_mode = str(context.get("depth_mode") or "standard")
        freshness_required = bool(context.get("freshness_required"))
        source_requirements = dict(context.get("source_requirements") or {})
        rounds_planned = dict(context.get("rounds_planned") or {})
        keywords = list(context.get("query_keywords") or self._extract_planning_keywords(description))
        subquestions = self._build_subquestions(description, classified_mode)
        search_queries = self._build_search_queries(description, keywords, classified_mode, depth_mode)
        claim_targets = list(context.get("claim_targets") or self._build_claim_targets(description, classified_mode))
        success_criteria = self._build_success_criteria(classified_mode)
        legacy_scope = self._build_legacy_scope(description, classified_mode, depth_mode)
        legacy_hypothesis = self._build_legacy_hypothesis(description, classified_mode)

        result = {
            "query": description,
            "research_question": self._build_research_question(description, classified_mode),
            "rewritten_research_brief": self._build_rewritten_brief(description, classified_mode, depth_mode),
            "classified_mode": classified_mode,
            "depth_mode": depth_mode,
            "freshness_required": freshness_required,
            "keywords": keywords,
            "key_entities": self._build_key_entities(description, keywords),
            "subquestions": subquestions,
            "search_queries": search_queries,
            "search_lanes": self._group_search_lanes(search_queries),
            "source_requirements": source_requirements,
            "rounds_planned": rounds_planned,
            "success_criteria": success_criteria,
            "excluded_assumptions": self._build_excluded_assumptions(classified_mode),
            "source_priorities": self._build_source_priorities(classified_mode),
            "claim_targets": claim_targets,
            "scenario_analysis_requested": bool(context.get("scenario_analysis_requested")),
            "planning_notes": [
                f"Mode: {classified_mode}",
                f"Depth: {depth_mode}",
                "Treat freshness as binding." if freshness_required else "Freshness is advisory.",
            ],
            "as_of_date": datetime.now(UTC).date().isoformat(),
            # Retained as additive metadata for legacy helper flows that still
            # validate against the old ProblemStatement schema.
            "hypothesis": legacy_hypothesis,
            "scope": legacy_scope,
            "domain": self._build_legacy_domain(classified_mode),
            "feasibility_score": self._estimate_feasibility_score(classified_mode, depth_mode),
            "novelty_score": self._estimate_novelty_score(description, classified_mode),
            "rationale": self._build_legacy_rationale(classified_mode, depth_mode, freshness_required),
        }

        self._update_reputation(success=True, quality_score=0.85)
        return {
            "success": True,
            "agent_id": self.agent_id,
            "result": result,
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }

    async def frame_problem(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Frame a research problem from a query.

        Args:
            query: User's research query
            context: Optional context (constraints, preferences, etc.)

        Returns:
            Framed problem with all components
        """
        # Build request for the agent
        request = f"""
        Frame the following research query into a formal research problem:

        Query: {query}

        Context:
        - Budget: {context.get('budget', 5.0) if context else 5.0} HBAR
        - Time: {context.get('timeframe', '30 days') if context else '30 days'}
        - Domain preference: {context.get('domain', 'Not specified') if context else 'Not specified'}

        Please:
        1. Parse the query to understand its components
        2. Generate a formal research question
        3. Create a testable hypothesis
        4. Define clear scope and boundaries
        5. Extract relevant keywords (10-15)
        6. Assess feasibility and novelty
        7. Provide the output in the specified JSON format
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to frame problem')
            }

        try:
            # Parse the agent's response
            agent_output = result['result']

            # If the output is a string, try to parse it as JSON
            if isinstance(agent_output, str):
                # Try to extract JSON from the response
                json_start = agent_output.find('{')
                json_end = agent_output.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = agent_output[json_start:json_end]
                    problem_data = json.loads(json_str)
                else:
                    # Agent didn't return JSON, construct from response
                    problem_data = self._construct_problem_from_text(agent_output, query, context=context)
            else:
                problem_data = agent_output

            # Validate the output
            is_valid, error, validated_problem = validate_problem_statement(problem_data)

            if not is_valid:
                return {
                    'success': False,
                    'error': f'Validation failed: {error}',
                    'raw_output': problem_data
                }

            # Store as artifact in database (would implement this)
            # self._store_artifact(validated_problem)

            return {
                'success': True,
                'problem_statement': validated_problem.dict(),
                'agent_id': self.agent_id,
                'metadata': {
                    'framing_model': self.model,
                    'original_query': query,
                    'payment_due': self.get_payment_rate()
                }
            }

        except json.JSONDecodeError as e:
            return {
                'success': False,
                'error': f'Failed to parse agent output as JSON: {str(e)}',
                'raw_output': result['result']
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error processing problem statement: {str(e)}'
            }

    def _construct_problem_from_text(
        self,
        text: str,
        query: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Construct problem statement from text response if JSON parsing fails.

        Args:
            text: Agent's text response
            query: Original query

        Returns:
            Problem statement dictionary
        """
        context = context or {}
        classified_mode = str(context.get("classified_mode") or "literature")
        depth_mode = str(context.get("depth_mode") or "standard")
        keywords = self._extract_keywords_from_text(text, query)
        search_queries = self._build_search_queries(query, keywords, classified_mode, depth_mode)
        claim_targets = list(context.get("claim_targets") or self._build_claim_targets(query, classified_mode))
        success_criteria = self._build_success_criteria(classified_mode)

        return {
            "query": query,
            "research_question": self._extract_research_question(text) or query,
            "rewritten_research_brief": self._build_rewritten_brief(query, classified_mode, depth_mode),
            "keywords": keywords,
            "subquestions": self._build_subquestions(query, classified_mode),
            "search_queries": search_queries,
            "search_lanes": self._group_search_lanes(search_queries),
            "success_criteria": success_criteria,
            "claim_targets": claim_targets,
            "key_entities": self._build_key_entities(query, keywords),
            "excluded_assumptions": self._build_excluded_assumptions(classified_mode),
            "source_priorities": self._build_source_priorities(classified_mode),
            "as_of_date": datetime.now(UTC).date().isoformat(),
            "hypothesis": self._extract_hypothesis(text) or self._build_legacy_hypothesis(query, classified_mode),
            "scope": self._build_legacy_scope(query, classified_mode, depth_mode),
            "domain": self._build_legacy_domain(classified_mode),
            "feasibility_score": self._estimate_feasibility_score(classified_mode, depth_mode),
            "novelty_score": self._estimate_novelty_score(query, classified_mode),
            "rationale": "Recovered from unstructured problem-framing output.",
        }

    def _extract_research_question(self, text: str) -> Optional[str]:
        """Extract research question from text."""
        # Look for patterns like "research question:" or "RQ:"
        patterns = ['research question:', 'formal question:', 'rq:', 'question:']
        text_lower = text.lower()

        for pattern in patterns:
            if pattern in text_lower:
                start = text_lower.find(pattern) + len(pattern)
                # Find the end (next newline or period)
                end = text.find('\n', start)
                if end == -1:
                    end = text.find('.', start) + 1
                if end > start:
                    return text[start:end].strip()
        return None

    def _extract_hypothesis(self, text: str) -> Optional[str]:
        """Extract hypothesis from text."""
        patterns = ['hypothesis:', 'h1:', 'primary hypothesis:', 'we hypothesize']
        text_lower = text.lower()

        for pattern in patterns:
            if pattern in text_lower:
                start = text_lower.find(pattern) + len(pattern)
                end = text.find('\n', start)
                if end == -1:
                    end = text.find('.', start) + 1
                if end > start:
                    return text[start:end].strip()
        return None

    def _extract_keywords_from_text(self, text: str, query: str) -> List[str]:
        """Extract keywords from text and query."""
        keywords = []

        # Look for keyword section
        if 'keywords:' in text.lower():
            start = text.lower().find('keywords:') + 9
            end = text.find('\n', start)
            if end > start:
                keyword_str = text[start:end]
                keywords = [k.strip() for k in keyword_str.split(',')]

        # Add words from query
        stop_words = {'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or', 'but', 'how', 'what', 'why', 'does'}
        query_words = [w for w in query.lower().split() if w not in stop_words and len(w) > 3]
        keywords.extend(query_words[:5])

        # Ensure minimum keywords
        if len(keywords) < 3:
            keywords.extend(['research', 'analysis', 'study'])

        return list(set(keywords))[:15]  # Unique keywords, max 15

    def _extract_planning_keywords(self, query: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", query.lower())
        keywords: List[str] = []
        for token in tokens:
            if token in {"the", "and", "for", "with", "that", "this", "from", "what", "when"}:
                continue
            if token not in keywords:
                keywords.append(token)
        return keywords[:10] or ["research", "analysis", "evidence"]

    def _build_legacy_hypothesis(self, description: str, classified_mode: str) -> str:
        if classified_mode == "live_analysis":
            return (
                f"The freshest credible reporting will show directly observable developments about "
                f"{description.strip()} while material uncertainty remains explicit."
            )
        if classified_mode == "hybrid":
            return (
                f"Current reporting and durable background research will align on the main explanation for "
                f"{description.strip()}, with uncertainty concentrated in the newest developments."
            )
        return (
            f"The strongest available literature and primary evidence will support a source-grounded answer to "
            f"{description.strip()} while preserving important limitations."
        )

    def _build_legacy_scope(self, description: str, classified_mode: str, depth_mode: str) -> Dict[str, Any]:
        included = [
            "Directly relevant evidence and source-backed findings",
            "Explicit limitations, caveats, and uncertainty",
        ]
        excluded = [
            "Unsupported speculation",
            "Claims without attributable evidence",
        ]
        if classified_mode in {"live_analysis", "hybrid"}:
            included.append("Fresh reporting and primary confirmations")
            excluded.append("Undated summaries of live developments")
        if classified_mode == "literature":
            included.append("Academic, review, and primary literature")
            excluded.append("Purely anecdotal commentary")
        return {
            "included": included,
            "excluded": excluded,
            "timeframe": "Current and relevant historical context" if classified_mode != "literature" else "Relevant literature and primary evidence",
            "domain_boundaries": f"{classified_mode.replace('_', ' ')} research planning ({depth_mode} depth)",
        }

    def _build_legacy_domain(self, classified_mode: str) -> str:
        if classified_mode == "live_analysis":
            return "Current Events and Source-Grounded Analysis"
        if classified_mode == "hybrid":
            return "Current Events with Background Research Synthesis"
        return "Literature and Evidence Synthesis"

    def _estimate_feasibility_score(self, classified_mode: str, depth_mode: str) -> float:
        base = 0.78 if classified_mode == "literature" else 0.72
        if classified_mode == "hybrid":
            base = 0.74
        if depth_mode == "deep":
            base -= 0.06
        return round(max(0.35, min(base, 0.95)), 2)

    def _estimate_novelty_score(self, description: str, classified_mode: str) -> float:
        base = 0.58 if classified_mode == "literature" else 0.52
        if any(term in description.lower() for term in ("agent", "autonomous", "marketplace", "payment", "protocol")):
            base += 0.08
        return round(max(0.3, min(base, 0.9)), 2)

    def _build_legacy_rationale(
        self,
        classified_mode: str,
        depth_mode: str,
        freshness_required: bool,
    ) -> str:
        freshness_clause = "Freshness is treated as binding." if freshness_required else "Freshness is advisory."
        return (
            f"Framed for {classified_mode.replace('_', ' ')} research with {depth_mode} depth. "
            f"{freshness_clause} The plan prioritizes a direct answer, explicit uncertainties, and claim targets that can be validated with citations."
        )

    def _build_research_question(self, description: str, classified_mode: str) -> str:
        if classified_mode == "live_analysis":
            return (
                "What do the freshest credible sources say about "
                f"{description.strip()} as of {datetime.now(UTC).date().isoformat()}?"
            )
        if classified_mode == "hybrid":
            return (
                f"What does current evidence say about {description.strip()}, and how does it compare "
                "with the strongest background research and historical context?"
            )
        return (
            f"What does the strongest available literature and primary evidence say about {description.strip()}?"
        )

    def _build_subquestions(self, description: str, classified_mode: str) -> List[str]:
        if classified_mode == "live_analysis":
            return [
                f"What happened most recently with respect to {description.strip()}?",
                "Which sources are primary, official, or otherwise closest to the event?",
                "What immediate market, policy, or operational impact is already being reported?",
                "What remains uncertain or disputed across recent reporting?",
            ]
        if classified_mode == "hybrid":
            return [
                f"What is the current state of play for {description.strip()}?",
                "What background literature or historical context is necessary to interpret the current event?",
                "Which claims are directly observed versus inferred from prior research?",
                "What uncertainties should remain explicit in the final answer?",
            ]
        return [
            f"What is the precise research question behind {description.strip()}?",
            "Which papers, reports, or primary documents are most relevant?",
            "What methodologies and recurring findings appear across the evidence base?",
            "What gaps, caveats, and unresolved questions matter for the final answer?",
        ]

    def _build_rewritten_brief(self, description: str, classified_mode: str, depth_mode: str) -> str:
        if classified_mode == "live_analysis":
            return (
                f"Investigate {description.strip()} as an active, time-sensitive question. Prioritize the freshest "
                "credible reporting, official confirmations, and directly observed impacts. Answer using absolute "
                f"dates and explicit uncertainty. Depth mode: {depth_mode}."
            )
        if classified_mode == "hybrid":
            return (
                f"Investigate {description.strip()} using both current evidence and durable background research. "
                "Separate observed developments from context and inference, and preserve uncertainty where current "
                f"coverage is mixed. Depth mode: {depth_mode}."
            )
        return (
            f"Investigate {description.strip()} as a literature and primary-evidence synthesis. Prioritize strong "
            "papers, primary sources, and durable findings, then surface methodological gaps and limitations. "
            f"Depth mode: {depth_mode}."
        )

    def _build_success_criteria(self, classified_mode: str) -> List[str]:
        criteria = [
            "Directly answer the query in a source-grounded way.",
            "Preserve explicit limitations and unresolved uncertainty.",
            "Produce claim targets that can be covered with citations.",
        ]
        if classified_mode in {"live_analysis", "hybrid"}:
            criteria.extend(
                [
                    "Use absolute dates for observed live developments.",
                    "Prefer primary and independently confirmed reporting for market-moving claims.",
                ]
            )
        else:
            criteria.extend(
                [
                    "Highlight recurring findings across strong sources.",
                    "Call out methodological disagreements and research gaps.",
                ]
            )
        return criteria

    def _build_excluded_assumptions(self, classified_mode: str) -> List[str]:
        assumptions = [
            "Do not assume facts that are not present in the evidence.",
            "Do not treat model priors as evidence.",
        ]
        if classified_mode in {"live_analysis", "hybrid"}:
            assumptions.append("Do not present the topic as hypothetical unless scenario analysis was requested.")
        return assumptions

    def _build_source_priorities(self, classified_mode: str) -> List[str]:
        if classified_mode == "live_analysis":
            return ["official_or_primary", "independent_wire", "market_or_policy_data", "secondary_analysis"]
        if classified_mode == "hybrid":
            return ["official_or_primary", "independent_wire", "academic_background", "secondary_analysis"]
        return ["academic", "primary", "review_or_meta_analysis", "contextual_analysis"]

    def _build_claim_targets(self, description: str, classified_mode: str) -> List[Dict[str, str]]:
        targets = [
            {
                "claim_id": "C1",
                "claim_target": f"Direct answer to the user request: {description.strip()}",
                "lane": "core-answer",
                "priority": "high",
            },
            {
                "claim_id": "C2",
                "claim_target": "Important uncertainty, limitation, or unresolved disagreement.",
                "lane": "uncertainty",
                "priority": "high",
            },
        ]
        if classified_mode in {"live_analysis", "hybrid"}:
            targets.extend(
                [
                    {
                        "claim_id": "C3",
                        "claim_target": "Most recent developments and their timing.",
                        "lane": "breaking-developments",
                        "priority": "high",
                    },
                    {
                        "claim_id": "C4",
                        "claim_target": "Primary or official confirmations relevant to the event.",
                        "lane": "official-confirmation",
                        "priority": "high",
                    },
                    {
                        "claim_id": "C5",
                        "claim_target": "Observed market, policy, or operational impacts.",
                        "lane": "market-data-confirmation",
                        "priority": "medium",
                    },
                ]
            )
        else:
            targets.extend(
                [
                    {
                        "claim_id": "C3",
                        "claim_target": "Most consistent findings in the strongest literature.",
                        "lane": "core-literature",
                        "priority": "high",
                    },
                    {
                        "claim_id": "C4",
                        "claim_target": "Methodological disagreements or unresolved gaps in the evidence base.",
                        "lane": "methods-and-gaps",
                        "priority": "medium",
                    },
                ]
            )
        return targets

    def _build_key_entities(self, description: str, keywords: List[str]) -> List[str]:
        entities = re.findall(r"[A-Z][A-Za-z0-9\-\+]+(?:\s+[A-Z][A-Za-z0-9\-\+]+)*", description)
        items: List[str] = []
        for item in entities + keywords:
            normalized = item.strip()
            if not normalized:
                continue
            if normalized.lower() in {value.lower() for value in items}:
                continue
            items.append(normalized)
        return items[:10]

    def _group_search_lanes(self, search_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lanes: Dict[str, Dict[str, Any]] = {}
        for query in search_queries:
            lane = str(query.get("lane") or query.get("role") or "general")
            bucket = lanes.setdefault(
                lane,
                {
                    "lane": lane,
                    "objective": query.get("objective") or lane.replace("-", " "),
                    "queries": [],
                },
            )
            bucket["queries"].append(query)
        return list(lanes.values())

    def _build_search_queries(
        self,
        description: str,
        keywords: List[str],
        classified_mode: str,
        depth_mode: str,
    ) -> List[Dict[str, Any]]:
        joined_keywords = " ".join(keywords[:6])
        queries: List[Dict[str, Any]] = []
        if classified_mode in {"live_analysis", "hybrid"}:
            queries.extend(
                [
                    {
                        "role": "breaking-news-scout",
                        "lane": "breaking-developments",
                        "objective": "Capture the freshest developments and timing.",
                        "query": f"{description} latest developments {datetime.now(UTC).year}",
                        "time_range": "w",
                    },
                    {
                        "role": "primary-source-scout",
                        "lane": "official-confirmation",
                        "objective": "Find official statements, direct data, and primary confirmation.",
                        "query": f"{description} official statement data report {joined_keywords}",
                        "time_range": "w",
                    },
                    {
                        "role": "market-impact-scout",
                        "lane": "market-data-confirmation",
                        "objective": "Find direct market, policy, or operational impact evidence.",
                        "query": f"{description} market impact prices analysis {joined_keywords}",
                        "time_range": "w",
                    },
                ]
            )
        if classified_mode in {"literature", "hybrid"}:
            queries.extend(
                [
                    {
                        "role": "academic-scout",
                        "lane": "core-literature",
                        "objective": "Find the strongest academic and literature-review evidence.",
                        "query": f"{description} research paper literature review {joined_keywords}",
                        "time_range": None,
                    },
                    {
                        "role": "context-scout",
                        "lane": "background-context",
                        "objective": "Gather contextual background and causal mechanisms.",
                        "query": f"{description} background analysis causes evidence {joined_keywords}",
                        "time_range": None,
                    },
                ]
            )
        if depth_mode == "deep":
            queries.append(
                {
                    "role": "counterpoint-scout",
                    "lane": "counterpoints",
                    "objective": "Find disagreement, contrary evidence, and uncertainty.",
                    "query": f"{description} criticism counterargument uncertainty {joined_keywords}",
                    "time_range": "m" if classified_mode != "literature" else None,
                }
            )
        return queries


# Create singleton instance
problem_framer_agent = ProblemFramerAgent()


# Convenience function for use as tool by other agents
async def frame_research_problem(query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Tool function for framing research problems.

    Args:
        query: Research query to frame
        context: Optional context

    Returns:
        Framed problem statement
    """
    return await problem_framer_agent.frame_problem(query, context)
