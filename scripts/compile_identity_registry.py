#!/usr/bin/env python
"""
Compile the IdentityRegistry.sol contract using py-solc-x.

This compiles the NEW contract with the 3-parameter newAgent function
that includes metadataUri.
"""

import json
import os
from pathlib import Path
from solcx import compile_standard, install_solc, get_installable_solc_versions

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONTRACT_PATH = PROJECT_ROOT / "IdentityRegistry.sol"
INTERFACES_DIR = PROJECT_ROOT / "interfaces"
OUTPUT_DIR = PROJECT_ROOT / "shared/contracts/IdentityRegistry.sol"

print("=" * 80)
print("COMPILING IDENTITY REGISTRY CONTRACT")
print("=" * 80)

# Check if contract exists
if not CONTRACT_PATH.exists():
    print(f"\n❌ Contract not found at: {CONTRACT_PATH}")
    exit(1)

print(f"\n📄 Contract: {CONTRACT_PATH}")

# Install Solidity compiler (version 0.8.19 as specified in contract)
print("\n🔧 Installing Solidity compiler v0.8.19...")
try:
    install_solc('0.8.19')
    print("✅ Compiler installed")
except Exception as e:
    print(f"⚠️  Error installing compiler: {e}")
    print("Trying to use existing installation...")

# Read contract source
print("\n📖 Reading contract source...")
with open(CONTRACT_PATH, 'r') as f:
    contract_source = f.read()

# Read interface sources
interfaces = {}
interface_files = [
    "IIdentityRegistry.sol",
    "IReputationRegistry.sol",
    "IValidationRegistry.sol"
]

print("📖 Reading interface files...")
for interface_file in interface_files:
    interface_path = INTERFACES_DIR / interface_file
    if interface_path.exists():
        with open(interface_path, 'r') as f:
            interfaces[f"interfaces/{interface_file}"] = {
                "content": f.read()
            }
        print(f"   ✅ {interface_file}")
    else:
        print(f"   ⚠️  {interface_file} not found (may cause compilation errors)")

# Prepare compilation input
print("\n⚙️  Preparing compilation...")
compile_input = {
    "language": "Solidity",
    "sources": {
        "IdentityRegistry.sol": {
            "content": contract_source
        },
        **interfaces
    },
    "settings": {
        "optimizer": {
            "enabled": True,
            "runs": 200
        },
        "outputSelection": {
            "*": {
                "*": [
                    "abi",
                    "metadata",
                    "evm.bytecode",
                    "evm.bytecode.sourceMap",
                    "evm.deployedBytecode",
                    "evm.deployedBytecode.sourceMap"
                ]
            }
        }
    }
}

# Compile
print("🔨 Compiling contract...")
try:
    compiled_sol = compile_standard(compile_input, solc_version='0.8.19')
    print("✅ Compilation successful!")
except Exception as e:
    print(f"\n❌ Compilation failed: {e}")
    exit(1)

# Extract contract data
contract_id = "IdentityRegistry.sol"
contract_name = "IdentityRegistry"

if contract_id not in compiled_sol['contracts']:
    print(f"\n❌ Contract {contract_id} not found in compilation output")
    exit(1)

if contract_name not in compiled_sol['contracts'][contract_id]:
    print(f"\n❌ Contract {contract_name} not found in {contract_id}")
    exit(1)

contract_data = compiled_sol['contracts'][contract_id][contract_name]

# Create output directory
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Prepare output JSON
output_json = {
    "_format": "hh-sol-artifact-1",
    "contractName": contract_name,
    "sourceName": contract_id,
    "abi": contract_data['abi'],
    "bytecode": contract_data['evm']['bytecode']['object'],
    "deployedBytecode": contract_data['evm']['deployedBytecode']['object'],
    "linkReferences": contract_data['evm']['bytecode'].get('linkReferences', {}),
    "deployedLinkReferences": contract_data['evm']['deployedBytecode'].get('linkReferences', {})
}

# Save to file
output_file = OUTPUT_DIR / "IdentityRegistry.json"
with open(output_file, 'w') as f:
    json.dump(output_json, f, indent=2)

print(f"\n💾 Saved to: {output_file}")

# Verify the new function signature
print("\n🔍 Verifying newAgent function signature...")
for item in output_json['abi']:
    if item.get('name') == 'newAgent':
        print(f"   ✅ Found newAgent with {len(item['inputs'])} parameters:")
        for i, inp in enumerate(item['inputs'], 1):
            print(f"      {i}. {inp['name']}: {inp['type']}")
        if len(item['inputs']) == 3:
            print("\n   ✅ Correct! Contract has the NEW 3-parameter version")
        else:
            print("\n   ⚠️  Warning: Expected 3 parameters, found", len(item['inputs']))
        break
else:
    print("   ❌ newAgent function not found in ABI")

# Print bytecode size
bytecode_size = len(output_json['bytecode']) // 2  # Hex string, 2 chars per byte
print(f"\n📊 Contract size: {bytecode_size:,} bytes")

if bytecode_size > 24576:
    print("   ⚠️  Warning: Contract exceeds 24KB limit (may not deploy on some networks)")

print("\n" + "=" * 80)
print("COMPILATION COMPLETE")
print("=" * 80)
print("\n📝 Next steps:")
print("   1. Deploy the contract: uv run python scripts/deploy_identity_registry.py")
print("   2. Update .env with new contract address")
print("   3. Register agents with metadata: uv run python scripts/register_agents_with_metadata.py register")
