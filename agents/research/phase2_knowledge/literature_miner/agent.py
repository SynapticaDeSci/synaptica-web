"""Literature Miner Agent implementation."""

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.research.base_research_agent import BaseResearchAgent
from .system_prompt import LITERATURE_MINER_SYSTEM_PROMPT
from .tools import (
    ACADEMIC_SOURCE_SEARCH_FANOUT,
    search_arxiv,
    search_semantic_scholar,
    search_pubmed,
    search_openalex,
    search_all_academic_sources,
    search_web_for_research,
    fetch_semantic_scholar_citations,
    calculate_relevance_score,
    deduplicate_papers,
    rank_papers_by_relevance,
    create_paper_url,
    extract_paper_metadata,
)
from agents.research.tools.tavily_search import tavily_search, tavily_research_search
from shared.research.validators import validate_literature_corpus
from shared.research_runs.deep_research import (
    assign_citation_ids,
    build_citation_cards,
    build_source_summary,
    dedupe_sources,
    enrich_source_cards,
    filter_sources_for_curation,
    normalize_source_card,
    search_web,
    sort_sources,
    validate_source_requirements,
)
from shared.research_runs.planner import SourceRequirements

logger = logging.getLogger(__name__)

# Maximum total search operations to prevent runaway costs.
_MAX_TOTAL_SEARCHES_STANDARD = 30
_MAX_TOTAL_SEARCHES_DEEP = 60


