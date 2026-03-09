#!/usr/bin/env python
"""
View research artifacts stored in the database.

Run with: uv run python scripts/view_artifacts.py
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, ResearchPipeline, ResearchPhase, ResearchArtifact, Agent
import json


def view_pipelines():
    """View all research pipelines."""
    db = SessionLocal()
    try:
        pipelines = db.query(ResearchPipeline).order_by(ResearchPipeline.created_at.desc()).all()

        print("=" * 80)
        print(f"RESEARCH PIPELINES ({len(pipelines)} total)")
        print("=" * 80)
        print()

        for i, pipeline in enumerate(pipelines, 1):
            print(f"{i}. Pipeline ID: {pipeline.id}")
            print(f"   Topic: {pipeline.research_topic}")
            print(f"   Status: {pipeline.status}")
            print(f"   Budget: {pipeline.budget} HBAR")
            print(f"   Spent: {pipeline.spent} HBAR")
            print(f"   Created: {pipeline.created_at}")
            print(f"   Phases: {len(pipeline.phases)}")
            print()

        return pipelines

    finally:
        db.close()


def view_pipeline_details(pipeline_id: str):
    """View detailed information about a specific pipeline."""
    db = SessionLocal()
    try:
        pipeline = db.query(ResearchPipeline).filter(ResearchPipeline.id == pipeline_id).first()

        if not pipeline:
            print(f"Pipeline {pipeline_id} not found!")
            return

        print("=" * 80)
        print(f"PIPELINE: {pipeline.id}")
        print("=" * 80)
        print(f"Topic: {pipeline.research_topic}")
        print(f"Status: {pipeline.status}")
        print(f"Budget: {pipeline.budget} HBAR / Spent: {pipeline.spent} HBAR")
        print(f"Created: {pipeline.created_at}")
        print()

        # Show phases
        print("PHASES:")
        print("-" * 80)
        for phase in pipeline.phases:
            print(f"\n{phase.phase_type.upper()}")
            print(f"  Status: {phase.status}")
            print(f"  Cost: {phase.total_cost} HBAR")
            print(f"  Agents: {', '.join(phase.agents_used) if phase.agents_used else 'None'}")
            if phase.completed_at:
                print(f"  Completed: {phase.completed_at}")

            if phase.outputs:
                print(f"  Outputs:")
                for key, value in phase.outputs.items():
                    if isinstance(value, dict):
                        print(f"    - {key}: {json.dumps(value, indent=6)[:200]}...")
                    elif isinstance(value, list):
                        print(f"    - {key}: {len(value)} items")
                    else:
                        print(f"    - {key}: {str(value)[:100]}")

        # Show artifacts
        print("\n\nARTIFACTS:")
        print("-" * 80)
        artifacts = db.query(ResearchArtifact).filter(
            ResearchArtifact.pipeline_id == pipeline_id
        ).all()

        for i, artifact in enumerate(artifacts, 1):
            print(f"\n{i}. {artifact.name}")
            print(f"   Type: {artifact.artifact_type}")
            print(f"   Created by: {artifact.created_by}")
            print(f"   Created at: {artifact.created_at}")
            print(f"   Description: {artifact.description}")

            if artifact.content:
                print(f"   Content Preview:")
                content_str = json.dumps(artifact.content, indent=4)[:500]
                print(f"   {content_str}...")

        print()

    finally:
        db.close()


def view_artifacts():
    """View all artifacts."""
    db = SessionLocal()
    try:
        artifacts = db.query(ResearchArtifact).order_by(ResearchArtifact.created_at.desc()).all()

        print("=" * 80)
        print(f"ALL RESEARCH ARTIFACTS ({len(artifacts)} total)")
        print("=" * 80)
        print()

        for i, artifact in enumerate(artifacts, 1):
            print(f"{i}. {artifact.name}")
            print(f"   Type: {artifact.artifact_type}")
            print(f"   Pipeline: {artifact.pipeline_id}")
            print(f"   Created by: {artifact.created_by}")
            print(f"   Created at: {artifact.created_at}")

            if artifact.content:
                # Pretty print a preview of the content
                content_preview = json.dumps(artifact.content, indent=2)[:300]
                print(f"   Content Preview:")
                print(f"   {content_preview}...")
            print()

    finally:
        db.close()


def export_artifact(artifact_id: int, output_file: str):
    """Export an artifact to a JSON file."""
    db = SessionLocal()
    try:
        artifact = db.query(ResearchArtifact).filter(ResearchArtifact.id == artifact_id).first()

        if not artifact:
            print(f"Artifact {artifact_id} not found!")
            return

        export_data = {
            "id": artifact.id,
            "name": artifact.name,
            "type": artifact.artifact_type,
            "pipeline_id": artifact.pipeline_id,
            "created_by": artifact.created_by,
            "created_at": artifact.created_at.isoformat(),
            "description": artifact.description,
            "content": artifact.content
        }

        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)

        print(f"✅ Artifact exported to {output_file}")

    finally:
        db.close()


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description='View research artifacts from database')
    parser.add_argument('--pipelines', action='store_true', help='List all pipelines')
    parser.add_argument('--pipeline', type=str, help='View details of a specific pipeline')
    parser.add_argument('--artifacts', action='store_true', help='List all artifacts')
    parser.add_argument('--export', type=int, help='Export artifact by ID')
    parser.add_argument('--output', type=str, help='Output file for export')

    args = parser.parse_args()

    if args.export:
        output_file = args.output or f"artifact_{args.export}.json"
        export_artifact(args.export, output_file)
    elif args.pipeline:
        view_pipeline_details(args.pipeline)
    elif args.artifacts:
        view_artifacts()
    elif args.pipelines:
        pipelines = view_pipelines()
        if pipelines:
            print("\nTo view details of a pipeline, run:")
            print(f"uv run python scripts/view_artifacts.py --pipeline {pipelines[0].id}")
    else:
        # Default: show latest pipeline
        db = SessionLocal()
        try:
            latest = db.query(ResearchPipeline).order_by(ResearchPipeline.created_at.desc()).first()
            if latest:
                print("Showing latest pipeline (use --help for more options)\n")
                view_pipeline_details(latest.id)
            else:
                print("No pipelines found in database!")
                print("\nRun the demo first: uv run python scripts/demo_research_pipeline.py")
        finally:
            db.close()


if __name__ == "__main__":
    main()
