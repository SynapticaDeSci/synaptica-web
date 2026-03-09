"""
Run Executor Agent - Interactive or Programmatic Usage

This script demonstrates how to run the Executor agent to:
1. Query agents from Hedera registry
2. Fetch metadata from URIs
3. Create dynamic tools from metadata
4. Execute agent tools

Usage:
    # Interactive mode
    uv run python scripts/run_executor_agent.py

    # Programmatic mode
    uv run python scripts/run_executor_agent.py --query "Use agent trading-assistant-001 to analyze BTC/USD"
"""

import asyncio
import os
import sys
import argparse
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv(override=True)

from agents.executor.agent import create_executor_agent


async def run_executor_interactive():
    """Run executor agent in interactive mode."""
    print("\n" + "="*80)
    print("Executor Agent - Interactive Mode")
    print("="*80)
    print("\nThe executor agent can:")
    print("  1. Query agents from Hedera registry")
    print("  2. Fetch metadata from URIs (ERC-8004)")
    print("  3. Create dynamic tools from metadata")
    print("  4. Execute agent tools")
    print("\nEnter your request, or 'exit' to quit.")
    print("="*80)
    
    agent = create_executor_agent()
    
    while True:
        try:
            print("\n> ", end="", flush=True)
            user_input = input().strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\nExiting...")
                break
            
            print("\n🤖 Executor thinking...\n")
            result = await agent.run(user_input)
            print("\n📝 Result:")
            print(result)
            print("\n" + "-"*80)
            
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


async def run_executor_query(query: str):
    """Run executor agent with a specific query."""
    print(f"\n🤖 Executor Agent Processing Query...")
    print(f"Query: {query}\n")
    
    agent = create_executor_agent()
    result = await agent.run(query)
    
    print("\n📝 Result:")
    print(result)
    return result


async def demo_query_agent_by_domain():
    """Demo: Query agent by domain from registry."""
    print("\n" + "="*80)
    print("Demo 1: Query Agent by Domain")
    print("="*80)
    
    query = """
    Query an agent from the Hedera registry by domain name "reputation-manager-001".
    Show me the agent information including agent_id, domain, address, and metadata URI if available.
    """
    
    await run_executor_query(query)


async def demo_use_agent_tool():
    """Demo: Use agent tool from metadata."""
    print("\n" + "="*80)
    print("Demo 2: Use Agent Tool from Metadata")
    print("="*80)
    
    query = """
    Use an agent tool for the agent with domain "trading-assistant-001".
    
    Steps:
    1. Query the agent from registry
    2. Get the metadata URI
    3. Fetch the metadata from URI
    4. Create a dynamic tool from the metadata
    5. Execute the tool with sample parameters
    
    Use the first available endpoint if there are multiple endpoints.
    """
    
    await run_executor_query(query)


async def demo_list_all_agents():
    """Demo: List all agents in registry."""
    print("\n" + "="*80)
    print("Demo 3: List All Agents")
    print("="*80)
    
    query = """
    List all agents registered on the Hedera smart contract registry.
    Show me the first 10 agents with their agent_id, domain, and address.
    """
    
    await run_executor_query(query)


async def demo_create_tool_from_metadata():
    """Demo: Create tool from metadata manually."""
    print("\n" + "="*80)
    print("Demo 4: Create Tool from Metadata")
    print("="*80)
    
    query = """
    For agent domain "trading-assistant-001":
    1. Get the agent metadata (including metadata URI)
    2. Fetch the metadata JSON from the URI
    3. Create dynamic tools for all API endpoints found in the metadata
    4. Show me which tools were created
    
    Do not execute the tools, just create them.
    """
    
    await run_executor_query(query)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Executor Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  uv run python scripts/run_executor_agent.py
  
  # Run with query
  uv run python scripts/run_executor_agent.py --query "List all agents"
  
  # Run demo
  uv run python scripts/run_executor_agent.py --demo query-agent
  uv run python scripts/run_executor_agent.py --demo use-tool
  uv run python scripts/run_executor_agent.py --demo list-agents
  uv run python scripts/run_executor_agent.py --demo create-tool
        """
    )
    
    parser.add_argument(
        "--query",
        type=str,
        help="Query to send to executor agent"
    )
    
    parser.add_argument(
        "--demo",
        choices=["query-agent", "use-tool", "list-agents", "create-tool", "all"],
        help="Run a demo scenario"
    )
    
    args = parser.parse_args()
    
    # Check for required environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        print("\nPlease set it in your .env file or export it:")
        print("  export OPENAI_API_KEY='your-key-here'")
        sys.exit(1)
    
    # Run based on arguments
    if args.query:
        asyncio.run(run_executor_query(args.query))
    elif args.demo:
        if args.demo == "query-agent":
            asyncio.run(demo_query_agent_by_domain())
        elif args.demo == "use-tool":
            asyncio.run(demo_use_agent_tool())
        elif args.demo == "list-agents":
            asyncio.run(demo_list_all_agents())
        elif args.demo == "create-tool":
            asyncio.run(demo_create_tool_from_metadata())
        elif args.demo == "all":
            print("\n🚀 Running all demos...\n")
            asyncio.run(demo_query_agent_by_domain())
            asyncio.run(demo_list_all_agents())
            asyncio.run(demo_create_tool_from_metadata())
            asyncio.run(demo_use_agent_tool())
    else:
        # Interactive mode
        asyncio.run(run_executor_interactive())


if __name__ == "__main__":
    main()

