import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app, _build_hol_registration_payload, _resolve_hol_error_status
from shared.database import Agent, AgentReputation, AgentsCacheEntry, SessionLocal
from shared.hol_client import _format_http_error, register_agent
from shared.metadata.publisher import PinataUploadResult


def _sample_agent() -> Agent:
    return Agent(  # type: ignore[call-arg]
        agent_id="demo-agent",
        name="Demo Agent",
        description="Research helper agent for HOL registration tests.",
        capabilities=["research", "summarization"],
        hedera_account_id="0.0.12345",
        erc8004_metadata_uri="ipfs://bafy-demo",
        status="active",
        meta={
            "endpoint_url": "https://agent.example.com/execute",
            "health_check_url": "https://agent.example.com/health",
            "pricing": {"rate": 1.25, "currency": "HBAR", "rate_type": "per_task"},
            "categories": ["Research", "DeSci"],
        },
    )


def test_build_hol_registration_payload_contains_hcs11_profile() -> None:
    payload = _build_hol_registration_payload(_sample_agent())

    profile = payload["profile"]
    assert profile["version"] == "1.0"
    assert profile["type"] == 1
    assert profile["display_name"] == "Demo Agent"
    assert profile["url"] == "https://agent.example.com/execute"
    assert profile["tags"] == ["Research", "DeSci"]
    assert profile["owner"] == {"account_id": "0.0.12345"}
    assert profile["aiAgent"]["metadata_uri"] == "ipfs://bafy-demo"
    assert profile["aiAgent"]["health_check_url"] == "https://agent.example.com/health"


def test_build_hol_registration_payload_requires_endpoint() -> None:
    agent = _sample_agent()
    agent.meta = {"pricing": {"rate": 1.0}, "categories": ["Research"]}

    with pytest.raises(HTTPException, match="Agent endpoint URL is required"):
        _build_hol_registration_payload(agent)


def test_build_hol_registration_payload_requires_metadata_uri() -> None:
    agent = _sample_agent()
    agent.erc8004_metadata_uri = None
    agent.meta = {
        "endpoint_url": "https://agent.example.com/execute",
        "pricing": {"rate": 1.0},
        "categories": ["Research"],
    }

    with pytest.raises(HTTPException, match="Agent metadata URI is required"):
        _build_hol_registration_payload(agent)


def test_format_http_error_includes_broker_error_message() -> None:
    request = httpx.Request("POST", "https://hol.org/registry/api/v1/register")
    response = httpx.Response(
        400,
        json={"error": "profile is required (HCS-11 format)"},
        request=request,
    )
    exc = httpx.HTTPStatusError("400 Bad Request", request=request, response=response)

    assert _format_http_error(exc) == "400 Bad Request: profile is required (HCS-11 format)"


def test_format_http_error_includes_credit_context() -> None:
    request = httpx.Request("POST", "https://hol.org/registry/api/v1/register")
    response = httpx.Response(
        402,
        json={
            "error": "insufficient_credits",
            "requiredCredits": 10,
            "availableCredits": 0,
            "shortfallCredits": 10,
        },
        request=request,
    )
    exc = httpx.HTTPStatusError("402 Payment Required", request=request, response=response)

    assert _format_http_error(exc) == (
        "402 Payment Required: insufficient_credits "
        "(requiredCredits=10, availableCredits=0, shortfallCredits=10)"
    )


def test_format_http_error_collapses_html_502_page() -> None:
    request = httpx.Request("POST", "https://hol.org/registry/api/v1/register")
    response = httpx.Response(
        502,
        text="<html><head><title>Bad gateway</title></head><body>Cloudflare</body></html>",
        headers={"content-type": "text/html; charset=UTF-8"},
        request=request,
    )
    exc = httpx.HTTPStatusError("502 Bad Gateway", request=request, response=response)

    assert _format_http_error(exc) == "502 Bad Gateway: upstream HOL registry error page"


def test_format_http_error_normalizes_timeout() -> None:
    exc = httpx.ReadTimeout("The read operation timed out")
    assert _format_http_error(exc) == "request timed out while waiting for HOL registry response"


