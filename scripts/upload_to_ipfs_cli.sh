#!/bin/bash
#
# Upload agent metadata to IPFS using IPFS CLI
#
# Prerequisites:
#   1. Install IPFS: brew install ipfs (macOS) or https://ipfs.io/#install
#   2. Initialize IPFS: ipfs init
#   3. Start IPFS daemon: ipfs daemon (in a separate terminal)
#
# Usage:
#   chmod +x scripts/upload_to_ipfs_cli.sh
#   ./scripts/upload_to_ipfs_cli.sh
#

set -e

METADATA_DIR="agent_metadata"

echo "================================================================================"
echo "UPLOADING METADATA TO IPFS (IPFS CLI)"
echo "================================================================================"

# Check if ipfs is installed
if ! command -v ipfs &> /dev/null; then
    echo "❌ IPFS CLI not found"
    echo ""
    echo "📝 Installation:"
    echo "   macOS:   brew install ipfs"
    echo "   Linux:   wget https://dist.ipfs.io/go-ipfs/v0.18.0/go-ipfs_v0.18.0_linux-amd64.tar.gz"
    echo "            tar -xvzf go-ipfs_v0.18.0_linux-amd64.tar.gz"
    echo "            cd go-ipfs && sudo bash install.sh"
    echo "   Windows: Download from https://ipfs.io/#install"
    echo ""
    echo "Then run:"
    echo "   ipfs init"
    echo "   ipfs daemon (in a separate terminal)"
    exit 1
fi

# Check if IPFS daemon is running
if ! ipfs swarm peers &> /dev/null; then
    echo "❌ IPFS daemon not running"
    echo ""
    echo "Please start the IPFS daemon in a separate terminal:"
    echo "   ipfs daemon"
    echo ""
    exit 1
fi

echo "✅ IPFS CLI found and daemon running"
echo ""

# Check if metadata directory exists
if [ ! -d "$METADATA_DIR" ]; then
    echo "❌ Metadata directory not found: $METADATA_DIR"
    echo "   Run: python -m scripts.generate_agent_metadata"
    exit 1
fi

# Count files
FILE_COUNT=$(ls -1 "$METADATA_DIR"/*.json 2>/dev/null | wc -l)
echo "📋 Found $FILE_COUNT metadata files in $METADATA_DIR"
echo ""

# Option 1: Upload entire directory (recommended for common base URL)
echo "================================================================================
OPTION 1: Upload as Directory (Recommended)
================================================================================"
echo "This creates a folder on IPFS with all metadata files."
echo "You'll get a single CID that works as a base URL."
echo ""

# Add directory to IPFS
echo "📤 Uploading directory to IPFS..."
DIR_CID=$(ipfs add -r -Q "$METADATA_DIR" | tail -1)

echo "✅ Directory uploaded!"
echo ""
echo "📍 Directory CID: $DIR_CID"
echo "🔗 Base URL: https://ipfs.io/ipfs/$DIR_CID"
echo "🔗 Gateway URL: https://gateway.pinata.cloud/ipfs/$DIR_CID"
echo ""
echo "Example file URLs:"
for file in "$METADATA_DIR"/*.json | head -3; do
    filename=$(basename "$file")
    echo "   • https://ipfs.io/ipfs/$DIR_CID/$filename"
done
echo ""

# Pin the directory
echo "📌 Pinning directory locally..."
ipfs pin add "$DIR_CID" > /dev/null
echo "✅ Directory pinned locally"
echo ""

# Option 2: Upload individual files
echo "================================================================================"
echo "OPTION 2: Individual File Uploads"
echo "================================================================================"
echo "Each file gets its own CID."
echo ""

# Create mapping file
MAPPING_FILE="$METADATA_DIR/ipfs_mapping.json"
echo "[" > "$MAPPING_FILE"

FIRST=true
for file in "$METADATA_DIR"/*.json; do
    if [ "$file" == "$METADATA_DIR/ipfs_mapping.json" ]; then
        continue
    fi

    filename=$(basename "$file")
    agent_id="${filename%.json}"

    echo "📤 Uploading $filename..."
    CID=$(ipfs add -Q "$file")

    # Add to mapping
    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$MAPPING_FILE"
    fi

    cat >> "$MAPPING_FILE" << EOF
  {
    "agent_id": "$agent_id",
    "filename": "$filename",
    "cid": "$CID",
    "url": "https://ipfs.io/ipfs/$CID",
    "gateway_url": "https://gateway.pinata.cloud/ipfs/$CID"
  }
EOF

    echo "   ✅ CID: $CID"

    # Pin the file
    ipfs pin add "$CID" > /dev/null
done

echo "" >> "$MAPPING_FILE"
echo "]" >> "$MAPPING_FILE"

echo ""
echo "================================================================================"
echo "UPLOAD COMPLETE"
echo "================================================================================"
echo ""
echo "💾 IPFS mapping saved to: $MAPPING_FILE"
echo ""
echo "📝 Recommended Usage:"
echo "   Use OPTION 1 (directory upload) for smart contract registration:"
echo "   "
echo "   METADATA_BASE_URL=https://ipfs.io/ipfs/$DIR_CID"
echo "   "
echo "   Then your agent metadata will be accessible at:"
echo "   https://ipfs.io/ipfs/$DIR_CID/problem-framer-001.json"
echo "   https://ipfs.io/ipfs/$DIR_CID/literature-miner-001.json"
echo "   etc."
echo ""
echo "📌 Important Notes:"
echo "   1. Files are pinned locally - they won't disappear as long as your node runs"
echo "   2. For permanent hosting, use a pinning service like Pinata or web3.storage"
echo "   3. Public gateways may be slow - consider using Pinata gateway for production"
echo ""
echo "🚀 Next Steps:"
echo "   1. Update .env: METADATA_BASE_URL=https://ipfs.io/ipfs/$DIR_CID"
echo "   2. Or use Pinata for more reliable hosting: uv run python scripts/upload_to_pinata.py"
echo ""
