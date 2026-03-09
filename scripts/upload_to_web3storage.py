#!/usr/bin/env python
"""
Upload agent metadata files to web3.storage (free IPFS pinning).

web3.storage Setup:
1. Sign up at https://web3.storage (free)
2. Create API token
3. Add to .env:
   WEB3_STORAGE_TOKEN=your_token

Advantages:
- Free unlimited storage
- Automatic pinning
- Fast global CDN
- No credit card required

Usage:
    uv sync
    uv run python scripts/upload_to_web3storage.py
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(override=True)

# Web3.storage token
WEB3_STORAGE_TOKEN = os.getenv("WEB3_STORAGE_TOKEN")

# Metadata directory
METADATA_DIR = Path(__file__).parent.parent / "agent_metadata"


def check_dependencies():
    """Check if web3-storage is installed."""
    try:
        import requests
        return True
    except ImportError:
        print("❌ Required package not installed")
        print("\nInstall with:")
        print("   uv add requests")
        return False


def check_credentials():
    """Check if web3.storage token is configured."""
    if not WEB3_STORAGE_TOKEN:
        print("❌ web3.storage token not configured")
        print("\n📝 Setup Instructions:")
        print("   1. Sign up at https://web3.storage (free)")
        print("   2. Go to Account -> Create API Token")
        print("   3. Copy the token")
        print("   4. Add to .env:")
        print("      WEB3_STORAGE_TOKEN=your_token")
        return False
    return True


def upload_directory_to_web3storage():
    """
    Upload entire metadata directory to web3.storage.

    Returns:
        Dict with CID and URLs, or None if failed
    """
    import requests
    from pathlib import Path

    if not METADATA_DIR.exists():
        print(f"❌ Metadata directory not found: {METADATA_DIR}")
        return None

    # Get all JSON files
    json_files = list(METADATA_DIR.glob("*.json"))

    if not json_files:
        print(f"❌ No metadata files found in {METADATA_DIR}")
        return None

    print(f"📋 Found {len(json_files)} metadata files")
    print(f"📤 Uploading to web3.storage...")
    print()

    # Prepare files for upload
    files = []
    for file_path in sorted(json_files):
        with open(file_path, 'rb') as f:
            files.append(
                ('file', (file_path.name, f.read(), 'application/json'))
            )

    # Upload to web3.storage
    headers = {
        'Authorization': f'Bearer {WEB3_STORAGE_TOKEN}',
    }

    try:
        response = requests.post(
            'https://api.web3.storage/upload',
            headers=headers,
            files=files
        )
        response.raise_for_status()

        result = response.json()
        cid = result['cid']

        print(f"✅ Upload successful!")
        print()

        return {
            "cid": cid,
            "url": f"https://w3s.link/ipfs/{cid}",
            "ipfs_url": f"https://ipfs.io/ipfs/{cid}",
            "files": [f.name for f in sorted(json_files)]
        }

    except requests.exceptions.RequestException as e:
        print(f"❌ Upload failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def upload_all_metadata():
    """Upload all agent metadata to web3.storage."""

    print("=" * 80)
    print("UPLOADING METADATA TO IPFS (WEB3.STORAGE)")
    print("=" * 80)
    print()

    # Check dependencies
    if not check_dependencies():
        return

    # Check credentials
    if not check_credentials():
        return

    # Upload directory
    result = upload_directory_to_web3storage()

    if not result:
        return

    # Print results
    print("=" * 80)
    print("UPLOAD COMPLETE")
    print("=" * 80)
    print()
    print(f"📍 CID: {result['cid']}")
    print(f"🔗 w3s.link: {result['url']}")
    print(f"🔗 IPFS: {result['ipfs_url']}")
    print()
    print(f"✅ Uploaded {len(result['files'])} files:")
    for filename in result['files'][:5]:
        print(f"   • {filename}")
    if len(result['files']) > 5:
        print(f"   ... and {len(result['files']) - 5} more")
    print()

    # Save to mapping file
    mapping_file = METADATA_DIR / "web3storage_upload.json"
    with open(mapping_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"💾 Upload info saved to: {mapping_file}")
    print()

    # Print example URLs
    print("📝 Example metadata URLs:")
    for filename in result['files'][:3]:
        print(f"   • {result['url']}/{filename}")
    print()

    # Print next steps
    print("🚀 Next Steps:")
    print()
    print("   1. Set metadata base URL in .env:")
    print(f"      METADATA_BASE_URL={result['url']}")
    print()
    print("   2. Test access:")
    agent_id = result['files'][0].replace('.json', '') if result['files'] else 'agent-id'
    print(f"      curl {result['url']}/{agent_id}.json")
    print()
    print("   3. Use this URL when registering agents:")
    print(f"      uv run python scripts/register_agents_with_metadata.py register")
    print()
    print("📌 Notes:")
    print("   • Files are permanently pinned on web3.storage")
    print("   • Available via multiple IPFS gateways")
    print("   • Free and no credit card required")
    print()


if __name__ == "__main__":
    upload_all_metadata()
