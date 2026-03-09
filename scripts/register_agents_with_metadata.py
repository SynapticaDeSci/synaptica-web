#!/usr/bin/env python
"""Register agents to the IdentityRegistry contract with metadata URIs."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Ensure direct script execution can import repo-root packages.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.database import SessionLocal, Agent as AgentModel
from shared.registry import (
    AgentRegistryConfigError,
    AgentRegistryRegistrationError,
    AgentRegistryResult,
    get_registry_client,
)

load_dotenv(override=True)

REGISTRY_CLIENT = None


def _client():
    global REGISTRY_CLIENT
    if REGISTRY_CLIENT is None:
        try:
            REGISTRY_CLIENT = get_registry_client()
        except AgentRegistryConfigError as exc:  # pragma: no cover - env/config error
            print(f"\n❌ Registry configuration error: {exc}")
            sys.exit(1)
    return REGISTRY_CLIENT


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _default_metadata_uri(domain: str) -> str:
    settings = _client().settings
    return f"{settings.metadata_base_url.rstrip('/')}/{domain}.json"


def _summarize_result(result: AgentRegistryResult) -> None:
    if result.status == "registered":
        print(f"   ✅ Registered agent '{result.domain}' (ID: {result.agent_id})")
        if result.tx_hash:
            print(f"   ⏳ Transaction: {result.tx_hash}")
    elif result.status == "metadata_updated":
        print(f"   🔁 Updated metadata for agent ID {result.agent_id}")
        if result.tx_hash:
            print(f"   ⏳ Transaction: {result.tx_hash}")
    elif result.status == "already_registered":
        print(f"   ✅ Agent '{result.domain}' already up to date (ID: {result.agent_id})")
    else:
        print(f"   ⚠️ Unknown result status: {result.status}")


def register_agent_on_chain(
    domain: str,
    *,
    metadata_uri: Optional[str] = None,
    registry_agent_id: Optional[int] = None,
) -> Optional[AgentRegistryResult]:
    metadata_uri = (metadata_uri or _default_metadata_uri(domain)).strip()
    print(f"   📄 Metadata URI: {metadata_uri}")

    try:
        result = _client().register_agent(
            domain,
            metadata_uri=metadata_uri,
            registry_agent_id=registry_agent_id,
        )
    except AgentRegistryRegistrationError as exc:
        print(f"   ❌ Registration failed: {exc}")
        return None

    _summarize_result(result)
    return result


def get_agent_count() -> int:
    try:
        return _client().get_agent_count()
    except AgentRegistryRegistrationError as exc:
        print(f"Error getting agent count: {exc}")
        return 0


def list_registered_agents() -> None:
    _print_header("REGISTERED AGENTS ON IDENTITY REGISTRY")

    try:
        count = _client().get_agent_count()
    except AgentRegistryRegistrationError as exc:
        print(f"\n❌ Error loading registry: {exc}")
        return

    print(f"\n📊 Total agents registered: {count}")
    if count == 0:
        print("\n⚠️  No agents registered yet")
        return

    contract = _client().identity_registry
    print(f"\n{'ID':<8} {'Domain':<35} {'Address':<45}")
    print("-" * 80)

    for agent_id in range(1, count + 1):
        try:
            agent_info = contract.functions.getAgent(agent_id).call()
        except Exception as exc:  # noqa: BLE001
            print(f"{agent_id:<8} Error fetching agent: {exc}")
            continue

        domain = agent_info[1]
        address = agent_info[2]
        print(f"{agent_id:<8} {domain:<35} {address:<45}")
        if len(agent_info) > 3 and agent_info[3]:
            print(f"         📄 Metadata: {agent_info[3]}")


def test_registration() -> None:
    _print_header("TEST REGISTRATION")
    test_domain = f"test-agent-{int(time.time())}"
    test_metadata_uri = _default_metadata_uri(test_domain)
    print(f"\n🧪 Testing with domain: {test_domain}")
    print(f"📄 Metadata URI: {test_metadata_uri}")

    result = register_agent_on_chain(test_domain, metadata_uri=test_metadata_uri)
    if result:
        print("\n✅ Test registration successful!")
    else:
        print("\n❌ Test registration failed")


def register_all_agents() -> None:
    _print_header("AGENT REGISTRATION WITH METADATA")

    db = SessionLocal()
    try:
        agents = db.query(AgentModel).filter(AgentModel.status == "active").all()
    finally:
        db.close()

    if not agents:
        print("\n❌ No active agents found in database")
        print("   Run: uv run python scripts/register_all_agents.py first")
        return

    client = _client()
    registration_fee_hbar = float(client.web3.from_wei(client.get_registration_fee(), "ether"))
    estimated_cost = registration_fee_hbar * len(agents)

    print(f"\n📋 Found {len(agents)} active agents")
    print(f"💰 Estimated cost: {estimated_cost:.4f} HBAR")
    print(f"📄 Metadata base URL: {client.settings.metadata_base_url}")

    balance_wei = client.web3.eth.get_balance(client.wallet_address)
    balance_hbar = float(client.web3.from_wei(balance_wei, "ether"))
    if balance_hbar < estimated_cost:
        print("\n⚠️  Warning: Insufficient operator balance!")
        print(f"   Required: {estimated_cost:.4f} HBAR")
        print(f"   Available: {balance_hbar:.4f} HBAR")

    print("\n" + "-" * 80)
    print("Starting registration...")
    print("-" * 80)

    registered = 0
    metadata_updates = 0
    already_registered = 0
    failed = 0

    for idx, agent in enumerate(agents, 1):
        print(f"\n[{idx}/{len(agents)}] {agent.name} ({agent.agent_id})")
        domain = agent.agent_id
        meta = agent.meta or {}
        metadata_uri = (
            agent.erc8004_metadata_uri
            or meta.get("metadata_gateway_url")
            or meta.get("metadata_public_url")
            or _default_metadata_uri(domain)
        )

        registry_agent_id = meta.get("registry_agent_id")
        try:
            registry_agent_id = int(registry_agent_id) if registry_agent_id is not None else None
        except (TypeError, ValueError):
            registry_agent_id = None

        result = register_agent_on_chain(
            domain,
            metadata_uri=metadata_uri,
            registry_agent_id=registry_agent_id,
        )

        if not result:
            failed += 1
            continue

        if result.status == "registered":
            registered += 1
        elif result.status == "metadata_updated":
            metadata_updates += 1
        elif result.status == "already_registered":
            already_registered += 1
        else:
            failed += 1

    print("\n" + "=" * 80)
    print("REGISTRATION COMPLETE")
    print("=" * 80)
    print(f"\n✅ Newly registered: {registered}")
    print(f"🔁 Metadata updated: {metadata_updates}")
    print(f"⚠️  Already registered: {already_registered}")
    print(f"❌ Failed: {failed}")

    try:
        total_on_chain = client.get_agent_count()
        print(f"\n📊 Total agents on-chain: {total_on_chain}")
    except AgentRegistryRegistrationError as exc:
        print(f"\n⚠️  Could not get on-chain count: {exc}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run python scripts/register_agents_with_metadata.py test       # Test with one agent")
        print("  uv run python scripts/register_agents_with_metadata.py list       # List registered agents")
        print("  uv run python scripts/register_agents_with_metadata.py register   # Register all agents")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "test":
        test_registration()
    elif command == "list":
        list_registered_agents()
    elif command == "register":
        register_all_agents()
    else:
        print(f"❌ Unknown command: {command}")
        print("\nValid commands: test, list, register")
        sys.exit(1)