def test_register_agent_tries_fallback_paths_after_timeout(monkeypatch) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, path: str, json: dict):
            self.paths.append(path)
            if path == "/register":
                raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", f"https://hol.org{path}"))
            request = httpx.Request("POST", f"https://hol.org{path}")
            return httpx.Response(200, json={"uaid": "uaid:hol:test:ok"}, request=request)

    fake_client = _FakeClient()
    monkeypatch.setattr("shared.hol_client._build_client", lambda **kwargs: fake_client)
    monkeypatch.setattr("shared.hol_client._get_base_url_candidates", lambda: ["https://hol.org/registry/api/v1"])
    monkeypatch.setattr("shared.hol_client._get_register_paths", lambda: ["/register", "/agents/register"])

    response = register_agent({"endpoint_url": "https://agent.example.com/execute"})
    assert response["uaid"] == "uaid:hol:test:ok"
    assert fake_client.paths == ["/register", "/agents/register"]


def test_register_agent_tries_fallback_base_url_after_timeouts(monkeypatch) -> None:
    class _TimeoutClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, path: str, json: dict):
            raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", f"https://hol.org{path}"))

    class _SuccessClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, path: str, json: dict):
            self.paths.append(path)
            request = httpx.Request("POST", f"https://api.hashgraph.online{path}")
            return httpx.Response(200, json={"uaid": "uaid:hol:fallback-base"}, request=request)

    timeout_client = _TimeoutClient()
    success_client = _SuccessClient()

    def _mock_build_client(*, base_url: str | None = None):
        if base_url == "https://hol.org/registry/api/v1":
            return timeout_client
        if base_url == "https://api.hashgraph.online/v1":
            return success_client
        raise AssertionError(f"Unexpected base_url: {base_url}")

    monkeypatch.setattr("shared.hol_client._build_client", _mock_build_client)
    monkeypatch.setattr(
        "shared.hol_client._get_base_url_candidates",
        lambda: ["https://hol.org/registry/api/v1", "https://api.hashgraph.online/v1"],
    )
    monkeypatch.setattr("shared.hol_client._get_register_paths", lambda: ["/register"])

    response = register_agent({"endpoint_url": "https://agent.example.com/execute"})
    assert response["uaid"] == "uaid:hol:fallback-base"
    assert success_client.paths == ["/register"]


def test_resolve_hol_error_status_marks_transient_failures_unregistered() -> None:
    message = "HOL register_agent failed after trying paths (/register): request timed out while waiting for HOL registry response"
    assert _resolve_hol_error_status("unregistered", message) == "unregistered"


def test_resolve_hol_error_status_marks_non_transient_failures_error() -> None:
    message = "HOL register_agent failed after trying paths (/register): 402 Payment Required: insufficient_credits"
    assert _resolve_hol_error_status("unregistered", message) == "error"