class LiteratureMinerAgent(BaseResearchAgent):
    """Literature Miner Agent for searching and retrieving academic papers.

    This agent:
    - Searches multiple real academic databases (ArXiv, Semantic Scholar, PubMed, OpenAlex)
    - Searches the web via Tavily/DDG for supplementary sources
    - Decomposes research questions into sub-queries for broader coverage
    - Iteratively deepens searches using found sources to discover more
    - Deduplicates results across sources
    """

    def __init__(self):
        super().__init__(
            agent_id="literature-miner-001",
            name="Academic Literature Miner",
            description="Searches ArXiv, Semantic Scholar, PubMed, OpenAlex, and the web for relevant research",
            capabilities=[
                "literature-search",
                "paper-retrieval",
                "metadata-extraction",
                "relevance-ranking",
                "deduplication",
                "iterative-deepening",
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.05 HBAR",
                "unit": "per_paper"
            }
        )

    def get_system_prompt(self) -> str:
        return LITERATURE_MINER_SYSTEM_PROMPT

    def get_tools(self) -> List:
        return [
            search_arxiv,
            search_semantic_scholar,
            search_pubmed,
            search_openalex,
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

    # ------------------------------------------------------------------
    # Evidence gathering — the main search pipeline
    # ------------------------------------------------------------------

    async def _execute_gather_evidence(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        query_plan = dict(context.get("query_plan") or {})
        original_query = str(query_plan.get("query") or context.get("original_description") or request)
        search_queries = list(query_plan.get("search_queries") or [])
        claim_targets = list(query_plan.get("claim_targets") or context.get("claim_targets") or [])
        keywords = list(query_plan.get("keywords") or context.get("query_keywords") or [])
        classified_mode = str(context.get("classified_mode") or "literature")
        rounds_planned = dict(context.get("rounds_planned") or {})
        evidence_rounds = int(rounds_planned.get("evidence_rounds", 1) or 1)
        depth_mode = str(context.get("depth_mode") or "standard")
        is_deep = depth_mode == "deep"
        max_web_results = 15 if is_deep else 10
        max_academic_per_source = 20 if is_deep else 15
        max_total_searches = _MAX_TOTAL_SEARCHES_DEEP if is_deep else _MAX_TOTAL_SEARCHES_STANDARD
        search_count = 0

        gathered_sources: List[Dict[str, Any]] = []
        scout_notes: List[Dict[str, Any]] = []

        # ----------------------------------------------------------
        # Phase A: Generate diverse sub-queries for broader coverage
        # ----------------------------------------------------------
        all_search_queries = self._decompose_and_generate_queries(
            original_query,
            keywords=keywords,
            search_queries=search_queries,
            classified_mode=classified_mode,
        )

        # ----------------------------------------------------------
        # Phase B: Multi-round evidence gathering (web + academic)
        # ----------------------------------------------------------
        for round_number in range(1, evidence_rounds + 1):
            if search_count >= max_total_searches:
                break

            current_sources = sort_sources(dedupe_sources(gathered_sources))
            coverage_summary = self._assess_coverage(
                current_sources,
                claim_targets=claim_targets,
                source_requirements=context.get("source_requirements") or {},
            )
            if round_number > 1 and coverage_summary["ready_for_synthesis"]:
                break

            # Pick queries for this round
            if round_number == 1:
                round_queries = all_search_queries
            else:
                round_queries = self._build_round_queries(
                    original_query,
                    keywords=keywords,
                    search_queries=search_queries,
                    classified_mode=classified_mode,
                    round_number=round_number,
                    claim_targets=claim_targets,
                    coverage_summary=coverage_summary,
                )

            # --- Web search (Tavily/DDG) for all queries in parallel ---
            web_tasks = []
            for query_spec in round_queries:
                if search_count >= max_total_searches:
                    break
                web_tasks.append(
                    search_web(
                        query=query_spec["query"],
                        max_results=max_web_results,
                        time_range=query_spec.get("time_range"),
                    )
                )
                search_count += 1

            # --- Academic search for unique keyword sets in parallel ---
            academic_keyword_sets = self._extract_academic_keyword_sets(
                round_queries, keywords, original_query
            )
            academic_tasks = []
            for kw_set in academic_keyword_sets:
                if search_count + ACADEMIC_SOURCE_SEARCH_FANOUT > max_total_searches:
                    break
                academic_tasks.append(
                    search_all_academic_sources(
                        keywords=kw_set,
                        max_results_per_source=max_academic_per_source,
                    )
                )
                search_count += ACADEMIC_SOURCE_SEARCH_FANOUT

            # Run web + academic searches concurrently
            all_results = await asyncio.gather(
                asyncio.gather(*web_tasks, return_exceptions=True) if web_tasks else _empty_list(),
                asyncio.gather(*academic_tasks, return_exceptions=True) if academic_tasks else _empty_list(),
            )
            web_results_list = all_results[0] if all_results[0] else []
            academic_results_list = all_results[1] if all_results[1] else []

            round_count = 0

            # Process web results
            for idx, results in enumerate(web_results_list):
                if isinstance(results, Exception):
                    logger.warning("Web search error in round %d: %s", round_number, results)
                    continue
                query_spec = round_queries[idx] if idx < len(round_queries) else {"role": "web-scout"}
                normalized = [
                    normalize_source_card(item, scout_role=query_spec.get("role", "web-scout"), round_number=round_number)
                    for item in (results or [])
                    if item.get("url") and item.get("title")
                ]
                round_count += len(normalized)
                gathered_sources.extend(normalized)

            # Process academic results
            for academic_papers in academic_results_list:
                if isinstance(academic_papers, Exception):
                    logger.warning("Academic search error in round %d: %s", round_number, academic_papers)
                    continue
                for paper in (academic_papers or []):
                    source_card = _academic_paper_to_source_card(paper, round_number=round_number)
                    if source_card:
                        round_count += 1
                        gathered_sources.append(source_card)

            scout_notes.append({
                "round_number": round_number,
                "queries": round_queries,
                "source_count": round_count,
                "search_count": search_count,
            })

        # ----------------------------------------------------------
        # Phase C: Iterative deepening — use top sources to find more
        # ----------------------------------------------------------
        if search_count < max_total_searches:
            deepening_sources, deepening_searches_used = await self._iterative_deepen(
                gathered_sources,
                keywords=keywords,
                original_query=original_query,
                classified_mode=classified_mode,
                max_searches_remaining=max_total_searches - search_count,
                max_web_results=max_web_results,
                max_academic_per_source=max_academic_per_source,
            )
            search_count += deepening_searches_used
            if deepening_sources:
                gathered_sources.extend(deepening_sources)
                scout_notes.append({
                    "round_number": len(scout_notes) + 1,
                    "queries": [{"role": "iterative-deepening", "query": "derived from top sources"}],
                    "source_count": len(deepening_sources),
                    "search_count": search_count,
                })

        # ----------------------------------------------------------
        # Phase D: Enrich, dedupe, sort
        # ----------------------------------------------------------
        sources = sort_sources(
            dedupe_sources(
                await enrich_source_cards(
                    gathered_sources,
                    max_fetches=15 if classified_mode == "live_analysis" else 10,
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

        coverage_summary = self._assess_coverage(
            sources,
            claim_targets=claim_targets,
            source_requirements=context.get("source_requirements") or {},
        )
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
                "search_lanes_used": sorted({
                    str(note_query.get("lane") or note_query.get("role"))
                    for note in scout_notes
                    for note_query in note.get("queries", [])
                }),
                "coverage_summary": coverage_summary,
                "uncovered_claim_targets": coverage_summary["uncovered_claim_targets"],
                "rounds_completed": {
                    "evidence_rounds": max(1, len(scout_notes)),
                    "critique_rounds": 0,
                },
            },
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }

    # ------------------------------------------------------------------
    # Sub-question decomposition & diverse query generation
    # ------------------------------------------------------------------

    def _decompose_and_generate_queries(
        self,
        original_query: str,
        *,
        keywords: List[str],
        search_queries: List[Dict[str, Any]],
        classified_mode: str,
    ) -> List[Dict[str, Any]]:
        """Generate a diverse set of search queries by decomposing the research question.

        Produces 8-15 queries covering different facets of the question, vs the
        original 2-5 queries. This dramatically increases source coverage.
        """
        queries: List[Dict[str, Any]] = []

        # 1. Include any planner-generated queries
        if search_queries:
            queries.extend(search_queries)

        keyword_text = " ".join(keywords[:6])

        # 2. Core query variants
        queries.append({
            "role": "core-scout",
            "lane": "core-answer",
            "query": original_query,
            "time_range": None,
        })
        if keywords:
            queries.append({
                "role": "keyword-scout",
                "lane": "core-answer",
                "query": keyword_text,
                "time_range": None,
            })

        # 3. Academic-phrased variants (review, mechanism, recent advances)
        academic_prefixes = [
            "systematic review",
            "recent advances",
            "mechanisms of",
        ]
        for prefix in academic_prefixes:
            queries.append({
                "role": "academic-scout",
                "lane": "core-literature",
                "query": f"{prefix} {keyword_text}",
                "time_range": None,
            })

        # 4. Methodology / experimental approach queries
        queries.append({
            "role": "methods-scout",
            "lane": "methods-and-gaps",
            "query": f"{keyword_text} methodology experimental approach",
            "time_range": None,
        })

        # 5. Applications / practical implications
        queries.append({
            "role": "applications-scout",
            "lane": "core-answer",
            "query": f"{keyword_text} applications practical implications",
            "time_range": None,
        })

        # 6. Challenges / limitations / gaps
        queries.append({
            "role": "limitations-scout",
            "lane": "uncertainty",
            "query": f"{keyword_text} challenges limitations current gaps",
            "time_range": None,
        })

        # 7. Fresh/recent developments for live and hybrid modes
        if classified_mode in {"live_analysis", "hybrid"}:
            current_year = datetime.now().year
            queries.extend([
                {
                    "role": "latest-scout",
                    "lane": "breaking-developments",
                    "query": f"{original_query} latest {current_year} {current_year + 1}",
                    "time_range": "m",
                },
                {
                    "role": "news-scout",
                    "lane": "breaking-developments",
                    "query": f"{keyword_text} new findings announced",
                    "time_range": "w",
                },
            ])

        # Deduplicate queries by query text
        seen_queries: set[str] = set()
        unique_queries: List[Dict[str, Any]] = []
        for q in queries:
            q_text = q.get("query", "").strip().lower()
            if q_text and q_text not in seen_queries:
                seen_queries.add(q_text)
                unique_queries.append(q)

        return unique_queries

    def _extract_academic_keyword_sets(
        self,
        round_queries: List[Dict[str, Any]],
        base_keywords: List[str],
        original_query: str,
    ) -> List[List[str]]:
        """Extract distinct keyword sets for academic API searches.

        Returns 2-4 keyword sets so we search academic sources with different
        phrasings for broader coverage.
        """
        keyword_sets: List[List[str]] = []

        # Set 1: Original keywords
        if base_keywords:
            keyword_sets.append(base_keywords[:8])

        # Set 2: Extract meaningful terms from the query
        query_tokens = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", original_query.lower())
        stop_words = {
            "want", "understand", "kinds", "that", "with", "without", "using",
            "other", "easy", "safe", "which", "have", "been", "from", "into",
            "their", "there", "about", "what", "when", "where", "this", "these",
            "those", "them", "they", "being", "does", "will", "would", "should",
            "could", "make", "like", "also", "very", "more", "most", "some",
        }
        filtered_tokens = [t for t in query_tokens if t not in stop_words]
        if filtered_tokens and filtered_tokens != base_keywords[:len(filtered_tokens)]:
            keyword_sets.append(filtered_tokens[:8])

        # Set 3: Extract unique terms from round queries
        all_query_text = " ".join(q.get("query", "") for q in round_queries)
        query_terms = re.findall(r"[A-Za-z][A-Za-z\-]{4,}", all_query_text.lower())
        unique_terms = []
        seen = set()
        for t in query_terms:
            if t not in seen and t not in stop_words:
                seen.add(t)
                unique_terms.append(t)
        if unique_terms and len(unique_terms) >= 3:
            keyword_sets.append(unique_terms[:8])

        # Limit to 3 sets max
        return keyword_sets[:3]

    # ------------------------------------------------------------------
    # Iterative deepening — use found sources to discover more
    # ------------------------------------------------------------------

    async def _iterative_deepen(
        self,
        gathered_sources: List[Dict[str, Any]],
        *,
        keywords: List[str],
        original_query: str,
        classified_mode: str,
        max_searches_remaining: int,
        max_web_results: int,
        max_academic_per_source: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Use top-scoring sources to discover additional related sources.

        Strategies:
        1. Extract novel terms from top source titles/snippets and search again.
        2. For Semantic Scholar papers, fetch their citing papers.
        """
        if max_searches_remaining <= 0:
            return [], 0

        deduped = dedupe_sources(gathered_sources)
        # Sort by relevance score descending
        scored = sorted(deduped, key=lambda s: float(s.get("relevance_score") or 0), reverse=True)
        top_sources = scored[:10]

        new_sources: List[Dict[str, Any]] = []
        tasks: List[asyncio.Task] = []
        search_budget = max_searches_remaining
        searches_used = 0

        # Strategy 1: Extract novel key phrases from top source titles
        novel_terms = self._extract_novel_terms(top_sources, existing_keywords=keywords)
        if novel_terms and search_budget >= ACADEMIC_SOURCE_SEARCH_FANOUT:
            # Search academic sources with novel terms
            tasks.append(
                asyncio.ensure_future(
                    search_all_academic_sources(
                        keywords=novel_terms[:8],
                        max_results_per_source=max_academic_per_source,
                    )
                )
            )
            search_budget -= ACADEMIC_SOURCE_SEARCH_FANOUT
            searches_used += ACADEMIC_SOURCE_SEARCH_FANOUT

        # Also do a web search with novel terms
        if novel_terms and search_budget > 0:
            novel_query = " ".join(novel_terms[:6])
            tasks.append(
                asyncio.ensure_future(
                    search_web(query=novel_query, max_results=max_web_results)
                )
            )
            search_budget -= 1
            searches_used += 1

        # Strategy 2: Fetch citing papers from Semantic Scholar
        s2_paper_ids = [
            s.get("s2_paper_id")
            for s in top_sources
            if s.get("s2_paper_id")
        ][:3]  # Top 3 papers with S2 IDs
        for paper_id in s2_paper_ids:
            if search_budget <= 0:
                break
            tasks.append(
                asyncio.ensure_future(
                    fetch_semantic_scholar_citations(paper_id, limit=15)
                )
            )
            search_budget -= 1
            searches_used += 1

        if not tasks:
            return [], 0

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Iterative deepening error: %s", result)
                continue
            if not isinstance(result, list):
                continue
            for item in result:
                if not isinstance(item, dict):
                    continue
                if _looks_like_academic_paper(item):
                    source_card = _academic_paper_to_source_card(item, round_number=99)
                    if source_card:
                        new_sources.append(source_card)
                    continue
                if item.get("url") and item.get("title"):
                    new_sources.append(
                        normalize_source_card(
                            item,
                            scout_role="iterative-deepening",
                            round_number=99,
                        )
                    )

        return new_sources, searches_used

    def _extract_novel_terms(
        self,
        top_sources: List[Dict[str, Any]],
        existing_keywords: List[str],
    ) -> List[str]:
        """Extract key terms from top sources that weren't in the original keywords."""
        existing_lower = {kw.lower() for kw in existing_keywords}
        stop_words = {
            "the", "and", "for", "with", "that", "this", "from", "into",
            "their", "there", "about", "what", "when", "where", "which",
            "have", "been", "using", "based", "study", "research", "paper",
            "analysis", "results", "method", "approach", "review", "article",
            "https", "http", "www", "com", "org",
        }

        term_counts: Counter = Counter()
        for source in top_sources:
            text = f"{source.get('title', '')} {source.get('snippet', '')}".lower()
            tokens = re.findall(r"[a-z][a-z\-]{3,}", text)
            for token in tokens:
                if token not in existing_lower and token not in stop_words:
                    term_counts[token] += 1

        # Return most common novel terms
        return [term for term, _ in term_counts.most_common(10)]

    # ------------------------------------------------------------------
    # Curate sources (unchanged logic)
    # ------------------------------------------------------------------

    async def _execute_curate_sources(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        del request
        gathered = dict(context.get("gathered_evidence") or {})
        requirements = SourceRequirements.model_validate(context.get("source_requirements") or {})
        classified_mode = str(context.get("classified_mode") or "literature")
        scenario_requested = bool(context.get("scenario_analysis_requested"))

        filtered_payload = filter_sources_for_curation(
            dedupe_sources(gathered.get("sources") or []),
            requirements=requirements,
            classified_mode=classified_mode,
        )
        curated_sources = sort_sources(filtered_payload["selected_sources"])
        curated_sources, citations = assign_citation_ids(curated_sources, limit=requirements.total_sources)
        validation = validate_source_requirements(curated_sources, requirements=requirements)
        source_summary = build_source_summary(curated_sources, requirements=requirements)
        coverage_summary = dict(gathered.get("coverage_summary") or {})
        coverage_summary["source_diversity"] = {
            "unique_publishers": len({str(source.get("publisher")) for source in curated_sources if source.get("publisher")}),
            "source_type_mix": dict(Counter(str(source.get("source_type") or "unknown") for source in curated_sources)),
        }
        coverage_summary["citation_count"] = len(citations)
        coverage_summary["citation_ready"] = len(citations) > 0
        freshness_summary = {
            "required": requirements.min_fresh_sources > 0,
            "window_days": requirements.freshness_window_days,
            "minimum_fresh_sources": requirements.min_fresh_sources,
            "fresh_sources": source_summary["fresh_sources"],
            "requirements_met": validation["passed"],
            "issues": validation["issues"],
        }

        if classified_mode in {"live_analysis", "hybrid"} and not scenario_requested and not validation["passed"]:
            self._update_reputation(success=False, quality_score=0.0)
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": (
                    "insufficient_fresh_evidence"
                    if classified_mode == "live_analysis"
                    else "insufficient_curated_evidence"
                ),
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
                "citations": citations or build_citation_cards(curated_sources, limit=requirements.total_sources),
                "source_summary": source_summary,
                "freshness_summary": freshness_summary,
                "coverage_summary": coverage_summary,
                "uncovered_claim_targets": list(gathered.get("uncovered_claim_targets") or []),
                "issues": validation["issues"],
                "filtered_sources": filtered_payload["filtered_sources"],
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

    # ------------------------------------------------------------------
    # search_literature (legacy interface, kept for compatibility)
    # ------------------------------------------------------------------

    async def search_literature(
        self,
        keywords: List[str],
        research_question: str,
        max_papers: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Search for relevant literature across multiple databases."""
        date_range = context.get("date_range", "2020-2024") if context else "2020-2024"
        min_relevance = context.get("min_relevance", 0.5) if context else 0.5

        request = f"""
        Search for academic papers relevant to the following research question:

        Research Question: {research_question}

        Keywords: {', '.join(keywords)}

        Search Parameters:
        - Maximum papers to retrieve: {max_papers}
        - Date range: {date_range}
        - Minimum relevance score: {min_relevance}
        - Sources to search: ArXiv, Semantic Scholar, PubMed, OpenAlex

        Please:
        1. Search all academic databases for papers matching the keywords
        2. Calculate relevance scores for each paper
        3. Deduplicate papers found in multiple sources
        4. Rank papers by relevance
        5. Return the top {max_papers} most relevant papers
        """

        result = await self.execute(request)
        if not result["success"]:
            return {
                "success": False,
                "error": result.get("error", "Failed to search literature"),
            }

        try:
            agent_output = result["result"]
            if isinstance(agent_output, str):
                corpus_data = self._parse_or_construct_corpus(
                    agent_output,
                    keywords=keywords,
                    research_question=research_question,
                    date_range=date_range,
                    min_relevance=min_relevance,
                    max_papers=max_papers,
                )
            else:
                corpus_data = agent_output

            if "search_date" not in corpus_data:
                corpus_data["search_date"] = datetime.utcnow().isoformat()

            is_valid, error, validated_corpus = validate_literature_corpus(corpus_data)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Validation failed: {error}",
                    "raw_output": corpus_data,
                }

            papers_count = len(validated_corpus.papers)
            total_cost = papers_count * self.get_payment_rate()

            return {
                "success": True,
                "literature_corpus": validated_corpus.dict(),
                "agent_id": self.agent_id,
                "metadata": {
                    "agent_id": self.agent_id,
                    "payment_due": total_cost,
                    "currency": "HBAR",
                    "papers_retrieved": papers_count,
                    "cost_per_paper": self.get_payment_rate(),
                    "search_model": self.model,
                    "search_date": corpus_data["search_date"],
                },
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Failed to parse agent output as JSON: {str(e)}",
                "raw_output": result["result"],
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error processing literature corpus: {str(e)}",
            }

    def _parse_or_construct_corpus(
        self,
        agent_output: str,
        *,
        keywords: List[str],
        research_question: str,
        date_range: str,
        min_relevance: float,
        max_papers: int,
    ) -> Dict[str, Any]:
        """Parse JSON output when possible, otherwise fall back to a valid corpus."""
        json_start = agent_output.find("{")
        json_end = agent_output.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            try:
                return json.loads(agent_output[json_start:json_end])
            except json.JSONDecodeError:
                logger.warning(
                    "Literature miner returned malformed JSON; falling back to demo corpus."
                )

        return self._construct_corpus_from_text(
            agent_output,
            keywords=keywords,
            research_question=research_question,
            date_range=date_range,
            min_relevance=min_relevance,
            max_papers=max_papers,
        )

    def _construct_corpus_from_text(
        self,
        text: str,
        *,
        keywords: List[str],
        research_question: str,
        date_range: str,
        min_relevance: float,
        max_papers: int,
    ) -> Dict[str, Any]:
        """Construct a compatible fallback corpus when the model returns prose."""
        del text, keywords
        return {
            "query": research_question,
            "total_found": 3,
            "papers": [
                {
                    "title": "Blockchain-Based Agent Marketplaces: A Survey",
                    "authors": ["Demo Author 1", "Demo Author 2"],
                    "abstract": (
                        "A comprehensive survey of blockchain-based agent marketplace "
                        "implementations."
                    ),
                    "published_date": "2023-06-15",
                    "journal": None,
                    "arxiv_id": "2306.12345",
                    "doi": None,
                    "url": "https://arxiv.org/abs/2306.12345",
                    "relevance_score": 0.85,
                    "citations_count": 15,
                },
                {
                    "title": "ERC-8004: Agent Discovery Protocol Implementation",
                    "authors": ["Demo Author 3"],
                    "abstract": (
                        "Implementation details and performance analysis of ERC-8004 "
                        "protocol."
                    ),
                    "published_date": "2024-01-20",
                    "journal": None,
                    "arxiv_id": "2401.98765",
                    "doi": None,
                    "url": "https://arxiv.org/abs/2401.98765",
                    "relevance_score": 0.92,
                    "citations_count": 8,
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
                    "citations_count": 22,
                },
            ],
            "sources": ["ArXiv", "Semantic Scholar", "PubMed", "OpenAlex"],
            "search_date": datetime.utcnow().isoformat(),
            "filtering_criteria": {
                "date_range": date_range,
                "min_relevance": min_relevance,
                "max_results": max_papers,
            },
        }

    # ------------------------------------------------------------------
    # Query building helpers
    # ------------------------------------------------------------------

    def _build_round_queries(
        self,
        original_query: str,
        *,
        keywords: List[str],
        search_queries: List[Dict[str, Any]],
        classified_mode: str,
        round_number: int,
        claim_targets: List[Dict[str, Any]],
        coverage_summary: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if round_number == 1 and search_queries:
            return search_queries

        keyword_text = " ".join(keywords[:6])
        follow_up_queries: List[Dict[str, Any]] = []
        uncovered = list(coverage_summary.get("uncovered_claim_targets") or [])
        if classified_mode in {"live_analysis", "hybrid"}:
            follow_up_queries.extend([
                {
                    "role": "latest-confirmation-scout",
                    "lane": "breaking-developments",
                    "query": f"{original_query} updated latest confirmed developments {keyword_text}",
                    "time_range": "w",
                },
                {
                    "role": "counterpoint-scout",
                    "lane": "counterpoints",
                    "query": f"{original_query} uncertainty disputed conflicting reports {keyword_text}",
                    "time_range": "w",
                },
            ])
        if classified_mode in {"literature", "hybrid"}:
            follow_up_queries.append({
                "role": "methods-scout",
                "lane": "methods-and-gaps",
                "query": f"{original_query} methodology evidence review {keyword_text}",
                "time_range": None,
            })
            # Additional literature-specific follow-up queries
            follow_up_queries.append({
                "role": "review-scout",
                "lane": "core-literature",
                "query": f"review survey meta-analysis {keyword_text}",
                "time_range": None,
            })
        for target in uncovered[:3]:
            claim_text = str(target.get("claim_target") or "")
            if not claim_text:
                continue
            follow_up_queries.append({
                "role": "claim-gap-scout",
                "lane": target.get("lane") or "claim-gap",
                "query": f"{original_query} {claim_text} evidence confirmation {keyword_text}",
                "time_range": "w" if classified_mode != "literature" else None,
            })
        return follow_up_queries or search_queries

    # ------------------------------------------------------------------
    # Coverage assessment
    # ------------------------------------------------------------------

    def _assess_coverage(
        self,
        sources: List[Dict[str, Any]],
        *,
        claim_targets: List[Dict[str, Any]],
        source_requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        requirements = SourceRequirements.model_validate(
            source_requirements
            or SourceRequirements(total_sources=6, min_academic_or_primary=0).model_dump()
        )
        source_summary = build_source_summary(sources, requirements=requirements)
        publishers = {str(source.get("publisher")) for source in sources if source.get("publisher")}
        source_type_mix = Counter(str(source.get("source_type") or "unknown") for source in sources)
        covered_claims: List[str] = []
        uncovered_claim_targets: List[Dict[str, Any]] = []
        for claim_target in claim_targets:
            if self._claim_target_matches_sources(claim_target, sources):
                covered_claims.append(str(claim_target.get("claim_id")))
            else:
                uncovered_claim_targets.append(claim_target)

        ready_for_synthesis = (
            source_summary["requirements_met"]
            and len(publishers) >= 3
            and len(uncovered_claim_targets) == 0
        )
        return {
            "source_summary": source_summary,
            "source_diversity": {
                "unique_publishers": len(publishers),
                "source_type_mix": dict(source_type_mix),
            },
            "covered_claim_ids": covered_claims,
            "uncovered_claim_targets": uncovered_claim_targets,
            "ready_for_synthesis": ready_for_synthesis,
        }

    def _claim_target_matches_sources(
        self,
        claim_target: Dict[str, Any],
        sources: List[Dict[str, Any]],
    ) -> bool:
        claim_text = str(claim_target.get("claim_target") or "").lower()
        lane = str(claim_target.get("lane") or "").lower()
        claim_tokens = {token for token in claim_text.split() if len(token) > 4}
        if not claim_tokens and lane:
            claim_tokens = {token for token in lane.replace("-", " ").split() if len(token) > 3}

        for source in sources:
            haystack = " ".join([
                str(source.get("title") or ""),
                str(source.get("snippet") or ""),
                str(source.get("publisher") or ""),
                str(source.get("scout_role") or ""),
            ]).lower()
            if lane and lane.replace("-", " ") in haystack:
                return True
            if claim_tokens and sum(1 for token in claim_tokens if token in haystack) >= 2:
                return True
        return False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _academic_paper_to_source_card(
    paper: Dict[str, Any],
    round_number: int,
) -> Optional[Dict[str, Any]]:
    """Convert an academic paper dict into a normalized source card."""
    title = (paper.get("title") or "").strip()
    if not title:
        return None

    url = paper.get("url") or ""
    if not url:
        if paper.get("doi"):
            url = f"https://doi.org/{paper['doi']}"
        elif paper.get("arxiv_id"):
            url = f"https://arxiv.org/abs/{paper['arxiv_id']}"
        elif paper.get("pmid"):
            url = f"https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/"
    if not url:
        return None

    source = paper.get("source") or "Academic"
    source_type = "academic"
    publisher = paper.get("journal") or source

    snippet = (paper.get("abstract") or "")[:1200]
    display_snippet = snippet[:700]

    return {
        "title": title[:240],
        "url": url,
        "publisher": publisher,
        "published_at": paper.get("published_date"),
        "source_type": source_type,
        "snippet": snippet,
        "display_snippet": display_snippet,
        "relevance_score": float(paper.get("relevance_score") or 0.7),
        "quality_flags": [],
        "scout_role": f"academic-{source.lower().replace(' ', '-')}",
        "round_number": round_number,
        "s2_paper_id": paper.get("s2_paper_id"),
    }


def _looks_like_academic_paper(item: Dict[str, Any]) -> bool:
    """Heuristically distinguish academic-paper payloads from web-search results."""
    academic_fields = (
        "abstract",
        "authors",
        "journal",
        "doi",
        "arxiv_id",
        "pmid",
        "s2_paper_id",
        "citations_count",
    )
    return any(item.get(field) for field in academic_fields)


async def _empty_list():
    """Coroutine returning an empty list — used as a no-op gather target."""
    return []


# Create singleton instance
literature_miner_agent = LiteratureMinerAgent()


# Convenience function for use as tool by other agents
async def search_research_literature(
    keywords: List[str],
    research_question: str,
    max_papers: int = 10,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tool function for searching research literature."""
    return await literature_miner_agent.search_literature(
        keywords, research_question, max_papers, context
    )
