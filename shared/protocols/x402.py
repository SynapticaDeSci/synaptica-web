"""x402 Payment Protocol implementation backed by TaskEscrow smart contract."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from eth_account import Account
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.types import Nonce, TxParams, Wei


class PaymentStatus(str, Enum):
    """Payment status tracked within the marketplace."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass
class PaymentRequest:
    """x402 payment request."""

    payment_id: str
    from_account: str
    to_account: str
    amount: Decimal
    currency: str = "HBAR"
    description: str = ""
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with stringified amount."""
        data = asdict(self)
        data["amount"] = str(self.amount)
        return data


@dataclass
class PaymentReceipt:
    """Payment receipt returned after contract interaction."""

    payment_id: str
    transaction_id: str
    status: PaymentStatus
    amount: Decimal
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class TaskEscrowConfig:
    """Configuration required to interact with the TaskEscrow contract."""

    contract_address: str
    marketplace_treasury: str
    signer_private_key: str
    rpc_url: str
    default_approvals: int
    marketplace_fee_bps: int
    verifier_fee_bps: int

    @classmethod
    def load(cls) -> "TaskEscrowConfig":
        def require(name: str) -> str:
            value = os.getenv(name)
            if not value:
                raise ValueError(f"Missing required environment variable: {name}")
            return value

        contract_address = require("TASK_ESCROW_ADDRESS")
        marketplace_treasury = require("TASK_ESCROW_MARKETPLACE_TREASURY")
        signer_private_key = require("TASK_ESCROW_OPERATOR_PRIVATE_KEY")
        rpc_url = os.getenv("HEDERA_EVM_RPC_URL", "https://testnet.hashio.io/api")
        default_approvals = int(os.getenv("TASK_ESCROW_DEFAULT_APPROVALS", "1") or 1)
        marketplace_fee_bps = int(os.getenv("TASK_ESCROW_MARKETPLACE_FEE_BPS", "0") or 0)
        verifier_fee_bps = int(os.getenv("TASK_ESCROW_VERIFIER_FEE_BPS", "0") or 0)

        return cls(
            contract_address=contract_address,
            marketplace_treasury=marketplace_treasury,
            signer_private_key=signer_private_key,
            rpc_url=rpc_url,
            default_approvals=default_approvals,
            marketplace_fee_bps=marketplace_fee_bps,
            verifier_fee_bps=verifier_fee_bps,
        )


def _load_task_escrow_abi() -> List[Dict[str, Any]]:
    """Load the TaskEscrow ABI from the shared contracts folder."""

    abi_path = Path(__file__).resolve().parent.parent / "contracts" / "TaskEscrow.sol" / "TaskEscrow.json"
    with abi_path.open("r", encoding="utf-8") as abi_file:
        data = json.load(abi_file)
    if isinstance(data, dict) and "abi" in data:
        return data["abi"]
    if isinstance(data, list):
        return data
    raise ValueError("Invalid ABI format at shared/contracts/TaskEscrow.sol/TaskEscrow.json")


TASK_ESCROW_ABI = _load_task_escrow_abi()

# Hedera network uses the same 10^18 base unit as Ethereum for native value.
HBAR_TO_WEI = Decimal("1000000000000000000")
# Hashio rejects transfers smaller than 1 tinybar (10_000_000_000 wei).
MIN_NATIVE_VALUE_WEI = 10_000_000_000


class X402Payment:
    """x402 Payment Protocol backed by the on-chain TaskEscrow contract."""

    def __init__(self, hedera_client: Any = None):
        # Hedera SDK client is kept for backwards compatibility with callers,
        # but all payment operations route through the TaskEscrow contract.
        self.hedera_client = hedera_client

        self.config = TaskEscrowConfig.load()
        self.web3 = Web3(Web3.HTTPProvider(self.config.rpc_url))
        if not self.web3.is_connected():
            raise RuntimeError("Unable to connect to Hedera EVM RPC endpoint")

        self.contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(self.config.contract_address),
            abi=TASK_ESCROW_ABI,
        )

        self.marketplace_treasury = Web3.to_checksum_address(self.config.marketplace_treasury)
        self.default_approvals = max(1, int(self.config.default_approvals))
        self.marketplace_fee_bps = int(self.config.marketplace_fee_bps)
        self.verifier_fee_bps = int(self.config.verifier_fee_bps)
        self.chain_id = self.web3.eth.chain_id

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    async def create_payment(self, payment_request: PaymentRequest) -> PaymentReceipt:
        """Fund an escrow on-chain and return the resulting transaction details."""

        task_id = self._task_id_bytes(payment_request)
        worker_address = self._resolve_worker_address(payment_request)
        verifier_addresses = self._resolve_verifiers(payment_request)
        approvals_required = self._resolve_approvals(payment_request, len(verifier_addresses))
        marketplace_fee_bps, verifier_fee_bps = self._resolve_fee_configuration(payment_request)
        amount_wei = self._to_wei(payment_request.amount)

        fn = self.contract.functions.createEscrow(
            task_id,
            worker_address,
            verifier_addresses,
            approvals_required,
            marketplace_fee_bps,
            verifier_fee_bps,
        )

        tx_hash, receipt = await self._send_transaction(
            fn,
            value=amount_wei,
            private_key=self.config.signer_private_key,
        )

        status = PaymentStatus.AUTHORIZED if receipt.get("status") == 1 else PaymentStatus.FAILED
        metadata = {
            "task_id": task_id.hex(),
            "transaction_hash": tx_hash,
            "approvals_required": approvals_required,
            "marketplace_fee_bps": marketplace_fee_bps,
            "verifier_fee_bps": verifier_fee_bps,
            "verifiers": verifier_addresses,
            "worker_address": worker_address,
            "block_number": receipt.get("blockNumber"),
            "gas_used": receipt.get("gasUsed"),
            "amount_wei": amount_wei,
        }

        thread_id = (payment_request.metadata or {}).get("a2a_thread_id") if payment_request.metadata else None
        if thread_id:
            metadata["a2a_thread_id"] = thread_id
            metadata["a2a_message_type"] = "payment/authorized"

        return PaymentReceipt(
            payment_id=payment_request.payment_id,
            transaction_id=tx_hash,
            status=status,
            amount=payment_request.amount,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata,
        )

    async def authorize_payment(self, payment_request: PaymentRequest) -> str:
        """Create and fund the escrow, returning the transaction hash."""

        receipt = await self.create_payment(payment_request)
        return receipt.transaction_id

    async def release_payment(
        self, authorization_id: str, payment_request: PaymentRequest
    ) -> PaymentReceipt:
        """Approve release of funds for the escrow associated with the payment request."""

        _ = authorization_id  # retained for backward compatibility
        task_id = self._task_id_bytes(payment_request)
        fn = self.contract.functions.approveRelease(task_id)
        tx_hash, receipt = await self._send_transaction(
            fn,
            value=0,
            private_key=self.config.signer_private_key,
        )

        escrow_status = await self._get_escrow_status(task_id)
        status = self._map_escrow_status_to_payment_status(escrow_status)
        metadata = {
            "task_id": task_id.hex(),
            "transaction_hash": tx_hash,
            "block_number": receipt.get("blockNumber"),
            "gas_used": receipt.get("gasUsed"),
            "escrow_status": escrow_status,
        }

        thread_id = (payment_request.metadata or {}).get("a2a_thread_id") if payment_request.metadata else None
        if thread_id:
            metadata["a2a_thread_id"] = thread_id
            metadata["a2a_message_type"] = "payment/released"

        return PaymentReceipt(
            payment_id=payment_request.payment_id,
            transaction_id=tx_hash,
            status=status,
            amount=payment_request.amount,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata,
        )

    async def approve_refund(self, payment_request: PaymentRequest) -> PaymentReceipt:
        """Approve refund of funds back to the client."""

        task_id = self._task_id_bytes(payment_request)
        fn = self.contract.functions.approveRefund(task_id)
        tx_hash, receipt = await self._send_transaction(
            fn,
            value=0,
            private_key=self.config.signer_private_key,
        )

        escrow_status = await self._get_escrow_status(task_id)
        status = self._map_escrow_status_to_payment_status(escrow_status)
        metadata = {
            "task_id": task_id.hex(),
            "transaction_hash": tx_hash,
            "block_number": receipt.get("blockNumber"),
            "gas_used": receipt.get("gasUsed"),
            "escrow_status": escrow_status,
        }

        thread_id = (payment_request.metadata or {}).get("a2a_thread_id") if payment_request.metadata else None
        if thread_id:
            metadata["a2a_thread_id"] = thread_id
            metadata["a2a_message_type"] = "payment/refunded"

        return PaymentReceipt(
            payment_id=payment_request.payment_id,
            transaction_id=tx_hash,
            status=status,
            amount=payment_request.amount,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata,
        )

    def calculate_service_fee(
        self, base_amount: Decimal, rate: Decimal = Decimal("0.01")
    ) -> Decimal:
        """Calculate service fee for agent marketplace usage."""

        return base_amount * rate

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_worker_address(self, payment_request: PaymentRequest) -> str:
        metadata = payment_request.metadata or {}
        worker = metadata.get("worker_address") or payment_request.to_account
        if not worker:
            raise ValueError("Worker address is required to create escrow")
        return Web3.to_checksum_address(worker)

    def _resolve_verifiers(self, payment_request: PaymentRequest) -> List[str]:
        metadata = payment_request.metadata or {}
        verifiers: List[str] = metadata.get("verifier_addresses") or []
        if not verifiers:
            verifiers = [self.marketplace_treasury]

        checksum_verifiers = []
        seen = set()
        for address in verifiers:
            checksum = Web3.to_checksum_address(address)
            if checksum in seen:
                continue
            seen.add(checksum)
            checksum_verifiers.append(checksum)

        if not checksum_verifiers:
            raise ValueError("At least one verifier address must be provided")

        return checksum_verifiers

    def _resolve_approvals(self, payment_request: PaymentRequest, verifier_count: int) -> int:
        metadata = payment_request.metadata or {}
        approvals = metadata.get("approvals_required") or self.default_approvals
        approvals = int(approvals)
        if approvals <= 0:
            approvals = 1
        if approvals > verifier_count:
            approvals = verifier_count
        return approvals

    def _resolve_fee_configuration(self, payment_request: PaymentRequest) -> tuple[int, int]:
        metadata = payment_request.metadata or {}
        marketplace_fee = int(metadata.get("marketplace_fee_bps", self.marketplace_fee_bps))
        verifier_fee = int(metadata.get("verifier_fee_bps", self.verifier_fee_bps))
        total = marketplace_fee + verifier_fee
        if total > 10_000:
            raise ValueError("Combined marketplace and verifier fees cannot exceed 100%")
        return marketplace_fee, verifier_fee

    def _task_id_bytes(self, payment_request: PaymentRequest) -> bytes:
        metadata = payment_request.metadata or {}
        task_identifier = metadata.get("task_id") or payment_request.payment_id
        if isinstance(task_identifier, bytes):
            if len(task_identifier) != 32:
                raise ValueError("Task ID bytes must be 32 bytes long")
            return task_identifier
        if isinstance(task_identifier, str) and task_identifier.startswith("0x") and len(task_identifier) == 66:
            return HexBytes(task_identifier)
        # Fallback: keccak hash of the identifier string for stable 32 bytes
        return Web3.keccak(text=str(task_identifier))

    async def _send_transaction(
        self,
        fn: ContractFunction,
        *,
        value: int,
        private_key: str,
    ) -> tuple[str, Dict[str, Any]]:
        account: LocalAccount = Account.from_key(private_key)
        from_address = Web3.to_checksum_address(account.address)

        loop = asyncio.get_running_loop()
        nonce = await loop.run_in_executor(None, self.web3.eth.get_transaction_count, from_address)
        gas_price = await loop.run_in_executor(None, lambda: self.web3.eth.gas_price)

        value_wei = Wei(value)
        gas_price_wei = Wei(gas_price)
        nonce_value = Nonce(nonce)

        gas_params: TxParams = {
            "from": from_address,
            "value": value_wei,
        }

        try:
            gas_estimate = await loop.run_in_executor(
                None,
                lambda: fn.estimate_gas(gas_params),
            )
        except Exception:
            gas_estimate = 1_500_000

        tx_params: TxParams = {
            "from": from_address,
            "value": value_wei,
            "nonce": nonce_value,
            "gas": gas_estimate,
            "gasPrice": gas_price_wei,
            "chainId": self.chain_id,
        }

        tx: TxParams = fn.build_transaction(tx_params)

        signed_tx = account.sign_transaction(cast(Dict[str, Any], tx))
        # eth-account renamed rawTransaction -> raw_transaction; support both.
        signed_tx_any = cast(Any, signed_tx)
        raw_tx: Optional[bytes] = getattr(signed_tx_any, "rawTransaction", None)
        if raw_tx is None:
            raw_tx = getattr(signed_tx_any, "raw_transaction", None)
        if raw_tx is None:
            raise AttributeError("Signed transaction is missing raw payload")
        tx_hash_bytes: HexBytes = await loop.run_in_executor(
            None, self.web3.eth.send_raw_transaction, raw_tx
        )
        receipt = await loop.run_in_executor(
            None,
            lambda: self.web3.eth.wait_for_transaction_receipt(tx_hash_bytes),
        )

        receipt_obj = cast(Any, receipt)
        receipt_summary = {
            "status": getattr(receipt_obj, "status", None),
            "blockNumber": getattr(receipt_obj, "blockNumber", None),
            "gasUsed": getattr(receipt_obj, "gasUsed", None),
            "transactionIndex": getattr(receipt_obj, "transactionIndex", None),
        }

        return tx_hash_bytes.hex(), receipt_summary

    async def _get_escrow_status(self, task_id: bytes) -> int:
        loop = asyncio.get_running_loop()
        escrow = await loop.run_in_executor(
            None, self.contract.functions.getEscrow(task_id).call
        )
        # Escrow tuple structure: (client, worker, amount, marketplaceFeeBps, verifierFeeBps,
        #                          status, approvalsRequired, releaseApprovals, refundApprovals)
        return int(escrow[5])

    def _map_escrow_status_to_payment_status(self, escrow_status: int) -> PaymentStatus:
        if escrow_status == 2:
            return PaymentStatus.COMPLETED
        if escrow_status == 3:
            return PaymentStatus.REFUNDED
        if escrow_status == 1:
            return PaymentStatus.AUTHORIZED
        return PaymentStatus.FAILED

    def _to_wei(self, amount: Decimal) -> int:
        """Convert an HBAR amount to wei (1 HBAR = 10^18 wei on Hedera)."""

        wei_value = int((Decimal(amount) * HBAR_TO_WEI).to_integral_value(rounding=ROUND_DOWN))
        if wei_value <= 0:
            raise ValueError("Escrow amount must be greater than zero")
        if wei_value < MIN_NATIVE_VALUE_WEI:
            raise ValueError("Escrow amount must be at least 1 tinybar (1e-8 HBAR)")
        return wei_value
