"""Built-in Data Agent routes for uploading and managing underused datasets."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from shared.database import DataAsset, get_db

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".json", ".txt", ".xlsx", ".zip"}
ALLOWED_CLASSIFICATIONS = {"failed", "underused"}
ALLOWED_VISIBILITY = {"private", "org", "public"}
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "data_agent_uploads"


class DataAssetResponse(BaseModel):
    """Serialized dataset metadata for API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    lab_name: str
    uploader_name: Optional[str] = None
    data_classification: str
    tags: List[str]
    intended_visibility: str
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    sha256: str
    created_at: str


class DataAssetListResponse(BaseModel):
    """Paginated datasets listing."""

    total: int
    limit: int
    offset: int
    datasets: List[DataAssetResponse]


class UploadDatasetResponse(DataAssetResponse):
    """Upload response payload."""

    message: str = Field(default="Dataset uploaded successfully.")


def _get_storage_dir() -> Path:
    configured = os.getenv("DATA_AGENT_STORAGE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_STORAGE_DIR


def _parse_tags(raw_tags: Optional[str]) -> List[str]:
    if not raw_tags:
        return []

    value = raw_tags.strip()
    if not value:
        return []

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tags must be comma-separated text or a JSON array",
            ) from exc
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tags JSON must be an array of strings",
            )
        return [str(tag).strip() for tag in parsed if str(tag).strip()]

    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _validate_classification(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in ALLOWED_CLASSIFICATIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"data_classification must be one of {sorted(ALLOWED_CLASSIFICATIONS)}",
        )
    return normalized


def _validate_visibility(value: str) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in ALLOWED_VISIBILITY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"intended_visibility must be one of {sorted(ALLOWED_VISIBILITY)}",
        )
    return normalized


def _serialize_asset(asset: DataAsset) -> Dict[str, Any]:
    return {
        "id": asset.id,
        "title": asset.title,
        "description": asset.description,
        "lab_name": asset.lab_name,
        "uploader_name": asset.uploader_name,
        "data_classification": asset.data_classification,
        "tags": asset.tags or [],
        "intended_visibility": asset.intended_visibility or "private",
        "filename": asset.filename,
        "size_bytes": asset.size_bytes,
        "content_type": asset.content_type,
        "sha256": asset.sha256,
        "created_at": asset.created_at.isoformat() if asset.created_at else "",
    }


@router.post("/datasets", response_model=UploadDatasetResponse, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    title: str = Form(...),
    description: str = Form(""),
    lab_name: str = Form(...),
    data_classification: str = Form(...),
    tags: Optional[str] = Form(default=None),
    intended_visibility: str = Form("private"),
    uploader_name: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadDatasetResponse:
    """Upload a dataset for Data Agent storage."""

    cleaned_title = title.strip()
    cleaned_lab = lab_name.strip()
    if not cleaned_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title is required")
    if not cleaned_lab:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lab_name is required")

    classification = _validate_classification(data_classification)
    visibility = _validate_visibility(intended_visibility)
    parsed_tags = _parse_tags(tags)

    original_name = (file.filename or "").strip()
    if not original_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file is required")

    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed extensions: {sorted(ALLOWED_EXTENSIONS)}",
        )

    payload = await file.read()
    size = len(payload)
    if size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File exceeds maximum size of 25MB",
        )

    safe_name = Path(original_name).name
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    storage_dir = _get_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / stored_name
    stored_path.write_bytes(payload)

    try:
        data_asset = DataAsset(  # type: ignore[call-arg]
            id=str(uuid.uuid4()),
            title=cleaned_title,
            description=description.strip() or None,
            lab_name=cleaned_lab,
            uploader_name=(uploader_name or "").strip() or None,
            data_classification=classification,
            tags=parsed_tags,
            intended_visibility=visibility,
            filename=safe_name,
            stored_path=str(stored_path),
            content_type=file.content_type,
            size_bytes=size,
            sha256=hashlib.sha256(payload).hexdigest(),
            meta={},
        )
        db.add(data_asset)
        db.commit()
        db.refresh(data_asset)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    response_payload = _serialize_asset(data_asset)
    return UploadDatasetResponse(**response_payload)


@router.get("/datasets", response_model=DataAssetListResponse)
async def list_datasets(
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    classification: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DataAssetListResponse:
    """List uploaded datasets with optional filtering."""

    query = db.query(DataAsset).order_by(DataAsset.created_at.desc())
    if classification:
        query = query.filter(DataAsset.data_classification == _validate_classification(classification))

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            DataAsset.title.ilike(term)
            | DataAsset.description.ilike(term)
            | DataAsset.lab_name.ilike(term)
        )

    records = query.all()
    if tag:
        tag_lower = tag.strip().lower()
        records = [
            row
            for row in records
            if any((asset_tag or "").strip().lower() == tag_lower for asset_tag in (row.tags or []))
        ]

    total = len(records)
    paged = records[offset : offset + limit]

    return DataAssetListResponse(
        total=total,
        limit=limit,
        offset=offset,
        datasets=[DataAssetResponse(**_serialize_asset(row)) for row in paged],
    )


@router.get("/datasets/{dataset_id}", response_model=DataAssetResponse)
async def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DataAssetResponse:
    """Fetch metadata for one dataset."""

    data_asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not data_asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    return DataAssetResponse(**_serialize_asset(data_asset))


@router.get("/datasets/{dataset_id}/download")
async def download_dataset(dataset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Download the original dataset file."""

    data_asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not data_asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    path = Path(data_asset.stored_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored file is missing for this dataset",
        )

    return FileResponse(
        path=str(path),
        media_type=data_asset.content_type or "application/octet-stream",
        filename=data_asset.filename,
    )
