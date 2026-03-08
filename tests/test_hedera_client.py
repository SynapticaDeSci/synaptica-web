import pytest

from shared.hedera.client import HEDERA_SDK_AVAILABLE, get_hedera_client


@pytest.mark.asyncio
async def test_stub_client_can_create_topic_and_submit_message(monkeypatch):
    if HEDERA_SDK_AVAILABLE:
        pytest.skip("Stub-only regression test")

    monkeypatch.setenv("HEDERA_ACCOUNT_ID", "0.0.12345")
    monkeypatch.setenv(
        "HEDERA_PRIVATE_KEY",
        "302e020100300506032b657004220420aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    monkeypatch.delenv("HEDERA_HCS_TOPIC_ID", raising=False)

    client = get_hedera_client()
    topic_id = await client.create_topic("Synaptica test topic")
    status = await client.submit_message("hello", topic_id=topic_id)

    assert str(topic_id) == "stub-topic-id"
    assert status == "STUB_OK"
