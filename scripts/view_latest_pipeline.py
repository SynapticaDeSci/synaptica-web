#!/usr/bin/env python
"""
View the latest research pipeline and its artifacts.
"""

import sys
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, ResearchPipeline, ResearchArtifact

def view_latest_pipeline():
    """View the most recent pipeline and its outputs."""
    db = SessionLocal()
    try:
        # Get latest pipeline
        pipeline = db.query(ResearchPipeline).order_by(ResearchPipeline.created_at.desc()).first()

        if not pipeline:
            print("No pipelines found in database.")
            return

        print("=" * 100)
        print("LATEST RESEARCH PIPELINE")
        print("=" * 100)
        print(f"\nPipeline ID: {pipeline.id}")
        print(f"Status: {pipeline.status}")
        print(f"Created: {pipeline.created_at}")
        print(f"\nQuery:")
        print(f"  {pipeline.query}")
        print(f"\nCosts:")
        print(f"  Budget: {pipeline.budget} HBAR")
        print(f"  Spent: {pipeline.spent} HBAR")
        print(f"  Remaining: {pipeline.budget - pipeline.spent} HBAR")

        # Get all artifacts for this pipeline
        artifacts = db.query(ResearchArtifact).filter(
            ResearchArtifact.pipeline_id == pipeline.id
        ).order_by(ResearchArtifact.created_at).all()

        print(f"\n" + "=" * 100)
        print(f"ARTIFACTS ({len(artifacts)} total)")
        print("=" * 100)

        if not artifacts:
            print("\nNo artifacts found for this pipeline.")
            return

        for i, artifact in enumerate(artifacts, 1):
            print(f"\n[{i}] {artifact.artifact_type.upper()}")
            print(f"    Agent: {artifact.agent_id}")
            print(f"    Created: {artifact.created_at}")

            # Parse and display content based on type
            try:
                content = json.loads(artifact.content)

                if artifact.artifact_type == "problem_statement":
                    print(f"    Research Question: {content.get('research_question', 'N/A')[:80]}...")
                    print(f"    Variables: {len(content.get('variables', []))}")

                elif artifact.artifact_type == "literature_corpus":
                    papers = content.get('papers', [])
                    print(f"    Papers: {len(papers)}")
                    if papers:
                        print(f"    Top Paper: {papers[0].get('title', 'N/A')[:80]}...")

                elif artifact.artifact_type == "feasibility_analysis":
                    print(f"    Score: {content.get('feasibility_score', 'N/A')}")
                    print(f"    Decision: {content.get('go_no_go_decision', 'N/A')}")

                elif artifact.artifact_type == "research_plan":
                    print(f"    Objectives: {len(content.get('objectives', []))}")
                    print(f"    Tasks: {len(content.get('tasks', []))}")

                elif artifact.artifact_type == "knowledge_synthesis":
                    print(f"    Key Claims: {len(content.get('key_claims', []))}")
                    print(f"    Research Gaps: {len(content.get('research_gaps', []))}")

                elif artifact.artifact_type == "hypothesis":
                    print(f"    Hypothesis: {content.get('hypothesis', 'N/A')[:80]}...")

                elif artifact.artifact_type == "experiment_code":
                    print(f"    Language: {content.get('language', 'N/A')}")
                    print(f"    Lines: {len(content.get('code', '').split('\\n'))}")

                elif artifact.artifact_type == "experiment_results":
                    print(f"    Status: {content.get('status', 'N/A')}")

                elif artifact.artifact_type == "insights":
                    print(f"    Insights: {len(content.get('insights', []))}")
                    print(f"    Patterns: {len(content.get('patterns', []))}")

                elif artifact.artifact_type == "bias_report":
                    biases = content.get('biases_detected', [])
                    if isinstance(biases, list):
                        print(f"    Biases Detected: {len(biases)}")
                    else:
                        print(f"    Biases Detected: {biases}")
                    print(f"    Overall Score: {content.get('overall_bias_score', 'N/A')}")

                elif artifact.artifact_type == "compliance_report":
                    print(f"    Status: {content.get('compliance_status', 'N/A')}")

                elif artifact.artifact_type == "research_paper":
                    print(f"    Title: {content.get('title', 'N/A')[:80]}...")
                    print(f"    Sections: {len(content.get('sections', []))}")

                elif artifact.artifact_type == "peer_review":
                    print(f"    Score: {content.get('overall_score', 'N/A')}/10")
                    print(f"    Recommendation: {content.get('recommendation', 'N/A')}")

                else:
                    print(f"    Content Keys: {', '.join(list(content.keys())[:5])}")

            except json.JSONDecodeError:
                print(f"    Content: {artifact.content[:100]}...")

        print("\n" + "=" * 100)
        print("To view full artifact content, use:")
        print(f"  uv run python scripts/view_artifacts.py --pipeline {pipeline.id}")
        print("=" * 100)

    finally:
        db.close()

if __name__ == "__main__":
    view_latest_pipeline()
