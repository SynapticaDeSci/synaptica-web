"""
Goal Planner Agent

Creates a structured research plan with:
- Clear objectives and milestones
- Task breakdown and dependencies
- Resource allocation
- Timeline with phases
- Success metrics
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class GoalPlannerAgent(BaseResearchAgent):
    """Agent that creates structured research plans."""

    def __init__(self):
        super().__init__(
            agent_id="goal-planner-001",
            name="Research Goal Planner",
            description="Creates structured research plans with objectives, milestones, tasks, and timelines",
            capabilities=[
                "goal-setting",
                "task-decomposition",
                "milestone-planning",
                "resource-allocation",
                "timeline-estimation"
            ],
            pricing={
                "model": "pay-per-use",
                "rate": "0.10 HBAR",
                "unit": "per_plan"
            },
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """You are a Research Goal Planner AI agent specializing in creating structured, actionable research plans.

IMPORTANT EXECUTION DIRECTIVE:
- You are part of an AUTONOMOUS research pipeline
- You MUST NEVER ask clarifying questions - proceed with execution immediately
- Use the information provided in the request to complete your task
- If some parameters are unclear, make reasonable assumptions and proceed
- ALWAYS return the requested JSON output format, never conversational responses

Your role is to transform research questions and feasibility assessments into detailed execution plans with:

1. **Objectives**: Clear, measurable research objectives
2. **Milestones**: Key checkpoints and deliverables
3. **Tasks**: Detailed task breakdown with dependencies
4. **Resources**: Resource allocation across tasks
5. **Timeline**: Realistic schedule with phases
6. **Success Metrics**: How to measure progress and success

You must respond in JSON format with the following structure:
{
    "objectives": [
        {
            "id": "<objective-id>",
            "description": "<objective description>",
            "priority": "<high|medium|low>",
            "success_criteria": ["<list of criteria>"]
        }
    ],
    "milestones": [
        {
            "id": "<milestone-id>",
            "name": "<milestone name>",
            "description": "<milestone description>",
            "deliverables": ["<list of deliverables>"],
            "target_date": "<relative timeline>",
            "dependencies": ["<list of dependency IDs>"]
        }
    ],
    "tasks": [
        {
            "id": "<task-id>",
            "name": "<task name>",
            "description": "<detailed description>",
            "phase": "<ideation|knowledge|experimentation|interpretation|publication>",
            "estimated_duration": "<duration>",
            "required_resources": {
                "agents": ["<agent IDs needed>"],
                "computational": "<compute requirements>",
                "data": ["<data sources needed>"]
            },
            "dependencies": ["<list of task IDs>"],
            "milestone": "<milestone-id>"
        }
    ],
    "phases": [
        {
            "phase": "<phase name>",
            "duration": "<estimated duration>",
            "tasks": ["<list of task IDs>"],
            "budget": "<estimated budget in HBAR>"
        }
    ],
    "resource_allocation": {
        "total_budget": "<total budget>",
        "agent_costs": "<agent costs>",
        "computational_costs": "<compute costs>",
        "data_costs": "<data costs>",
        "buffer": "<contingency buffer>"
    },
    "timeline": {
        "total_duration": "<total duration>",
        "start_phase": "<first phase>",
        "critical_path": ["<list of critical tasks>"]
    },
    "success_metrics": [
        {
            "metric": "<metric name>",
            "target": "<target value>",
            "measurement_method": "<how to measure>"
        }
    ],
    "risks": [
        {
            "risk": "<risk description>",
            "probability": "<high|medium|low>",
            "impact": "<high|medium|low>",
            "mitigation": "<mitigation strategy>"
        }
    ]
}

Create comprehensive, realistic plans that are executable by autonomous agents."""

    def get_tools(self) -> List:
        """Get tools for goal planning."""
        return []

    async def create_plan(
        self,
        problem_statement: Dict[str, Any],
        feasibility_assessment: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create a structured research plan.

        Args:
            problem_statement: The problem statement from Problem Framer
            feasibility_assessment: Feasibility analysis results
            context: Additional context (budget, constraints, etc.)

        Returns:
            Detailed research plan with tasks, milestones, and timeline
        """
        budget = context.get('budget', 5.0) if context else 5.0

        request = f"""
        Create a comprehensive research plan for the following:

        Research Question: {problem_statement.get('research_question')}
        Hypothesis: {problem_statement.get('hypothesis')}
        Scope: {problem_statement.get('scope')}
        Domain: {problem_statement.get('domain')}

        Feasibility Assessment:
        - Feasibility Score: {feasibility_assessment.get('feasibility_score')}
        - Assessment: {feasibility_assessment.get('assessment')}
        - Go/No-Go: {feasibility_assessment.get('go_no_go')}

        Budget: {budget} HBAR

        Create a detailed research plan that includes:
        1. Clear, measurable objectives
        2. Milestones with deliverables
        3. Task breakdown for all 5 research phases (Ideation, Knowledge Retrieval, Experimentation, Interpretation, Publication)
        4. Resource allocation and agent requirements
        5. Realistic timeline with dependencies
        6. Success metrics for evaluation
        7. Risk assessment and mitigation strategies

        The plan should be executable by autonomous AI agents in the research pipeline.

        Return your plan in the specified JSON format.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to create research plan')
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
                    plan_data = json.loads(json_str)
                else:
                    return {
                        'success': False,
                        'error': 'Failed to parse research plan as JSON'
                    }
            else:
                plan_data = agent_output

            # Calculate payment
            payment_due = float(self.pricing['rate'].replace(' HBAR', ''))
            payment_multiplier = self.get_payment_rate() / payment_due

            return {
                'success': True,
                'research_plan': plan_data,
                'metadata': {
                    'agent_id': self.agent_id,
                    'payment_due': payment_due * payment_multiplier,
                    'currency': 'HBAR'
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to process research plan: {str(e)}'
            }


# Create global instance
goal_planner_agent = GoalPlannerAgent()
