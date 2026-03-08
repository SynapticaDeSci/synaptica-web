"""Hedera client configuration and utilities."""

import os
from typing import Optional
from dataclasses import dataclass

from pydantic_settings import BaseSettings

try:
    from hedera import (
        Client as _HederaClient,
        AccountId as _HederaAccountId,
        PrivateKey as _HederaPrivateKey,
        TopicCreateTransaction as _HederaTopicCreateTransaction,
        TopicMessageSubmitTransaction as _HederaTopicMessageSubmitTransaction,
        TopicId as _HederaTopicId,
    )
    _HEDERA_HAS_FACTORY = any(
        hasattr(_HederaClient, name)
        for name in ("for_testnet", "forTestnet", "forTestNet")
    ) and any(
        hasattr(_HederaClient, name)
        for name in ("for_mainnet", "forMainnet", "forMainNet")
    )
except ModuleNotFoundError:  # pragma: no cover - executed when SDK missing locally
    _HederaClient = None  # type: ignore[assignment]
    _HederaAccountId = None  # type: ignore[assignment]
    _HederaPrivateKey = None  # type: ignore[assignment]
    _HederaTopicCreateTransaction = None  # type: ignore[assignment]
    _HederaTopicMessageSubmitTransaction = None  # type: ignore[assignment]
    _HederaTopicId = None  # type: ignore[assignment]
    _HEDERA_HAS_FACTORY = False


if _HederaClient is not None and _HEDERA_HAS_FACTORY:
    HEDERA_SDK_AVAILABLE = True
    Client = _HederaClient
    AccountId = _HederaAccountId
    PrivateKey = _HederaPrivateKey
    TopicCreateTransaction = _HederaTopicCreateTransaction
    TopicMessageSubmitTransaction = _HederaTopicMessageSubmitTransaction
    TopicId = _HederaTopicId
else:  # pragma: no cover - stub mode for local testing without SDK
    HEDERA_SDK_AVAILABLE = False

    class _StubReceipt:
        def __init__(self, topic_id: str | None = None, status: str = "NOT_AVAILABLE"):
            self.topic_id = topic_id
            self.status = status

    class _StubTransactionResponse:
        def __init__(self, receipt: _StubReceipt):
            self._receipt = receipt

        async def get_receipt(self, client: "Client") -> _StubReceipt:
            return self._receipt


    class Client:  # type: ignore[override]
        """Minimal stub mimicking the Hedera Client interface."""

        def __init__(self, network: str):
            self.network = network
            self.operator = None

        @classmethod
        def for_testnet(cls) -> "Client":
            return cls("testnet")

        @classmethod
        def for_mainnet(cls) -> "Client":
            return cls("mainnet")

        def set_operator(self, operator_id, operator_key) -> None:
            self.operator = (operator_id, operator_key)


    class AccountId:  # type: ignore[override]
        @staticmethod
        def from_string(value: str) -> str:
            return value


    class PrivateKey:  # type: ignore[override]
        @staticmethod
        def from_string(value: str) -> str:
            return value


    class TopicId:  # type: ignore[override]
        @staticmethod
        def from_string(value: str) -> str:
            return value


    class TopicCreateTransaction:  # type: ignore[override]
        def __init__(self):
            self.memo = ""

        def set_topic_memo(self, memo: str) -> "TopicCreateTransaction":
            self.memo = memo
            return self

        async def execute(self, client: Client) -> _StubTransactionResponse:
            return _StubTransactionResponse(_StubReceipt(topic_id="stub-topic-id"))


    class TopicMessageSubmitTransaction:  # type: ignore[override]
        def __init__(self):
            self.topic_id = None
            self.message = b""

        def set_topic_id(self, topic_id) -> "TopicMessageSubmitTransaction":
            self.topic_id = topic_id
            return self

        def set_message(self, message: bytes) -> "TopicMessageSubmitTransaction":
            self.message = message
            return self

        async def execute(self, client: Client) -> _StubTransactionResponse:
            return _StubTransactionResponse(_StubReceipt(status="STUB_OK"))


class HederaConfig(BaseSettings):
    """Hedera configuration from environment."""

    network: str = "testnet"
    account_id: str
    private_key: str
    hcs_topic_id: Optional[str] = None

    class Config:
        env_prefix = "HEDERA_"
        case_sensitive = False


