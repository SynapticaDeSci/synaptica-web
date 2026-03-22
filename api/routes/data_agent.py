"""Built-in Data Agent routes for upload, verification, anchoring, and reuse."""

from __future__ import annotations

import csv
import contextlib
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from shared.database import DataAsset, get_db
from shared.hedera.client import get_hedera_client
from shared.hol_client import (
    HolClientError,
    create_session as hol_create_session,
    search_agents as hol_search_agents,
    send_message as hol_send_message,
)

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".json", ".txt", ".xlsx", ".zip"}
ALLOWED_CLASSIFICATIONS = {"failed", "underused"}
ALLOWED_VISIBILITY = {"private", "org", "public"}
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "data_agent_uploads"
PINATA_PIN_JSON_URL = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
DEFAULT_HOL_DATA_AGENT_CAPABILITIES = [
    "data analysis",
    "dataset curation",
    "csv processing",
    "tabular validation",
]
HOL_SESSION_HISTORY_LIMIT = 20


class SimilarDataset(BaseModel):
    """Compact representation for related datasets."""

    id: str
    title: str
    data_classification: str
    tags: List[str]
    similarity_score: float


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
    verification_status: str
    proof_status: str
    manifest_cid: Optional[str] = None
    reuse_count: int
    last_reused_at: Optional[str] = None
    failed_reason: Optional[str] = None
    reuse_domains: List[str]


class DataAssetDetailResponse(DataAssetResponse):
    """Detailed dataset response with trust and similarity context."""

    verification_report: Optional[Dict[str, Any]] = None
    proof_bundle: Optional[Dict[str, Any]] = None
    similar_datasets: List[SimilarDataset] = Field(default_factory=list)
    hol_sessions: List[Dict[str, Any]] = Field(default_factory=list)


class DataAssetListResponse(BaseModel):
    """Paginated datasets listing."""

    total: int
    limit: int
    offset: int
    datasets: List[DataAssetResponse]


class UploadDatasetResponse(DataAssetResponse):
    """Upload response payload."""

    message: str = Field(default="Dataset uploaded successfully.")


class DatasetProofResponse(BaseModel):
    """Proof bundle payload for judges and downstream tooling."""

    dataset_id: str
    file_sha256: str
    manifest_cid: Optional[str] = None
    manifest_sha256: Optional[str] = None
    manifest_gateway_url: Optional[str] = None
    hcs_topic_id: Optional[str] = None
    hcs_message_status: Optional[str] = None
    anchor_payload: Optional[Dict[str, Any]] = None
    anchored_at: Optional[str] = None
    verification_status: str
    verification_report: Optional[Dict[str, Any]] = None
    proof_status: str


class DatasetCitationResponse(BaseModel):
    """JSON citation payload for dataset reuse."""

    citation: Dict[str, Any]


class ReuseEventResponse(BaseModel):
    """Response for manual dataset reuse registration."""

    dataset_id: str
    reuse_count: int
    last_reused_at: str
    message: str


class HolUseDatasetRequest(BaseModel):
    """Request payload for hiring a HOL data agent on top of an uploaded dataset."""

    uaid: Optional[str] = None
    search_query: Optional[str] = None
    required_capabilities: List[str] = Field(default_factory=list)
    instructions: Optional[str] = None
    transport: Optional[str] = None
    as_uaid: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=25)


class HolUseDatasetResponse(BaseModel):
    """Response payload for HOL data-agent usage."""

    success: bool = True
    dataset_id: str
    uaid: str
    agent_name: Optional[str] = None
    registry: Optional[str] = None
    session_id: str
    query: str
    hol_session: Dict[str, Any] = Field(default_factory=dict)
    broker_response: Dict[str, Any] = Field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_storage_dir() -> Path:
    configured = os.getenv("DATA_AGENT_STORAGE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_STORAGE_DIR


def _parse_string_list(raw_value: Optional[str], field_name: str) -> List[str]:
    if not raw_value:
        return []

    value = raw_value.strip()
    if not value:
        return []

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{field_name} must be comma-separated text or a JSON array",
            ) from exc
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{field_name} JSON must be an array of strings",
            )
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in value.split(",") if item.strip()]


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


