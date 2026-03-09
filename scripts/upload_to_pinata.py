#!/usr/bin/env python
"""
Upload agent metadata files to Pinata (IPFS pinning service).

Pinata Setup:
1. Sign up at https://pinata.cloud (free tier available)
2. Go to API Keys section
3. Create new API key with pinFileToIPFS permission
4. Add to .env:
   PINATA_API_KEY=your_api_key
   PINATA_SECRET_KEY=your_secret_key

Usage:
    uv run python scripts/upload_to_pinata.py
"""

import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(override=True)

# Pinata credentials
PINATA_API_KEY = os.getenv("PINATA_API_KEY")
PINATA_SECRET_KEY = os.getenv("PINATA_SECRET_KEY")

# Metadata directory
METADATA_DIR = Path(__file__).parent.parent / "agent_metadata"

# Pinata API endpoints
PINATA_PIN_FILE_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
PINATA_PIN_JSON_URL = "https://api.pinata.cloud/pinning/pinJSONToIPFS"


def check_credentials():
    """Check if Pinata credentials are configured."""
    if not PINATA_API_KEY or not PINATA_SECRET_KEY:
        print("❌ Pinata credentials not configured")
        print("\n📝 Setup Instructions:")
        print("   1. Sign up at https://pinata.cloud")
        print("   2. Go to API Keys section")
        print("   3. Create new API key")
        print("   4. Add to .env:")
        print("      PINATA_API_KEY=your_api_key")
        print("      PINATA_SECRET_KEY=your_secret_key")
        return False
    return True


def upload_file_to_pinata(file_path: Path, name: str = None):
    """
    Upload a single file to Pinata.

    Args:
        file_path: Path to file to upload
        name: Optional name for the file on IPFS

    Returns:
        Dict with IPFS hash and URL, or None if failed
    """
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return None

    headers = {
        "pinata_api_key": PINATA_API_KEY,
        "pinata_secret_api_key": PINATA_SECRET_KEY,
    }

    # Read file
    with open(file_path, 'rb') as f:
        files = {
            'file': (name or file_path.name, f)
        }

        # Optional metadata
        metadata = {
            "name": name or file_path.name,
            "keyvalues": {
                "project": "ProvidAI",
                "type": "agent_metadata"
            }
        }

        data = {
            "pinataMetadata": json.dumps(metadata),
            "pinataOptions": json.dumps({
                "cidVersion": 1
            })
        }

        try:
            response = requests.post(
                PINATA_PIN_FILE_URL,
                files=files,
                data=data,
                headers=headers
            )
            response.raise_for_status()

            result = response.json()
            ipfs_hash = result['IpfsHash']

            return {
                "hash": ipfs_hash,
                "url": f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}",
                "public_url": f"https://ipfs.io/ipfs/{ipfs_hash}",
                "size": result.get('PinSize', 0)
            }

        except requests.exceptions.RequestException as e:
            print(f"❌ Upload failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response: {e.response.text}")
            return None


def upload_all_metadata():
    """Upload all agent metadata files to Pinata."""

    print("=" * 80)
    print("UPLOADING METADATA TO IPFS (PINATA)")
    print("=" * 80)

    # Check credentials
    if not check_credentials():
        return

    # Check metadata directory
    if not METADATA_DIR.exists():
        print(f"\n❌ Metadata directory not found: {METADATA_DIR}")
        print("   Run: python -m scripts.generate_agent_metadata")
        return

    # Get all JSON files
    json_files = list(METADATA_DIR.glob("*.json"))

    if not json_files:
        print(f"\n❌ No metadata files found in {METADATA_DIR}")
        return

    print(f"\n📋 Found {len(json_files)} metadata files")
    print(f"📁 Directory: {METADATA_DIR}")
    print()

    uploaded = []
    failed = []

    for i, file_path in enumerate(sorted(json_files), 1):
        print(f"[{i}/{len(json_files)}] {file_path.name}")

        result = upload_file_to_pinata(file_path)

        if result:
            uploaded.append({
                "file": file_path.name,
                "agent_id": file_path.stem,
                **result
            })
            print(f"   ✅ Uploaded: {result['hash']}")
            print(f"   🔗 URL: {result['public_url']}")
        else:
            failed.append(file_path.name)
            print(f"   ❌ Failed")

        print()

    # Summary
    print("=" * 80)
    print("UPLOAD COMPLETE")
    print("=" * 80)
    print(f"\n✅ Uploaded: {len(uploaded)}")
    print(f"❌ Failed: {len(failed)}")

    if failed:
        print(f"\nFailed files:")
        for f in failed:
            print(f"   • {f}")

    # Save mapping to file
    if uploaded:
        mapping_file = METADATA_DIR / "ipfs_mapping.json"
        with open(mapping_file, 'w') as f:
            json.dump(uploaded, f, indent=2)

        print(f"\n💾 IPFS mapping saved to: {mapping_file}")

        # Print base URL for contract registration
        print("\n📝 Next Steps:")
        print("   1. Each file has its own IPFS hash/URL")
        print("   2. To use a common base URL, upload the entire directory as a folder")
        print("   3. Or use the mapping file to update agent metadata URIs individually")
        print("\n🔗 Example URLs:")
        for item in uploaded[:3]:
            print(f"   • {item['agent_id']}: {item['public_url']}")
        if len(uploaded) > 3:
            print(f"   ... and {len(uploaded) - 3} more")


if __name__ == "__main__":
    upload_all_metadata()