@dataclass
class HederaClientWrapper:
    """Wrapper for Hedera client with utilities."""

    client: Client
    operator_id: AccountId
    operator_key: PrivateKey
    topic_id: Optional[TopicId] = None

    async def _extract_receipt(self, response):
        """Support both SDK and fallback response shapes."""
        if hasattr(response, "get_receipt"):
            return await response.get_receipt(self.client)
        if hasattr(response, "getReceipt"):
            return await response.getReceipt(self.client)
        return response

    async def create_topic(self, memo: str = "Agent Coordination Topic") -> TopicId:
        """Create a new HCS topic."""
        transaction = TopicCreateTransaction()
        if hasattr(transaction, "set_topic_memo"):
            transaction = transaction.set_topic_memo(memo)
        elif hasattr(transaction, "setTopicMemo"):
            transaction = transaction.setTopicMemo(memo)
        else:
            raise AttributeError("TopicCreateTransaction lacks set_topic_memo/setTopicMemo")

        response = await transaction.execute(self.client)
        receipt = await self._extract_receipt(response)

        topic_id = getattr(receipt, "topic_id", None)
        if topic_id is None and hasattr(receipt, "topicId"):
            topic_id = getattr(receipt, "topicId")

        if topic_id is None:
            raise ValueError("Failed to create topic")

        self.topic_id = topic_id
        return self.topic_id

    async def submit_message(self, message: str, topic_id: Optional[TopicId] = None) -> str:
        """Submit a message to HCS topic."""
        target_topic = topic_id or self.topic_id
        if target_topic is None:
            raise ValueError("No topic ID specified")

        transaction = (
            TopicMessageSubmitTransaction()
        )
        if hasattr(transaction, "set_topic_id"):
            transaction = transaction.set_topic_id(target_topic)
        elif hasattr(transaction, "setTopicId"):
            transaction = transaction.setTopicId(target_topic)
        else:
            raise AttributeError("TopicMessageSubmitTransaction lacks set_topic_id/setTopicId")

        if hasattr(transaction, "set_message"):
            transaction = transaction.set_message(message.encode("utf-8"))
        elif hasattr(transaction, "setMessage"):
            transaction = transaction.setMessage(message.encode("utf-8"))
        else:
            raise AttributeError("TopicMessageSubmitTransaction lacks set_message/setMessage")

        response = await transaction.execute(self.client)
        receipt = await self._extract_receipt(response)
        status = getattr(receipt, "status", None)
        if status is None and hasattr(receipt, "statusString"):
            status = getattr(receipt, "statusString")
        if status is None:
            status = "SUCCESS"

        return str(status)


def get_hedera_client(config: Optional[HederaConfig] = None) -> HederaClientWrapper:
    """
    Get configured Hedera client for testnet.

    Args:
        config: Optional HederaConfig, if None will load from environment

    Returns:
        Configured HederaClientWrapper
    """
    if config is None:
        config = HederaConfig()

    # Create client for testnet or mainnet, handling camelCase factories in Jython bindings
    def _factory(method_names):
        for name in method_names:
            if hasattr(Client, name):
                method = getattr(Client, name)
                return method()
        raise AttributeError(
            "Client factory methods not found. Tried: " + ", ".join(method_names)
        )

    if config.network == "testnet":
        client = _factory(["for_testnet", "forTestnet", "forTestNet"])
    elif config.network == "mainnet":
        client = _factory(["for_mainnet", "forMainnet", "forMainNet"])
    else:
        raise ValueError(f"Unsupported network: {config.network}")

    def _from_string(cls, value: str):
        for name in ("from_string", "fromString", "fromStringLiteral"):
            if hasattr(cls, name):
                return getattr(cls, name)(value)
        raise AttributeError(f"{cls.__name__} lacks from_string/fromString method")

    operator_id = _from_string(AccountId, config.account_id)
    operator_key = _from_string(PrivateKey, config.private_key)

    if hasattr(client, "set_operator"):
        client.set_operator(operator_id, operator_key)
    elif hasattr(client, "setOperator"):
        client.setOperator(operator_id, operator_key)
    else:
        raise AttributeError("Client object missing set_operator/setOperator method")

    # Parse topic ID if provided
    topic_id = None
    if config.hcs_topic_id:
        topic_id = _from_string(TopicId, config.hcs_topic_id)

    return HederaClientWrapper(
        client=client, operator_id=operator_id, operator_key=operator_key, topic_id=topic_id
    )
