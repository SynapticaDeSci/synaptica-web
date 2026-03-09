"""
Compliance Checker Agent

Checks research compliance with ethical guidelines, regulations, and standards
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class ComplianceCheckerAgent(BaseResearchAgent):
    """Agent for compliance checker."""

    def __init__(self):
        super().__init__(
            agent_id="compliance-checker-001",
            name="Compliance Checker",
            description="Checks research compliance with ethical guidelines, regulations, and standards",
            capabilities=['compliance-checking', 'ethics-review', 'regulatory-validation', 'standards-verification', 'documentation-review'],
            pricing={
                "model": "pay-per-use",
                "rate": "0.09 HBAR",
                "unit": "per_task"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are a Compliance Checker AI agent that ensures research compliance.

Your role is to verify research adheres to ethical guidelines, regulatory requirements, and academic standards.

Return JSON with: compliance_status, violations, warnings, ethical_concerns, regulatory_issues, recommendations, approval_status"""

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
compliance_checker_001_agent = ComplianceCheckerAgent()
