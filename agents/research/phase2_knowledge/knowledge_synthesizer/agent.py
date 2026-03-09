"""
Knowledge Synthesizer Agent

Synthesizes, critiques, and revises source-grounded research answers.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Dict, List

from agents.research.base_research_agent import BaseResearchAgent
from shared.strands_openai_agent import create_strands_openai_agent


def _extract_json_block(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}


class KnowledgeSynthesizerAgent(BaseResearchAgent):
    """Agent that drafts, critiques, and revises evidence-grounded answers."""

    def __init__(self):
        super().__init__(
            agent_id="knowledge-synthesizer-001",
            name="Knowledge Synthesizer",
            description="Synthesizes information from multiple papers, extracts key knowledge, identifies patterns and research gaps",
            capabilities=[
                "knowledge-extraction",
                "pattern-recognition",
                "gap-analysis",
                "state-of-art-summary",
                "methodology-comparison",
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.15 HBAR",
                "unit": "per_synthesis",
            },
            model="gpt-5.4",
        )

    def get_system_prompt(self) -> str:
        return """You are a Knowledge Synthesizer AI agent specializing in extracting and synthesizing insights from evidence collections.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions
- Use only the evidence supplied to you
- If evidence is insufficient, say so explicitly
- ALWAYS return valid JSON and avoid conversational filler

You produce concise, source-grounded outputs that preserve uncertainty."""

    def get_tools(self) -> List:
        return []

    async def execute(self, request: str, **kwargs) -> Dict[str, Any]:
        context = kwargs.get("context") or {}
        node_strategy = context.get("node_strategy")
        if node_strategy == "draft_synthesis":
            return await self._execute_draft_synthesis(request, context)
        if node_strategy == "critique_and_fact_check":
            return await self._execute_critique(request, context)
        if node_strategy == "revise_final_answer":
            return await self._execute_revision(request, context)
        return await super().execute(request, **kwargs)

    async def _execute_draft_synthesis(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        query_plan = dict(context.get("query_plan") or {})
        curated_sources = dict(context.get("curated_sources") or {})
        sources = list(curated_sources.get("sources") or [])
        citations = list(curated_sources.get("citations") or [])
        claim_targets = list(query_plan.get("claim_targets") or context.get("claim_targets") or [])
        quality_requirements = dict(context.get("quality_requirements") or {})

        if not sources:
            self._update_reputation(success=False, quality_score=0.0)
            return self._error_result("No curated sources available for synthesis.")

        prompt = f"""
Create a source-grounded draft answer.

User query: {query_plan.get('query') or context.get('original_description') or request}
Research question: {query_plan.get('research_question')}
Rewritten research brief: {query_plan.get('rewritten_research_brief')}
Classified mode: {context.get('classified_mode')}
Depth mode: {context.get('depth_mode')}
Freshness required: {context.get('freshness_required')}
As-of date: {datetime.now(UTC).date().isoformat()}

Success criteria:
{json.dumps(query_plan.get('success_criteria') or [], indent=2)}

Claim targets:
{json.dumps(claim_targets, indent=2)}

Subquestions:
{json.dumps(query_plan.get('subquestions') or [], indent=2)}

