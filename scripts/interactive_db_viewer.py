#!/usr/bin/env python
"""
Interactive database viewer for research artifacts.

Run with: uv run python scripts/interactive_db_viewer.py
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, ResearchPipeline, ResearchArtifact, Agent, AgentReputation
import json


def main_menu():
    """Display main menu."""
    while True:
        print("\n" + "=" * 80)
        print("ProvidAI Database Viewer - Interactive Menu")
        print("=" * 80)
        print("\n1. View All Pipelines")
        print("2. View Pipeline Details")
        print("3. View All Artifacts")
        print("4. View Artifact Content")
        print("5. View Registered Agents")
        print("6. View Agent Reputations")
        print("7. Export Artifact to JSON")
        print("8. Search Artifacts by Type")
        print("0. Exit")

        choice = input("\nEnter your choice: ").strip()

        if choice == "1":
            view_all_pipelines()
        elif choice == "2":
            view_pipeline_details()
        elif choice == "3":
            view_all_artifacts()
        elif choice == "4":
            view_artifact_content()
        elif choice == "5":
            view_agents()
        elif choice == "6":
            view_reputations()
        elif choice == "7":
            export_artifact()
        elif choice == "8":
            search_artifacts()
        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("\n❌ Invalid choice. Please try again.")


def view_all_pipelines():
    """View all pipelines."""
    db = SessionLocal()
    try:
        pipelines = db.query(ResearchPipeline).order_by(ResearchPipeline.created_at.desc()).all()

        print("\n" + "=" * 80)
        print(f"RESEARCH PIPELINES ({len(pipelines)} total)")
        print("=" * 80)

        for i, p in enumerate(pipelines, 1):
            print(f"\n{i}. ID: {p.id}")
            print(f"   Topic: {p.research_topic[:70]}...")
            print(f"   Status: {p.status}")
            print(f"   Budget: {p.budget} HBAR | Spent: {p.spent} HBAR")
            print(f"   Created: {p.created_at}")

        input("\nPress Enter to continue...")

    finally:
        db.close()


def view_pipeline_details():
    """View detailed pipeline info."""
    db = SessionLocal()
    try:
        pipelines = db.query(ResearchPipeline).order_by(ResearchPipeline.created_at.desc()).all()

        print("\nAvailable Pipelines:")
        for i, p in enumerate(pipelines, 1):
            print(f"{i}. {p.id[:8]}... - {p.research_topic[:50]}...")

        choice = input("\nEnter pipeline number: ").strip()
        try:
            idx = int(choice) - 1
            pipeline = pipelines[idx]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            return

        print("\n" + "=" * 80)
        print(f"PIPELINE: {pipeline.id}")
        print("=" * 80)
        print(f"Topic: {pipeline.research_topic}")
        print(f"Status: {pipeline.status}")
        print(f"Budget: {pipeline.budget} HBAR | Spent: {pipeline.spent} HBAR\n")

        print("PHASES:")
        for phase in pipeline.phases:
            print(f"\n  {phase.phase_type.upper()}")
            print(f"    Status: {phase.status}")
            print(f"    Cost: {phase.total_cost} HBAR")
            print(f"    Agents: {', '.join(phase.agents_used) if phase.agents_used else 'None'}")

        print("\nARTIFACTS:")
        artifacts = db.query(ResearchArtifact).filter(
            ResearchArtifact.pipeline_id == pipeline.id
        ).all()
        for i, art in enumerate(artifacts, 1):
            print(f"  {i}. {art.name} ({art.artifact_type})")

        input("\nPress Enter to continue...")

    finally:
        db.close()


def view_all_artifacts():
    """View all artifacts."""
    db = SessionLocal()
    try:
        artifacts = db.query(ResearchArtifact).order_by(ResearchArtifact.created_at.desc()).all()

        print("\n" + "=" * 80)
        print(f"RESEARCH ARTIFACTS ({len(artifacts)} total)")
        print("=" * 80)

        for i, art in enumerate(artifacts, 1):
            print(f"\n{i}. {art.name}")
            print(f"   Type: {art.artifact_type}")
            print(f"   ID: {art.id}")
            print(f"   Created by: {art.created_by}")
            print(f"   Pipeline: {art.pipeline_id[:8]}...")

        input("\nPress Enter to continue...")

    finally:
        db.close()


def view_artifact_content():
    """View full artifact content."""
    db = SessionLocal()
    try:
        artifacts = db.query(ResearchArtifact).order_by(ResearchArtifact.created_at.desc()).all()

        print("\nAvailable Artifacts:")
        for i, art in enumerate(artifacts, 1):
            print(f"{i}. {art.name} ({art.artifact_type})")

        choice = input("\nEnter artifact number: ").strip()
        try:
            idx = int(choice) - 1
            artifact = artifacts[idx]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            return

        print("\n" + "=" * 80)
        print(f"ARTIFACT: {artifact.name}")
        print("=" * 80)
        print(f"Type: {artifact.artifact_type}")
        print(f"Created by: {artifact.created_by}")
        print(f"Created at: {artifact.created_at}\n")
        print("CONTENT:")
        print("-" * 80)
        print(json.dumps(artifact.content, indent=2))

        input("\nPress Enter to continue...")

    finally:
        db.close()


def view_agents():
    """View registered agents."""
    db = SessionLocal()
    try:
        agents = db.query(Agent).all()

        print("\n" + "=" * 80)
        print(f"REGISTERED AGENTS ({len(agents)} total)")
        print("=" * 80)

        for agent in agents:
            print(f"\nAgent ID: {agent.agent_id}")
            print(f"Name: {agent.name}")
            print(f"Type: {agent.agent_type}")
            print(f"Status: {agent.status}")
            print(f"Capabilities: {', '.join(agent.capabilities)}")

        input("\nPress Enter to continue...")

    finally:
        db.close()


def view_reputations():
    """View agent reputations."""
    db = SessionLocal()
    try:
        reps = db.query(AgentReputation).all()

        print("\n" + "=" * 80)
        print("AGENT REPUTATIONS")
        print("=" * 80)

        for rep in reps:
            print(f"\nAgent: {rep.agent_id}")
            print(f"Reputation Score: {rep.reputation_score:.2f}")
            print(f"Total Tasks: {rep.total_tasks}")
            print(f"Success Rate: {rep.successful_tasks}/{rep.total_tasks}")
            print(f"Payment Multiplier: {rep.payment_multiplier}x")

        input("\nPress Enter to continue...")

    finally:
        db.close()


def export_artifact():
    """Export artifact to JSON."""
    db = SessionLocal()
    try:
        artifacts = db.query(ResearchArtifact).all()

        print("\nAvailable Artifacts:")
        for i, art in enumerate(artifacts, 1):
            print(f"{i}. {art.name} (ID: {art.id})")

        choice = input("\nEnter artifact number: ").strip()
        try:
            idx = int(choice) - 1
            artifact = artifacts[idx]
        except (ValueError, IndexError):
            print("❌ Invalid selection")
            return

        filename = f"artifact_{artifact.id}_{artifact.artifact_type}.json"

        data = {
            "id": artifact.id,
            "name": artifact.name,
            "type": artifact.artifact_type,
            "created_by": artifact.created_by,
            "created_at": artifact.created_at.isoformat(),
            "content": artifact.content
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\n✅ Exported to {filename}")
        input("\nPress Enter to continue...")

    finally:
        db.close()


def search_artifacts():
    """Search artifacts by type."""
    db = SessionLocal()
    try:
        print("\nArtifact Types:")
        print("1. problem_statement")
        print("2. literature_corpus")
        print("3. All types")

        choice = input("\nEnter choice: ").strip()

        if choice == "1":
            artifact_type = "problem_statement"
        elif choice == "2":
            artifact_type = "literature_corpus"
        else:
            artifact_type = None

        if artifact_type:
            artifacts = db.query(ResearchArtifact).filter(
                ResearchArtifact.artifact_type == artifact_type
            ).all()
        else:
            artifacts = db.query(ResearchArtifact).all()

        print(f"\n{len(artifacts)} artifacts found:")
        for i, art in enumerate(artifacts, 1):
            print(f"{i}. {art.name} - {art.artifact_type}")

        input("\nPress Enter to continue...")

    finally:
        db.close()


if __name__ == "__main__":
    main_menu()
