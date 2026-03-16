#!/usr/bin/env python
"""
Legacy scaffolding script for the old research specialist roster.

This created stub implementations for the quarantined specialist agents in the
original demo pipeline. It is retained only as historical scaffolding.
"""

import os

# Agent definitions based on agent-plan.pdf
AGENTS = {
    # Phase 3: Experimentation
    "hypothesis_designer": {
        "path": "agents/research/phase3_experimentation/hypothesis_designer",
        "class_name": "HypothesisDesignerAgent",
        "agent_id": "hypothesis-designer-001",
        "name": "Hypothesis Designer",
        "description": "Designs testable hypotheses and experiment protocols based on literature synthesis",
        "capabilities": ["hypothesis-design", "experiment-protocol", "variable-identification", "control-design", "metrics-definition"],
        "rate": "0.12",
        "system_prompt": """You are a Hypothesis Designer AI agent that creates testable hypotheses and experiment designs.

Your role is to transform research questions and literature insights into concrete, testable hypotheses with detailed experiment protocols.

Return JSON with: hypothesis, null_hypothesis, independent_variables, dependent_variables, controlled_variables, experiment_design, success_metrics, sample_size, statistical_tests"""
    },
    "experiment_runner": {
        "path": "agents/research/phase3_experimentation/experiment_runner",
        "class_name": "ExperimentRunnerAgent",
        "agent_id": "experiment-runner-001",
        "name": "Experiment Runner",
        "description": "Executes experiments, simulations, and data analysis based on experiment protocols",
        "capabilities": ["experiment-execution", "simulation", "data-collection", "monitoring", "error-handling"],
        "rate": "0.20",
        "system_prompt": """You are an Experiment Runner AI agent that executes research experiments and simulations.

Your role is to run experiments according to protocols, collect data, monitor execution, and handle errors.

Return JSON with: execution_id, results, metrics, raw_data, execution_time, status, errors, logs"""
    },
    "code_generator": {
        "path": "agents/research/phase3_experimentation/code_generator",
        "class_name": "CodeGeneratorAgent",
        "agent_id": "code-generator-001",
        "name": "Code Generator",
        "description": "Generates experimental code, analysis scripts, and visualization code",
        "capabilities": ["code-generation", "script-writing", "data-processing", "visualization", "testing"],
        "rate": "0.15",
        "system_prompt": """You are a Code Generator AI agent that creates experimental and analysis code.

Your role is to generate Python code for experiments, data processing, analysis, and visualization.

Return JSON with: code, language, description, dependencies, usage_instructions, test_cases"""
    },
    # Phase 4: Interpretation
    "insight_generator": {
        "path": "agents/research/phase4_interpretation/insight_generator",
        "class_name": "InsightGeneratorAgent",
        "agent_id": "insight-generator-001",
        "name": "Insight Generator",
        "description": "Generates insights and interpretations from experimental results",
        "capabilities": ["insight-extraction", "pattern-analysis", "causal-inference", "implication-analysis", "conclusion-generation"],
        "rate": "0.14",
        "system_prompt": """You are an Insight Generator AI agent that extracts meaningful insights from research results.

Your role is to analyze experimental data and generate insights, identify patterns, draw conclusions, and discuss implications.

Return JSON with: insights, patterns, causal_relationships, implications, limitations, confidence_scores"""
    },
    "bias_detector": {
        "path": "agents/research/phase4_interpretation/bias_detector",
        "class_name": "BiasDetectorAgent",
        "agent_id": "bias-detector-001",
        "name": "Bias Detector",
        "description": "Detects potential biases in research methodology, data, and interpretations",
        "capabilities": ["bias-detection", "fairness-analysis", "validity-checking", "confounding-identification", "mitigation-recommendation"],
        "rate": "0.11",
        "system_prompt": """You are a Bias Detector AI agent that identifies potential biases in research.

Your role is to detect selection bias, confirmation bias, data bias, and methodological biases in research.

Return JSON with: biases_detected, bias_types, severity, impact_assessment, mitigation_strategies, overall_bias_score"""
    },
    "compliance_checker": {
        "path": "agents/research/phase4_interpretation/compliance_checker",
        "class_name": "ComplianceCheckerAgent",
        "agent_id": "compliance-checker-001",
        "name": "Compliance Checker",
        "description": "Checks research compliance with ethical guidelines, regulations, and standards",
        "capabilities": ["compliance-checking", "ethics-review", "regulatory-validation", "standards-verification", "documentation-review"],
        "rate": "0.09",
        "system_prompt": """You are a Compliance Checker AI agent that ensures research compliance.

Your role is to verify research adheres to ethical guidelines, regulatory requirements, and academic standards.

Return JSON with: compliance_status, violations, warnings, ethical_concerns, regulatory_issues, recommendations, approval_status"""
    },
    # Phase 5: Publication
    "paper_writer": {
        "path": "agents/research/phase5_publication/paper_writer",
        "class_name": "PaperWriterAgent",
        "agent_id": "paper-writer-001",
        "name": "Research Paper Writer",
        "description": "Writes research papers in academic format with proper structure and citations",
        "capabilities": ["paper-writing", "academic-formatting", "citation-management", "figure-generation", "abstract-writing"],
        "rate": "0.25",
        "system_prompt": """You are a Research Paper Writer AI agent that creates academic papers.

Your role is to write well-structured research papers with introduction, methods, results, discussion, and conclusion sections.

Return JSON with: title, abstract, sections, citations, figures, tables, word_count, formatting_style"""
    },
    "peer_reviewer": {
        "path": "agents/research/phase5_publication/peer_reviewer",
        "class_name": "PeerReviewerAgent",
        "agent_id": "peer-reviewer-001",
        "name": "Peer Reviewer",
        "description": "Provides peer review feedback on research papers evaluating quality, rigor, and contribution",
        "capabilities": ["peer-review", "quality-assessment", "rigor-evaluation", "contribution-analysis", "feedback-generation"],
        "rate": "0.18",
        "system_prompt": """You are a Peer Reviewer AI agent that evaluates research papers.

Your role is to provide constructive peer review feedback on novelty, rigor, clarity, and contribution.

Return JSON with: overall_score, novelty_score, rigor_score, clarity_score, strengths, weaknesses, questions, recommendation"""
    },
    "reputation_manager": {
        "path": "agents/research/phase5_publication/reputation_manager",
        "class_name": "ReputationManagerAgent",
        "agent_id": "reputation-manager-001",
        "name": "Reputation Manager",
        "description": "Updates agent reputations based on research quality and contribution",
        "capabilities": ["reputation-scoring", "contribution-tracking", "performance-evaluation", "quality-metrics", "reputation-updates"],
        "rate": "0.05",
        "system_prompt": """You are a Reputation Manager AI agent that maintains agent reputation scores.

Your role is to evaluate agent contributions and update reputation scores based on quality, accuracy, and impact.

Return JSON with: reputation_updates, agent_scores, contribution_analysis, quality_metrics, performance_ratings"""
    },
    "archiver": {
        "path": "agents/research/phase5_publication/archiver",
        "class_name": "ArchiverAgent",
        "agent_id": "archiver-001",
        "name": "Research Archiver",
        "description": "Archives research artifacts to IPFS and blockchain for permanent, verifiable storage",
        "capabilities": ["ipfs-upload", "blockchain-recording", "metadata-generation", "versioning", "retrieval"],
        "rate": "0.07",
        "system_prompt": """You are a Research Archiver AI agent that stores research artifacts permanently.

Your role is to archive papers, data, and artifacts to IPFS and record metadata on blockchain for verifiability.

Return JSON with: ipfs_hashes, blockchain_tx_hashes, metadata, archive_locations, verification_proofs, retrieval_instructions"""
    },
}


