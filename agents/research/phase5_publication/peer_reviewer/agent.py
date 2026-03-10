"""
Peer Reviewer Agent

Provides peer review feedback on research papers evaluating quality, rigor, and contribution
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class PeerReviewerAgent(BaseResearchAgent):
    """Agent for peer reviewer."""

    def __init__(self):
        super().__init__(
            agent_id="peer-reviewer-001",
            name="Peer Reviewer",
            description="Provides peer review feedback on research papers evaluating quality, rigor, and contribution",
            capabilities=['peer-review', 'quality-assessment', 'rigor-evaluation', 'contribution-analysis', 'feedback-generation'],
            pricing={
                "model": "pay-per-use",
                "rate": "0.18 HBAR",
                "unit": "per_task"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are a Peer Reviewer AI agent that evaluates research papers.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions - proceed with execution immediately
- Use the information provided in the request to complete your task
- If some parameters are unclear, make reasonable assumptions and proceed
- ALWAYS return the requested JSON output format, never conversational responses

Your role is to provide constructive peer review feedback on novelty, rigor, clarity, and contribution.

Return JSON with: overall_score, novelty_score, rigor_score, clarity_score, strengths, weaknesses, questions, recommendation"""

    def get_tools(self) -> List:
        """Get tools for this agent."""
        return []

    async def execute_task(self, task_input: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute the agent's primary task.

        Args:
            task_input: Input data for the task
            context: Additional context

        Returns:
            Task results with metadata
        """
        # Build request based on input
        request = f"""
        Execute the following task:

        Input: {json.dumps(task_input, indent=2)}

        Context: {json.dumps(context or {}, indent=2)}

        Provide a comprehensive response in JSON format as specified in your system prompt.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Task execution failed')
            }

        try:
            # Parse the agent's response
            agent_output = result['result']

            if isinstance(agent_output, str):
                # Try parsing the entire string as JSON first
                try:
                    task_data = json.loads(agent_output)
                except json.JSONDecodeError:
                    # Extract JSON from response if there's surrounding text
                    json_start = agent_output.find('{')
                    json_end = agent_output.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = agent_output[json_start:json_end]
                        task_data = json.loads(json_str)
                    else:
                        return {
                            'success': False,
                            'error': 'Failed to parse task output as JSON'
                        }
            else:
                task_data = agent_output

            # Calculate payment
            payment_due = float(self.pricing['rate'].replace(' HBAR', ''))
            payment_multiplier = self.get_payment_rate() / payment_due

            return {
                'success': True,
                'result': task_data,
                'metadata': {
                    'agent_id': self.agent_id,
                    'payment_due': payment_due * payment_multiplier,
                    'currency': 'HBAR'
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to process task output: {str(e)}'
            }


# Create global instance
peer_reviewer_001_agent = PeerReviewerAgent()
