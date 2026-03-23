"""Dataset query tools for the Data Agent."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from strands import tool


@tool
async def list_datasets(
    query: str = "",
    classification: str = "",
    lab_name: str = "",
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Search and list datasets in the Synaptica Data Vault.

    Args:
        query: Free-text search term matched against title, description, and tags.
        classification: Filter by data classification ('failed' or 'underused').
        lab_name: Filter by lab name.
        limit: Maximum number of datasets to return (default 10).

    Returns:
        A dict with 'total' count and 'datasets' list of summary dicts.
    """
    from shared.database import SessionLocal
    from shared.database.models import DataAsset

    db = SessionLocal()
    try:
        q = db.query(DataAsset).order_by(DataAsset.created_at.desc())

        if classification:
            q = q.filter(DataAsset.data_classification == classification)
        if lab_name:
            q = q.filter(DataAsset.lab_name.ilike(f"%{lab_name}%"))
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                DataAsset.title.ilike(pattern)
                | DataAsset.description.ilike(pattern)
            )

        rows = q.limit(limit).all()
        datasets = []
        for r in rows:
            meta = r.meta if isinstance(r.meta, dict) else {}
            datasets.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "description": (r.description or "")[:200],
                    "lab_name": r.lab_name,
                    "classification": r.data_classification,
                    "tags": r.tags or [],
                    "verification_status": meta.get("verification_status", "pending"),
                    "proof_status": meta.get("proof_status", "unanchored"),
                    "size_bytes": r.size_bytes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return {"total": len(datasets), "datasets": datasets}
    finally:
        db.close()


@tool
async def get_dataset_detail(dataset_id: str) -> Dict[str, Any]:
    """
    Get full metadata for a specific dataset by its ID.

    Args:
        dataset_id: The unique dataset identifier.

    Returns:
        A dict with all dataset fields, or an error message if not found.
    """
    from shared.database import SessionLocal
    from shared.database.models import DataAsset

    db = SessionLocal()
    try:
        asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).first()
        if not asset:
            return {"error": f"Dataset '{dataset_id}' not found."}

        meta = asset.meta if isinstance(asset.meta, dict) else {}
        return {
            "id": asset.id,
            "title": asset.title,
            "description": asset.description,
            "lab_name": asset.lab_name,
            "uploader_name": asset.uploader_name,
            "classification": asset.data_classification,
            "tags": asset.tags or [],
            "intended_visibility": asset.intended_visibility,
            "filename": asset.filename,
            "content_type": asset.content_type,
            "size_bytes": asset.size_bytes,
            "sha256": asset.sha256,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "verification_status": meta.get("verification_status", "pending"),
            "verification_report": meta.get("verification_report"),
            "proof_status": meta.get("proof_status", "unanchored"),
            "manifest_cid": meta.get("manifest_cid"),
            "reuse_count": meta.get("reuse_count", 0),
            "hol_sessions_count": len(meta.get("hol_sessions", [])),
        }
    finally:
        db.close()


@tool
async def get_dataset_content_preview(
    dataset_id: str, max_lines: int = 20
) -> Dict[str, Any]:
    """
    Read a preview of the actual dataset file contents (first N lines).

    Args:
        dataset_id: The unique dataset identifier.
        max_lines: Maximum number of lines to return (default 20).

    Returns:
        A dict with 'filename', 'content_type', and 'preview' text,
        or an error message if the file cannot be read.
    """
    from shared.database import SessionLocal
    from shared.database.models import DataAsset

    db = SessionLocal()
    try:
        asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).first()
        if not asset:
            return {"error": f"Dataset '{dataset_id}' not found."}

        path = asset.stored_path
        if not path or not os.path.isfile(path):
            return {
                "filename": asset.filename,
                "error": "Dataset file is not available on disk.",
            }

        try:
            with open(path, "r", errors="replace") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line.rstrip("\n"))
            return {
                "filename": asset.filename,
                "content_type": asset.content_type,
                "lines_returned": len(lines),
                "preview": "\n".join(lines),
            }
        except Exception as exc:
            return {
                "filename": asset.filename,
                "error": f"Could not read file: {exc}",
            }
    finally:
        db.close()
