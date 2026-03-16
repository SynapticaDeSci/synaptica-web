"""
Legacy demo script for the research pipeline.

This script demonstrates the older multi-phase demo pipeline with:
- Problem framing
- Literature search
- Simulated experimentation
- Interpretation
- Publication

It is retained as a legacy reference and is not part of the supported research-run runtime.

Run with: uv run python scripts/demo_research_pipeline.py
"""

import asyncio
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.research.research_pipeline import ResearchPipeline
from shared.database import engine, Base

# Load environment variables
load_dotenv(override=True)


async def demo_research_pipeline():
    """Run the legacy demo research pipeline."""

    print("=" * 80)
    print("ProvidAI Legacy Research Pipeline Demo")
    print("Reference-only multi-phase prototype with micropayments")
    print("=" * 80)
    print()

    # Initialize database
    print("🔧 Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database ready")
    print()

    # Create research pipeline
    pipeline = ResearchPipeline()

    # The research query
    research_query = """
    What is the quantitative impact of blockchain-based micropayment systems
    on the adoption rate and operational efficiency of autonomous AI agent marketplaces?
    """

    print("📚 Research Query:")
    print(f"   {research_query.strip()}")
    print()

    # Start the pipeline
    print("🚀 Starting research pipeline...")
    start_result = await pipeline.start_pipeline(
        query=research_query,
        budget=5.0,  # 5 HBAR budget
        context={
            'domain': 'Blockchain and AI',
            'timeframe': '30 days',
            'focus': 'Hedera ecosystem'
        }
    )

    if not start_result['success']:
        print(f"❌ Failed to start pipeline: {start_result.get('error')}")
        return

    print(f"✅ Pipeline initialized with ID: {start_result['pipeline_id']}")
    print(f"   Budget: {start_result['budget']} HBAR")
    print(f"   Phases: {', '.join(start_result['phases'])}")
    print()

    # Execute each phase
    print("=" * 80)
    print("PHASE 1: IDEATION")
    print("=" * 80)

    ideation_result = await pipeline.execute_phase(
        ResearchPhaseType.IDEATION
    )

    if ideation_result['success']:
        print("✅ Ideation phase completed")
        problem = ideation_result['outputs'].get('problem_statement', {})
        print(f"   Research Question: {problem.get('research_question', 'N/A')[:100]}...")
        print(f"   Hypothesis: {problem.get('hypothesis', 'N/A')[:100]}...")
        print(f"   Keywords: {', '.join(problem.get('keywords', [])[:5])}")
        print(f"   Cost: {ideation_result.get('cost', 0)} HBAR")
    else:
        print(f"❌ Ideation failed: {ideation_result.get('error')}")
    print()

    # Knowledge Retrieval
    print("=" * 80)
    print("PHASE 2: KNOWLEDGE RETRIEVAL")
    print("=" * 80)

    knowledge_result = await pipeline.execute_phase(
        ResearchPhaseType.KNOWLEDGE_RETRIEVAL
    )

    if knowledge_result['success']:
        print("✅ Knowledge retrieval completed")
        corpus = knowledge_result['outputs'].get('literature_corpus', {})
        papers = corpus.get('papers', [])
        print(f"   Papers found: {len(papers)}")
        if papers:
            print("   Top papers:")
            for i, paper in enumerate(papers[:3], 1):
                print(f"   {i}. {paper.get('title', 'Unknown')[:60]}...")
                print(f"      Relevance: {paper.get('relevance_score', 0)}")
        print(f"   Cost: {knowledge_result.get('cost', 0)} HBAR")
    else:
        print(f"❌ Knowledge retrieval failed: {knowledge_result.get('error')}")
    print()

    # Experimentation (simulated for now)
    print("=" * 80)
    print("PHASE 3: EXPERIMENTATION (Simulated)")
    print("=" * 80)

    experiment_result = await pipeline.execute_phase(
        ResearchPhaseType.EXPERIMENTATION
    )

    if experiment_result['success']:
        print("✅ Experimentation completed (simulated)")
        results = experiment_result['outputs'].get('experiment_results', {})
        print(f"   Cost Reduction: {results.get('cost_reduction', 0) * 100:.1f}%")
        print(f"   Trust Improvement: {results.get('trust_improvement', 0) * 100:.1f}%")
        print(f"   Cost: {experiment_result.get('cost', 0)} HBAR")
    else:
        print(f"❌ Experimentation failed: {experiment_result.get('error')}")
    print()

    # Interpretation
    print("=" * 80)
    print("PHASE 4: INTERPRETATION (Simulated)")
    print("=" * 80)

    interpretation_result = await pipeline.execute_phase(
        ResearchPhaseType.INTERPRETATION
    )

    if interpretation_result['success']:
        print("✅ Interpretation completed (simulated)")
        insights = interpretation_result['outputs'].get('insights', [])
        print(f"   Insights generated: {len(insights)}")
        for insight in insights[:2]:
            print(f"   • {insight}")
        print(f"   Bias Score: {interpretation_result['outputs'].get('bias_report', {}).get('overall_bias_score', 0)}")
        print(f"   Cost: {interpretation_result.get('cost', 0)} HBAR")
    else:
        print(f"❌ Interpretation failed: {interpretation_result.get('error')}")
    print()

    # Publication
    print("=" * 80)
    print("PHASE 5: PUBLICATION (Simulated)")
    print("=" * 80)

    publication_result = await pipeline.execute_phase(
        ResearchPhaseType.PUBLICATION
    )

    if publication_result['success']:
        print("✅ Publication completed (simulated)")
        paper = publication_result['outputs'].get('research_paper', {})
        print(f"   Paper Title: {paper.get('title', 'N/A')}")
        print(f"   Sections: {', '.join(paper.get('sections', []))}")
        review = publication_result['outputs'].get('peer_review', {})
        print(f"   Peer Review Score: {review.get('overall_score', 0)}/10")
        print(f"   Recommendation: {review.get('recommendation', 'N/A')}")
        print(f"   Cost: {publication_result.get('cost', 0)} HBAR")
    else:
        print(f"❌ Publication failed: {publication_result.get('error')}")
    print()

    # Final Summary
    print("=" * 80)
    print("PIPELINE SUMMARY")
    print("=" * 80)

    status = pipeline.get_status()
    if status['success']:
        print(f"📊 Pipeline Status: {status['overall_status']}")
        print(f"   Research Topic: {status['research_topic'][:100]}...")
        print(f"   Total Cost: {status['spent']} / {status['budget']} HBAR")
        print(f"   Cost Breakdown:")
        for phase in status['phases']:
            if phase['cost'] > 0:
                print(f"   • {phase['phase']}: {phase['cost']} HBAR")
                if phase['agents_used']:
                    print(f"     Agents: {', '.join(phase['agents_used'])}")
    print()

    # Final output
    final = pipeline._get_final_output()
    print("📝 Final Research Output:")
    print(f"   Problem Statement: ✅")
    print(f"   Literature Corpus: ✅ ({len(final.get('literature_summary', {}).get('papers', []))} papers)")
    print(f"   Experiment Results: ✅ (simulated)")
    print(f"   Insights Generated: ✅")
    print(f"   Research Paper: ✅ (simulated)")
    print(f"   Total Cost: {final['total_cost_hbar']} HBAR")
    print()

    print("=" * 80)
    print("🎉 Research Pipeline Demo Complete!")
    print("=" * 80)
    print()
    print("Key Achievements:")
    print("✅ Problem framed using AI agent with micropayment")
    print("✅ Literature searched across multiple sources")
    print("✅ Per-paper micropayments demonstrated")
    print("✅ Complete research workflow orchestrated")
    print("✅ Agent-to-agent transactions simulated")
    print()
    print("This demonstrates how autonomous research agents can:")
    print("• Discover each other via ERC-8004")
    print("• Execute tasks with x402 micropayments")
    print("• Produce complete research outputs")
    print("• Operate with full autonomy")
    print()


