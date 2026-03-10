"""Verifier Agent implementation using OpenAI API."""

from shared.strands_openai_agent import AsyncStrandsAgent, create_strands_openai_agent

from .system_prompt import VERIFIER_SYSTEM_PROMPT
from .research_system_prompt import RESEARCH_VERIFIER_SYSTEM_PROMPT
from .tools import (
    verify_task_result,
    validate_output_schema,
    check_quality_metrics,
    release_payment,
    reject_and_refund,
    run_verification_code,
    run_unit_tests,
    validate_code_output,
    search_web,
    verify_fact,
    check_data_source_credibility,
    research_best_practices,
    verify_research_output,
    calculate_quality_score,
    check_citation_quality,
    validate_statistical_significance,
    generate_feedback_report,
)


def create_verifier_agent(use_research_mode: bool = False) -> AsyncStrandsAgent:
    """
    Create and configure the Verifier agent with advanced verification capabilities.

    The Verifier now includes:
    - Code execution for automated testing
    - Web search for fact-checking
    - Data source credibility assessment
    - Research-specific verification (if use_research_mode=True)

    Args:
        use_research_mode: If True, use research-specific system prompt and tools

    Returns:
        Configured OpenAI Agent instance
    """
    # Base tools (always included)
    tools = [
        # Core verification
        verify_task_result,
        validate_output_schema,
        check_quality_metrics,
        # Payment management
        release_payment,
        reject_and_refund,
        # Code execution
        run_verification_code,
        run_unit_tests,
        validate_code_output,
        # Web search & fact-checking
        search_web,
        verify_fact,
        check_data_source_credibility,
        research_best_practices,
    ]

    # Add research-specific tools if in research mode
    if use_research_mode:
        tools.extend([
            verify_research_output,
            calculate_quality_score,
            check_citation_quality,
            validate_statistical_significance,
            generate_feedback_report,
        ])
        system_prompt = RESEARCH_VERIFIER_SYSTEM_PROMPT
    else:
        system_prompt = VERIFIER_SYSTEM_PROMPT

    agent = create_strands_openai_agent(
        system_prompt=system_prompt,
        tools=tools,
        model_env_var="VERIFIER_MODEL",
        agent_id="verifier-agent",
        name="Verifier",
        description="Verifies outputs and manages release or refund decisions.",
    )

    return agent


def create_research_verifier_agent() -> AsyncStrandsAgent:
    """
    Create a Research Verifier agent specialized for academic research pipeline.

    This is a convenience function that creates a verifier agent with research mode enabled.

    Returns:
        Configured OpenAI Agent instance for research verification
    """
    return create_verifier_agent(use_research_mode=True)


# Example usage
async def run_verifier_example():
    """Example of using the verifier agent with advanced verification."""
    agent = create_verifier_agent()

    request = """
    Verify task task-123 with comprehensive checks:

    1. Basic verification:
       - Required fields: ["summary", "insights", "data"]
       - Quality threshold: 80
       - Max errors: 2

    2. Code-based verification:
       - Write Python code to verify data completeness is >= 95%
       - Run statistical analysis on the insights

    3. Fact-checking:
       - The task claims "Average SaaS churn rate is 5% monthly"
       - Use web search to verify this claim

    4. Data source credibility:
       - Check if data sources mentioned are credible

    If all verification passes, release payment payment-456.
    """

    result = await agent.run(request)
    print(result)


async def run_code_verification_example():
    """Example of code-based verification."""
    agent = create_verifier_agent()

    request = """
    Task task-123 returned analysis results. Verify quality by running this code:

    ```python
    import json
    import sys

    # Load task results
    task_result = json.loads(sys.argv[1])

    # Check data completeness
    data = task_result.get('data', [])
    completeness = len([x for x in data if x is not None]) / len(data) * 100

    # Check insights quality
    insights = task_result.get('insights', [])
    has_insights = len(insights) >= 3

    # Validation
    if completeness >= 95 and has_insights:
        print(f"PASS: Completeness {completeness}%, {len(insights)} insights")
        sys.exit(0)
    else:
        print(f"FAIL: Completeness {completeness}%, {len(insights)} insights")
        sys.exit(1)
    ```

    If code verification passes, release payment.
    """

    result = await agent.run(request)
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_verifier_example())
