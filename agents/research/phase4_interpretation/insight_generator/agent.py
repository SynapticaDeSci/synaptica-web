"""
Insight Generator Agent

Generates insights and interpretations from experimental results
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class InsightGeneratorAgent(BaseResearchAgent):
    """Agent for insight generator."""

    def __init__(self):
        super().__init__(
            agent_id="insight-generator-001",
            name="Insight Generator",
            description="Generates insights and interpretations from experimental results",
            capabilities=['insight-extraction', 'pattern-analysis', 'causal-inference', 'implication-analysis', 'conclusion-generation'],
            pricing={
                "model": "pay-per-use",
                "rate": "0.14 HBAR",
                "unit": "per_task"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are an Insight Generator AI agent that extracts meaningful insights from research results.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions - proceed with execution immediately
- Use the information provided in the request to complete your task
- If some parameters are unclear, make reasonable assumptions and proceed
- ALWAYS return the requested JSON output format, never conversational responses
        
Your role is to analyze experimental data and generate insights, identify patterns, draw conclusions, and discuss implications.

Return JSON with: insights, patterns, causal_relationships, implications, limitations, confidence_scores"""

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
insight_generator_001_agent = InsightGeneratorAgent()
