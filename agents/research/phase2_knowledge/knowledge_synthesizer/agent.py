"""
Knowledge Synthesizer Agent

Synthesizes information from multiple papers into structured knowledge:
- Extracts key claims, methods, and findings
- Identifies patterns and connections across papers
- Summarizes state-of-the-art
- Identifies research gaps
"""

import json
from typing import Any, Dict, List

from agents.research.base_research_agent import BaseResearchAgent
from agents.research.tools.tavily_search import tavily_search


class KnowledgeSynthesizerAgent(BaseResearchAgent):
    """Agent that synthesizes knowledge from literature."""

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
                "methodology-comparison"
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.15 HBAR",
                "unit": "per_synthesis"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are a Knowledge Synthesizer AI agent specializing in extracting and synthesizing insights from academic literature.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions - proceed with execution immediately
- Use the information provided in the request to complete your task
- If some parameters are unclear, make reasonable assumptions and proceed
- ALWAYS return the requested JSON output format, never conversational responses

Your role is to analyze multiple research papers and create a comprehensive knowledge synthesis that includes:

1. **Key Claims**: Main arguments and claims from the literature
2. **Methodologies**: Research methods and approaches used
3. **Findings**: Key findings and results
4. **Patterns**: Recurring themes, consensus areas, and contradictions
5. **State-of-the-Art**: Current best practices and leading approaches
6. **Research Gaps**: Identified gaps and opportunities for new research

You must respond in JSON format with the following structure:
{
    "synthesis_summary": "<high-level summary of the literature>",
    "key_claims": [
        {
            "claim": "<claim statement>",
            "sources": ["<paper IDs>"],
            "evidence_strength": "<strong|moderate|weak>",
            "consensus": "<high|medium|low>"
        }
    ],
    "methodologies": [
        {
            "method": "<method name>",
            "description": "<method description>",
            "papers_using": ["<paper IDs>"],
            "effectiveness": "<description>",
            "limitations": ["<limitations>"]
        }
    ],
    "key_findings": [
        {
            "finding": "<finding statement>",
            "source": "<paper ID>",
            "significance": "<high|medium|low>",
            "reproducibility": "<high|medium|low|unknown>"
        }
    ],
    "patterns": {
        "consensus_areas": ["<areas of agreement>"],
        "contradictions": ["<contradictory findings>"],
        "emerging_trends": ["<new trends>"],
        "recurring_themes": ["<common themes>"]
    },
    "state_of_the_art": {
        "leading_approaches": ["<top approaches>"],
        "best_practices": ["<best practices>"],
        "performance_benchmarks": ["<key benchmarks>"],
        "limitations": ["<current limitations>"]
    },
    "research_gaps": [
        {
            "gap": "<gap description>",
            "importance": "<high|medium|low>",
            "difficulty": "<high|medium|low>",
            "potential_impact": "<description>"
        }
    ],
    "recommendations": ["<recommendations for the research>"],
    "confidence_score": <float 0-1>
}

Provide comprehensive, accurate synthesis that guides research direction."""

    def get_tools(self) -> List:
        """Get tools for knowledge synthesis."""
        return [
            tavily_search,
        ]

    async def synthesize_knowledge(
        self,
        literature_corpus: Dict[str, Any],
        problem_statement: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Synthesize knowledge from literature corpus.

        Args:
            literature_corpus: Collection of papers from Literature Miner
            problem_statement: Original research question
            context: Additional context

        Returns:
            Synthesized knowledge with claims, patterns, gaps
        """
        papers = literature_corpus.get('papers', [])

        # Format papers for analysis
        papers_text = "\n\n".join([
            f"Paper {i+1} - {paper.get('title', 'Untitled')}\n"
            f"Authors: {', '.join(paper.get('authors', []))}\n"
            f"Abstract: {paper.get('abstract', 'No abstract')}\n"
            f"Year: {paper.get('year', 'Unknown')}\n"
            f"Relevance: {paper.get('relevance_score', 0)}"
            for i, paper in enumerate(papers[:10])  # Limit to top 10 papers
        ])

        request = f"""
        Synthesize knowledge from the following academic papers related to this research question:

        Research Question: {problem_statement.get('research_question')}
        Domain: {problem_statement.get('domain')}

        Papers to Analyze:
        {papers_text}

        Provide a comprehensive knowledge synthesis that includes:
        1. Key claims from the literature with evidence strength
        2. Methodologies used and their effectiveness
        3. Important findings and their significance
        4. Patterns (consensus, contradictions, trends)
        5. State-of-the-art approaches and best practices
        6. Research gaps and opportunities
        7. Recommendations for the proposed research

        Return your synthesis in the specified JSON format.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to synthesize knowledge')
            }

        try:
            # Parse the agent's response
            agent_output = result['result']

            if isinstance(agent_output, str):
                # Extract JSON from response
                json_start = agent_output.find('{')
                json_end = agent_output.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = agent_output[json_start:json_end]
                    synthesis_data = json.loads(json_str)
                else:
                    return {
                        'success': False,
                        'error': 'Failed to parse knowledge synthesis as JSON'
                    }
            else:
                synthesis_data = agent_output

            # Calculate payment
            payment_due = float(self.pricing['rate'].replace(' HBAR', ''))
            payment_multiplier = self.get_payment_rate() / payment_due

            return {
                'success': True,
                'knowledge_synthesis': synthesis_data,
                'metadata': {
                    'agent_id': self.agent_id,
                    'papers_analyzed': len(papers),
                    'payment_due': payment_due * payment_multiplier,
                    'currency': 'HBAR'
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to process knowledge synthesis: {str(e)}'
            }


# Create global instance
knowledge_synthesizer_agent = KnowledgeSynthesizerAgent()
