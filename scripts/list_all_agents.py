#!/usr/bin/env python
"""
List all research agents in the registry.

Run with: uv run python scripts/list_all_agents.py
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, Agent


def list_all_agents():
    """List all agents in the database registry."""
    db = SessionLocal()
    try:
        agents = db.query(Agent).order_by(Agent.agent_type, Agent.agent_id).all()

        print("=" * 100)
        print("PROVIDAI AGENT REGISTRY")
        print("=" * 100)
        print(f"\nTotal Agents: {len(agents)}")
        print()

        # Group by phase
        phases = {
            "phase1": [],
            "phase2": [],
            "phase3": [],
            "phase4": [],
            "phase5": [],
            "core": []
        }

        for agent in agents:
            if "problem-framer" in agent.agent_id or "feasibility" in agent.agent_id or "goal-planner" in agent.agent_id:
                phases["phase1"].append(agent)
            elif "literature" in agent.agent_id or "knowledge-synthesizer" in agent.agent_id:
                phases["phase2"].append(agent)
            elif "hypothesis" in agent.agent_id or "experiment" in agent.agent_id or "code-generator" in agent.agent_id:
                phases["phase3"].append(agent)
            elif "insight" in agent.agent_id or "bias" in agent.agent_id or "compliance" in agent.agent_id:
                phases["phase4"].append(agent)
            elif "paper" in agent.agent_id or "peer" in agent.agent_id or "reputation" in agent.agent_id or "archiver" in agent.agent_id:
                phases["phase5"].append(agent)
            else:
                phases["core"].append(agent)

        # Display by phase
        phase_names = {
            "phase1": "PHASE 1: IDEATION",
            "phase2": "PHASE 2: KNOWLEDGE RETRIEVAL",
            "phase3": "PHASE 3: EXPERIMENTATION",
            "phase4": "PHASE 4: INTERPRETATION",
            "phase5": "PHASE 5: PUBLICATION",
            "core": "CORE AGENTS"
        }

        for phase_key, phase_name in phase_names.items():
            phase_agents = phases[phase_key]
            if phase_agents:
                print(f"\n{phase_name}")
                print("-" * 100)
                for agent in phase_agents:
                    pricing = agent.meta.get('pricing', {})
                    rate = pricing.get('rate', 'N/A')
                    print(f"\n  {agent.name}")
                    print(f"    ID: {agent.agent_id}")
                    print(f"    Status: {agent.status}")
                    print(f"    Pricing: {rate}")
                    print(f"    Capabilities: {', '.join(agent.capabilities[:3])}...")

        print()
        print("=" * 100)
        print("SUMMARY BY PHASE")
        print("=" * 100)
        for phase_key, phase_name in phase_names.items():
            count = len(phases[phase_key])
            if count > 0:
                print(f"{phase_name}: {count} agents")

        print()

    finally:
        db.close()


def main():
    """Main function."""
    list_all_agents()


if __name__ == "__main__":
    main()
