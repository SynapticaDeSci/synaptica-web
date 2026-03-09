#!/usr/bin/env python
"""
Register all research agents in the database.

Run with: uv run python scripts/register_all_agents.py
"""

import sys
import os
import asyncio
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def register_all_agents():
    """Register all agents by importing them (they auto-register)."""
    print("Registering all research agents...\n")

    agents_registered = []

    # Phase 1: Ideation
    print("Phase 1: Ideation")
    try:
        from agents.research.phase1_ideation.problem_framer.agent import problem_framer_agent
        agents_registered.append(problem_framer_agent.name)
        print(f"  ✅ {problem_framer_agent.name}")
    except Exception as e:
        print(f"  ❌ Problem Framer: {e}")

    try:
        from agents.research.phase1_ideation.feasibility_analyst.agent import feasibility_analyst_001_agent
        agents_registered.append(feasibility_analyst_001_agent.name)
        print(f"  ✅ {feasibility_analyst_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Feasibility Analyst: {e}")

    try:
        from agents.research.phase1_ideation.goal_planner.agent import goal_planner_001_agent
        agents_registered.append(goal_planner_001_agent.name)
        print(f"  ✅ {goal_planner_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Goal Planner: {e}")

    # Phase 2: Knowledge Retrieval
    print("\nPhase 2: Knowledge Retrieval")
    try:
        from agents.research.phase2_knowledge.literature_miner.agent import literature_miner_agent
        agents_registered.append(literature_miner_agent.name)
        print(f"  ✅ {literature_miner_agent.name}")
    except Exception as e:
        print(f"  ❌ Literature Miner: {e}")

    try:
        from agents.research.phase2_knowledge.knowledge_synthesizer.agent import knowledge_synthesizer_001_agent
        agents_registered.append(knowledge_synthesizer_001_agent.name)
        print(f"  ✅ {knowledge_synthesizer_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Knowledge Synthesizer: {e}")

    # Phase 3: Experimentation
    print("\nPhase 3: Experimentation")
    try:
        from agents.research.phase3_experimentation.hypothesis_designer.agent import hypothesis_designer_001_agent
        agents_registered.append(hypothesis_designer_001_agent.name)
        print(f"  ✅ {hypothesis_designer_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Hypothesis Designer: {e}")

    try:
        from agents.research.phase3_experimentation.experiment_runner.agent import experiment_runner_001_agent
        agents_registered.append(experiment_runner_001_agent.name)
        print(f"  ✅ {experiment_runner_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Experiment Runner: {e}")

    try:
        from agents.research.phase3_experimentation.code_generator.agent import code_generator_001_agent
        agents_registered.append(code_generator_001_agent.name)
        print(f"  ✅ {code_generator_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Code Generator: {e}")

    # Phase 4: Interpretation
    print("\nPhase 4: Interpretation")
    try:
        from agents.research.phase4_interpretation.insight_generator.agent import insight_generator_001_agent
        agents_registered.append(insight_generator_001_agent.name)
        print(f"  ✅ {insight_generator_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Insight Generator: {e}")

    try:
        from agents.research.phase4_interpretation.bias_detector.agent import bias_detector_001_agent
        agents_registered.append(bias_detector_001_agent.name)
        print(f"  ✅ {bias_detector_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Bias Detector: {e}")

    try:
        from agents.research.phase4_interpretation.compliance_checker.agent import compliance_checker_001_agent
        agents_registered.append(compliance_checker_001_agent.name)
        print(f"  ✅ {compliance_checker_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Compliance Checker: {e}")

    # Phase 5: Publication
    print("\nPhase 5: Publication")
    try:
        from agents.research.phase5_publication.paper_writer.agent import paper_writer_001_agent
        agents_registered.append(paper_writer_001_agent.name)
        print(f"  ✅ {paper_writer_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Paper Writer: {e}")

    try:
        from agents.research.phase5_publication.peer_reviewer.agent import peer_reviewer_001_agent
        agents_registered.append(peer_reviewer_001_agent.name)
        print(f"  ✅ {peer_reviewer_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Peer Reviewer: {e}")

    try:
        from agents.research.phase5_publication.reputation_manager.agent import reputation_manager_001_agent
        agents_registered.append(reputation_manager_001_agent.name)
        print(f"  ✅ {reputation_manager_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Reputation Manager: {e}")

    try:
        from agents.research.phase5_publication.archiver.agent import archiver_001_agent
        agents_registered.append(archiver_001_agent.name)
        print(f"  ✅ {archiver_001_agent.name}")
    except Exception as e:
        print(f"  ❌ Archiver: {e}")

    print(f"\n✅ Successfully registered {len(agents_registered)} agents!")

    # Now list them
    from shared.database import SessionLocal, Agent

    db = SessionLocal()
    try:
        all_agents = db.query(Agent).all()
        print(f"\nTotal agents in database: {len(all_agents)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(register_all_agents())
