"""Legacy demo research pipeline orchestration.

This class is retained as a reference for the original hackathon prototype.
It is not part of the active phase 0 runtime, which now runs through
``POST /execute`` in ``api.main``.
"""

import uuid
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from shared.database import (
    SessionLocal,
    ResearchPipeline as ResearchPipelineModel,
    ResearchPhase,
    ResearchArtifact,
    ResearchPhaseStatus,
    ResearchPhaseType,
)
from shared.research.validators import validate_phase_transition

# Import research agents (we'll import more as we implement them)
from agents.research.phase1_ideation.problem_framer.agent import problem_framer_agent
from agents.research.phase2_knowledge.literature_miner.agent import literature_miner_agent


class ResearchPipeline:
    """
    Orchestrates the complete research pipeline.

    This class coordinates all research agents across 5 phases:
    1. Ideation: Problem framing, feasibility, planning
    2. Knowledge Retrieval: Literature search, ranking, extraction
    3. Experimentation: Hypothesis design, simulation, verification
    4. Interpretation: Result synthesis, bias audit, compliance
    5. Publication: Paper generation, peer review, reputation
    """

    def __init__(self, pipeline_id: Optional[str] = None):
        """
        Initialize research pipeline.

        Args:
            pipeline_id: Optional existing pipeline ID to resume
        """
        self.pipeline_id = pipeline_id or str(uuid.uuid4())
        self.db = SessionLocal()
        self.pipeline = None
        self.current_phase = None
        self.phase_outputs = {}
        self.total_cost = 0.0

        # Agent registry (add more as implemented)
        self.agents = {
            'problem_framer': problem_framer_agent,
            'literature_miner': literature_miner_agent,
            # TODO: Add more agents as implemented
        }

        # Load existing pipeline if ID provided
        if pipeline_id:
            self._load_pipeline()

    def _load_pipeline(self):
        """Load existing pipeline from database."""
        self.pipeline = self.db.query(ResearchPipelineModel).filter(
            ResearchPipelineModel.id == self.pipeline_id
        ).first()

        if self.pipeline:
            # Load phase outputs
            phases = self.db.query(ResearchPhase).filter(
                ResearchPhase.pipeline_id == self.pipeline_id
            ).all()

            for phase in phases:
                if phase.outputs:
                    self.phase_outputs[phase.phase_type.value] = phase.outputs

            self.total_cost = self.pipeline.spent

    async def start_pipeline(
        self,
        query: str,
        budget: float = 5.0,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Start a new research pipeline.

        Args:
            query: Research query from user
            budget: Total budget in HBAR
            context: Optional context

        Returns:
            Pipeline initialization status
        """
        try:
            # Create pipeline record
            self.pipeline = ResearchPipelineModel(
                id=self.pipeline_id,
                query=query,
                research_topic="To be determined",
                budget=budget,
                spent=0.0,
                status=ResearchPhaseStatus.IN_PROGRESS,
                current_phase=ResearchPhaseType.IDEATION,
                meta=context or {}
            )
            self.db.add(self.pipeline)

            # Create phase records
            phases = [
                ResearchPhaseType.IDEATION,
                ResearchPhaseType.KNOWLEDGE_RETRIEVAL,
                ResearchPhaseType.EXPERIMENTATION,
                ResearchPhaseType.INTERPRETATION,
                ResearchPhaseType.PUBLICATION
            ]

            for phase_type in phases:
                phase = ResearchPhase(
                    pipeline_id=self.pipeline_id,
                    phase_type=phase_type,
                    status=ResearchPhaseStatus.PENDING
                )
                self.db.add(phase)

            self.db.commit()

            return {
                'success': True,
                'pipeline_id': self.pipeline_id,
                'status': 'initialized',
                'budget': budget,
                'phases': [p.value for p in phases],
                'message': 'Research pipeline initialized successfully'
            }

        except Exception as e:
            self.db.rollback()
            return {
                'success': False,
                'error': str(e)
            }

    async def execute_phase(self, phase_type: ResearchPhaseType) -> Dict[str, Any]:
        """
        Execute a specific research phase.

        Args:
            phase_type: Phase to execute

        Returns:
            Phase execution results
        """
        # Get phase record
        phase = self.db.query(ResearchPhase).filter(
            ResearchPhase.pipeline_id == self.pipeline_id,
            ResearchPhase.phase_type == phase_type
        ).first()

        if not phase:
            return {'success': False, 'error': 'Phase not found'}

        # Update phase status
        phase.status = ResearchPhaseStatus.IN_PROGRESS
        phase.started_at = datetime.utcnow()
        self.pipeline.current_phase = phase_type
        self.db.commit()

        try:
            # Execute phase based on type
            if phase_type == ResearchPhaseType.IDEATION:
                result = await self._execute_ideation_phase()
            elif phase_type == ResearchPhaseType.KNOWLEDGE_RETRIEVAL:
                result = await self._execute_knowledge_phase()
            elif phase_type == ResearchPhaseType.EXPERIMENTATION:
                result = await self._execute_experimentation_phase()
            elif phase_type == ResearchPhaseType.INTERPRETATION:
                result = await self._execute_interpretation_phase()
            elif phase_type == ResearchPhaseType.PUBLICATION:
                result = await self._execute_publication_phase()
            else:
                result = {'success': False, 'error': f'Unknown phase type: {phase_type}'}

            # Update phase with results
            if result['success']:
                phase.status = ResearchPhaseStatus.COMPLETED
                phase.completed_at = datetime.utcnow()
                # Serialize outputs to ensure JSON compatibility
                phase.outputs = self._serialize_for_json(result.get('outputs', {}))
                phase.total_cost = result.get('cost', 0.0)
                phase.agents_used = result.get('agents_used', [])

                # Update pipeline cost
                self.pipeline.spent += phase.total_cost
                self.total_cost = self.pipeline.spent

                # Store outputs for next phase (keep original for internal use)
                self.phase_outputs[phase_type.value] = result.get('outputs', {})

            else:
                phase.status = ResearchPhaseStatus.FAILED

            self.db.commit()

            return result

        except Exception as e:
            phase.status = ResearchPhaseStatus.FAILED
            self.db.commit()
            return {'success': False, 'error': str(e)}

    async def _execute_ideation_phase(self) -> Dict[str, Any]:
        """Execute Phase 1: Ideation."""
        outputs = {}
        agents_used = []
        total_cost = 0.0

        try:
            # Step 1: Problem Framing
            if 'problem_framer' in self.agents:
                result = await self.agents['problem_framer'].frame_problem(
                    self.pipeline.query,
                    context={'budget': self.pipeline.budget}
                )

                if result['success']:
                    outputs['problem_statement'] = result['problem_statement']
                    agents_used.append('problem-framer-001')
                    total_cost += result['metadata']['payment_due']

                    # Update pipeline topic
                    self.pipeline.research_topic = result['problem_statement']['research_question']
                    self.db.commit()

                    # Store as artifact
                    self._store_artifact(
                        'problem_statement',
                        'Research Problem Statement',
                        result['problem_statement'],
                        'problem-framer-001'
                    )
                else:
                    return {'success': False, 'error': f"Problem framing failed: {result.get('error')}"}

            # TODO: Add Feasibility Analyst when implemented
            outputs['feasibility_assessment'] = {
                'feasibility_score': 0.85,
                'assessment': 'Feasible',
                'simulated': True
            }

            # TODO: Add Goal Planner when implemented
            outputs['task_plan'] = {
                'phases': 5,
                'estimated_time': '30 days',
                'simulated': True
            }

            return {
                'success': True,
                'outputs': outputs,
                'agents_used': agents_used,
                'cost': total_cost,
                'phase': 'ideation'
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _execute_knowledge_phase(self) -> Dict[str, Any]:
        """Execute Phase 2: Knowledge Retrieval."""
        outputs = {}
        agents_used = []
        total_cost = 0.0

        try:
            # Get problem statement from previous phase
            problem_statement = self.phase_outputs.get('ideation', {}).get('problem_statement')
            if not problem_statement:
                return {'success': False, 'error': 'No problem statement from ideation phase'}

            # Step 1: Literature Mining
            if 'literature_miner' in self.agents:
                result = await self.agents['literature_miner'].search_literature(
                    keywords=problem_statement.get('keywords', ['blockchain', 'ai', 'agents']),
                    research_question=problem_statement.get('research_question', self.pipeline.query),
                    max_papers=10,
                    context={'date_range': '2020-2024'}
                )

                if result['success']:
                    outputs['literature_corpus'] = result['literature_corpus']
                    agents_used.append('literature-miner-001')
                    total_cost += result['metadata']['total_cost_hbar']

                    # Store as artifact
                    self._store_artifact(
                        'literature_corpus',
                        'Literature Search Results',
                        result['literature_corpus'],
                        'literature-miner-001'
                    )
                else:
                    return {'success': False, 'error': f"Literature search failed: {result.get('error')}"}

            # TODO: Add Relevance Ranker when implemented
            outputs['ranked_papers'] = outputs['literature_corpus']['papers'][:5]  # Top 5

            # TODO: Add Knowledge Extractor when implemented
            outputs['extracted_knowledge'] = {
                'key_findings': ['Blockchain reduces transaction costs', 'Agent discovery is critical'],
                'methods': ['Consensus algorithms', 'Smart contracts'],
                'simulated': True
            }

            return {
                'success': True,
                'outputs': outputs,
                'agents_used': agents_used,
                'cost': total_cost,
                'phase': 'knowledge_retrieval'
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _execute_experimentation_phase(self) -> Dict[str, Any]:
        """Execute Phase 3: Experimentation."""
        # Placeholder for now - implement when agents are ready
        outputs = {
            'hypothesis': 'Blockchain reduces agent transaction costs by 30%',
            'experiment_results': {
                'cost_reduction': 0.32,
                'trust_improvement': 0.25,
                'simulated': True
            },
            'verification_report': {
                'reproducible': True,
                'confidence': 0.85,
                'simulated': True
            }
        }

        return {
            'success': True,
            'outputs': outputs,
            'agents_used': [],
            'cost': 0.0,
            'phase': 'experimentation'
        }

    async def _execute_interpretation_phase(self) -> Dict[str, Any]:
        """Execute Phase 4: Interpretation."""
        # Placeholder for now
        outputs = {
            'insights': ['Significant cost reduction achieved', 'Trust metrics improved'],
            'bias_report': {'overall_bias_score': 0.2, 'simulated': True},
            'compliance_report': {'compliance_score': 0.95, 'approved': True, 'simulated': True}
        }

        return {
            'success': True,
            'outputs': outputs,
            'agents_used': [],
            'cost': 0.0,
            'phase': 'interpretation'
        }

    async def _execute_publication_phase(self) -> Dict[str, Any]:
        """Execute Phase 5: Publication."""
        # Placeholder for now
        outputs = {
            'research_paper': {
                'title': 'Impact of Blockchain on AI Agent Marketplaces',
                'sections': ['introduction', 'methods', 'results', 'discussion', 'conclusion'],
                'simulated': True
            },
            'peer_review': {
                'overall_score': 7.5,
                'recommendation': 'accept',
                'simulated': True
            },
            'reputation_updates': {
                'agents_updated': 2,
                'simulated': True
            }
        }

        return {
            'success': True,
            'outputs': outputs,
            'agents_used': [],
            'cost': 0.0,
            'phase': 'publication'
        }

    async def execute_full_pipeline(self) -> Dict[str, Any]:
        """
        Execute the complete research pipeline.

        Returns:
            Final pipeline results
        """
        results = {}
        phases = [
            ResearchPhaseType.IDEATION,
            ResearchPhaseType.KNOWLEDGE_RETRIEVAL,
            ResearchPhaseType.EXPERIMENTATION,
            ResearchPhaseType.INTERPRETATION,
            ResearchPhaseType.PUBLICATION
        ]

        for phase in phases:
            # Check if we can transition to this phase
            if len(results) > 0:
                prev_phase = phases[phases.index(phase) - 1]
                can_transition, error = validate_phase_transition(
                    prev_phase.value,
                    phase.value,
                    self.phase_outputs.get(prev_phase.value, {})
                )

                if not can_transition:
                    return {
                        'success': False,
                        'error': f'Cannot transition to {phase.value}: {error}',
                        'completed_phases': list(results.keys())
                    }

            # Execute phase
            result = await self.execute_phase(phase)

            if not result['success']:
                return {
                    'success': False,
                    'error': f'Phase {phase.value} failed: {result.get("error")}',
                    'completed_phases': list(results.keys())
                }

            results[phase.value] = result

            # Check budget
            if self.total_cost > self.pipeline.budget:
                return {
                    'success': False,
                    'error': f'Budget exceeded: {self.total_cost} > {self.pipeline.budget}',
                    'completed_phases': list(results.keys())
                }

        # Mark pipeline as completed
        self.pipeline.status = ResearchPhaseStatus.COMPLETED
        self.pipeline.completed_at = datetime.utcnow()
        self.db.commit()

        return {
            'success': True,
            'pipeline_id': self.pipeline_id,
            'research_topic': self.pipeline.research_topic,
            'total_cost': self.total_cost,
            'phases': results,
            'final_output': self._get_final_output()
        }

    def _get_final_output(self) -> Dict[str, Any]:
        """Get final research output."""
        # Collect key outputs from all phases
        return {
            'problem_statement': self.phase_outputs.get('ideation', {}).get('problem_statement'),
            'literature_summary': self.phase_outputs.get('knowledge_retrieval', {}).get('literature_corpus'),
            'experiment_results': self.phase_outputs.get('experimentation', {}).get('experiment_results'),
            'insights': self.phase_outputs.get('interpretation', {}).get('insights'),
            'research_paper': self.phase_outputs.get('publication', {}).get('research_paper'),
            'total_cost_hbar': self.total_cost
        }

    def _store_artifact(
        self,
        artifact_type: str,
        name: str,
        content: Any,
        created_by: str
    ):
        """Store research artifact in database."""
        try:
            # Serialize datetime objects to ISO format strings
            serialized_content = self._serialize_for_json(content)

            artifact = ResearchArtifact(
                pipeline_id=self.pipeline_id,
                artifact_type=artifact_type,
                name=name,
                description=f'{artifact_type} for pipeline {self.pipeline_id}',
                content=serialized_content,
                created_by=created_by
            )
            self.db.add(artifact)
            self.db.commit()
        except Exception as e:
            print(f"Failed to store artifact: {e}")

    def _serialize_for_json(self, obj: Any) -> Any:
        """Recursively serialize objects to JSON-compatible format."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self._serialize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        elif hasattr(obj, 'dict'):
            # Handle Pydantic models
            return self._serialize_for_json(obj.dict())
        elif hasattr(obj, '__dict__'):
            # Handle other objects with __dict__
            return self._serialize_for_json(obj.__dict__)
        else:
            return obj

    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status."""
        if not self.pipeline:
            return {'success': False, 'error': 'Pipeline not initialized'}

        phases = self.db.query(ResearchPhase).filter(
            ResearchPhase.pipeline_id == self.pipeline_id
        ).all()

        phase_status = []
        for phase in phases:
            phase_status.append({
                'phase': phase.phase_type.value,
                'status': phase.status.value,
                'cost': phase.total_cost,
                'agents_used': phase.agents_used or []
            })

        return {
            'success': True,
            'pipeline_id': self.pipeline_id,
            'research_topic': self.pipeline.research_topic,
            'overall_status': self.pipeline.status.value,
            'current_phase': self.pipeline.current_phase.value if self.pipeline.current_phase else None,
            'budget': self.pipeline.budget,
            'spent': self.pipeline.spent,
            'phases': phase_status
        }

    def __del__(self):
        """Clean up database connection."""
        if hasattr(self, 'db'):
            self.db.close()