async def demo_simple_agents():
    """Demo individual agents for testing."""
    print("\n" + "=" * 80)
    print("Testing Individual Agents")
    print("=" * 80 + "\n")

    # Test Problem Framer
    from agents.research.phase1_ideation.problem_framer.agent import problem_framer_agent

    print("Testing Problem Framer Agent...")
    framer_result = await problem_framer_agent.frame_problem(
        "How do blockchain payments affect AI agents?",
        context={'budget': 1.0}
    )

    if framer_result['success']:
        print("✅ Problem Framer working")
        print(f"   Payment due: {framer_result['metadata']['payment_due']} HBAR")
    else:
        print(f"❌ Problem Framer failed: {framer_result.get('error')}")

    # Test Literature Miner
    from agents.research.phase2_knowledge.literature_miner.agent import literature_miner_agent

    print("\nTesting Literature Miner Agent...")
    miner_result = await literature_miner_agent.search_literature(
        keywords=['blockchain', 'ai', 'agents'],
        research_question="Impact of blockchain on AI agents",
        max_papers=3
    )

    if miner_result['success']:
        print("✅ Literature Miner working")
        print(f"   Papers retrieved: {miner_result['metadata']['papers_retrieved']}")
        print(f"   Total cost: {miner_result['metadata']['total_cost_hbar']} HBAR")
    else:
        print(f"❌ Literature Miner failed: {miner_result.get('error')}")


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY not set in environment")
        print("Please set your OpenAI API key in .env file")
        sys.exit(1)

    # Import here to avoid issues if database models change
    from shared.database.models import ResearchPhaseType

    # Run the demo
    print("Starting Research Pipeline Demo...\n")

    # Choose demo mode
    if len(sys.argv) > 1 and sys.argv[1] == "--agents":
        # Test individual agents
        asyncio.run(demo_simple_agents())
    else:
        # Run full pipeline demo
        asyncio.run(demo_research_pipeline())

    print("\nDemo complete! Check the database for stored artifacts.")