def _reset_agent_state() -> None:
    session = SessionLocal()
    try:
        session.query(AgentsCacheEntry).delete()
        session.query(AgentReputation).delete()
        session.query(Agent).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch):
    _reset_agent_state()
    monkeypatch.setattr("api.main.ensure_registry_cache", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


def _insert_agent(
    *,
    agent_id: str,
    agent_type: str,
    endpoint_url: str,
    metadata_uri: str | None = None,
) -> None:
    session = SessionLocal()
    try:
        row = Agent(  # type: ignore[call-arg]
            agent_id=agent_id,
            name=f"{agent_id}-name",
            description="Agent used for HOL registration endpoint tests.",
            capabilities=["dataset-upload", "dataset-analysis"],
            status="active",
            agent_type=agent_type,
            hedera_account_id="0.0.555",
            erc8004_metadata_uri=metadata_uri,
            meta={
                "endpoint_url": endpoint_url,
                "pricing": {"rate": 1.0, "currency": "HBAR", "rate_type": "per_task"},
                "categories": ["Data", "Research"],
            },
        )
        session.add(row)
        session.add(
            AgentReputation(
                agent_id=agent_id,
                reputation_score=0.8,
                payment_multiplier=1.0,
            )
        )
        session.commit()
    finally:
        session.close()


def test_register_data_agent_auto_publishes_metadata_and_rewrites_endpoint(client: TestClient, monkeypatch):
    _insert_agent(
        agent_id="hol-data-auto-001",
        agent_type="data",
        endpoint_url="/api/data-agent/datasets",
        metadata_uri=None,
    )
    monkeypatch.setenv("HOL_PUBLIC_BASE_URL", "https://api.synaptica.example")

    async def _mock_publish(_agent_id: str, metadata: dict):
        assert metadata["agentId"] == "hol-data-auto-001"
        assert metadata["endpoints"][0]["endpoint"].startswith("https://api.synaptica.example/")
        return PinataUploadResult(
            cid="bafy-data-001",
            ipfs_uri="ipfs://bafy-data-001",
            gateway_url="https://gateway.pinata.cloud/ipfs/bafy-data-001",
            pinata_url="https://app.pinata.cloud/pinmanager?search=bafy-data-001",
        )

    captured: dict = {}

    def _mock_hol_register(payload: dict, *, mode: str = "register"):
        captured["payload"] = payload
        captured["mode"] = mode
        return {"uaid": "uaid:data:auto:001"}

    monkeypatch.setattr("api.main.publish_agent_metadata", _mock_publish)
    monkeypatch.setattr("api.main.hol_register_agent", _mock_hol_register)

    response = client.post(
        "/api/hol/register-agent",
        json={"agent_id": "hol-data-auto-001", "mode": "register"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["hol_registration_status"] == "registered"
    assert payload["hol_uaid"] == "uaid:data:auto:001"

    register_payload = captured["payload"]
    assert register_payload["endpoint_url"].startswith("https://api.synaptica.example/")
    assert register_payload["metadata_uri"] == "ipfs://bafy-data-001"

    session = SessionLocal()
    try:
        agent = session.query(Agent).filter(Agent.agent_id == "hol-data-auto-001").one()
        assert agent.erc8004_metadata_uri == "ipfs://bafy-data-001"
        assert agent.meta["metadata_cid"] == "bafy-data-001"
        assert agent.meta["metadata_gateway_url"] == "https://gateway.pinata.cloud/ipfs/bafy-data-001"
    finally:
        session.close()


def test_register_agent_honors_endpoint_and_metadata_overrides(client: TestClient, monkeypatch):
    _insert_agent(
        agent_id="hol-data-override-001",
        agent_type="data",
        endpoint_url="/api/data-agent/datasets",
        metadata_uri="ipfs://bafy-existing",
    )
    monkeypatch.setenv("HOL_PUBLIC_BASE_URL", "https://api.synaptica.example")

    captured: dict = {}

    def _mock_hol_register(payload: dict, *, mode: str = "register"):
        captured["payload"] = payload
        captured["mode"] = mode
        return {"uaid": "uaid:data:override:001"}

    monkeypatch.setattr("api.main.hol_register_agent", _mock_hol_register)

    response = client.post(
        "/api/hol/register-agent",
        json={
            "agent_id": "hol-data-override-001",
            "mode": "quote",
            "endpoint_url_override": "https://public.agent.example/execute",
            "metadata_uri_override": "ipfs://bafy-override",
        },
    )
    assert response.status_code == 200
    register_payload = captured["payload"]
    assert register_payload["endpoint_url"] == "https://public.agent.example/execute"
    assert register_payload["metadata_uri"] == "ipfs://bafy-override"
    assert register_payload["profile"]["url"] == "https://public.agent.example/execute"
    assert register_payload["profile"]["aiAgent"]["metadata_uri"] == "ipfs://bafy-override"


def test_register_data_agent_requires_public_endpoint_base_when_relative(client: TestClient, monkeypatch):
    _insert_agent(
        agent_id="hol-data-relative-001",
        agent_type="data",
        endpoint_url="/api/data-agent/datasets",
        metadata_uri="ipfs://bafy-existing",
    )
    monkeypatch.delenv("HOL_PUBLIC_BASE_URL", raising=False)

    response = client.post(
        "/api/hol/register-agent",
        json={"agent_id": "hol-data-relative-001", "mode": "register"},
    )
    assert response.status_code == 400
    assert "HOL_PUBLIC_BASE_URL" in response.json()["detail"]
