"""
Knowledge Synthesizer Agent

Synthesizes, critiques, and revises source-grounded research answers.
"""

from __future__ import annotations

import json
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

        if not sources:
            self._update_reputation(success=False, quality_score=0.0)
            return self._error_result("No curated sources available for synthesis.")

        prompt = f"""
Create a source-grounded draft answer.

User query: {query_plan.get('query') or context.get('original_description') or request}
Research question: {query_plan.get('research_question')}
Classified mode: {context.get('classified_mode')}
Depth mode: {context.get('depth_mode')}
Freshness required: {context.get('freshness_required')}
As-of date: {datetime.now(UTC).date().isoformat()}

Subquestions:
{json.dumps(query_plan.get('subquestions') or [], indent=2)}

Source summary:
{json.dumps(curated_sources.get('source_summary') or {}, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

Sources:
{self._format_sources_for_prompt(sources)}

Return JSON with this shape:
{{
  "answer": "<direct answer that cites the evidence and uses absolute dates when relevant>",
  "claims": [
    {{
      "claim": "<specific claim>",
      "supporting_citations": ["<source title>", "<source title>"],
      "confidence": "<high|medium|low>"
    }}
  ],
  "limitations": ["<important caveat>"]
}}

Rules:
- Do not invent events or outcomes that are not reflected in the sources.
- If the topic is live/current, state the answer as of the date above.
- Keep claims tied to sources.
"""

        parsed = await self._run_role_prompt(
            system_prompt=(
                "You are a rigorous synthesis drafter. Produce a source-grounded draft answer in JSON."
            ),
            prompt=prompt,
        )
        draft_result = self._normalize_answer_payload(parsed, fallback_query=str(query_plan.get("query") or request))
        draft_result["citations"] = citations
        draft_result["sources"] = sources
        draft_result["source_summary"] = curated_sources.get("source_summary") or {}
        draft_result["freshness_summary"] = curated_sources.get("freshness_summary") or {}
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
        critique_rounds = int((context.get("rounds_planned") or {}).get("critique_rounds", 1) or 1)

        deterministic_findings = self._deterministic_findings(
            draft=draft,
            freshness_summary=curated_sources.get("freshness_summary") or {},
            scenario_requested=bool(context.get("scenario_analysis_requested")),
        )

        llm_findings: List[Dict[str, Any]] = []
        for round_number in range(1, critique_rounds + 1):
            prompt = f"""
Review this draft answer for unsupported claims, missing caveats, stale evidence, or overstatement.

Research question: {query_plan.get('research_question')}
Draft answer:
{json.dumps(draft, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

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

        if not draft:
            self._update_reputation(success=False, quality_score=0.0)
            return self._error_result("Missing draft synthesis for final revision.")

        prompt = f"""
Revise the answer using the critic findings while staying strictly grounded in the sources.

User query: {query_plan.get('query') or context.get('original_description')}
Research question: {query_plan.get('research_question')}
As-of date: {datetime.now(UTC).date().isoformat()}

Draft:
{json.dumps(draft, indent=2)}

Critic findings:
{json.dumps(critic_review.get('critic_findings') or [], indent=2)}

Source summary:
{json.dumps(curated_sources.get('source_summary') or {}, indent=2)}

Freshness summary:
{json.dumps(curated_sources.get('freshness_summary') or {}, indent=2)}

Sources:
{self._format_sources_for_prompt(sources)}

Return JSON:
{{
  "answer": "<final revised answer>",
  "claims": [
    {{
      "claim": "<specific claim>",
      "supporting_citations": ["<source title>"],
      "confidence": "<high|medium|low>"
    }}
  ],
  "limitations": ["<remaining caveat>"]
}}

Rules:
- Use absolute dates for current events.
- Preserve uncertainty instead of speculating.
- Do not claim evidence beyond what is in the sources.
"""

        parsed = await self._run_role_prompt(
            system_prompt=(
                "You are a careful revising editor. Incorporate critic findings and produce a final source-grounded answer in JSON."
            ),
            prompt=prompt,
        )
        revised = self._normalize_answer_payload(parsed, fallback_query=str(query_plan.get("query") or "research query"))
        revised["citations"] = citations
        revised["sources"] = sources
        revised["source_summary"] = curated_sources.get("source_summary") or {}
        revised["freshness_summary"] = curated_sources.get("freshness_summary") or {}
        revised["critic_findings"] = critic_review.get("critic_findings") or []
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
                        f"Publisher: {source.get('publisher')}",
                        f"Published: {source.get('published_at')}",
                        f"Type: {source.get('source_type')}",
                        f"URL: {source.get('url')}",
                        f"Snippet: {source.get('snippet')}",
                    ]
                )
            )
        return "\n\n".join(formatted)

    def _normalize_answer_payload(self, payload: Dict[str, Any], *, fallback_query: str) -> Dict[str, Any]:
        claims = []
        for item in payload.get("claims") or []:
            if isinstance(item, dict) and item.get("claim"):
                claims.append(
                    {
                        "claim": str(item.get("claim")),
                        "supporting_citations": list(item.get("supporting_citations") or []),
                        "confidence": str(item.get("confidence") or "medium"),
                    }
                )
        limitations = [
            str(item)
            for item in (payload.get("limitations") or [])
            if isinstance(item, (str, int, float))
        ]
        answer = str(payload.get("answer") or "").strip()
        if not answer:
            answer = f"Insufficient model output to complete a final synthesis for: {fallback_query}"
        return {
            "answer": answer,
            "claims": claims,
            "limitations": limitations,
        }

    def _deterministic_findings(
        self,
        *,
        draft: Dict[str, Any],
        freshness_summary: Dict[str, Any],
        scenario_requested: bool,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        answer = str(draft.get("answer") or "").lower()
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
        return findings

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