def _default_meta(*, failed_reason: Optional[str], reuse_domains: List[str]) -> Dict[str, Any]:
    return {
        "verification_status": "pending",
        "verification_report": None,
        "proof_status": "unanchored",
        "manifest_cid": None,
        "manifest_sha256": None,
        "manifest_gateway_url": None,
        "hcs_topic_id": None,
        "hcs_message_status": None,
        "anchor_payload": None,
        "anchored_at": None,
        "proof_last_error": None,
        "reuse_count": 0,
        "last_reused_at": None,
        "failed_reason": failed_reason,
        "reuse_domains": reuse_domains,
    }


def _coerce_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = _default_meta(failed_reason=None, reuse_domains=[])
    if isinstance(meta, dict):
        merged.update(meta)
    if not isinstance(merged.get("reuse_domains"), list):
        merged["reuse_domains"] = []
    merged["reuse_count"] = int(merged.get("reuse_count") or 0)
    return merged


def _coerce_hol_sessions(meta: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(meta, dict):
        return []
    raw_sessions = meta.get("hol_sessions")
    if not isinstance(raw_sessions, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in raw_sessions:
        if isinstance(item, dict):
            cleaned.append(dict(item))
    return cleaned[-HOL_SESSION_HISTORY_LIMIT:]


def _append_hol_session(meta: Dict[str, Any], session_payload: Dict[str, Any]) -> Dict[str, Any]:
    sessions = _coerce_hol_sessions(meta)
    sessions.append(dict(session_payload))
    next_meta = dict(meta)
    next_meta["hol_sessions"] = sessions[-HOL_SESSION_HISTORY_LIMIT:]
    return next_meta


def _tabular_summary(payload: bytes, delimiter: str) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = payload.decode("latin-1")
        except UnicodeDecodeError as exc:
            return False, {}, f"Unable to decode text payload: {exc}"

    row_count = 0
    max_columns = 0
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for row in reader:
        row_count += 1
        max_columns = max(max_columns, len(row))
    return True, {"rows": row_count, "columns": max_columns}, None


def _json_summary(payload: bytes) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"Invalid JSON payload: {exc}"

    if isinstance(data, list):
        row_count = len(data)
        keys = set()
        for item in data:
            if isinstance(item, dict):
                keys.update(item.keys())
        return True, {"rows": row_count, "columns": len(keys), "shape": "list"}, None
    if isinstance(data, dict):
        return True, {"rows": 1, "columns": len(data.keys()), "shape": "object"}, None
    return True, {"rows": 1, "columns": 1, "shape": type(data).__name__}, None


def _xlsx_summary(payload: bytes) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"openpyxl is unavailable for xlsx validation: {exc}"

    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        sheet = workbook.active
        row_count = 0
        max_columns = 0
        for row in sheet.iter_rows(values_only=True):
            if any(cell is not None for cell in row):
                row_count += 1
                max_columns = max(max_columns, len(row))
        return True, {"rows": row_count, "columns": max_columns, "sheet": sheet.title}, None
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"Invalid XLSX payload: {exc}"


def _zip_summary(payload: bytes) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            files = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            return True, {"file_count": len(files), "sample_files": files[:10]}, None
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"Invalid ZIP payload: {exc}"


def _txt_summary(payload: bytes) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("latin-1", errors="ignore")
    lines = text.splitlines()
    return True, {"rows": len(lines), "columns": 1}, None


def _extension_summary(extension: str, payload: bytes) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    if extension == ".csv":
        return _tabular_summary(payload, ",")
    if extension == ".tsv":
        return _tabular_summary(payload, "\t")
    if extension == ".json":
        return _json_summary(payload)
    if extension == ".txt":
        return _txt_summary(payload)
    if extension == ".xlsx":
        return _xlsx_summary(payload)
    if extension == ".zip":
        return _zip_summary(payload)
    return False, {}, f"Unsupported extension {extension}"


def _build_verification_report(
    *,
    asset: DataAsset,
    payload: bytes,
    extension: str,
    db: Session,
) -> Tuple[str, Dict[str, Any]]:
    computed_hash = hashlib.sha256(payload).hexdigest()
    checksum_ok = computed_hash == asset.sha256
    not_empty = len(payload) > 0
    parse_ok, summary, parse_error = _extension_summary(extension, payload)

    duplicates = (
        db.query(DataAsset)
        .filter(DataAsset.sha256 == asset.sha256)
        .filter(DataAsset.id != asset.id)
        .all()
    )
    duplicate_ok = len(duplicates) == 0

    checks = {
        "checksum": {
            "passed": checksum_ok,
            "expected": asset.sha256,
            "computed": computed_hash,
        },
        "file_type_consistency": {
            "passed": parse_ok,
            "extension": extension,
            "error": parse_error,
        },
        "empty_file": {
            "passed": not_empty,
            "size_bytes": len(payload),
        },
        "duplicate_hash": {
            "passed": duplicate_ok,
            "duplicate_ids": [row.id for row in duplicates],
        },
    }
    status_value = "passed" if all(item["passed"] for item in checks.values()) else "failed"
    report = {
        "checked_at": _now_iso(),
        "status": status_value,
        "checks": checks,
        "summary": summary,
    }
    return status_value, report


def _serialize_asset(asset: DataAsset) -> Dict[str, Any]:
    meta = _coerce_meta(asset.meta)
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
        "verification_status": meta.get("verification_status") or "pending",
        "proof_status": meta.get("proof_status") or "unanchored",
        "manifest_cid": meta.get("manifest_cid"),
        "reuse_count": int(meta.get("reuse_count") or 0),
        "last_reused_at": meta.get("last_reused_at"),
        "failed_reason": meta.get("failed_reason"),
        "reuse_domains": meta.get("reuse_domains") or [],
    }


def _build_proof_bundle(asset: DataAsset) -> Dict[str, Any]:
    meta = _coerce_meta(asset.meta)
    return {
        "dataset_id": asset.id,
        "file_sha256": asset.sha256,
        "manifest_cid": meta.get("manifest_cid"),
        "manifest_sha256": meta.get("manifest_sha256"),
        "manifest_gateway_url": meta.get("manifest_gateway_url"),
        "hcs_topic_id": meta.get("hcs_topic_id"),
        "hcs_message_status": meta.get("hcs_message_status"),
        "anchor_payload": meta.get("anchor_payload"),
        "anchored_at": meta.get("anchored_at"),
        "verification_status": meta.get("verification_status") or "pending",
        "verification_report": meta.get("verification_report"),
        "proof_status": meta.get("proof_status") or "unanchored",
    }


def _manifest_payload(asset: DataAsset) -> Dict[str, Any]:
    meta = _coerce_meta(asset.meta)
    return {
        "schema": "synaptica-data-asset-manifest-v1",
        "datasetId": asset.id,
        "title": asset.title,
        "description": asset.description,
        "labName": asset.lab_name,
        "uploaderName": asset.uploader_name,
        "dataClassification": asset.data_classification,
        "tags": asset.tags or [],
        "intendedVisibility": asset.intended_visibility,
        "filename": asset.filename,
        "sizeBytes": asset.size_bytes,
        "contentType": asset.content_type,
        "fileSha256": asset.sha256,
        "verificationStatus": meta.get("verification_status") or "pending",
        "verificationReport": meta.get("verification_report"),
        "failedReason": meta.get("failed_reason"),
        "reuseDomains": meta.get("reuse_domains") or [],
        "createdAt": asset.created_at.isoformat() if asset.created_at else None,
    }


def _pinata_headers() -> Dict[str, str]:
    jwt = os.getenv("PINATA_JWT")
    if jwt:
        return {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        }

    api_key = os.getenv("PINATA_API_KEY")
    secret_key = os.getenv("PINATA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError(
            "Pinata credentials missing. Configure PINATA_JWT or PINATA_API_KEY/PINATA_SECRET_KEY."
        )
    return {
        "pinata_api_key": api_key,
        "pinata_secret_api_key": secret_key,
        "Content-Type": "application/json",
    }


async def _pin_manifest_to_pinata(asset: DataAsset, manifest: Dict[str, Any]) -> Tuple[str, str]:
    headers = _pinata_headers()
    payload = {
        "pinataMetadata": {
            "name": f"data-asset-manifest-{asset.id}.json",
            "keyvalues": {
                "project": "Synaptica",
                "type": "data_asset_manifest",
                "dataset_id": asset.id,
            },
        },
        "pinataContent": manifest,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(PINATA_PIN_JSON_URL, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        response_body = ""
        with contextlib.suppress(Exception):
            response_body = exc.response.text.strip()
        snippet = f" Body: {response_body[:240]}" if response_body else ""
        raise RuntimeError(
            f"Pinata request failed with status {exc.response.status_code}.{snippet}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Pinata request error: {exc}") from exc

    cid = body.get("IpfsHash")
    if not cid:
        raise RuntimeError("Pinata did not return IpfsHash")
    return cid, f"https://gateway.pinata.cloud/ipfs/{cid}"


async def _submit_anchor_message(anchor_payload: Dict[str, Any]) -> Tuple[str, str]:
    try:
        client = get_hedera_client()
    except ValidationError as exc:
        raise RuntimeError(
            "Hedera configuration missing. Configure HEDERA_ACCOUNT_ID and HEDERA_PRIVATE_KEY."
        ) from exc
    topic_id = client.topic_id
    if topic_id is None:
        topic_id = await client.create_topic("Synaptica Data Agent Provenance")
    message_status = await client.submit_message(
        json.dumps(anchor_payload, sort_keys=True, separators=(",", ":")),
        topic_id=topic_id,
    )
    return str(topic_id), str(message_status)


def _apply_verification(asset: DataAsset, db: Session) -> None:
    path = Path(asset.stored_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file is missing")
    payload = path.read_bytes()
    extension = path.suffix.lower()
    verification_status, report = _build_verification_report(
        asset=asset,
        payload=payload,
        extension=extension,
        db=db,
    )
    meta = _coerce_meta(asset.meta)
    meta["verification_status"] = verification_status
    meta["verification_report"] = report
    asset.meta = meta


def _similar_datasets(db: Session, asset: DataAsset, limit: int = 5) -> List[Dict[str, Any]]:
    source_tags = set(tag.lower() for tag in (asset.tags or []))
    rows = (
        db.query(DataAsset)
        .filter(DataAsset.id != asset.id)
        .order_by(DataAsset.created_at.desc())
        .all()
    )

    scored: List[Tuple[float, DataAsset]] = []
    for row in rows:
        row_tags = set(tag.lower() for tag in (row.tags or []))
        overlap = len(source_tags.intersection(row_tags))
        score = float(overlap)
        if row.data_classification == asset.data_classification:
            score += 1.0
        if row.lab_name == asset.lab_name:
            score += 0.5
        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    output: List[Dict[str, Any]] = []
    for score, row in scored[:limit]:
        output.append(
            {
                "id": row.id,
                "title": row.title,
                "data_classification": row.data_classification,
                "tags": row.tags or [],
                "similarity_score": round(score, 2),
            }
        )
    return output


async def _anchor_dataset_internal(asset: DataAsset, db: Session) -> Dict[str, Any]:
    meta = _coerce_meta(asset.meta)

    manifest = _manifest_payload(asset)
    manifest_bytes = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    try:
        cid, gateway_url = await _pin_manifest_to_pinata(asset, manifest)
    except Exception as exc:  # noqa: BLE001
        meta["proof_status"] = "failed"
        meta["proof_last_error"] = f"Pinata upload failed: {exc}"
        asset.meta = meta
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to pin manifest to Pinata: {exc}",
        ) from exc

    anchor_payload = {
        "dataset_id": asset.id,
        "manifest_cid": cid,
        "manifest_sha256": manifest_sha256,
        "lab_name": asset.lab_name,
        "uploaded_at": asset.created_at.isoformat() if asset.created_at else _now_iso(),
    }

    try:
        topic_id, message_status = await _submit_anchor_message(anchor_payload)
    except Exception as exc:  # noqa: BLE001
        meta["proof_status"] = "manifest_pinned"
        meta["manifest_cid"] = cid
        meta["manifest_sha256"] = manifest_sha256
        meta["manifest_gateway_url"] = gateway_url
        meta["proof_last_error"] = f"Hedera anchoring failed: {exc}"
        asset.meta = meta
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to anchor manifest on Hedera: {exc}",
        ) from exc

    meta["proof_status"] = "anchored"
    meta["manifest_cid"] = cid
    meta["manifest_sha256"] = manifest_sha256
    meta["manifest_gateway_url"] = gateway_url
    meta["hcs_topic_id"] = topic_id
    meta["hcs_message_status"] = message_status
    meta["anchor_payload"] = anchor_payload
    meta["anchored_at"] = _now_iso()
    meta["proof_last_error"] = None
    asset.meta = meta
    db.commit()
    db.refresh(asset)
    return _build_proof_bundle(asset)


@router.post("/datasets", response_model=UploadDatasetResponse, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    title: str = Form(...),
    description: str = Form(""),
    lab_name: str = Form(...),
    data_classification: str = Form(...),
    tags: Optional[str] = Form(default=None),
    intended_visibility: str = Form("private"),
    uploader_name: Optional[str] = Form(default=None),
    failed_reason: Optional[str] = Form(default=None),
    reuse_domains: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadDatasetResponse:
    """Upload a dataset for Data Agent storage and run automated verification."""

    cleaned_title = title.strip()
    cleaned_lab = lab_name.strip()
    if not cleaned_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title is required")
    if not cleaned_lab:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lab_name is required")

    classification = _validate_classification(data_classification)
    visibility = _validate_visibility(intended_visibility)
    parsed_tags = _parse_string_list(tags, "tags")
    parsed_reuse_domains = _parse_string_list(reuse_domains, "reuse_domains")

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
            meta=_default_meta(
                failed_reason=(failed_reason or "").strip() or None,
                reuse_domains=parsed_reuse_domains,
            ),
        )
        db.add(data_asset)
        db.flush()

        _apply_verification(data_asset, db)
        db.commit()
        db.refresh(data_asset)

        auto_anchor = os.getenv("DATA_AGENT_AUTO_ANCHOR", "0").lower() in {"1", "true", "yes"}
        if auto_anchor:
            try:
                await _anchor_dataset_internal(data_asset, db)
            except HTTPException:
                # Keep upload successful even when anchoring fails; proof_status captures failure.
                pass
            db.refresh(data_asset)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    return UploadDatasetResponse(**_serialize_asset(data_asset))


@router.post("/datasets/{dataset_id}/verify", response_model=DataAssetDetailResponse)
async def verify_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DataAssetDetailResponse:
    """Manually trigger verification checks for an existing dataset."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    _apply_verification(asset, db)
    db.commit()
    db.refresh(asset)

    return DataAssetDetailResponse(
        **_serialize_asset(asset),
        verification_report=_coerce_meta(asset.meta).get("verification_report"),
        proof_bundle=_build_proof_bundle(asset),
        similar_datasets=[SimilarDataset(**row) for row in _similar_datasets(db, asset)],
        hol_sessions=_coerce_hol_sessions(asset.meta),
    )


@router.post("/datasets/{dataset_id}/anchor", response_model=DatasetProofResponse)
async def anchor_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DatasetProofResponse:
    """Pin canonical manifest and anchor provenance payload to Hedera HCS."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    # Ensure trust report is fresh before anchoring.
    _apply_verification(asset, db)
    db.commit()
    db.refresh(asset)

    proof = await _anchor_dataset_internal(asset, db)
    return DatasetProofResponse(**proof)


@router.get("/datasets", response_model=DataAssetListResponse)
async def list_datasets(
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    classification: Optional[str] = Query(default=None),
    verification_status: Optional[str] = Query(default=None),
    proof_status: Optional[str] = Query(default=None),
    lab_name: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DataAssetListResponse:
    """List datasets with discovery-focused filters."""

    query = db.query(DataAsset).order_by(DataAsset.created_at.desc())
    if classification:
        query = query.filter(DataAsset.data_classification == _validate_classification(classification))
    if lab_name:
        query = query.filter(DataAsset.lab_name.ilike(f"%{lab_name.strip()}%"))
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
    if verification_status:
        normalized = verification_status.strip().lower()
        records = [
            row for row in records if (_coerce_meta(row.meta).get("verification_status") or "").lower() == normalized
        ]
    if proof_status:
        normalized = proof_status.strip().lower()
        records = [row for row in records if (_coerce_meta(row.meta).get("proof_status") or "").lower() == normalized]

    total = len(records)
    paged = records[offset : offset + limit]
    return DataAssetListResponse(
        total=total,
        limit=limit,
        offset=offset,
        datasets=[DataAssetResponse(**_serialize_asset(row)) for row in paged],
    )


@router.get("/datasets/{dataset_id}", response_model=DataAssetDetailResponse)
async def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DataAssetDetailResponse:
    """Fetch detailed dataset metadata with trust and similarity context."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    meta = _coerce_meta(asset.meta)
    return DataAssetDetailResponse(
        **_serialize_asset(asset),
        verification_report=meta.get("verification_report"),
        proof_bundle=_build_proof_bundle(asset),
        similar_datasets=[SimilarDataset(**row) for row in _similar_datasets(db, asset)],
        hol_sessions=_coerce_hol_sessions(asset.meta),
    )


@router.get("/datasets/{dataset_id}/proof", response_model=DatasetProofResponse)
async def get_dataset_proof(dataset_id: str, db: Session = Depends(get_db)) -> DatasetProofResponse:
    """Return proof bundle used for judge-facing verifiability demo."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return DatasetProofResponse(**_build_proof_bundle(asset))


@router.get("/datasets/{dataset_id}/citation", response_model=DatasetCitationResponse)
async def get_dataset_citation(dataset_id: str, db: Session = Depends(get_db)) -> DatasetCitationResponse:
    """Return a JSON citation object for copy/paste into reports and tools."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    meta = _coerce_meta(asset.meta)

    citation = {
        "type": "dataset",
        "title": asset.title,
        "dataset_id": asset.id,
        "authoring_lab": asset.lab_name,
        "uploader": asset.uploader_name,
        "published_at": asset.created_at.isoformat() if asset.created_at else _now_iso(),
        "provider": "Synaptica Data Agent",
        "classification": asset.data_classification,
        "failed_reason": meta.get("failed_reason"),
        "reuse_domains": meta.get("reuse_domains") or [],
        "identifiers": {
            "file_sha256": asset.sha256,
            "manifest_cid": meta.get("manifest_cid"),
            "manifest_sha256": meta.get("manifest_sha256"),
            "hcs_topic_id": meta.get("hcs_topic_id"),
        },
        "links": {
            "manifest_gateway_url": meta.get("manifest_gateway_url"),
            "proof_endpoint": f"/api/data-agent/datasets/{asset.id}/proof",
        },
    }
    return DatasetCitationResponse(citation=citation)


def _default_hol_query(asset: DataAsset, required_capabilities: List[str]) -> str:
    terms = [
        "data agent",
        asset.data_classification,
        asset.lab_name,
        *(asset.tags or []),
        *required_capabilities,
    ]
    return " ".join(part.strip() for part in terms if isinstance(part, str) and part.strip())


def _build_hol_search_queries(
    asset: DataAsset,
    *,
    required_capabilities: List[str],
    search_query: Optional[str],
) -> List[str]:
    explicit = (search_query or "").strip()
    if explicit:
        return [explicit]

    candidates = [
        _default_hol_query(asset, required_capabilities),
        "data agent",
        "dataset curation",
        "tabular validation",
    ]
    deduped: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _default_hol_instructions(asset: DataAsset) -> str:
    return (
        "Analyze this dataset metadata and propose reuse opportunities, data quality caveats, "
        "and practical next-step recommendations. Keep the response concise and structured."
    )


@router.post("/datasets/{dataset_id}/hol-use", response_model=HolUseDatasetResponse)
async def use_hol_data_agent(
    dataset_id: str,
    request: HolUseDatasetRequest,
    db: Session = Depends(get_db),
) -> HolUseDatasetResponse:
    """Use a HOL-discovered (or explicit) data agent for a dataset microtask."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    meta = _coerce_meta(asset.meta)
    required_capabilities = [
        item.strip()
        for item in (request.required_capabilities or [])
        if isinstance(item, str) and item.strip()
    ] or list(DEFAULT_HOL_DATA_AGENT_CAPABILITIES)
    query_candidates = _build_hol_search_queries(
        asset,
        required_capabilities=required_capabilities,
        search_query=request.search_query,
    )
    query = query_candidates[0]

    selected_uaid = (request.uaid or "").strip()
    selected_name: Optional[str] = None
    selected_registry: Optional[str] = None

    if not selected_uaid:
        try:
            candidates: List[Any] = []
            for candidate_query in query_candidates:
                discovered = hol_search_agents(query=candidate_query, limit=request.limit)
                if discovered:
                    candidates = discovered
                    query = candidate_query
                    break
        except HolClientError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No HOL agents found for the provided dataset query. "
                    "Try specifying a known UAID override."
                ),
            )

        selected = candidates[0]
        selected_uaid = selected.uaid
        selected_name = selected.name
        selected_registry = selected.registry

    instructions = (request.instructions or "").strip() or _default_hol_instructions(asset)
    context_payload = {
        "dataset_id": asset.id,
        "title": asset.title,
        "description": asset.description,
        "lab_name": asset.lab_name,
        "data_classification": asset.data_classification,
        "tags": asset.tags or [],
        "reuse_domains": meta.get("reuse_domains") or [],
        "verification_status": meta.get("verification_status") or "pending",
        "proof_status": meta.get("proof_status") or "unanchored",
        "manifest_cid": meta.get("manifest_cid"),
        "sha256": asset.sha256,
        "size_bytes": asset.size_bytes,
    }
    message_payload = {
        "role": "user",
        "type": "synaptica_data_agent_microtask",
        "instructions": instructions,
        "context": context_payload,
    }

    try:
        session_id = hol_create_session(
            uaid=selected_uaid,
            transport=request.transport,
            as_uaid=request.as_uaid,
        )
        broker_response = hol_send_message(
            session_id=session_id,
            message=json.dumps(message_payload, ensure_ascii=True),
            as_uaid=request.as_uaid,
        )
    except HolClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    public_url = None
    if isinstance(broker_response, dict):
        maybe_url = broker_response.get("publicUrl") or broker_response.get("public_url")
        if isinstance(maybe_url, str) and maybe_url.strip():
            public_url = maybe_url.strip()

    hol_session = {
        "created_at": _now_iso(),
        "session_id": session_id,
        "uaid": selected_uaid,
        "agent_name": selected_name,
        "registry": selected_registry,
        "query": query,
        "instructions": instructions,
        "transport": request.transport,
        "public_url": public_url,
    }
    asset.meta = _append_hol_session(meta, hol_session)
    db.commit()
    db.refresh(asset)

    return HolUseDatasetResponse(
        dataset_id=asset.id,
        uaid=selected_uaid,
        agent_name=selected_name,
        registry=selected_registry,
        session_id=session_id,
        query=query,
        hol_session=hol_session,
        broker_response=broker_response if isinstance(broker_response, dict) else {},
    )


@router.post("/datasets/{dataset_id}/reuse-events", response_model=ReuseEventResponse)
async def record_dataset_reuse(dataset_id: str, db: Session = Depends(get_db)) -> ReuseEventResponse:
    """Increment reuse counters for a dataset."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    meta = _coerce_meta(asset.meta)
    meta["reuse_count"] = int(meta.get("reuse_count") or 0) + 1
    meta["last_reused_at"] = _now_iso()
    asset.meta = meta
    db.commit()
    db.refresh(asset)

    return ReuseEventResponse(
        dataset_id=asset.id,
        reuse_count=int(meta["reuse_count"]),
        last_reused_at=meta["last_reused_at"],
        message="Reuse event recorded.",
    )


@router.get("/datasets/{dataset_id}/download")
async def download_dataset(dataset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Download the original dataset file."""

    asset = db.query(DataAsset).filter(DataAsset.id == dataset_id).one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    path = Path(asset.stored_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored file is missing for this dataset",
        )

    return FileResponse(
        path=str(path),
        media_type=asset.content_type or "application/octet-stream",
        filename=asset.filename,
    )
