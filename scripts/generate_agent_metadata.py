#!/usr/bin/env python
"""Generate ERC-8004 metadata JSON for all registered agents."""

import os
import sys
from pathlib import Path

# Ensure direct script execution can import repo-root packages.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.database import SessionLocal, Agent as AgentModel
from shared.metadata import (
    AgentMetadataPayload,
    build_agent_metadata_payload,
    save_agent_metadata_locally,
)

# Output directory for metadata files
METADATA_DIR = Path(__file__).parent.parent / "agent_metadata"


def _resolve_endpoint_url(agent: AgentModel) -> str:
    """Compute the best available endpoint URL for an agent."""
    meta = agent.meta or {}
    endpoint = meta.get("endpoint_url")
    if endpoint:
        return endpoint

    base_url = os.getenv("RESEARCH_API_URL", "http://localhost:5001")
    return f"{base_url.rstrip('/')}/agents/{agent.agent_id}"


def _resolve_pricing(agent: AgentModel) -> tuple[float, str, str]:
    """Extract pricing details from agent metadata."""
    meta = agent.meta or {}
    pricing = meta.get("pricing") if isinstance(meta.get("pricing"), dict) else {}

    rate = pricing.get("rate")
    if rate is None:
        rate = meta.get("payment_rate")
    rate = float(rate) if rate is not None else 0.0

    currency = pricing.get("currency") or meta.get("payment_currency") or "HBAR"
    rate_type = pricing.get("rate_type") or pricing.get("rateType") or meta.get("payment_model") or "per_task"

    return rate, currency, rate_type


def _coerce_str_list(value):
    if not value:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else None
    if isinstance(value, (list, tuple, set)):
        cleaned_list = [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
        return cleaned_list or None
    return None


def _get_first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _resolve_chain_id(meta: dict, agent_id: str) -> str:
    raw_chain_id = meta.get("registry_chain_id") or _get_first_env(
        "ERC8004_CHAIN_ID",
        "CHAIN_ID",
        "HEDERA_CHAIN_ID",
    )
    if not raw_chain_id:
        raise ValueError(
            f"Agent '{agent_id}' is missing a chain id. Set registry_chain_id in the database or ERC8004_CHAIN_ID in the environment."
        )
    try:
        chain_id_int = int(str(raw_chain_id), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Agent '{agent_id}' has an invalid chain id value: {raw_chain_id}"
        ) from exc
    return str(chain_id_int)


def _resolve_registry_address(meta: dict, agent_id: str) -> str:
    raw_address = (
        meta.get("registry_contract_address")
        or meta.get("identity_contract_address")
        or meta.get("identity_registry_address")
        or meta.get("registry_address")
        or _get_first_env(
            "IDENTITY_CONTRACT_ADDRESS",
            "IDENTITY_REGISTRY_ADDRESS",
            "ERC8004_REGISTRY_ADDRESS",
        )
    )
    if not raw_address:
        raise ValueError(
            f"Agent '{agent_id}' does not know the identity registry address. Configure IDENTITY_CONTRACT_ADDRESS / IDENTITY_REGISTRY_ADDRESS."
        )
    address = raw_address.strip().lower()
    if not address.startswith("0x"):
        raise ValueError(
            f"Agent '{agent_id}' has an invalid registry address '{raw_address}'. Expected 0x-prefixed hex string."
        )
    return address


def _resolve_registrations(agent: AgentModel) -> list[dict]:
    meta = agent.meta or {}
    registry_agent_id = meta.get("registry_agent_id")
    if registry_agent_id is None:
        raise ValueError(
            f"Agent '{agent.agent_id}' is missing registry_agent_id. Sync on-chain metadata before generating ERC-8004 files."
        )
    try:
        agent_id_int = int(registry_agent_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Agent '{agent.agent_id}' has an invalid registry_agent_id: {registry_agent_id}"
        ) from exc

    chain_id = _resolve_chain_id(meta, agent.agent_id)
    registry_address = _resolve_registry_address(meta, agent.agent_id)

    return [
        {
            "agentId": agent_id_int,
            "agentRegistry": f"eip155:{chain_id}:{registry_address}",
        }
    ]


def generate_agent_metadata(agent: AgentModel) -> dict:
    """Build metadata document for a single agent."""
    rate, currency, rate_type = _resolve_pricing(agent)
    meta = agent.meta or {}

    payload = AgentMetadataPayload(
        agent_id=agent.agent_id,
        name=agent.name,
        description=agent.description or f"{agent.name} - Research agent for AI marketplace",
        endpoint_url=_resolve_endpoint_url(agent),
        capabilities=agent.capabilities or ["research"],
        pricing_rate=rate,
        pricing_currency=currency,
        pricing_rate_type=rate_type,
        categories=_coerce_str_list(meta.get("categories")),
        contact_email=meta.get("contact_email") or (meta.get("contact") or {}).get("email"),
        logo_url=meta.get("logo_url") or meta.get("image"),
        health_check_url=meta.get("health_check_url"),
        hedera_account=agent.hedera_account_id,
        supported_trust=_coerce_str_list(meta.get("supported_trust") or meta.get("supportedTrust")),
        registrations=_resolve_registrations(agent),
    )

    return build_agent_metadata_payload(payload)


def generate_all_metadata():
    """Generate metadata files for all active agents."""

    print("=" * 80)
    print("GENERATING AGENT METADATA FILES")
    print("=" * 80)

    # Load agents from database
    db = SessionLocal()
    try:
        agents = db.query(AgentModel).filter(AgentModel.status == "active").all()

        if not agents:
            print("\n❌ No active agents found in database")
            return

        print(f"\n📋 Found {len(agents)} active agents")
        print(f"📁 Output directory: {METADATA_DIR}")
        print()

        generated = []
        failed: list[tuple[str, str]] = []

        for i, agent in enumerate(agents, 1):
            print(f"[{i}/{len(agents)}] {agent.name} ({agent.agent_id})")

            try:
                metadata = generate_agent_metadata(agent)
            except ValueError as exc:
                error_message = str(exc)
                print(f"   ❌ Skipped: {error_message}")
                failed.append((agent.agent_id, error_message))
                continue

            filepath = save_agent_metadata_locally(agent.agent_id, metadata)
            generated.append(filepath)

            print(f"   ✅ Saved to: {filepath}")

        print("\n" + "=" * 80)
        print("METADATA GENERATION COMPLETE")
        print("=" * 80)
        print(f"\n✅ Generated {len(generated)} metadata files")
        print(f"📁 Location: {METADATA_DIR}")

        if failed:
            print(f"\n⚠️ Skipped {len(failed)} agents due to missing registry data:")
            for agent_id, reason in failed:
                print(f"   - {agent_id}: {reason}")

        print("\n📝 Next Steps:")
        print("   1. Review generated metadata files")
        print("   2. Upload metadata to IPFS or web server")
        print("   3. Update registration script with metadata URIs")
        print("   4. Redeploy IdentityRegistry contract with new ABI")
        print("   5. Register agents with metadata URIs")

    finally:
        db.close()


if __name__ == "__main__":
    generate_all_metadata()
