"""
Feasibility Analyst Agent

Evaluates the feasibility of research questions by analyzing:
- Available data sources
- Required resources (computational, data, human)
- Technical complexity
- Regulatory/ethical constraints
- Time and budget requirements
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class FeasibilityAnalystAgent(BaseResearchAgent):
    """Agent that evaluates research feasibility."""

    def __init__(self):
        super().__init__(
            agent_id="feasibility-analyst-001",
            name="Research Feasibility Analyst",
            description="Evaluates research question feasibility considering resources, data, complexity, and constraints",
            capabilities=[
                "feasibility-analysis",
                "resource-estimation",
                "constraint-identification",
                "risk-assessment",
                "timeline-estimation"
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.08 HBAR",
                "unit": "per_analysis"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are a Research Feasibility Analyst AI agent specializing in evaluating the viability of research questions.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions - proceed with execution immediately
- Use the information provided in the request to complete your task
- If some parameters are unclear, make reasonable assumptions and proceed
- ALWAYS return the requested JSON output format, never conversational responses

Your role is to analyze research proposals and assess their feasibility across multiple dimensions:

1. **Data Availability**: Are the required data sources accessible? Are there quality issues?
2. **Resource Requirements**: What computational power, datasets, tools, and human expertise are needed?
3. **Technical Complexity**: How difficult is the implementation? What are the technical risks?
4. **Regulatory/Ethical Constraints**: Are there legal, ethical, or compliance issues?
5. **Timeline & Budget**: What is a realistic timeline and cost estimate?

You must respond in JSON format with the following structure:
{
    "feasibility_score": <float 0-1>,
    "assessment": "<feasible|challenging|infeasible>",
    "data_availability": {
        "score": <float 0-1>,
        "sources": ["<list of available data sources>"],
        "gaps": ["<list of data gaps>"],
        "quality_concerns": ["<list of quality issues>"]
    },
    "resource_requirements": {
        "computational": "<description of compute needs>",
        "data_storage": "<storage requirements>",
        "human_expertise": ["<required skills>"],
        "estimated_cost": "<cost estimate in HBAR or USD>"
    },
    "technical_complexity": {
        "score": <float 0-1>,
        "challenges": ["<list of technical challenges>"],
        "risks": ["<list of technical risks>"],
        "mitigation_strategies": ["<strategies to address risks>"]
    },
    "constraints": {
        "regulatory": ["<list of regulatory constraints>"],
        "ethical": ["<list of ethical considerations>"],
        "legal": ["<list of legal constraints>"]
    },
    "timeline": {
        "estimated_duration": "<duration estimate>",
        "phases": ["<list of major phases>"],
        "critical_path": ["<critical dependencies>"]
    },
    "recommendations": ["<list of recommendations>"],
    "go_no_go": "<go|conditional|no-go>"
}

Be thorough, realistic, and identify potential blockers early."""

    def get_tools(self) -> List:
        """Get tools for feasibility analysis."""
        return []

    async def analyze_feasibility(
        self,
        problem_statement: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Analyze the feasibility of a research question.

        Args:
            problem_statement: The problem statement from Problem Framer
            context: Additional context (budget, timeline constraints, etc.)

        Returns:
            Feasibility assessment with scoring and recommendations
        """
        budget = context.get('budget', 'not specified') if context else 'not specified'
        timeline = context.get('timeline', 'not specified') if context else 'not specified'

        request = f"""
        Analyze the feasibility of the following research question:

        Research Question: {problem_statement.get('research_question')}
        Hypothesis: {problem_statement.get('hypothesis')}
        Scope: {problem_statement.get('scope')}
        Keywords: {', '.join(problem_statement.get('keywords', []))}
        Domain: {problem_statement.get('domain')}

        Context:
        - Available Budget: {budget}
        - Target Timeline: {timeline}

        Provide a comprehensive feasibility analysis covering:
        1. Data availability and quality
        2. Resource requirements (computational, data, expertise)
        3. Technical complexity and risks
        4. Regulatory, ethical, and legal constraints
        5. Realistic timeline and cost estimates
        6. Go/No-Go recommendation with justification

        Return your analysis in the specified JSON format.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to analyze feasibility')
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
                    feasibility_data = json.loads(json_str)
                else:
                    return {
                        'success': False,
                        'error': 'Failed to parse feasibility analysis as JSON'
                    }
            else:
                feasibility_data = agent_output

            # Calculate payment
            payment_due = float(self.pricing['rate'].replace(' HBAR', ''))
            payment_multiplier = self.get_payment_rate() / payment_due

            return {
                'success': True,
                'feasibility_assessment': feasibility_data,
                'metadata': {
                    'agent_id': self.agent_id,
                    'payment_due': payment_due * payment_multiplier,
                    'currency': 'HBAR'
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to process feasibility analysis: {str(e)}'
            }


# Create global instance
feasibility_analyst_agent = FeasibilityAnalystAgent()
