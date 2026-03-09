#!/usr/bin/env python
"""
Quick test script to verify OpenAI integration is working.

Run with: uv run python scripts/test_openai_integration.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

if __name__ != "__main__":  # pragma: no cover - skip under pytest collection
    import pytest

    pytest.skip(
        "scripts/test_openai_integration.py is an interactive smoke test and should be run manually",
        allow_module_level=True,
    )

# Load environment variables
load_dotenv(override=True)

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_openai_connection():
    """Test basic OpenAI connection."""
    print("=" * 60)
    print("Testing OpenAI Integration")
    print("=" * 60)
    print()

    # Check API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in environment")
        return False

    print(f"✅ API key found: {api_key[:10]}...")
    print()

    # Test OpenAI client
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)

        print("Testing GPT-3.5-turbo (cheaper model)...")
        response = await client.chat.completions.create(
            model="gpt-5.4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Hello, ProvidAI is working!' in exactly those words."}
            ],
            max_tokens=50,
            temperature=0.0
        )

        result = response.choices[0].message.content
        print(f"Response: {result}")
        print("✅ GPT-3.5-turbo works!")
        print()

        # Test GPT-4 if you want (more expensive)
        print("Testing GPT-4-turbo (advanced model)...")
        response2 = await client.chat.completions.create(
            model="gpt-5.4",
            messages=[
                {"role": "system", "content": "You are a research assistant."},
                {"role": "user", "content": "In one sentence, what is blockchain?"}
            ],
            max_tokens=100,
            temperature=0.3
        )

        result2 = response2.choices[0].message.content
        print(f"Response: {result2}")
        print("✅ GPT-4-turbo works!")
        print()

        return True

    except Exception as e:
        print(f"❌ Error testing OpenAI: {e}")
        return False


async def test_openai_agent_wrapper():
    """Test our OpenAI agent wrapper."""
    print("=" * 60)
    print("Testing OpenAI Agent Wrapper")
    print("=" * 60)
    print()

    try:
        from shared.openai_agent import Agent

        # Create agent
        agent = Agent(
            model="gpt-5.4",
            system_prompt="You are a helpful research assistant specialized in blockchain technology.",
            tools=[]
        )

        # Test simple query
        result = await agent.run("What is the main benefit of using blockchain for AI agent marketplaces? Answer in one sentence.")
        print("Agent Response:")
        print(result)
        print()
        print("✅ Agent wrapper works!")

        return True

    except Exception as e:
        print(f"❌ Error testing agent wrapper: {e}")
        return False


async def test_research_agent():
    """Test a research agent with OpenAI."""
    print("=" * 60)
    print("Testing Research Agent with OpenAI")
    print("=" * 60)
    print()

    try:
        # Import after environment setup
        from agents.research.phase1_ideation.problem_framer.agent import ProblemFramerAgent

        # Create agent (will use OpenAI now)
        agent = ProblemFramerAgent()
        print(f"Created agent: {agent.agent_id}")
        print(f"Using model: {agent.model}")
        print()

        # Test problem framing
        result = await agent.frame_problem(
            query="How can blockchain reduce costs in AI agent marketplaces?",
            context={"budget": 1.0}
        )

        if result['success']:
            print("✅ Problem Framer Agent works with OpenAI!")
            problem = result['problem_statement']
            print(f"Research Question: {problem.get('research_question', 'N/A')[:100]}...")
            print(f"Keywords: {', '.join(problem.get('keywords', [])[:5])}")
        else:
            print(f"❌ Problem framing failed: {result.get('error')}")
            return False

        return True

    except Exception as e:
        print(f"❌ Error testing research agent: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("ProvidAI OpenAI Integration Test Suite")
    print("=" * 60)
    print()

    # Check environment
    print("Environment Check:")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Working Directory: {os.getcwd()}")
    print()

    # Run tests
    tests = [
        ("OpenAI Connection", test_openai_connection),
        ("Agent Wrapper", test_openai_agent_wrapper),
        ("Research Agent", test_research_agent),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\nRunning: {test_name}")
        print("-" * 40)
        success = await test_func()
        results.append((test_name, success))
        print()

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name}: {status}")

    all_passed = all(success for _, success in results)
    print()
    if all_passed:
        print("🎉 All tests passed! Your OpenAI integration is working correctly.")
        print("\nNext steps:")
        print("1. Run the full demo: uv run python scripts/demo_research_pipeline.py")
        print("2. Monitor your OpenAI usage at: https://platform.openai.com/usage")
        print("3. Set up Hedera testnet credentials in .env")
    else:
        print("⚠️ Some tests failed. Please check the errors above.")
        print("\nCommon issues:")
        print("- Invalid API key: Check your OPENAI_API_KEY in .env")
        print("- Rate limits: Check your OpenAI account limits")
        print("- Network issues: Ensure you have internet connection")


if __name__ == "__main__":
    asyncio.run(main())
