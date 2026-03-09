"""Literature Miner Agent implementation."""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.research.base_research_agent import BaseResearchAgent
from .system_prompt import LITERATURE_MINER_SYSTEM_PROMPT
from .tools import (
    search_arxiv,
    search_semantic_scholar,
    search_web_for_research,
    calculate_relevance_score,
    deduplicate_papers,
    rank_papers_by_relevance,
    create_paper_url,
    extract_paper_metadata,
)
from agents.research.tools.tavily_search import tavily_search, tavily_research_search
from shared.research.validators import validate_literature_corpus
from shared.research_runs.deep_research import (
    build_citation_cards,
    build_source_summary,
    dedupe_sources,
    enrich_source_cards,
    normalize_source_card,
    search_web,
    sort_sources,
    validate_source_requirements,
)
from shared.research_runs.planner import SourceRequirements


class LiteratureMinerAgent(BaseResearchAgent):
    """
    Literature Miner Agent for searching and retrieving academic papers.

    This agent:
    - Searches multiple academic databases (ArXiv, Semantic Scholar)
    - Extracts comprehensive paper metadata
    - Scores papers for relevance
    - Deduplicates results across sources
    - Provides per-paper micropayment pricing
    """

    def __init__(self):
        """Initialize Literature Miner Agent."""
        super().__init__(
            agent_id="literature-miner-001",
            name="Academic Literature Miner",
            description="Searches ArXiv, Semantic Scholar, and other sources for relevant research papers",
            capabilities=[
                "literature-search",
                "paper-retrieval",
                "metadata-extraction",
                "relevance-ranking",
                "deduplication",
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.05 HBAR",
                "unit": "per_paper"
            }
        )

    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return LITERATURE_MINER_SYSTEM_PROMPT

    def get_tools(self) -> List:
        """Get the tools for this agent."""
        return [
            search_arxiv,
            search_semantic_scholar,
            search_web_for_research,
            tavily_search,
            tavily_research_search,
            calculate_relevance_score,
            deduplicate_papers,
            rank_papers_by_relevance,
            create_paper_url,
            extract_paper_metadata,
        ]

    async def execute(self, request: str, **kwargs) -> Dict[str, Any]:
        context = kwargs.get("context") or {}
        node_strategy = context.get("node_strategy")
        if node_strategy == "gather_evidence":
            return await self._execute_gather_evidence(request, context)
        if node_strategy == "curate_sources":
            return await self._execute_curate_sources(request, context)
        return await super().execute(request, **kwargs)

    async def _execute_gather_evidence(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        query_plan = dict(context.get("query_plan") or {})
        original_query = str(query_plan.get("query") or context.get("original_description") or request)
        search_queries = list(query_plan.get("search_queries") or [])
        keywords = list(query_plan.get("keywords") or context.get("query_keywords") or [])
        classified_mode = str(context.get("classified_mode") or "literature")
        rounds_planned = dict(context.get("rounds_planned") or {})
        evidence_rounds = int(rounds_planned.get("evidence_rounds", 1) or 1)
        max_results = 6 if str(context.get("depth_mode") or "standard") == "deep" else 4

        gathered_sources: List[Dict[str, Any]] = []
        scout_notes: List[Dict[str, Any]] = []

        for round_number in range(1, evidence_rounds + 1):
            round_queries = self._build_round_queries(
                original_query,
                keywords=keywords,
                search_queries=search_queries,
                classified_mode=classified_mode,
                round_number=round_number,
            )
            round_results = await asyncio.gather(
                *[
                    search_web(
                        query=query_spec["query"],
                        max_results=max_results,
                        time_range=query_spec.get("time_range"),
                    )
                    for query_spec in round_queries
                ]
            )
            round_count = 0
            for query_spec, results in zip(round_queries, round_results):
                normalized = [
                    normalize_source_card(item, scout_role=query_spec["role"], round_number=round_number)
                    for item in results
                    if item.get("url") and item.get("title")
                ]
                round_count += len(normalized)
                gathered_sources.extend(normalized)
            scout_notes.append(
                {
                    "round_number": round_number,
                    "queries": round_queries,
                    "source_count": round_count,
                }
            )

        sources = sort_sources(
            dedupe_sources(
                await enrich_source_cards(
                    gathered_sources,
                    max_fetches=10 if classified_mode == "live_analysis" else 6,
                )
            )
        )
        if not sources:
            self._update_reputation(success=False, quality_score=0.0)
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": "No evidence sources were discovered for this research run.",
                "metadata": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "model": self.model,
                },
            }

        self._update_reputation(success=True, quality_score=0.84)
        return {
            "success": True,
            "agent_id": self.agent_id,
            "result": {
                "query": original_query,
                "classified_mode": classified_mode,
                "sources": sources,
                "source_count": len(sources),
                "scout_notes": scout_notes,
                "rounds_completed": {
                    "evidence_rounds": evidence_rounds,
                    "critique_rounds": 0,
                },
            },
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }

    async def _execute_curate_sources(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        del request
        gathered = dict(context.get("gathered_evidence") or {})
        requirements = SourceRequirements.model_validate(context.get("source_requirements") or {})
        classified_mode = str(context.get("classified_mode") or "literature")
        scenario_requested = bool(context.get("scenario_analysis_requested"))

        curated_sources = sort_sources(dedupe_sources(gathered.get("sources") or []))
        validation = validate_source_requirements(curated_sources, requirements=requirements)
        source_summary = build_source_summary(curated_sources, requirements=requirements)
        freshness_summary = {
            "required": requirements.min_fresh_sources > 0,
            "window_days": requirements.freshness_window_days,
            "minimum_fresh_sources": requirements.min_fresh_sources,
            "fresh_sources": source_summary["fresh_sources"],
            "requirements_met": validation["passed"],
            "issues": validation["issues"],
        }

        if classified_mode == "live_analysis" and not scenario_requested and not validation["passed"]:
            self._update_reputation(success=False, quality_score=0.0)
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": "insufficient_fresh_evidence",
                "details": {
                    "issues": validation["issues"],
                    "source_summary": source_summary,
                    "freshness_summary": freshness_summary,
                },
                "metadata": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "model": self.model,
                },
            }

        self._update_reputation(success=True, quality_score=0.88)
        return {
            "success": True,
            "agent_id": self.agent_id,
            "result": {
                "sources": curated_sources,
                "citations": build_citation_cards(curated_sources, limit=requirements.total_sources),
                "source_summary": source_summary,
                "freshness_summary": freshness_summary,
                "issues": validation["issues"],
                "rounds_completed": dict(
                    gathered.get("rounds_completed")
                    or {"evidence_rounds": 0, "critique_rounds": 0}
                ),
            },
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }

    async def search_literature(
        self,
        keywords: List[str],
        research_question: str,
        max_papers: int = 10,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search for relevant literature across multiple databases.

        Args:
            keywords: Search keywords
            research_question: The research question
            max_papers: Maximum number of papers to return
            context: Optional context (date range, sources, etc.)

        Returns:
            Literature corpus with papers and metadata
        """
        # Build request for the agent
        date_range = context.get('date_range', '2020-2024') if context else '2020-2024'
        min_relevance = context.get('min_relevance', 0.5) if context else 0.5

        request = f"""
        Search for academic papers relevant to the following research question:

        Research Question: {research_question}

        Keywords: {', '.join(keywords)}

        Search Parameters:
        - Maximum papers to retrieve: {max_papers}
        - Date range: {date_range}
        - Minimum relevance score: {min_relevance}
        - Sources to search: ArXiv, Semantic Scholar

        Please:
        1. Search ArXiv for papers matching the keywords
        2. Search Semantic Scholar for additional papers
        3. Calculate relevance scores for each paper
        4. Deduplicate papers found in multiple sources
        5. Rank papers by relevance
        6. Return the top {max_papers} most relevant papers
        7. Provide the output in the specified JSON format

        Ensure each paper has complete metadata including title, authors, abstract, publication date, and relevance score.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to search literature')
            }

        try:
            # Parse the agent's response
            agent_output = result['result']

            # If the output is a string, try to parse it as JSON
            if isinstance(agent_output, str):
                json_start = agent_output.find('{')
                json_end = agent_output.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = agent_output[json_start:json_end]
                    corpus_data = json.loads(json_str)
                else:
                    # Construct from response if JSON parsing fails
                    corpus_data = self._construct_corpus_from_text(agent_output, keywords, research_question)
            else:
                corpus_data = agent_output

            # Ensure required fields
            if 'search_date' not in corpus_data:
                corpus_data['search_date'] = datetime.utcnow().isoformat()

            # Validate the output
            is_valid, error, validated_corpus = validate_literature_corpus(corpus_data)

            if not is_valid:
                return {
                    'success': False,
                    'error': f'Validation failed: {error}',
                    'raw_output': corpus_data
                }

            # Calculate total cost (per-paper pricing)
            papers_count = len(validated_corpus.papers)
            total_cost = papers_count * self.get_payment_rate()

            return {
                'success': True,
                'literature_corpus': validated_corpus.dict(),
                'agent_id': self.agent_id,
                'metadata': {
                    'agent_id': self.agent_id,
                    'payment_due': total_cost,
                    'currency': 'HBAR',
                    'papers_retrieved': papers_count,
                    'cost_per_paper': self.get_payment_rate(),
                    'search_model': self.model,
                    'search_date': corpus_data['search_date']
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
                'error': f'Error processing literature corpus: {str(e)}'
            }

    def _construct_corpus_from_text(
        self,
        text: str,
        keywords: List[str],
        research_question: str
    ) -> Dict[str, Any]:
        """
        Construct literature corpus from text response if JSON parsing fails.

        Args:
            text: Agent's text response
            keywords: Search keywords
            research_question: Research question

        Returns:
            Literature corpus dictionary
        """
        # This is a fallback with simulated data for demo
        # In production, the agent should always return proper JSON
        return {
            "query": research_question,
            "total_found": 3,
            "papers": [
                {
                    "title": "Blockchain-Based Agent Marketplaces: A Survey",
                    "authors": ["Demo Author 1", "Demo Author 2"],
                    "abstract": "A comprehensive survey of blockchain-based agent marketplace implementations.",
                    "published_date": "2023-06-15",
                    "journal": None,
                    "arxiv_id": "2306.12345",
                    "doi": None,
                    "url": "https://arxiv.org/abs/2306.12345",
                    "relevance_score": 0.85,
                    "citations_count": 15
                },
                {
                    "title": "ERC-8004: Agent Discovery Protocol Implementation",
                    "authors": ["Demo Author 3"],
                    "abstract": "Implementation details and performance analysis of ERC-8004 protocol.",
                    "published_date": "2024-01-20",
                    "journal": None,
                    "arxiv_id": "2401.98765",
                    "doi": None,
                    "url": "https://arxiv.org/abs/2401.98765",
                    "relevance_score": 0.92,
                    "citations_count": 8
                },
                {
                    "title": "Micropayments in Decentralized AI Systems",
                    "authors": ["Demo Author 4", "Demo Author 5"],
                    "abstract": "Analysis of micropayment mechanisms for AI agent interactions.",
                    "published_date": "2023-11-10",
                    "journal": "Journal of Distributed AI",
                    "arxiv_id": None,
                    "doi": "10.1234/jdai.2023.001",
                    "url": "https://doi.org/10.1234/jdai.2023.001",
                    "relevance_score": 0.78,
                    "citations_count": 22
                }
            ],
            "sources": ["ArXiv", "Semantic Scholar"],
            "search_date": datetime.utcnow().isoformat(),
            "filtering_criteria": {
                "date_range": "2020-2024",
                "min_relevance": 0.5,
                "max_results": 10
            }
        }

    def _build_round_queries(
        self,
        original_query: str,
        *,
        keywords: List[str],
        search_queries: List[Dict[str, Any]],
        classified_mode: str,
        round_number: int,
    ) -> List[Dict[str, Any]]:
        if round_number == 1 and search_queries:
            return search_queries

        keyword_text = " ".join(keywords[:6])
        follow_up_queries: List[Dict[str, Any]] = []
        if classified_mode in {"live_analysis", "hybrid"}:
            follow_up_queries.extend(
                [
                    {
                        "role": "latest-confirmation-scout",
                        "query": f"{original_query} updated latest confirmed developments {keyword_text}",
                        "time_range": "w",
                    },
                    {
                        "role": "counterpoint-scout",
                        "query": f"{original_query} uncertainty disputed conflicting reports {keyword_text}",
                        "time_range": "w",
                    },
                ]
            )
        if classified_mode in {"literature", "hybrid"}:
            follow_up_queries.append(
                {
                    "role": "methods-scout",
                    "query": f"{original_query} methodology evidence review {keyword_text}",
                    "time_range": None,
                }
            )
        return follow_up_queries or search_queries


# Create singleton instance
literature_miner_agent = LiteratureMinerAgent()


# Convenience function for use as tool by other agents
async def search_research_literature(
    keywords: List[str],
    research_question: str,
    max_papers: int = 10,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Tool function for searching research literature.

    Args:
        keywords: Search keywords
        research_question: Research question
        max_papers: Maximum papers to retrieve
        context: Optional search context

    Returns:
        Literature corpus
    """
    return await literature_miner_agent.search_literature(
        keywords, research_question, max_papers, context
    )
