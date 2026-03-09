"""Force refresh the on-chain registry cache used by /api/agents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure direct script execution can import repo-root packages.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.registry_sync import (
    RegistrySyncError,
    ensure_registry_cache,
    get_registry_sync_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the local agent registry cache")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the cache TTL and force a sync",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        result = ensure_registry_cache(force=args.force)
    except RegistrySyncError as exc:
        print(f"Registry sync failed: {exc}")
        return 1

    if result:
        print(f"Synced {result.synced} agents from registry (domains: {len(result.domains)})")
    else:
        print("Registry cache already fresh; no sync performed")

    status, synced_at = get_registry_sync_status()
    timestamp = synced_at.isoformat() if synced_at else "never"
    print(f"Current status: {status} (last successful sync: {timestamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
