"""Helpers for syncing ERC-8004 registry data into the local cache."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from shared.database import (
    Agent,
    AgentReputation,
    AgentRegistrySyncState,
    SessionLocal,
)
from shared.agents_cache import rebuild_agents_cache
from shared.payments.runtime import sync_verified_payment_profile
from shared.handlers.identity_registry_handlers import get_all_domains, resolve_by_domain
from shared.handlers.reputation_registry_handlers import get_full_reputation_info
from shared.handlers.validation_registry_handlers import get_full_validation_info
from shared.research.agent_inventory import is_supported_builtin_research_agent

logger = logging.getLogger(__name__)

_SYNC_LOCK = threading.Lock()
_METADATA_CACHE_LOCK = threading.Lock()
SUPPORTED_AGENT_REPUTATION_FLOOR = 0.8


class RegistrySyncError(RuntimeError):
    """Raised when registry data cannot be synchronized."""


class RegistryUnavailableError(RegistrySyncError):
    """Raised when the registry contracts are unreachable or misconfigured."""


@dataclass
class AgentSnapshot:
    """Normalized snapshot of an on-chain agent."""

    agent_id: str
    name: str
    description: str
    capabilities: List[str]
    categories: List[str]
    metadata_uri: Optional[str]
    metadata_url: Optional[str]
    metadata_cid: Optional[str]
    hedera_account_id: Optional[str]
    endpoint_url: Optional[str]
    health_check_url: Optional[str]
    pricing: Dict[str, Any]
    contact_email: Optional[str]
    logo_url: Optional[str]
    registry_agent_id: int
    registry_domain: str
    registry_address: str
    metadata: Optional[Dict[str, Any]]
    reputation: Dict[str, Any]
    validation: Dict[str, Any]
    reputation_score: float


@dataclass
class RegistrySyncResult:
    """Summary of a registry sync run."""

    synced: int
    domains: List[str]
    status: str
    error: Optional[str] = None


@dataclass
class _PendingSnapshot:
    """Intermediate representation used while resolving metadata."""

    registry_agent_id: int
    registry_domain: str
    registry_address: str
    metadata_uri: Optional[str]
    metadata_cid: Optional[str]
    metadata_url: Optional[str]
    reputation: Dict[str, Any]
    validation: Dict[str, Any]


@dataclass(frozen=True)
class MetadataFetchJob:
    """Metadata fetch instructions for worker threads."""

    metadata_uri: str
    cid: Optional[str]
    urls: List[str]


@dataclass
class _DomainProcessingResult:
    """Container for parallel domain resolution work."""

    pending_snapshot: Optional[_PendingSnapshot]
    metadata_job: Optional[MetadataFetchJob]


def ensure_registry_cache(force: bool = False) -> Optional[RegistrySyncResult]:
    """
    Synchronize registry data when the cache is stale.

    Args:
        force: When True sync regardless of TTL.

    Returns:
        RegistrySyncResult if a sync was performed, otherwise None.
    """

    if not force and not _needs_sync():
        return None

    if not _SYNC_LOCK.acquire(blocking=False):
        logger.debug("Agent registry sync already running; skipping duplicate trigger.")
        return None

    try:
        return _sync_agents_from_registry()
    finally:
        _SYNC_LOCK.release()


def trigger_registry_cache_refresh(force: bool = False) -> bool:
    """Trigger a registry sync in a background thread when the cache is stale."""

    if not force and not _needs_sync():
        return False

    def _runner() -> None:
        try:
            ensure_registry_cache(force=force)
        except Exception:  # noqa: BLE001
            logger.exception("Background registry sync failed")

    threading.Thread(target=_runner, daemon=True, name="registry-sync").start()
    return True


def is_registry_cache_stale() -> bool:
    """Return True when the registry cache TTL has expired."""

    return _needs_sync()


def get_registry_cache_ttl_seconds() -> int:
    """Expose the configured registry cache TTL."""

    return _get_cache_ttl_seconds()


def get_registry_sync_status() -> Tuple[str, Optional[datetime]]:
    """Return the last recorded sync status and timestamp."""

    session = SessionLocal()
    try:
        state = _get_or_create_state(session)
        return state.status or "never", state.last_successful_at
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _needs_sync() -> bool:
    ttl_seconds = _get_cache_ttl_seconds()
    session = SessionLocal()
    try:
        state = _get_or_create_state(session)
        if state.last_successful_at is None:
            return True
        delta = datetime.utcnow() - state.last_successful_at
        return delta.total_seconds() >= ttl_seconds
    finally:
        session.close()


def _sync_agents_from_registry() -> RegistrySyncResult:
    session = SessionLocal()
    now = datetime.utcnow()
    state = None
    try:
        state = _get_or_create_state(session)
        state.status = "running"
        state.last_attempted_at = now
        state.last_error = None
        session.commit()
    finally:
        session.close()

    try:
        snapshots = _fetch_registry_snapshots()
    except Exception as exc:  # noqa: BLE001
        session = SessionLocal()
        try:
            state = _get_or_create_state(session)
            state.status = "error"
            state.last_error = str(exc)
            state.last_attempted_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()
        raise

    session = SessionLocal()
    synced_domains: List[str] = []
    synced_timestamp: Optional[datetime] = None
    try:
        synced_domains = _apply_snapshots(session, snapshots)
        state = _get_or_create_state(session)
        synced_timestamp = datetime.utcnow()
        state.status = "ok"
        state.last_successful_at = synced_timestamp
        state.last_attempted_at = synced_timestamp
        state.last_error = None
        session.commit()
    finally:
        session.close()

    if synced_timestamp:
        try:
            rebuild_agents_cache(synced_at=synced_timestamp)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to rebuild agents cache after registry sync")

    return RegistrySyncResult(
        synced=len(synced_domains),
        domains=synced_domains,
        status="ok",
    )


def _fetch_registry_snapshots() -> List[AgentSnapshot]:
    started_at = time.perf_counter()
    try:
        domains = get_all_domains()
    except RuntimeError as exc:  # pragma: no cover - depends on web3 config
        raise RegistryUnavailableError("Identity registry unavailable. Check RPC/contract configuration.") from exc

    if not domains:
        logger.info("Identity registry returned no domains.")
        return []

    logger.info("Syncing %s agents from registry", len(domains))

    metadata_cache = _load_existing_metadata_cache()
    pending_jobs: Dict[str, MetadataFetchJob] = {}
    pending_snapshots: List[_PendingSnapshot] = []

    workers = _get_registry_worker_count(len(domains))
    logger.debug("Resolving %s registry domains with %s workers", len(domains), workers)
    resolution_started = time.perf_counter()

    if workers <= 1:
        for domain in domains:
            result = _process_domain_for_snapshot(domain, metadata_cache)
            _collect_domain_result(result, pending_snapshots, pending_jobs)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="registry-domain") as executor:
            future_map = {
                executor.submit(_process_domain_for_snapshot, domain, metadata_cache): domain
                for domain in domains
            }
            for future in as_completed(future_map):
                domain = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Domain %s processing failed: %s", domain, exc)
                    continue
                _collect_domain_result(result, pending_snapshots, pending_jobs)

    logger.debug(
        "Domain resolution produced %s snapshots and %s metadata jobs in %.2fs",
        len(pending_snapshots),
        len(pending_jobs),
        time.perf_counter() - resolution_started,
    )

    if pending_jobs:
        fetch_started = time.perf_counter()
        fetched_metadata = _fetch_metadata_batch(pending_jobs)
        for metadata_uri, entry in fetched_metadata.items():
            payload, gateway_url, cid = entry
            _store_metadata_cache_entry(metadata_cache, metadata_uri, gateway_url, cid, payload)
        logger.info(
            "Fetched %s metadata payloads in %.2fs",
            len(fetched_metadata),
            time.perf_counter() - fetch_started,
        )

    snapshots: List[AgentSnapshot] = []
    for item in pending_snapshots:
        payload: Optional[Dict[str, Any]] = None
        metadata_url = item.metadata_url
        metadata_cid = item.metadata_cid

        cache_entry = _get_cached_metadata_entry(metadata_cache, item.metadata_uri, item.metadata_cid)
        if cache_entry:
            payload, cached_url, cached_cid = cache_entry
            metadata_url = cached_url or metadata_url
            metadata_cid = cached_cid or metadata_cid

        snapshot = _build_snapshot(
            registry_agent_id=item.registry_agent_id,
            registry_domain=item.registry_domain,
            registry_address=item.registry_address,
            metadata_uri=item.metadata_uri,
            metadata_payload=payload,
            metadata_url=metadata_url,
            metadata_cid=metadata_cid,
            reputation=item.reputation,
            validation=item.validation,
        )
        snapshots.append(snapshot)

    logger.info(
        "Registry snapshot build completed in %.2fs (agents=%s)",
        time.perf_counter() - started_at,
        len(snapshots),
    )
    return snapshots


def _collect_domain_result(
    result: Optional[_DomainProcessingResult],
    pending_snapshots: List[_PendingSnapshot],
    pending_jobs: Dict[str, MetadataFetchJob],
) -> None:
    if result is None:
        return
    if result.pending_snapshot:
        pending_snapshots.append(result.pending_snapshot)
    job = result.metadata_job
    if job and job.metadata_uri:
        pending_jobs[job.metadata_uri] = job


def _process_domain_for_snapshot(
    domain: str,
    metadata_cache: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]],
) -> Optional[_DomainProcessingResult]:
    domain = (domain or "").strip()
    if not domain:
        return None

    try:
        agent_info = resolve_by_domain(domain)
    except RuntimeError as exc:  # pragma: no cover - contract errors
        logger.warning("Failed to resolve domain %s: %s", domain, exc)
        return None

    if not agent_info:
        logger.warning("Domain %s resolved to empty agent info", domain)
        return None

    try:
        registry_agent_id = int(agent_info[0])
    except (TypeError, ValueError):
        logger.warning("Unexpected agent id for domain %s: %s", domain, agent_info)
        return None

    registry_domain = agent_info[1] or domain
    registry_address = agent_info[2]
    metadata_uri = agent_info[3] if len(agent_info) > 3 else None

    metadata_cid: Optional[str] = None
    metadata_url: Optional[str] = None

    cache_entry = _get_cached_metadata_entry(metadata_cache, metadata_uri, None)
    if cache_entry:
        _, metadata_url, metadata_cid = cache_entry

    metadata_job: Optional[MetadataFetchJob] = None
    if metadata_uri and cache_entry is None:
        resolved_url, resolved_cid = _resolve_metadata_uri(metadata_uri)
        metadata_url = metadata_url or resolved_url
        metadata_cid = metadata_cid or resolved_cid
        cache_entry = _get_cached_metadata_entry(metadata_cache, None, resolved_cid)
        if cache_entry is None:
            job = _build_metadata_fetch_job(metadata_uri, resolved_url, resolved_cid)
            if job:
                metadata_job = job
        else:
            with _METADATA_CACHE_LOCK:
                metadata_cache[metadata_uri] = cache_entry

    rep_info = _safe_reputation_lookup(registry_agent_id)
    val_info = _safe_validation_lookup(registry_agent_id)

    pending_snapshot = _PendingSnapshot(
        registry_agent_id=registry_agent_id,
        registry_domain=registry_domain,
        registry_address=registry_address,
        metadata_uri=metadata_uri,
        metadata_cid=metadata_cid,
        metadata_url=metadata_url,
        reputation=rep_info,
        validation=val_info,
    )

    return _DomainProcessingResult(pending_snapshot=pending_snapshot, metadata_job=metadata_job)


def _get_registry_worker_count(total_domains: int) -> int:
    if total_domains <= 1:
        return 1
    default_workers = 8
    env_value = os.getenv("AGENT_REGISTRY_WORKERS")
    if env_value:
        try:
            parsed = int(env_value)
            if parsed > 0:
                default_workers = parsed
        except ValueError:
            logger.debug("Invalid AGENT_REGISTRY_WORKERS value: %s", env_value)
    return max(1, min(default_workers, total_domains, 32))


def _load_existing_metadata_cache() -> Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]]:
    cache: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]] = {}
    session = SessionLocal()
    try:
        agents = (
            session.query(Agent)
            .filter(Agent.erc8004_metadata_uri.isnot(None))
            .all()
        )
        for agent in agents:
            metadata_uri = agent.erc8004_metadata_uri
            if not metadata_uri:
                continue
            meta = agent.meta or {}
            payload = meta.get("registry_metadata")
            metadata_url = meta.get("metadata_gateway_url")
            metadata_cid = meta.get("metadata_cid")
            if payload is None and metadata_url is None:
                continue
            _store_metadata_cache_entry(cache, metadata_uri, metadata_url, metadata_cid, payload)
    finally:
        session.close()
    return cache


def _get_cached_metadata_entry(
    cache: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]],
    metadata_uri: Optional[str],
    metadata_cid: Optional[str],
) -> Optional[Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]]:
    if metadata_uri:
        entry = cache.get(metadata_uri)
        if entry:
            return entry
    if metadata_cid:
        entry = cache.get(_metadata_cid_cache_key(metadata_cid))
        if entry:
            return entry
    return None


def _store_metadata_cache_entry(
    cache: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]],
    metadata_uri: Optional[str],
    metadata_url: Optional[str],
    metadata_cid: Optional[str],
    payload: Optional[Dict[str, Any]],
) -> None:
    if payload is None:
        return
    if metadata_uri:
        cache[metadata_uri] = (payload, metadata_url, metadata_cid)
    if metadata_cid:
        cache[_metadata_cid_cache_key(metadata_cid)] = (payload, metadata_url, metadata_cid)


def _metadata_cid_cache_key(cid: str) -> str:
    return f"cid::{cid}"


def _build_metadata_fetch_job(
    metadata_uri: Optional[str],
    resolved_url: Optional[str],
    cid: Optional[str],
) -> Optional[MetadataFetchJob]:
    if not metadata_uri:
        return None

    urls: List[str] = []

    def _add(url: Optional[str]) -> None:
        if url and url not in urls:
            urls.append(url)

    _add(resolved_url)

    if cid:
        for gateway in _get_ipfs_gateways():
            gateway = gateway.rstrip("/")
            _add(f"{gateway}/{cid}")

    if not urls:
        return None

    return MetadataFetchJob(metadata_uri=metadata_uri, cid=cid, urls=urls)


def _get_ipfs_gateways() -> List[str]:
    preferred = os.getenv("AGENT_METADATA_GATEWAY_URL", "https://gateway.pinata.cloud/ipfs")
    fallbacks = [preferred, "https://cloudflare-ipfs.com/ipfs", "https://ipfs.io/ipfs"]
    seen = set()
    gateways: List[str] = []
    for gateway in fallbacks:
        gateway = (gateway or "").strip()
        if not gateway:
            continue
        gateway = gateway.rstrip("/")
        if gateway not in seen:
            seen.add(gateway)
            gateways.append(gateway)
    return gateways


def _fetch_metadata_batch(
    jobs: Dict[str, MetadataFetchJob]
) -> Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]]:
    if not jobs:
        return {}

    max_workers = min(8, max(2, len(jobs)))
    results: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="metadata-fetch") as executor:
        future_map = {executor.submit(_fetch_metadata_from_job, job): job.metadata_uri for job in jobs.values()}
        for future in as_completed(future_map):
            metadata_uri = future_map[future]
            job = jobs.get(metadata_uri)
            try:
                payload, url, cid = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Metadata fetch failed for %s: %s", metadata_uri, exc)
                fallback_cid = job.cid if job else None
                payload, url, cid = None, job.urls[0] if job and job.urls else None, fallback_cid
            results[metadata_uri] = (payload, url, cid)

    return results


def _fetch_metadata_from_job(job: MetadataFetchJob) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    if not job.urls:
        return None, None, job.cid

    timeout = httpx.Timeout(6.0, connect=3.0)
    limits = httpx.Limits(max_keepalive_connections=1, max_connections=1)
    with httpx.Client(timeout=timeout, limits=limits) as client:
        for url in job.urls:
            try:
                response = client.get(url)
                response.raise_for_status()
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    payload = response.json()
                else:
                    payload = json.loads(response.text)
                return payload, url, job.cid
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Metadata fetch attempt failed for %s via %s: %s",
                    job.metadata_uri,
                    url,
                    exc,
                )
    fallback_url = job.urls[0]
    return None, fallback_url, job.cid


def _apply_snapshots(session: Session, snapshots: List[AgentSnapshot]) -> List[str]:
    seen_ids: List[str] = []
    now = datetime.utcnow().isoformat()

    for snapshot in snapshots:
        agent = (
            session.query(Agent)
            .filter(Agent.agent_id == snapshot.agent_id)
            .one_or_none()
        )
        created = False
        if agent is None:
            agent = Agent(  # type: ignore[call-arg]
                agent_id=snapshot.agent_id,
                name=snapshot.name,
                agent_type="http",
                status="active",
                capabilities=snapshot.capabilities,
                description=snapshot.description,
            )
            session.add(agent)
            created = True

        agent.name = snapshot.name or snapshot.agent_id
        agent.description = snapshot.description
        agent.capabilities = snapshot.capabilities
        agent.erc8004_metadata_uri = snapshot.metadata_uri
        agent.hedera_account_id = snapshot.hedera_account_id
        agent.status = "active"

        meta = dict(agent.meta or {})
        meta.update(
            {
                "endpoint_url": snapshot.endpoint_url,
                "health_check_url": snapshot.health_check_url,
                "pricing": snapshot.pricing,
                "categories": snapshot.categories,
                "contact_email": snapshot.contact_email,
                "logo_url": snapshot.logo_url,
                "metadata_gateway_url": snapshot.metadata_url,
                "metadata_cid": snapshot.metadata_cid,
                "registry_agent_id": snapshot.registry_agent_id,
                "registry_domain": snapshot.registry_domain,
                "registry_address": snapshot.registry_address,
                "registry_synced_at": now,
                "registry_managed": True,
                "registry_metadata": snapshot.metadata,
                "registry_validation": snapshot.validation,
                "registry_reputation": snapshot.reputation,
            }
        )
        agent.meta = meta

        _upsert_reputation(session, snapshot)
        sync_verified_payment_profile(
            session,
            agent=agent,
            verification_method="registry_sync",
        )

        if created:
            session.flush()

        seen_ids.append(agent.agent_id)

    if seen_ids:
        inactive_candidates = (
            session.query(Agent)
            .filter(~Agent.agent_id.in_(seen_ids))
            .all()
        )
        for agent in inactive_candidates:
            agent_meta = agent.meta or {}
            if agent_meta.get("registry_managed"):
                agent.status = "inactive"
                agent_meta["registry_synced_at"] = now
                agent.meta = agent_meta

    session.commit()
    return seen_ids


def _upsert_reputation(session: Session, snapshot: AgentSnapshot) -> None:
    effective_reputation_score = _effective_reputation_score(
        snapshot.agent_id,
        snapshot.reputation_score,
    )
    reputation = (
        session.query(AgentReputation)
        .filter(AgentReputation.agent_id == snapshot.agent_id)
        .one_or_none()
    )

    if reputation is None:
        reputation = AgentReputation(  # type: ignore[call-arg]
            agent_id=snapshot.agent_id,
            reputation_score=effective_reputation_score,
        )
        session.add(reputation)
    else:
        reputation.reputation_score = effective_reputation_score

    meta = dict(reputation.meta or {})
    meta.update(
        {
            "registry_reputation": snapshot.reputation,
            "registry_validation": snapshot.validation,
        }
    )
    reputation.meta = meta


def _build_snapshot(
    *,
    registry_agent_id: int,
    registry_domain: str,
    registry_address: str,
    metadata_uri: Optional[str],
    metadata_payload: Optional[Dict[str, Any]],
    metadata_url: Optional[str],
    metadata_cid: Optional[str],
    reputation: Dict[str, Any],
    validation: Dict[str, Any],
) -> AgentSnapshot:
    fields = _extract_metadata_fields(registry_domain, metadata_payload)
    reputation_score = _normalize_reputation_score(reputation)

    return AgentSnapshot(
        agent_id=fields["agent_id"],
        name=fields["name"],
        description=fields["description"],
        capabilities=fields["capabilities"],
        categories=fields["categories"],
        metadata_uri=metadata_uri,
        metadata_url=metadata_url,
        metadata_cid=metadata_cid,
        hedera_account_id=fields["hedera_account_id"],
        endpoint_url=fields["endpoint_url"],
        health_check_url=fields["health_check_url"],
        pricing=fields["pricing"],
        contact_email=fields["contact_email"],
        logo_url=fields["logo_url"],
        registry_agent_id=registry_agent_id,
        registry_domain=registry_domain,
        registry_address=registry_address,
        metadata=metadata_payload,
        reputation=reputation,
        validation=validation,
        reputation_score=reputation_score,
    )


def _extract_metadata_fields(domain: str, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = metadata or {}
    agent_id = (metadata.get("agentId") or domain or "").strip() or domain
    name = metadata.get("name") or agent_id
    description = metadata.get("description") or ""
    capabilities = _coerce_str_list(metadata.get("capabilities"))
    categories = _coerce_str_list(metadata.get("categories"))
    logo = metadata.get("image")
    contact = metadata.get("contact") or {}
    contact_email = contact.get("email")
    hedera_account = metadata.get("agentWallet") or metadata.get("agent_wallet")

    endpoints = metadata.get("endpoints") or []
    endpoint_url = _select_endpoint(endpoints, preferred_type="primary")
    health_url = _select_endpoint(endpoints, preferred_type="health")

    endpoint_url = _override_endpoint(
        endpoint_url,
        agent_id=agent_id,
        endpoint_kind="primary",
    )
    health_url = _override_endpoint(
        health_url,
        agent_id=agent_id,
        endpoint_kind="health",
    )

    pricing = metadata.get("pricing") or {}
    normalized_pricing = {
        "rate": pricing.get("rate") or pricing.get("base_rate") or 0,
        "currency": pricing.get("currency") or pricing.get("currency_code") or "HBAR",
        "rate_type": pricing.get("rateType") or pricing.get("rate_type") or "per_task",
    }

    return {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "capabilities": capabilities,
        "categories": categories,
        "logo_url": logo,
        "contact_email": contact_email,
        "hedera_account_id": hedera_account,
        "endpoint_url": endpoint_url,
        "health_check_url": health_url,
        "pricing": normalized_pricing,
    }


def _coerce_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        cleaned = []
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    cleaned.append(stripped)
        return cleaned
    return []


def _select_endpoint(endpoints: Iterable[Dict[str, Any]], preferred_type: str) -> Optional[str]:
    for endpoint in endpoints:
        endpoint_type = (
            (endpoint.get("type") or "").lower()
            if isinstance(endpoint.get("type"), str)
            else ""
        )
        endpoint_name = (
            (endpoint.get("name") or "").lower()
            if isinstance(endpoint.get("name"), str)
            else ""
        )
        if preferred_type.lower() in {endpoint_type, endpoint_name}:
            return endpoint.get("url") or endpoint.get("endpoint")
    for endpoint in endpoints:
        url = endpoint.get("url") or endpoint.get("endpoint")
        if url:
            return url
    return None


def _override_endpoint(
    url: Optional[str],
    *,
    agent_id: str,
    endpoint_kind: str,
) -> Optional[str]:
    env_var = (
        "AGENT_HEALTH_ENDPOINT_BASE_URL_OVERRIDE"
        if endpoint_kind == "health"
        else "AGENT_ENDPOINT_BASE_URL_OVERRIDE"
    )
    override_base = (os.getenv(env_var) or "").strip()
    if endpoint_kind == "health" and not override_base:
        override_base = (os.getenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE") or "").strip()

    if not override_base:
        return url

    if url:
        parsed = urlparse(url)
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            return url
        path = parsed.path or ""
        if parsed.params:
            path = f"{path};{parsed.params}"
        if not path or path == "/":
            path = f"/agents/{agent_id}"
        query = f"?{parsed.query}" if parsed.query else ""
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    else:
        path = f"/agents/{agent_id}"
        query = ""
        fragment = ""

    if not path.startswith("/"):
        path = f"/{path}"

    override_base = override_base.rstrip("/")
    overridden = f"{override_base}{path}{query}{fragment}"
    logger.debug(
        "Overriding %s endpoint for %s: %s -> %s",
        endpoint_kind,
        agent_id,
        url or "<default>",
        overridden,
    )
    return overridden


def _normalize_reputation_score(reputation: Dict[str, Any]) -> float:
    if not reputation:
        return 0.0
    score = reputation.get("reputationScore") or reputation.get("score") or 0
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    if score > 1:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _effective_reputation_score(agent_id: str, raw_score: float) -> float:
    """Keep curated supported agents runnable even when registry reputation is empty."""

    normalized = max(0.0, min(1.0, float(raw_score)))
    if is_supported_builtin_research_agent(agent_id):
        return max(normalized, SUPPORTED_AGENT_REPUTATION_FLOOR)
    return normalized


def _safe_reputation_lookup(agent_id: int) -> Dict[str, Any]:
    try:
        data = get_full_reputation_info(agent_id)
        return data or {}
    except RuntimeError as exc:  # pragma: no cover - depends on configuration
        logger.warning("Reputation registry unavailable for agent %s: %s", agent_id, exc)
        return {}


def _safe_validation_lookup(agent_id: int) -> Dict[str, Any]:
    try:
        data = get_full_validation_info(agent_id)
        return data or {}
    except RuntimeError as exc:  # pragma: no cover - depends on configuration
        logger.warning("Validation registry unavailable for agent %s: %s", agent_id, exc)
        return {}


def _resolve_metadata_uri(metadata_uri: str) -> Tuple[Optional[str], Optional[str]]:
    metadata_uri = metadata_uri.strip()
    cid = None
    if metadata_uri.startswith("ipfs://"):
        cid = metadata_uri.replace("ipfs://", "", 1)
        gateway = os.getenv("AGENT_METADATA_GATEWAY_URL", "https://gateway.pinata.cloud/ipfs/")
        gateway = gateway.rstrip("/")
        return f"{gateway}/{cid}", cid
    if metadata_uri.startswith("http://") or metadata_uri.startswith("https://"):
        return metadata_uri, None
    return None, None


def _get_or_create_state(session: Session) -> AgentRegistrySyncState:
    state = session.query(AgentRegistrySyncState).order_by(AgentRegistrySyncState.id.asc()).first()
    if state:
        return state
    state = AgentRegistrySyncState(status="never")
    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def _get_cache_ttl_seconds() -> int:
    value = os.getenv("AGENT_REGISTRY_CACHE_TTL_SECONDS", "300")
    try:
        ttl = int(value)
    except ValueError:
        ttl = 300
    return max(60, ttl)
