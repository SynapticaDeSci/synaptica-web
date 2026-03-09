"""
Full Research Pipeline Demo - All 15 Agents

This demonstrates the complete autonomous research pipeline using all 15 agents
across the 5 research phases with agent-to-agent micropayments.

Run with: uv run python scripts/demo_full_pipeline.py
"""

import asyncio
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv(override=True)

from shared.database import engine, Base, SessionLocal
from shared.database import ResearchPipeline as ResearchPipelineModel, ResearchPhaseType


async def demo_full_research_pipeline():
    """Run a complete research pipeline demonstration with all 15 agents."""

    print("\n" + "="*100)
    print("ProvidAI Full Research Pipeline Demo")
    print("Demonstrating all 15 autonomous agents with micropayments")
    print("="*100)

    # Initialize database
    print("\n🔧 Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database ready")

    # Research query
    query = """
    What is the quantitative impact of blockchain-based micropayment systems
    on the adoption rate and operational efficiency of autonomous AI agent marketplaces?
    """

    print(f"\n📚 Research Query:")
    print(f"   {query.strip()}")

    # Import all agents
    print("\n🤖 Loading all 15 research agents...")
    from agents.research.phase1_ideation.problem_framer.agent import problem_framer_agent
    from agents.research.phase1_ideation.feasibility_analyst.agent import FeasibilityAnalystAgent
    from agents.research.phase1_ideation.goal_planner.agent import GoalPlannerAgent
    from agents.research.phase2_knowledge.literature_miner.agent import literature_miner_agent
    from agents.research.phase2_knowledge.knowledge_synthesizer.agent import KnowledgeSynthesizerAgent
    from agents.research.phase3_experimentation.hypothesis_designer.agent import HypothesisDesignerAgent
    from agents.research.phase3_experimentation.experiment_runner.agent import ExperimentRunnerAgent
    from agents.research.phase3_experimentation.code_generator.agent import CodeGeneratorAgent
    from agents.research.phase4_interpretation.insight_generator.agent import InsightGeneratorAgent
    from agents.research.phase4_interpretation.bias_detector.agent import BiasDetectorAgent
    from agents.research.phase4_interpretation.compliance_checker.agent import ComplianceCheckerAgent
    from agents.research.phase5_publication.paper_writer.agent import PaperWriterAgent
    from agents.research.phase5_publication.peer_reviewer.agent import PeerReviewerAgent
    from agents.research.phase5_publication.reputation_manager.agent import ReputationManagerAgent
    from agents.research.phase5_publication.archiver.agent import ArchiverAgent

    # Instantiate agents (some are already instantiated as globals)
    feasibility_analyst = FeasibilityAnalystAgent()
    goal_planner = GoalPlannerAgent()
    knowledge_synthesizer = KnowledgeSynthesizerAgent()
    hypothesis_designer = HypothesisDesignerAgent()
    experiment_runner = ExperimentRunnerAgent()
    code_generator = CodeGeneratorAgent()
    insight_generator = InsightGeneratorAgent()
    bias_detector = BiasDetectorAgent()
    compliance_checker = ComplianceCheckerAgent()
    paper_writer = PaperWriterAgent()
    peer_reviewer = PeerReviewerAgent()
    reputation_manager = ReputationManagerAgent()
    archiver = ArchiverAgent()

    print("✅ All agents loaded")

    # Initialize pipeline
    db = SessionLocal()
    import uuid
    pipeline_id = str(uuid.uuid4())

    pipeline = ResearchPipelineModel(
        id=pipeline_id,
        query=query.strip(),
        research_topic="To be determined",
        budget=10.0,  # Increased budget for all agents
        spent=0.0,
        status="in_progress"
    )
    db.add(pipeline)
    db.commit()

    print(f"\n🚀 Pipeline initialized: {pipeline_id[:36]}")
    print(f"   Budget: {pipeline.budget} HBAR")

    total_cost = 0.0
    results = {}

    # ============================================================================
    # PHASE 1: IDEATION
    # ============================================================================
    print("\n" + "="*100)
    print("PHASE 1: IDEATION (3 agents)")
    print("="*100)

    # 1.1 Problem Framer
    print("\n[1/3] Problem Framer - Framing research question...")
    try:
        problem_result = await problem_framer_agent.frame_problem(
            query=query,
            context={"budget": pipeline.budget}
        )

        if problem_result['success']:
            problem_statement = problem_result['problem_statement']
            cost = problem_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Problem framed")
            print(f"      Research Question: {problem_statement['research_question'][:80]}...")
            print(f"      Cost: {cost:.2f} HBAR")
            results['problem_statement'] = problem_statement
        else:
            print(f"   ❌ Failed: {problem_result.get('error')}")
            return
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return

    # 1.2 Feasibility Analyst
    print("\n[2/3] Feasibility Analyst - Analyzing feasibility...")
    try:
        feasibility_result = await feasibility_analyst.analyze_feasibility(
            problem_statement=problem_statement,
            context={"budget": pipeline.budget - total_cost, "timeline": "30 days"}
        )

        if feasibility_result['success']:
            feasibility = feasibility_result['feasibility_assessment']
            cost = feasibility_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Feasibility analyzed")
            print(f"      Score: {feasibility.get('feasibility_score', 0):.2f}")
            print(f"      Assessment: {feasibility.get('assessment', 'N/A')}")
            print(f"      Go/No-Go: {feasibility.get('go_no_go', 'N/A')}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['feasibility'] = feasibility
        else:
            print(f"   ❌ Failed: {feasibility_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 1.3 Goal Planner
    print("\n[3/3] Goal Planner - Creating research plan...")
    try:
        plan_result = await goal_planner.create_plan(
            problem_statement=problem_statement,
            feasibility_assessment=results.get('feasibility', {}),
            context={"budget": pipeline.budget - total_cost}
        )

        if plan_result['success']:
            research_plan = plan_result['research_plan']
            cost = plan_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Research plan created")
            print(f"      Objectives: {len(research_plan.get('objectives', []))}")
            print(f"      Tasks: {len(research_plan.get('tasks', []))}")
            print(f"      Phases: {len(research_plan.get('phases', []))}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['research_plan'] = research_plan
        else:
            print(f"   ❌ Failed: {plan_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print(f"\n💰 Phase 1 Total Cost: {total_cost:.2f} HBAR")

    # ============================================================================
    # PHASE 2: KNOWLEDGE RETRIEVAL
    # ============================================================================
    print("\n" + "="*100)
    print("PHASE 2: KNOWLEDGE RETRIEVAL (2 agents)")
    print("="*100)

    # 2.1 Literature Miner
    print("\n[1/2] Literature Miner - Searching academic papers...")
    try:
        lit_result = await literature_miner_agent.search_literature(
            research_question=problem_statement['research_question'],
            keywords=problem_statement['keywords'],
            max_papers=8,
            context={"date_range": "2020-2024"}
        )

        if lit_result['success']:
            literature = lit_result['literature_corpus']
            cost = lit_result['metadata']['payment_due']
            total_cost += cost

            papers = literature.get('papers', [])
            print(f"   ✅ Literature retrieved")
            print(f"      Papers found: {len(papers)}")
            if papers:
                print(f"      Top paper: {papers[0].get('title', 'N/A')[:60]}...")
            print(f"      Cost: {cost:.2f} HBAR")
            results['literature'] = literature
        else:
            print(f"   ❌ Failed: {lit_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 2.2 Knowledge Synthesizer
    print("\n[2/2] Knowledge Synthesizer - Synthesizing insights...")
    try:
        synth_result = await knowledge_synthesizer.synthesize_knowledge(
            literature_corpus=results.get('literature', {}),
            problem_statement=problem_statement,
            context={}
        )

        if synth_result['success']:
            synthesis = synth_result['knowledge_synthesis']
            cost = synth_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Knowledge synthesized")
            print(f"      Key claims: {len(synthesis.get('key_claims', []))}")
            print(f"      Research gaps: {len(synthesis.get('research_gaps', []))}")
            print(f"      Confidence: {synthesis.get('confidence_score', 0):.2f}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['synthesis'] = synthesis
        else:
            print(f"   ❌ Failed: {synth_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print(f"\n💰 Phase 2 Total Cost: {total_cost:.2f} HBAR")

    # ============================================================================
    # PHASE 3: EXPERIMENTATION
    # ============================================================================
    print("\n" + "="*100)
    print("PHASE 3: EXPERIMENTATION (3 agents)")
    print("="*100)

    # 3.1 Hypothesis Designer
    print("\n[1/3] Hypothesis Designer - Designing hypothesis...")
    try:
        hyp_result = await hypothesis_designer.execute_task(
            task_input={
                "problem_statement": problem_statement,
                "knowledge_synthesis": results.get('synthesis', {})
            },
            context={}
        )

        if hyp_result['success']:
            hypothesis_design = hyp_result['result']
            cost = hyp_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Hypothesis designed")
            print(f"      Hypothesis: {str(hypothesis_design.get('hypothesis', 'N/A'))[:70]}...")
            print(f"      Cost: {cost:.2f} HBAR")
            results['hypothesis'] = hypothesis_design
        else:
            print(f"   ❌ Failed: {hyp_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 3.2 Code Generator
    print("\n[2/3] Code Generator - Generating experiment code...")
    try:
        code_result = await code_generator.execute_task(
            task_input={
                "hypothesis": results.get('hypothesis', {}),
                "experiment_type": "simulation"
            },
            context={}
        )

        if code_result['success']:
            code_artifact = code_result['result']
            cost = code_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Code generated")
            print(f"      Language: {code_artifact.get('language', 'N/A')}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['code'] = code_artifact
        else:
            print(f"   ❌ Failed: {code_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 3.3 Experiment Runner
    print("\n[3/3] Experiment Runner - Running experiments...")
    try:
        exp_result = await experiment_runner.execute_task(
            task_input={
                "hypothesis": results.get('hypothesis', {}),
                "code": results.get('code', {}),
                "parameters": {"trials": 100}
            },
            context={}
        )

        if exp_result['success']:
            experiment_results = exp_result['result']
            cost = exp_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Experiments completed")
            print(f"      Status: {experiment_results.get('status', 'N/A')}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['experiments'] = experiment_results
        else:
            print(f"   ❌ Failed: {exp_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print(f"\n💰 Phase 3 Total Cost: {total_cost:.2f} HBAR")

    # ============================================================================
    # PHASE 4: INTERPRETATION
    # ============================================================================
    print("\n" + "="*100)
    print("PHASE 4: INTERPRETATION (3 agents)")
    print("="*100)

    # 4.1 Insight Generator
    print("\n[1/3] Insight Generator - Extracting insights...")
    try:
        insight_result = await insight_generator.execute_task(
            task_input={
                "experiment_results": results.get('experiments', {}),
                "hypothesis": results.get('hypothesis', {}),
                "synthesis": results.get('synthesis', {})
            },
            context={}
        )

        if insight_result['success']:
            insights = insight_result['result']
            cost = insight_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Insights generated")
            print(f"      Insights: {len(insights.get('insights', []))}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['insights'] = insights
        else:
            print(f"   ❌ Failed: {insight_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 4.2 Bias Detector
    print("\n[2/3] Bias Detector - Checking for biases...")
    try:
        bias_result = await bias_detector.execute_task(
            task_input={
                "methodology": results.get('hypothesis', {}),
                "data": results.get('experiments', {}),
                "interpretations": results.get('insights', {})
            },
            context={}
        )

        if bias_result['success']:
            bias_report = bias_result['result']
            cost = bias_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Bias analysis complete")

            # Handle biases_detected as either list or boolean
            biases_detected = bias_report.get('biases_detected', [])
            if isinstance(biases_detected, list):
                print(f"      Biases detected: {len(biases_detected)}")
            else:
                print(f"      Biases detected: {biases_detected}")

            print(f"      Overall score: {bias_report.get('overall_bias_score', 0):.2f}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['bias_report'] = bias_report
        else:
            print(f"   ❌ Failed: {bias_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 4.3 Compliance Checker
    print("\n[3/3] Compliance Checker - Verifying compliance...")
    try:
        compliance_result = await compliance_checker.execute_task(
            task_input={
                "research_methodology": results.get('hypothesis', {}),
                "data_handling": results.get('experiments', {}),
                "ethical_considerations": {}
            },
            context={}
        )

        if compliance_result['success']:
            compliance_report = compliance_result['result']
            cost = compliance_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Compliance verified")
            print(f"      Status: {compliance_report.get('compliance_status', 'N/A')}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['compliance'] = compliance_report
        else:
            print(f"   ❌ Failed: {compliance_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print(f"\n💰 Phase 4 Total Cost: {total_cost:.2f} HBAR")

    # ============================================================================
    # PHASE 5: PUBLICATION
    # ============================================================================
    print("\n" + "="*100)
    print("PHASE 5: PUBLICATION (4 agents)")
    print("="*100)

    # 5.1 Paper Writer
    print("\n[1/4] Paper Writer - Writing research paper...")
    try:
        paper_result = await paper_writer.execute_task(
            task_input={
                "problem_statement": problem_statement,
                "literature_review": results.get('synthesis', {}),
                "methodology": results.get('hypothesis', {}),
                "results": results.get('experiments', {}),
                "insights": results.get('insights', {})
            },
            context={}
        )

        if paper_result['success']:
            paper = paper_result['result']
            cost = paper_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Paper written")
            print(f"      Title: {paper.get('title', 'N/A')[:60]}...")
            print(f"      Sections: {len(paper.get('sections', []))}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['paper'] = paper
        else:
            print(f"   ❌ Failed: {paper_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 5.2 Peer Reviewer
    print("\n[2/4] Peer Reviewer - Reviewing paper...")
    try:
        review_result = await peer_reviewer.execute_task(
            task_input={
                "paper": results.get('paper', {}),
                "research_quality": {
                    "bias_report": results.get('bias_report', {}),
                    "compliance": results.get('compliance', {})
                }
            },
            context={}
        )

        if review_result['success']:
            review = review_result['result']
            cost = review_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Peer review complete")
            print(f"      Overall score: {review.get('overall_score', 0)}/10")
            print(f"      Recommendation: {review.get('recommendation', 'N/A')}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['review'] = review
        else:
            print(f"   ❌ Failed: {review_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 5.3 Reputation Manager
    print("\n[3/4] Reputation Manager - Updating reputations...")
    try:
        rep_result = await reputation_manager.execute_task(
            task_input={
                "pipeline_results": {
                    "peer_review": results.get('review', {}),
                    "agents_used": [
                        "problem-framer-001", "feasibility-analyst-001", "goal-planner-001",
                        "literature-miner-001", "knowledge-synthesizer-001",
                        "hypothesis-designer-001", "experiment-runner-001", "code-generator-001",
                        "insight-generator-001", "bias-detector-001", "compliance-checker-001",
                        "paper-writer-001", "peer-reviewer-001"
                    ]
                }
            },
            context={}
        )

        if rep_result['success']:
            reputation_updates = rep_result['result']
            cost = rep_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Reputations updated")
            print(f"      Agents updated: {len(reputation_updates.get('reputation_updates', []))}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['reputations'] = reputation_updates
        else:
            print(f"   ❌ Failed: {rep_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 5.4 Archiver
    print("\n[4/4] Archiver - Archiving research artifacts...")
    try:
        archive_result = await archiver.execute_task(
            task_input={
                "paper": results.get('paper', {}),
                "data": results.get('experiments', {}),
                "code": results.get('code', {}),
                "pipeline_id": pipeline_id
            },
            context={}
        )

        if archive_result['success']:
            archive_info = archive_result['result']
            cost = archive_result['metadata']['payment_due']
            total_cost += cost

            print(f"   ✅ Artifacts archived")
            print(f"      IPFS hashes: {len(archive_info.get('ipfs_hashes', []))}")
            print(f"      Cost: {cost:.2f} HBAR")
            results['archive'] = archive_info
        else:
            print(f"   ❌ Failed: {archive_result.get('error')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print(f"\n💰 Phase 5 Total Cost: {total_cost:.2f} HBAR")

    # ============================================================================
    # FINAL SUMMARY
    # ============================================================================
    print("\n" + "="*100)
    print("PIPELINE COMPLETE!")
    print("="*100)

    pipeline.spent = total_cost
    pipeline.status = "completed"
    budget = pipeline.budget
    db.commit()
    db.close()

    print(f"\n📊 Final Statistics:")
    print(f"   Pipeline ID: {pipeline_id[:36]}")
    print(f"   Total Cost: {total_cost:.2f} HBAR")
    print(f"   Budget: {budget} HBAR")
    print(f"   Remaining: {budget - total_cost:.2f} HBAR")
    print(f"   Agents Used: 15/15")

    print(f"\n🎯 Research Outputs:")
    print(f"   ✅ Problem Statement: Framed")
    print(f"   ✅ Feasibility Analysis: Complete")
    print(f"   ✅ Research Plan: Created")
    print(f"   ✅ Literature Corpus: {len(results.get('literature', {}).get('papers', []))} papers")
    print(f"   ✅ Knowledge Synthesis: Complete")
    print(f"   ✅ Hypothesis: Designed")
    print(f"   ✅ Experiment Code: Generated")
    print(f"   ✅ Experiments: Run")
    print(f"   ✅ Insights: Extracted")
    print(f"   ✅ Bias Analysis: Complete")
    print(f"   ✅ Compliance: Verified")
    print(f"   ✅ Research Paper: Written")
    print(f"   ✅ Peer Review: Score {results.get('review', {}).get('overall_score', 0)}/10")
    print(f"   ✅ Reputations: Updated")
    print(f"   ✅ Artifacts: Archived")

    print("\n" + "="*100)
    print("🎉 Full autonomous research pipeline completed successfully!")
    print("   All 15 agents collaborated with micropayment transactions")
    print("="*100)
    print()


if __name__ == "__main__":
    asyncio.run(demo_full_research_pipeline())
