#!/usr/bin/env python
"""Manual helper to sync Identity Registry agents into the local cache."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Ensure direct script execution can import repo-root packages.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(override=True)

from shared.registry_sync import ensure_registry_cache, RegistrySyncError, get_registry_sync_status  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("registry_sync")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync agents from ERC-8004 registry into SQLite cache.")
    parser.add_argument("--force", action="store_true", help="Force sync even if cache TTL not expired.")
    args = parser.parse_args()

    try:
        result = ensure_registry_cache(force=args.force)
        status, synced_at = get_registry_sync_status()
    except RegistrySyncError as exc:
        logger.error("Registry sync failed: %s", exc)
        raise SystemExit(1) from exc

    if result:
        logger.info("Synced %s agents (%s)", result.synced, ", ".join(result.domains))
    else:
        logger.info("Cache already fresh; no sync needed.")

    if synced_at:
        logger.info("Last successful sync: %s (status=%s)", synced_at.isoformat(), status)
    else:
        logger.info("Sync status: %s", status)


if __name__ == "__main__":
    main()
