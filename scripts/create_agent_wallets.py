#!/usr/bin/env python
"""
Fund deterministic agent aliases on Hedera so they can submit metadata updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv
from eth_account import Account as EthAccount
from hiero_sdk_python import (
    AccountId,
    Client,
    Hbar,
    Network,
    TransferTransaction,
)
from hiero_sdk_python.exceptions import PrecheckError, ReceiptStatusError
from hiero_sdk_python.crypto.private_key import PrivateKey
from web3 import Web3

# Ensure direct script execution can import repo-root packages.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.database import Agent as AgentModel
from shared.database import SessionLocal

load_dotenv(override=True)

OPERATOR_ID = os.getenv("HEDERA_ACCOUNT_ID")
OPERATOR_KEY = os.getenv("HEDERA_PRIVATE_KEY")
NETWORK = os.getenv("HEDERA_NETWORK", "testnet").lower()
INITIAL_BALANCE_HBAR = float(os.getenv("AGENT_WALLET_INITIAL_HBAR", "0.05"))
TARGET_BALANCE_WEI = Web3.to_wei(INITIAL_BALANCE_HBAR, "ether")
MIRROR_BASE = {
    "mainnet": "https://mainnet-public.mirrornode.hedera.com",
    "testnet": "https://testnet.mirrornode.hedera.com",
    "previewnet": "https://previewnet.mirrornode.hedera.com",
}.get(NETWORK, "https://testnet.mirrornode.hedera.com")
REPORT_PATH = Path(__file__).resolve().parents[1] / "agent_metadata" / "agent_wallets.json"


@dataclass
class WalletReport:
    agent_id: str
    evm_address: str
    hedera_account_id: str | None
    status: str
    error: str | None = None


def _derive_agent_private_key(agent_id: str) -> PrivateKey:
    seed = hashlib.sha256(agent_id.encode()).hexdigest()
    return PrivateKey.from_bytes_ecdsa(bytes.fromhex(seed))


def _derive_evm_address(agent_id: str) -> str:
    seed = hashlib.sha256(agent_id.encode()).hexdigest()
    acct = EthAccount.from_key("0x" + seed)
    return acct.address


def _load_operator_key(value: str) -> PrivateKey:
    raw = value.strip()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) == 64:
        return PrivateKey.from_bytes_ecdsa(bytes.fromhex(raw))
    return PrivateKey.from_string(raw)


def _get_client() -> Client:
    if not OPERATOR_ID or not OPERATOR_KEY:
        raise SystemExit("HEDERA_ACCOUNT_ID and HEDERA_PRIVATE_KEY must be configured in .env")

    client = Client(Network(NETWORK if NETWORK in {"mainnet", "testnet", "previewnet"} else "testnet"))
    operator_key = _load_operator_key(OPERATOR_KEY)
    client.set_operator(AccountId.from_string(OPERATOR_ID), operator_key)
    return client


def _lookup_account_id(evm_address: str) -> str | None:
    alias = evm_address.lower()
    if alias.startswith("0x"):
        alias = alias[2:]
    url = f"{MIRROR_BASE}/api/v1/accounts/0x{alias}"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("account")
    except requests.RequestException as exc:
        print(f"   ⚠️  Mirror lookup failed: {exc}")
    return None


def create_wallets() -> None:
    client = _get_client()
    web3 = Web3(Web3.HTTPProvider(os.getenv("HEDERA_RPC_URL", "https://testnet.hashio.io/api")))
    session = SessionLocal()

    agents: List[AgentModel] = (
        session.query(AgentModel).filter(AgentModel.status == "active").order_by(AgentModel.agent_id.asc()).all()
    )

    if not agents:
        print("❌ No active agents found.")
        return

    print(f"📋 Funding alias wallets for {len(agents)} agents on Hedera {NETWORK}")
    reports: List[WalletReport] = []

    for agent in agents:
        domain = agent.agent_id
        evm_address = _derive_evm_address(domain)
        print(f"\n➡️  {domain}")

        current_balance = 0
        try:
            current_balance = web3.eth.get_balance(evm_address)
        except Exception as exc:  # noqa: BLE001
            print(f"   ⚠️  Could not read RPC balance: {exc}")

        if current_balance >= TARGET_BALANCE_WEI:
            account_id = _lookup_account_id(evm_address) or agent.hedera_account_id
            if account_id and account_id != agent.hedera_account_id:
                agent.hedera_account_id = account_id
                meta = dict(agent.meta or {})
                meta["hedera_account_id"] = account_id
                agent.meta = meta
                session.commit()
            print(f"   ✅ Alias already funded (~{web3.from_wei(current_balance, 'ether')} HBAR)")
            reports.append(
                WalletReport(
                    agent_id=domain,
                    evm_address=evm_address,
                    hedera_account_id=account_id,
                    status="exists",
                )
            )
            continue

        try:
            priv_key = _derive_agent_private_key(domain)
            alias_account = AccountId(alias_key=priv_key.public_key())
            amount_tinybars = Hbar(INITIAL_BALANCE_HBAR).to_tinybars()

            txn_response = (
                TransferTransaction()
                .add_hbar_transfer(AccountId.from_string(OPERATOR_ID), -amount_tinybars)
                .add_hbar_transfer(alias_account, amount_tinybars)
            ).execute(client)
            receipt = txn_response.get_receipt(client)

            account_id_str = _lookup_account_id(evm_address)
            if account_id_str:
                agent.hedera_account_id = account_id_str
                meta = dict(agent.meta or {})
                meta["hedera_account_id"] = account_id_str
                agent.meta = meta
                session.commit()

            status_name = getattr(receipt.status, "name", receipt.status)
            print(f"   ✅ Alias funded with {INITIAL_BALANCE_HBAR} HBAR (status {status_name})")
            reports.append(
                WalletReport(
                    agent_id=domain,
                    evm_address=evm_address,
                    hedera_account_id=account_id_str,
                    status="created",
                )
            )
        except (PrecheckError, ReceiptStatusError) as exc:
            session.rollback()
            print(f"   ❌ Hedera transfer failed: {exc}")
            reports.append(
                WalletReport(
                    agent_id=domain,
                    evm_address=evm_address,
                    hedera_account_id=None,
                    status="error",
                    error=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"   ❌ Unexpected error: {exc}")
            reports.append(
                WalletReport(
                    agent_id=domain,
                    evm_address=evm_address,
                    hedera_account_id=None,
                    status="error",
                    error=str(exc),
                )
            )

    session.close()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as fh:
        json.dump([report.__dict__ for report in reports], fh, indent=2)

    created = sum(1 for r in reports if r.status == "created")
    existing = sum(1 for r in reports if r.status == "exists")
    failed = sum(1 for r in reports if r.status == "error")

    print("\n" + "=" * 80)
    print("ALIAS FUNDING SUMMARY")
    print("=" * 80)
    print(f"✅ Funded: {created}")
    print(f"⚠️  Already funded: {existing}")
    print(f"❌ Failed: {failed}")
    print(f"📝 Report saved to {REPORT_PATH}")


if __name__ == "__main__":
    create_wallets()
