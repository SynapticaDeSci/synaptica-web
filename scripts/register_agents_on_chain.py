#!/usr/bin/env python
"""
Register all ProvidAI agents to the on-chain Identity Registry.

This script:
1. Loads all agents from the local database
2. Registers each agent on the Hedera Identity Registry contract
3. Updates the local database with on-chain registration status
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, Agent as AgentModel

# Load environment variables
load_dotenv(override=True)

# -------- CONFIG --------
RPC_URL = os.getenv("HEDERA_RPC_URL", "https://testnet.hashio.io/api")
PRIVATE_KEY = os.getenv("HEDERA_PRIVATE_KEY")
CONTRACT_ADDRESS = os.getenv("IDENTITY_REGISTRY_ADDRESS", "0x8984Af52606420ECa228A81b300D4b5c69b990cA")

# -------- VALIDATION --------
if not PRIVATE_KEY or PRIVATE_KEY == "your_hedera_private_key_here":
    print("❌ Error: HEDERA_PRIVATE_KEY not set in .env file")
    print("\nPlease add to .env:")
    print("  HEDERA_PRIVATE_KEY=0x...")
    print("  IDENTITY_REGISTRY_ADDRESS=0x...")
    sys.exit(1)

# -------- WEB3 SETUP --------
print("🔧 Connecting to Hedera testnet...")
web3 = Web3(Web3.HTTPProvider(RPC_URL))

if not web3.is_connected():
    print("❌ Failed to connect to Hedera RPC")
    sys.exit(1)

print(f"✅ Connected to Hedera testnet")

# Setup account
try:
    account = web3.eth.account.from_key(PRIVATE_KEY)
    wallet_address = account.address
    print(f"📍 Wallet address: {wallet_address}")

    # Check balance
    balance = web3.eth.get_balance(wallet_address)
    balance_eth = web3.from_wei(balance, 'ether')
    print(f"💰 Balance: {balance_eth} HBAR")

    if balance == 0:
        print("⚠️  Warning: Wallet has 0 HBAR. You need HBAR to register agents.")
        print("   Get testnet HBAR from: https://portal.hedera.com/")

except Exception as e:
    print(f"❌ Error setting up account: {e}")
    sys.exit(1)

# -------- LOAD CONTRACT ABI --------
print("\n🔧 Loading Identity Registry contract...")
contract_json_path = Path(__file__).parent.parent / "shared/contracts/IdentityRegistry.sol/IdentityRegistry.json"

if not contract_json_path.exists():
    print(f"❌ Contract ABI not found at: {contract_json_path}")
    sys.exit(1)

try:
    with open(contract_json_path) as f:
        contract_json = json.load(f)
        abi = contract_json["abi"]

    identity_registry = web3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=abi
    )
    print(f"✅ Contract loaded at: {CONTRACT_ADDRESS}")

except Exception as e:
    print(f"❌ Error loading contract: {e}")
    sys.exit(1)

# -------- HELPER FUNCTIONS --------

def register_agent_on_chain(domain: str, agent_address: str = None):
    """
    Register an agent on the identity registry.

    Args:
        domain: Agent domain/identifier (e.g., "problem-framer-001")
        agent_address: Ethereum address (defaults to unique generated address)

    Returns:
        Transaction receipt or None if failed
    """
    if agent_address is None:
        # Generate unique deterministic address for each agent domain
        from eth_account import Account
        import hashlib

        # Hash the domain to create a seed
        seed = hashlib.sha256(domain.encode()).hexdigest()
        # Generate account from seed (deterministic and unique per domain)
        agent_account = Account.from_key('0x' + seed)
        agent_address = agent_account.address

    print(f"   🔐 Agent address: {agent_address}")

    try:
        # Check if agent already exists by domain
        try:
            existing = identity_registry.functions.resolveByDomain(domain).call()
            if existing[0] > 0:  # agent_id > 0 means exists
                print(f"   ⚠️  Agent '{domain}' already registered (ID: {existing[0]})")
                return {"status": "already_registered", "agent_id": existing[0]}
        except Exception:
            pass  # Agent doesn't exist, continue with registration

        # Get the required registration fee from contract
        try:
            required_fee = identity_registry.functions.REGISTRATION_FEE().call()
            print(f"   💰 Required fee: {web3.from_wei(required_fee, 'ether')} HBAR ({required_fee} wei)")
        except Exception as e:
            print(f"   ⚠️  Could not fetch registration fee: {e}")
            required_fee = web3.to_wei(0.005, "ether")

        # Estimate gas first
        try:
            gas_estimate = identity_registry.functions.newAgent(domain, agent_address).estimate_gas({
                "from": wallet_address,
                "value": required_fee,
            })
            print(f"   📊 Estimated gas: {gas_estimate}")
        except Exception as e:
            print(f"   ⚠️  Gas estimation failed: {e}")
            print(f"   Trying with call() to see error...")
            try:
                identity_registry.functions.newAgent(domain, agent_address).call({
                    "from": wallet_address,
                    "value": required_fee,
                })
            except Exception as call_error:
                print(f"   ❌ Call error: {call_error}")
                raise

        # Build transaction
        tx = identity_registry.functions.newAgent(domain, agent_address).build_transaction({
            "from": wallet_address,
            "value": required_fee,  # Use fee from contract
            "nonce": web3.eth.get_transaction_count(wallet_address),
            "gas": min(500000, gas_estimate + 50000),  # Add buffer to estimate
            "gasPrice": web3.eth.gas_price,
        })

        # Sign and send
        signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"   ⏳ TX: {tx_hash.hex()}")

        # Wait for confirmation
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] == 1:
            print(f"   ✅ Registered successfully!")
            return receipt
        else:
            print(f"   ❌ Transaction failed")
            print(f"   Gas used: {receipt.get('gasUsed', 'N/A')}")
            print(f"   Receipt: {receipt}")
            return None

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def get_agent_count():
    """Get total number of registered agents."""
    try:
        return identity_registry.functions.getAgentCount().call()
    except Exception as e:
        print(f"❌ Error getting agent count: {e}")
        return 0


def resolve_by_domain(domain: str):
    """Look up agent by domain."""
    try:
        agent = identity_registry.functions.resolveByDomain(domain).call()
        return {
            "agent_id": agent[0],
            "domain": agent[1],
            "agent_address": agent[2],
            "is_active": agent[3]
        }
    except Exception as e:
        return None


# -------- MAIN REGISTRATION LOGIC --------

def register_all_agents():
    """Register all agents from database to on-chain registry."""

    print("\n" + "="*80)
    print("AGENT REGISTRATION TO ON-CHAIN IDENTITY REGISTRY")
    print("="*80)

    # Load agents from database
    db = SessionLocal()
    try:
        agents = db.query(AgentModel).filter(AgentModel.status == "active").all()

        if not agents:
            print("\n❌ No active agents found in database")
            print("   Run: uv run python scripts/register_all_agents.py first")
            return

        print(f"\n📋 Found {len(agents)} active agents in database")
        print(f"💰 Estimated cost: {len(agents) * 0.005} HBAR (0.005 per agent)")

        # Check balance
        balance = web3.eth.get_balance(wallet_address)
        balance_eth = float(web3.from_wei(balance, 'ether'))
        required = len(agents) * 0.005

        if balance_eth < required:
            print(f"\n⚠️  Warning: Insufficient balance!")
            print(f"   Required: {required} HBAR")
            print(f"   Available: {balance_eth} HBAR")

            response = input("\nContinue anyway? (y/n): ")
            if response.lower() != 'y':
                print("Aborted.")
                return

        print("\n" + "-"*80)
        print("Starting registration...")
        print("-"*80)

        registered = 0
        already_registered = 0
        failed = 0

        for i, agent in enumerate(agents, 1):
            print(f"\n[{i}/{len(agents)}] {agent.name} ({agent.agent_id})")

            # Use agent_id as domain (unique identifier)
            domain = agent.agent_id

            # Don't pass agent_address - let it generate unique address
            result = register_agent_on_chain(domain)

            if result:
                if isinstance(result, dict) and result.get("status") == "already_registered":
                    already_registered += 1
                else:
                    registered += 1
            else:
                failed += 1

        # Summary
        print("\n" + "="*80)
        print("REGISTRATION COMPLETE")
        print("="*80)
        print(f"\n✅ Newly registered: {registered}")
        print(f"⚠️  Already registered: {already_registered}")
        print(f"❌ Failed: {failed}")

        # Get on-chain count
        try:
            on_chain_count = get_agent_count()
            print(f"\n📊 Total agents on-chain: {on_chain_count}")
        except Exception as e:
            print(f"\n⚠️  Could not fetch on-chain count: {e}")

    finally:
        db.close()


def test_registration():
    """Test registration with a single agent."""

    print("\n" + "="*80)
    print("TEST MODE - Single Agent Registration")
    print("="*80)

    test_domain = "test-agent-001"

    print(f"\n🧪 Testing registration of: {test_domain}")

    # Try to register
    result = register_agent_on_chain(test_domain, wallet_address)

    if result:
        print("\n✅ Test registration successful!")

        # Try to look it up
        print("\n🔍 Verifying registration...")
        agent_info = resolve_by_domain(test_domain)

        if agent_info:
            print(f"\n✅ Agent found on-chain:")
            print(f"   ID: {agent_info['agent_id']}")
            print(f"   Domain: {agent_info['domain']}")
            print(f"   Address: {agent_info['agent_address']}")
            print(f"   Active: {agent_info['is_active']}")
        else:
            print("\n⚠️  Could not verify registration")
    else:
        print("\n❌ Test registration failed")


def list_registered_agents():
    """List all agents registered on-chain."""

    print("\n" + "="*80)
    print("ON-CHAIN REGISTERED AGENTS")
    print("="*80)

    try:
        count = get_agent_count()
        print(f"\n📊 Total registered agents: {count}")

        if count == 0:
            print("\nNo agents registered yet.")
            return

        print("\n" + "-"*80)

        # Note: This requires iterating through all agent IDs
        # The contract doesn't have a function to get all agents at once
        print("\n⚠️  Note: To list all agents, the contract would need a getAllAgents() function")
        print("   or we'd need to query each ID from 1 to count.")

    except Exception as e:
        print(f"\n❌ Error: {e}")


# -------- CLI --------

def main():
    """Main CLI interface."""

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "test":
            test_registration()
        elif command == "list":
            list_registered_agents()
        elif command == "register":
            register_all_agents()
        else:
            print(f"❌ Unknown command: {command}")
            print("\nUsage:")
            print("  uv run python scripts/register_agents_on_chain.py test       # Test with one agent")
            print("  uv run python scripts/register_agents_on_chain.py list       # List registered agents")
            print("  uv run python scripts/register_agents_on_chain.py register   # Register all agents")
    else:
        print("\n" + "="*80)
        print("ProvidAI Agent Registration Script")
        print("="*80)
        print("\nCommands:")
        print("  test       - Test registration with a single agent")
        print("  list       - List agents registered on-chain")
        print("  register   - Register all agents from database")
        print("\nUsage:")
        print("  uv run python scripts/register_agents_on_chain.py <command>")
        print("\nExample:")
        print("  uv run python scripts/register_agents_on_chain.py test")


if __name__ == "__main__":
    main()
