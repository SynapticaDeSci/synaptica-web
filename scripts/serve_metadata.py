#!/usr/bin/env python
"""
Simple HTTP server to serve agent metadata files.

This is for testing/development. For production, upload metadata to:
- IPFS (decentralized, permanent)
- Cloud storage (AWS S3, Google Cloud Storage)
- Your own API server

Usage:
    uv run python scripts/serve_metadata.py

Then metadata will be available at:
    http://localhost:8001/problem-framer-001.json
    http://localhost:8001/literature-miner-001.json
    etc.
"""

import http.server
import socketserver
import os
from pathlib import Path

# Metadata directory
METADATA_DIR = Path(__file__).parent.parent / "agent_metadata"
PORT = 8001


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler with CORS enabled."""

    def end_headers(self):
        # Enable CORS
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


def serve_metadata():
    """Start HTTP server to serve metadata files."""

    if not METADATA_DIR.exists():
        print(f"❌ Metadata directory not found: {METADATA_DIR}")
        print("\nRun first: uv run python scripts/generate_agent_metadata.py")
        return

    # Change to metadata directory
    os.chdir(METADATA_DIR)

    # Start server
    with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
        print("=" * 80)
        print("AGENT METADATA SERVER")
        print("=" * 80)
        print(f"\n🌐 Serving metadata from: {METADATA_DIR}")
        print(f"🔗 Server URL: http://localhost:{PORT}")
        print(f"\n📋 Available metadata files:")

        # List all JSON files
        for json_file in sorted(METADATA_DIR.glob("*.json")):
            print(f"   • http://localhost:{PORT}/{json_file.name}")

        print(f"\n⚡ Press Ctrl+C to stop the server")
        print("=" * 80)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n✅ Server stopped")


if __name__ == "__main__":
    serve_metadata()