def create_agent_files(agent_info):
    """Create __init__.py and agent.py for an agent."""
    path = agent_info['path']
    class_name = agent_info['class_name']
    agent_id = agent_info['agent_id']
    name = agent_info['name']
    description = agent_info['description']
    capabilities = agent_info['capabilities']
    rate = agent_info['rate']
    system_prompt = agent_info['system_prompt']

    # Create __init__.py
    init_content = f'''"""{name} agent for research pipeline."""
'''

    init_path = os.path.join(path, '__init__.py')
    with open(init_path, 'w') as f:
        f.write(init_content)

    # Create agent.py
    agent_content = f'''"""
{name} Agent

{description}
"""

import json
from typing import Dict, Any, List
from agents.research.base_research_agent import BaseResearchAgent


class {class_name}(BaseResearchAgent):
    """Agent for {name.lower()}."""

    def __init__(self):
        super().__init__(
            agent_id="{agent_id}",
            name="{name}",
            description="{description}",
            capabilities={capabilities},
            pricing={{
                "model": "pay-per-use",
                "rate": "{rate} HBAR",
                "unit": "per_task"
            }},
            model="gpt-5.4"
        )

    def get_system_prompt(self) -> str:
        return """{system_prompt}"""

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

        Input: {{json.dumps(task_input, indent=2)}}

        Context: {{json.dumps(context or {{}}, indent=2)}}

        Provide a comprehensive response in JSON format as specified in your system prompt.
        """

        # Execute agent
        result = await self.execute(request)

        if not result['success']:
            return {{
                'success': False,
                'error': result.get('error', 'Task execution failed')
            }}

        try:
            # Parse the agent's response
            agent_output = result['result']

            if isinstance(agent_output, str):
                # Extract JSON from response
                json_start = agent_output.find('{{')
                json_end = agent_output.rfind('}}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = agent_output[json_start:json_end]
                    task_data = json.loads(json_str)
                else:
                    return {{
                        'success': False,
                        'error': 'Failed to parse task output as JSON'
                    }}
            else:
                task_data = agent_output

            # Calculate payment
            payment_due = float(self.pricing['rate'].replace(' HBAR', ''))
            payment_multiplier = self.get_payment_rate() / payment_due

            return {{
                'success': True,
                'result': task_data,
                'metadata': {{
                    'agent_id': self.agent_id,
                    'payment_due': payment_due * payment_multiplier,
                    'currency': 'HBAR'
                }}
            }}

        except Exception as e:
            return {{
                'success': False,
                'error': f'Failed to process task output: {{str(e)}}'
            }}


# Create global instance
{agent_id.replace('-', '_')}_agent = {class_name}()
'''

    agent_path = os.path.join(path, 'agent.py')
    with open(agent_path, 'w') as f:
        f.write(agent_content)

    print(f"✅ Created {name} ({agent_id})")


def main():
    """Generate all remaining agents."""
    print("Generating remaining research agents...\n")

    for agent_key, agent_info in AGENTS.items():
        create_agent_files(agent_info)

    print(f"\n✅ Successfully generated {len(AGENTS)} agents!")
    print("\nAgents created:")
    for agent_key, agent_info in AGENTS.items():
        print(f"  - {agent_info['name']} ({agent_info['agent_id']})")


if __name__ == "__main__":
    main()