Source summary:
{json.dumps(curated_sources.get('source_summary') or {}, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

Citation catalog:
{json.dumps(citations, indent=2)}

Sources:
{self._format_sources_for_prompt(sources)}

Return JSON with this shape:
{{
  "answer_markdown": "<direct answer in markdown with inline citations like [S1] that uses absolute dates when relevant>",
  "claims": [
    {{
      "claim_id": "<claim target id such as C1>",
      "claim": "<specific claim>",
      "supporting_citation_ids": ["S1", "S2"],
      "confidence": "<high|medium|low>"
    }}
  ],
  "limitations": ["<important caveat>"]
}}

Rules:
- Do not invent events or outcomes that are not reflected in the sources.
- If the topic is live/current, state the answer as of the date above.
- Keep claims tied to the supplied citation IDs.
- Use section headings for Summary, Evidence, and Limitations.
- Every material factual claim should have at least one inline citation marker such as [S1].
- If the freshest evidence is mixed, say so explicitly and preserve uncertainty.
"""

        parsed = await self._run_role_prompt(
            system_prompt=(
                "You are a rigorous synthesis drafter. Produce a source-grounded draft answer in JSON."
            ),
            prompt=prompt,
        )
        draft_result = self._normalize_answer_payload(
            parsed,
            fallback_query=str(query_plan.get("query") or request),
            citations=citations,
        )
        draft_result["citations"] = citations
        draft_result["sources"] = sources
        draft_result["source_summary"] = curated_sources.get("source_summary") or {}
        draft_result["freshness_summary"] = curated_sources.get("freshness_summary") or {}
        draft_result["quality_summary"] = self._build_quality_summary(
            answer_markdown=draft_result.get("answer_markdown", ""),
            claims=draft_result.get("claims") or [],
            citations=citations,
            source_summary=draft_result["source_summary"],
            freshness_summary=draft_result["freshness_summary"],
            critic_findings=[],
            quality_requirements=quality_requirements,
            classified_mode=str(context.get("classified_mode") or ""),
        )
        draft_result["rounds_completed"] = {
            "evidence_rounds": int((context.get("rounds_planned") or {}).get("evidence_rounds", 0) or 0),
            "critique_rounds": 0,
        }

        self._update_reputation(success=True, quality_score=0.9)
        return self._success_result(draft_result)

    async def _execute_critique(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        del request
        query_plan = dict(context.get("query_plan") or {})
        curated_sources = dict(context.get("curated_sources") or {})
        draft = dict(context.get("draft_synthesis") or {})
        sources = list(curated_sources.get("sources") or [])
        citations = list(curated_sources.get("citations") or [])
        critique_rounds = int((context.get("rounds_planned") or {}).get("critique_rounds", 1) or 1)
        quality_requirements = dict(context.get("quality_requirements") or {})

        deterministic_findings = self._deterministic_findings(
            draft=draft,
            citations=citations,
            freshness_summary=curated_sources.get("freshness_summary") or {},
            scenario_requested=bool(context.get("scenario_analysis_requested")),
            quality_requirements=quality_requirements,
            classified_mode=str(context.get("classified_mode") or ""),
        )

        llm_findings: List[Dict[str, Any]] = []
        for round_number in range(1, critique_rounds + 1):
            prompt = f"""
Review this draft answer for unsupported claims, missing caveats, stale evidence, missing inline citations, benchmark mismatches, unsupported causal language, and overstatement.

Research question: {query_plan.get('research_question')}
Rewritten research brief: {query_plan.get('rewritten_research_brief')}
Draft answer:
{json.dumps(draft, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

Claim targets:
{json.dumps(query_plan.get('claim_targets') or [], indent=2)}

Quality requirements:
{json.dumps(quality_requirements, indent=2)}

Sources:
{self._format_sources_for_prompt(sources)}

Return JSON:
{{
  "critic_findings": [
    {{
      "issue": "<what needs attention>",
      "severity": "<high|medium|low>",
      "recommendation": "<how to fix it>"
    }}
  ]
}}
"""
            parsed = await self._run_role_prompt(
                system_prompt=(
                    "You are a strict fact-checking critic. Flag overstatement, unsupported claims, and missing caveats."
                ),
                prompt=prompt,
            )
            for finding in parsed.get("critic_findings") or []:
                if isinstance(finding, dict):
                    finding["round_number"] = round_number
                    llm_findings.append(finding)

        critic_findings = deterministic_findings + llm_findings
        result = {
            "critic_findings": critic_findings,
            "limitations": draft.get("limitations") or [],
            "rounds_completed": {
                "evidence_rounds": int((draft.get("rounds_completed") or {}).get("evidence_rounds", 0) or 0),
                "critique_rounds": critique_rounds,
            },
        }
        self._update_reputation(success=True, quality_score=0.86)
        return self._success_result(result)

    async def _execute_revision(self, request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        del request
        query_plan = dict(context.get("query_plan") or {})
        curated_sources = dict(context.get("curated_sources") or {})
        draft = dict(context.get("draft_synthesis") or {})
        critic_review = dict(context.get("critic_review") or {})
        sources = list(curated_sources.get("sources") or [])
        citations = list(curated_sources.get("citations") or [])
        quality_requirements = dict(context.get("quality_requirements") or {})

        if not draft:
            self._update_reputation(success=False, quality_score=0.0)
            return self._error_result("Missing draft synthesis for final revision.")

        prompt = f"""
Revise the answer using the critic findings while staying strictly grounded in the sources.

User query: {query_plan.get('query') or context.get('original_description')}
Research question: {query_plan.get('research_question')}
Rewritten research brief: {query_plan.get('rewritten_research_brief')}
As-of date: {datetime.now(UTC).date().isoformat()}

Draft:
{json.dumps(draft, indent=2)}

Critic findings:
{json.dumps(critic_review.get('critic_findings') or [], indent=2)}

Source summary:
{json.dumps(curated_sources.get('source_summary') or {}, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

Claim targets:
{json.dumps(query_plan.get('claim_targets') or [], indent=2)}

Success criteria:
{json.dumps(query_plan.get('success_criteria') or [], indent=2)}

Quality requirements:
{json.dumps(quality_requirements, indent=2)}

Citation catalog:
{json.dumps(citations, indent=2)}

Sources:
{self._format_sources_for_prompt(sources)}

Return JSON:
{{
  "answer_markdown": "<final revised markdown answer with inline citation markers like [S1]>",
  "claims": [
    {{
      "claim_id": "<claim id>",
      "claim": "<specific claim>",
      "supporting_citation_ids": ["S1"],
      "confidence": "<high|medium|low>"
    }}
  ],
  "limitations": ["<remaining caveat>"]
}}

Rules:
- Use absolute dates for current events.
- Preserve uncertainty instead of speculating.
- Do not claim evidence beyond what is in the sources.
- Keep the final answer in markdown with Summary, Evidence, and Limitations sections.
- Use inline citation markers like [S1] throughout the answer.
- Every claim must map to at least one supporting citation ID that exists in the citation catalog.
"""

        parsed = await self._run_role_prompt(
            system_prompt=(
                "You are a careful revising editor. Incorporate critic findings and produce a final source-grounded answer in JSON."
            ),
            prompt=prompt,
        )
        revised = self._normalize_answer_payload(
            parsed,
            fallback_query=str(query_plan.get("query") or "research query"),
            citations=citations,
        )
        revised["citations"] = citations
        revised["sources"] = sources
        revised["source_summary"] = curated_sources.get("source_summary") or {}
        revised["freshness_summary"] = curated_sources.get("freshness_summary") or {}
        revised["critic_findings"] = critic_review.get("critic_findings") or []
        revised["quality_summary"] = self._build_quality_summary(
            answer_markdown=revised.get("answer_markdown", ""),
            claims=revised.get("claims") or [],
            citations=citations,
            source_summary=revised["source_summary"],
            freshness_summary=revised["freshness_summary"],
            critic_findings=revised["critic_findings"],
            quality_requirements=quality_requirements,
            classified_mode=str(context.get("classified_mode") or ""),
        )
        revised["rounds_completed"] = {
            "evidence_rounds": int((draft.get("rounds_completed") or {}).get("evidence_rounds", 0) or 0),
            "critique_rounds": int((critic_review.get("rounds_completed") or {}).get("critique_rounds", 0) or 0),
        }

        self._update_reputation(success=True, quality_score=0.92)
        return self._success_result(revised)

    async def synthesize_knowledge(
        self,
        literature_corpus: Dict[str, Any],
        problem_statement: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Legacy helper retained for older flows."""
        papers = literature_corpus.get("papers", [])
        request = {
            "query_plan": {
                "query": problem_statement.get("query"),
                "research_question": problem_statement.get("research_question"),
            },
            "curated_sources": {
                "sources": [
                    {
                        "title": paper.get("title"),
                        "publisher": paper.get("journal") or paper.get("source"),
                        "published_at": paper.get("published_date"),
                        "snippet": paper.get("abstract"),
                        "url": paper.get("url"),
                        "source_type": "academic",
                        "relevance_score": paper.get("relevance_score", 0.5),
                    }
                    for paper in papers[:10]
                ],
                "citations": [
                    {
                        "title": paper.get("title"),
                        "url": paper.get("url"),
                        "publisher": paper.get("journal") or paper.get("source"),
                        "published_at": paper.get("published_date"),
                        "source_type": "academic",
                    }
                    for paper in papers[:10]
                    if paper.get("title") and paper.get("url")
                ],
                "source_summary": {"total_sources": len(papers)},
                "freshness_summary": {"required": False},
            },
            "rounds_planned": {"evidence_rounds": 1, "critique_rounds": 1},
        }
        result = await self._execute_draft_synthesis(
            problem_statement.get("research_question") or "Synthesize the supplied literature.",
            request | (context or {}),
        )
        if not result["success"]:
            return {"success": False, "error": result.get("error", "Failed to synthesize knowledge")}
        return {
            "success": True,
            "knowledge_synthesis": result["result"],
            "metadata": {
                "agent_id": self.agent_id,
                "papers_analyzed": len(papers),
                "currency": "HBAR",
            },
        }

    async def _run_role_prompt(self, *, system_prompt: str, prompt: str) -> Dict[str, Any]:
        agent = create_strands_openai_agent(
            system_prompt=system_prompt,
            tools=[],
            model=self.model,
            agent_id=f"{self.agent_id}-internal",
            name=f"{self.name} Internal",
            description="Internal deep-research role",
        )
        result = await agent.run(prompt)
        if isinstance(result, str):
            return _extract_json_block(result)
        if isinstance(result, dict):
            return result
        return {}

    def _format_sources_for_prompt(self, sources: List[Dict[str, Any]], limit: int = 12) -> str:
        formatted = []
        for index, source in enumerate(sources[:limit], start=1):
            formatted.append(
                "\n".join(
                    [
                        f"Source {index}: {source.get('title')}",
                        f"Citation ID: {source.get('citation_id') or f'S{index}'}",
                        f"Publisher: {source.get('publisher')}",
                        f"Published: {source.get('published_at')}",
                        f"Type: {source.get('source_type')}",
                        f"URL: {source.get('url')}",
                        f"Snippet: {source.get('display_snippet') or source.get('snippet')}",
                    ]
                )
            )
        return "\n\n".join(formatted)

    def _normalize_answer_payload(
        self,
        payload: Dict[str, Any],
        *,
        fallback_query: str,
        citations: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        citations = list(citations or payload.get("citations") or [])
        citation_lookup = self._build_citation_lookup(citations)
        claims = []
        for index, item in enumerate(payload.get("claims") or [], start=1):
            if isinstance(item, dict) and item.get("claim"):
                claim_id = str(item.get("claim_id") or f"C{index}")
                supporting_citation_ids = self._resolve_supporting_citation_ids(item, citation_lookup)
                claims.append(
                    {
                        "claim_id": claim_id,
                        "claim": str(item.get("claim")),
                        "supporting_citation_ids": supporting_citation_ids,
                        "supporting_citations": [
                            citation_lookup[citation_id]["title"]
                            for citation_id in supporting_citation_ids
                            if citation_id in citation_lookup and citation_lookup[citation_id].get("title")
                        ],
                        "confidence": str(item.get("confidence") or "medium"),
                    }
                )
        limitations = [
            str(item)
            for item in (payload.get("limitations") or [])
            if isinstance(item, (str, int, float))
        ]
        answer_markdown = str(payload.get("answer_markdown") or payload.get("answer") or "").strip()
        if not answer_markdown:
            answer_markdown = (
                "## Summary\n\n"
                f"Insufficient model output to complete a final synthesis for: {fallback_query}\n\n"
                "## Evidence\n\nThe available evidence could not be synthesized into a reliable answer.\n\n"
                "## Limitations\n\nThe generated answer was incomplete."
            )
        answer = answer_markdown
        return {
            "answer": answer,
            "answer_markdown": answer_markdown,
            "claims": claims,
            "limitations": limitations,
        }

    def _deterministic_findings(
        self,
        *,
        draft: Dict[str, Any],
        citations: List[Dict[str, Any]],
        freshness_summary: Dict[str, Any],
        scenario_requested: bool,
        quality_requirements: Dict[str, Any],
        classified_mode: str,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        answer_markdown = str(draft.get("answer_markdown") or draft.get("answer") or "")
        answer = answer_markdown.lower()
        quality_summary = self._build_quality_summary(
            answer_markdown=answer_markdown,
            claims=list(draft.get("claims") or []),
            citations=citations,
            source_summary=draft.get("source_summary") or {},
            freshness_summary=freshness_summary,
            critic_findings=[],
            quality_requirements=quality_requirements,
            classified_mode=classified_mode,
        )
        if freshness_summary.get("required") and not freshness_summary.get("requirements_met"):
            findings.append(
                {
                    "issue": "Fresh-source minimum not met for this live-analysis answer.",
                    "severity": "high",
                    "recommendation": "Reduce certainty and explain that the freshest evidence is incomplete.",
                    "round_number": 0,
                }
            )
        if "hypothetical" in answer and not scenario_requested:
            findings.append(
                {
                    "issue": "Answer drifts into hypothetical framing for a non-scenario query.",
                    "severity": "high",
                    "recommendation": "Rewrite around observed evidence and dated uncertainty instead of hypotheticals.",
                    "round_number": 0,
                }
            )
        if len(draft.get("claims") or []) < 2:
            findings.append(
                {
                    "issue": "Draft includes too few explicit claims.",
                    "severity": "medium",
                    "recommendation": "Extract more concrete claims and link them to citations.",
                    "round_number": 0,
                }
            )
        for note in quality_summary.get("verification_notes") or []:
            findings.append(
                {
                    "issue": str(note),
                    "severity": "high" if "missing" in str(note).lower() or "must" in str(note).lower() else "medium",
                    "recommendation": "Revise the answer so the final report satisfies the research-answer contract.",
                    "round_number": 0,
                }
            )
        return findings

    def _build_citation_lookup(self, citations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        for citation in citations:
            citation_id = citation.get("citation_id")
            if isinstance(citation_id, str) and citation_id.strip():
                lookup[citation_id.strip()] = citation
        return lookup

    def _resolve_supporting_citation_ids(
        self,
        claim: Dict[str, Any],
        citation_lookup: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        direct_ids = [
            str(value).strip()
            for value in (claim.get("supporting_citation_ids") or [])
            if isinstance(value, (str, int, float)) and str(value).strip()
        ]
        if direct_ids:
            return sorted(dict.fromkeys(direct_ids))

        title_lookup = {
            str(citation.get("title") or "").strip().lower(): citation_id
            for citation_id, citation in citation_lookup.items()
            if citation.get("title")
        }
        resolved: List[str] = []
        for title in claim.get("supporting_citations") or []:
            normalized = str(title).strip().lower()
            if normalized and normalized in title_lookup:
                resolved.append(title_lookup[normalized])
        return sorted(dict.fromkeys(resolved))

    def _extract_inline_citation_ids(self, answer_markdown: str) -> List[str]:
        return sorted(set(re.findall(r"\[(S\d+)\]", answer_markdown or "")))

    def _has_absolute_date(self, answer_markdown: str) -> bool:
        return bool(
            re.search(r"\b20\d{2}-\d{2}-\d{2}\b", answer_markdown)
            or re.search(
                r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\s+\d{1,2},\s+20\d{2}\b",
                answer_markdown,
            )
        )

    def _has_uncertainty_language(self, answer_markdown: str) -> bool:
        normalized = answer_markdown.lower()
        uncertainty_markers = (
            "appears",
            "likely",
            "uncertain",
            "reported",
            "as of",
            "so far",
            "suggests",
            "indicates",
            "may",
            "still evolving",
        )
        return any(marker in normalized for marker in uncertainty_markers)

    def _build_quality_summary(
        self,
        *,
        answer_markdown: str,
        claims: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        source_summary: Dict[str, Any],
        freshness_summary: Dict[str, Any],
        critic_findings: List[Dict[str, Any]],
        quality_requirements: Dict[str, Any],
        classified_mode: str,
    ) -> Dict[str, Any]:
        citation_lookup = self._build_citation_lookup(citations)
        inline_citation_ids = self._extract_inline_citation_ids(answer_markdown)
        claim_count = len(claims)
        covered_claims = 0
        uncovered_claims: List[str] = []
        verification_notes: List[str] = []

        for index, claim in enumerate(claims, start=1):
            claim_id = str(claim.get("claim_id") or f"C{index}")
            supporting_ids = [
                str(item).strip()
                for item in (claim.get("supporting_citation_ids") or [])
                if isinstance(item, str) and item.strip()
            ]
            unknown_ids = [citation_id for citation_id in supporting_ids if citation_id not in citation_lookup]
            if supporting_ids and not unknown_ids:
                covered_claims += 1
            else:
                uncovered_claims.append(claim_id)
                if not supporting_ids:
                    verification_notes.append(
                        f"Claim {claim_id} is missing supporting citation IDs."
                    )
                if unknown_ids:
                    verification_notes.append(
                        f"Claim {claim_id} references unknown citation IDs: {', '.join(unknown_ids)}."
                    )

        citation_coverage = (covered_claims / claim_count) if claim_count else 0.0
        min_claim_count = int(quality_requirements.get("min_claim_count", 0) or 0)
        min_citation_coverage = float(quality_requirements.get("min_citation_coverage", 0.0) or 0.0)

        if min_claim_count and claim_count < min_claim_count:
            verification_notes.append(
                f"Need at least {min_claim_count} explicit claims; found {claim_count}."
            )
        if claim_count and citation_coverage < min_citation_coverage:
            verification_notes.append(
                "Citation coverage is incomplete for the final claims."
            )

        required_sections = [
            str(section).strip()
            for section in (quality_requirements.get("required_sections") or [])
            if str(section).strip()
        ]
        missing_sections = [
            section
            for section in required_sections
            if section.lower() not in (answer_markdown or "").lower()
        ]
        if missing_sections:
            verification_notes.append(
                f"Answer is missing required sections: {', '.join(missing_sections)}."
            )

        if quality_requirements.get("require_inline_citations") and citations:
            if not inline_citation_ids:
                verification_notes.append("Answer is missing inline citation markers such as [S1].")
            else:
                unknown_inline = [
                    citation_id for citation_id in inline_citation_ids if citation_id not in citation_lookup
                ]
                if unknown_inline:
                    verification_notes.append(
                        "Answer references unknown inline citation IDs: "
                        + ", ".join(sorted(unknown_inline))
                        + "."
                    )

        if quality_requirements.get("require_absolute_dates") and not self._has_absolute_date(
            answer_markdown
        ):
            verification_notes.append("Live-analysis answer must include an absolute date.")
        if quality_requirements.get("require_uncertainty_language") and not self._has_uncertainty_language(
            answer_markdown
        ):
            verification_notes.append("Live-analysis answer must include explicit uncertainty language.")

        if freshness_summary.get("required") and not freshness_summary.get("requirements_met"):
            verification_notes.append("Fresh-source requirements were not fully met.")

        if critic_findings:
            high_severity = [
                finding
                for finding in critic_findings
                if str(finding.get("severity") or "").lower() == "high"
            ]
            if high_severity:
                verification_notes.append(
                    f"{len(high_severity)} high-severity critic finding(s) remain unresolved."
                )

        source_types = {
            str(citation.get("source_type") or "unknown")
            for citation in citations
            if citation.get("source_type")
        }
        publishers = {
            str(citation.get("publisher") or "").strip()
            for citation in citations
            if citation.get("publisher")
        }
        source_diversity = {
            "publishers": len(publishers) or len(source_summary.get("publishers") or []),
            "source_types": len(source_types),
            "fresh_sources": int(source_summary.get("fresh_sources", 0) or 0),
            "academic_or_primary_sources": int(
                source_summary.get("academic_or_primary_sources", 0) or 0
            ),
        }

        strict_live_analysis = bool(
            quality_requirements.get("strict_live_analysis")
            or classified_mode in {"live_analysis", "hybrid"}
        )

        return {
            "citation_coverage": round(citation_coverage, 3),
            "uncovered_claims": uncovered_claims,
            "source_diversity": source_diversity,
            "verification_notes": sorted(dict.fromkeys(verification_notes)),
            "strict_live_analysis_checks_passed": (
                not verification_notes if strict_live_analysis else True
            ),
        }

    def _success_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "agent_id": self.agent_id,
            "result": result,
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }

    def _error_result(self, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "agent_id": self.agent_id,
            "error": error,
            "metadata": {
                "timestamp": datetime.utcnow().isoformat(),
                "model": self.model,
            },
        }


# Create global instance
knowledge_synthesizer_agent = KnowledgeSynthesizerAgent()
