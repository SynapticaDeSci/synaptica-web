#!/usr/bin/env python
"""
Deploy the fixed IdentityRegistry contract to Hedera testnet.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

# Load environment
load_dotenv(override=True)

# Configuration
RPC_URL = os.getenv("HEDERA_RPC_URL", "https://testnet.hashio.io/api")
PRIVATE_KEY = os.getenv("HEDERA_PRIVATE_KEY")

if not PRIVATE_KEY or PRIVATE_KEY == "your_hedera_private_key_here":
    print("❌ Error: HEDERA_PRIVATE_KEY not set in .env")
    sys.exit(1)

# Connect to Hedera
print("🔧 Connecting to Hedera testnet...")
web3 = Web3(Web3.HTTPProvider(RPC_URL))

if not web3.is_connected():
    print("❌ Failed to connect to Hedera")
    sys.exit(1)

print("✅ Connected to Hedera testnet")

# Setup account
account = web3.eth.account.from_key(PRIVATE_KEY)
wallet = account.address
print(f"📍 Deployer address: {wallet}")

balance = web3.eth.get_balance(wallet)
balance_hbar = web3.from_wei(balance, 'ether')
print(f"💰 Balance: {balance_hbar} HBAR")

if balance_hbar < 0.1:
    print("⚠️  Warning: Low balance. Deployment may require ~0.05-0.1 HBAR")

# Load contract JSON
contract_json_path = Path(__file__).parent.parent / "shared/contracts/IdentityRegistry.sol/IdentityRegistry.json"

print(f"\n📄 Loading contract from: {contract_json_path}")

if not contract_json_path.exists():
    print(f"❌ Contract JSON not found. Please compile the contract first:")
    print("   You need to compile IdentityRegistry.sol to generate the JSON artifact")
    print("   The contract source is at: IdentityRegistry.sol")
    sys.exit(1)

with open(contract_json_path) as f:
    contract_data = json.load(f)
    abi = contract_data['abi']
    bytecode = contract_data.get('bytecode', '')

if not bytecode or bytecode == '0x':
    print("❌ No bytecode found in contract JSON")
    print("   The contract needs to be compiled with Hardhat or Foundry")
    sys.exit(1)

print(f"✅ Contract loaded ({len(bytecode)} bytes bytecode)")

# Deploy contract
print("\n🚀 Deploying IdentityRegistry contract...")
print("   This will take ~30-60 seconds...")

try:
    # Create contract instance
    Contract = web3.eth.contract(abi=abi, bytecode=bytecode)

    # Build deployment transaction
    tx = Contract.constructor(
    "0x90dFCF20AaeF4fc1f213Bb79E8A6F53EE732Bb2e",  # ReputationRegistry (zero address for now)
    "0x8E71DC262992A9125EF1a0B2bd74A32eBFC96c2d"   # ValidationRegistry (zero address for now)
).build_transaction({
        'from': wallet,
        'nonce': web3.eth.get_transaction_count(wallet),
        'gas': 2000000,  # Generous gas limit for deployment
        'gasPrice': web3.eth.gas_price,
    })

    print(f"   Gas price: {web3.from_wei(tx['gasPrice'], 'gwei')} Gwei")
    print(f"   Estimated cost: {web3.from_wei(tx['gas'] * tx['gasPrice'], 'ether')} HBAR")

    # Sign and send
    signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

    print(f"\n   ⏳ TX Hash: {tx_hash.hex()}")
    print(f"   Waiting for confirmation...")

    # Wait for receipt
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

    if receipt['status'] == 1:
        contract_address = receipt['contractAddress']

        print(f"\n{'='*80}")
        print(f"✅ CONTRACT DEPLOYED SUCCESSFULLY!")
        print(f"{'='*80}")
        print(f"\n📍 Contract Address: {contract_address}")
        print(f"   Transaction: {tx_hash.hex()}")
        print(f"   Block: {receipt['blockNumber']}")
        print(f"   Gas Used: {receipt['gasUsed']:,}")
        print(f"   Cost: {web3.from_wei(receipt['gasUsed'] * tx['gasPrice'], 'ether')} HBAR")

        print(f"\n🔗 View on Hedera Explorer:")
        print(f"   https://hashscan.io/testnet/contract/{contract_address}")

        print(f"\n📝 Next Steps:")
        print(f"   1. Update your .env file:")
        print(f"      IDENTITY_REGISTRY_ADDRESS={contract_address}")
        print(f"   2. Test registration:")
        print(f"      uv run python scripts/register_agents_on_chain.py test")
        print(f"   3. Register all agents:")
        print(f"      uv run python scripts/register_agents_on_chain.py register")

    else:
        print(f"\n❌ Deployment failed!")
        print(f"   Transaction: {tx_hash.hex()}")
        print(f"   Receipt: {receipt}")

except Exception as e:
    print(f"\n❌ Deployment error: {e}")
    sys.exit(1)
