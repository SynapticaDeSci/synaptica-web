#!/usr/bin/env python3
"""
Reputation Management Script for ProvidAI

Usage:
  uv run python scripts/manage_reputation.py view              # View all reputations
  uv run python scripts/manage_reputation.py boost [agent_id]  # Boost specific agent (or all if no ID)
  uv run python scripts/manage_reputation.py reset             # Reset all to neutral
  uv run python scripts/manage_reputation.py set <agent_id> <score>  # Set specific score
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.database import SessionLocal, AgentReputation


def view_reputations():
    """View all agent reputations."""
    db = SessionLocal()
    try:
        reputations = db.query(AgentReputation).order_by(
            AgentReputation.reputation_score.desc()
        ).all()

        if not reputations:
            print("No agents found in database")
            return

        print("\n" + "=" * 120)
        print("Agent Reputations")
        print("=" * 120)
        print(f"{'Agent ID':<30} | {'Score':>6} | {'Tasks':>6} | {'Success':>7} | {'Quality':>7} | {'Multiplier':>10}")
        print("-" * 120)

        for rep in reputations:
            success_rate = f"{rep.successful_tasks}/{rep.total_tasks}" if rep.total_tasks > 0 else "0/0"
            print(
                f"{rep.agent_id:<30} | "
                f"{rep.reputation_score:>6.2f} | "
                f"{rep.total_tasks:>6} | "
                f"{success_rate:>7} | "
                f"{rep.average_quality_score:>7.2f} | "
                f"{rep.payment_multiplier:>10.2f}x"
            )

        print("=" * 120)
        print(f"\nTotal agents: {len(reputations)}")
        print(f"Average reputation: {sum(r.reputation_score for r in reputations) / len(reputations):.2f}")

    finally:
        db.close()


def boost_agent(agent_id: str = None, score: float = 0.9):
    """
    Boost agent reputation to high level.

    Args:
        agent_id: Specific agent to boost, or None for all agents
        score: Target reputation score (default: 0.9)
    """
    db = SessionLocal()
    try:
        if agent_id:
            # Boost specific agent
            rep = db.query(AgentReputation).filter(
                AgentReputation.agent_id == agent_id
            ).first()

            if not rep:
                print(f"❌ Agent '{agent_id}' not found")
                return

            agents = [rep]
        else:
            # Boost all agents
            agents = db.query(AgentReputation).all()

        for agent in agents:
            agent.reputation_score = score
            agent.total_tasks = max(agent.total_tasks, 100)
            agent.successful_tasks = max(agent.successful_tasks, int(100 * score))
            agent.average_quality_score = score * 0.95  # Slightly lower than reputation

            # Update payment multiplier
            if agent.reputation_score >= 0.8:
                agent.payment_multiplier = 1.2
            elif agent.reputation_score >= 0.6:
                agent.payment_multiplier = 1.0
            elif agent.reputation_score >= 0.4:
                agent.payment_multiplier = 0.9
            else:
                agent.payment_multiplier = 0.8

        db.commit()

        if agent_id:
            print(f"✅ Boosted {agent_id} to {score:.2f} reputation")
        else:
            print(f"✅ Boosted {len(agents)} agents to {score:.2f} reputation")

    finally:
        db.close()


def reset_reputations():
    """Reset all agent reputations to neutral (0.5)."""
    db = SessionLocal()
    try:
        count = db.query(AgentReputation).update({
            "reputation_score": 0.5,
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "average_quality_score": 0.0,
            "payment_multiplier": 1.0
        })
        db.commit()

        print(f"✅ Reset {count} agents to neutral reputation (0.5)")

    finally:
        db.close()


def set_reputation(agent_id: str, score: float):
    """Set specific reputation score for an agent."""
    if score < 0.0 or score > 1.0:
        print("❌ Score must be between 0.0 and 1.0")
        return

    db = SessionLocal()
    try:
        rep = db.query(AgentReputation).filter(
            AgentReputation.agent_id == agent_id
        ).first()

        if not rep:
            print(f"❌ Agent '{agent_id}' not found")
            return

        rep.reputation_score = score

        # Adjust payment multiplier
        if rep.reputation_score >= 0.8:
            rep.payment_multiplier = 1.2
        elif rep.reputation_score >= 0.6:
            rep.payment_multiplier = 1.0
        elif rep.reputation_score >= 0.4:
            rep.payment_multiplier = 0.9
        else:
            rep.payment_multiplier = 0.8

        db.commit()

        print(f"✅ Set {agent_id} reputation to {score:.2f} (multiplier: {rep.payment_multiplier:.2f}x)")

    finally:
        db.close()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "view":
        view_reputations()

    elif command == "boost":
        if len(sys.argv) >= 3:
            agent_id = sys.argv[2]
            boost_agent(agent_id)
        else:
            boost_agent()  # Boost all

    elif command == "reset":
        confirm = input("⚠️  This will reset ALL agent reputations to 0.5. Continue? (yes/no): ")
        if confirm.lower() == "yes":
            reset_reputations()
        else:
            print("Cancelled")

    elif command == "set":
        if len(sys.argv) < 4:
            print("Usage: uv run python scripts/manage_reputation.py set <agent_id> <score>")
            print("Example: uv run python scripts/manage_reputation.py set problem-framer-001 0.95")
            sys.exit(1)

        agent_id = sys.argv[2]
        try:
            score = float(sys.argv[3])
        except ValueError:
            print(f"❌ Invalid score: {sys.argv[3]}")
            print("Score must be a number between 0.0 and 1.0")
            sys.exit(1)

        set_reputation(agent_id, score)

    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
