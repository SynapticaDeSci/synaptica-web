import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from api.main import (
    _build_hol_registration_payload,
    _is_hol_insufficient_credits_error,
    _resolve_hol_error_status,
)
from shared.database import Agent, AgentReputation, AgentsCacheEntry, HolAgentVerification, SessionLocal
import shared.hol_client as hol_client
from shared.hol_client import (
    _format_http_error,
    _get_quote_paths,
    create_session,
    get_history,
    register_agent,
    search_agents,
    send_message,
    vector_search_agents,
)
from shared.research.catalog import default_public_research_endpoint, default_public_research_health_url


def _reset_state() -> None:
    session = SessionLocal()
    try:
        session.query(HolAgentVerification).delete()
        session.query(AgentsCacheEntry).delete()
        session.query(AgentReputation).delete()
        session.query(Agent).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _reset_state()
    monkeypatch.setattr("api.main.ensure_registry_cache", lambda: None)
    monkeypatch.setattr("api.routes.agents.trigger_registry_cache_refresh", lambda: False)
    monkeypatch.setattr("api.routes.agents.get_registry_sync_status", lambda: ("test", None))
    monkeypatch.setattr("api.main.hol_check_sidecar_health", lambda: {"ok": True})
    with TestClient(app) as test_client:
        yield test_client


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
    assert payload["additionalRegistries"] == []


def test_build_hol_registration_payload_honors_additional_registries_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "HOL_REGISTER_ADDITIONAL_REGISTRIES",
        "erc-8004:skale-base, erc-8004:ethereum-sepolia",
    )

    payload = _build_hol_registration_payload(_sample_agent())
    assert payload["additionalRegistries"] == [
        "erc-8004:skale-base",
        "erc-8004:ethereum-sepolia",
    ]


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


def test_resolve_hol_error_status_marks_transient_failures_unregistered() -> None:
    message = "HOL register_agent failed after trying paths (/register): request timed out while waiting for HOL registry response"
    assert _resolve_hol_error_status("unregistered", message) == "unregistered"


def test_resolve_hol_error_status_marks_non_transient_failures_error() -> None:
    message = "HOL register_agent failed after trying paths (/register): 402 Payment Required: insufficient_credits"
    assert _resolve_hol_error_status("unregistered", message) == "error"


def test_is_hol_insufficient_credits_error() -> None:
    assert _is_hol_insufficient_credits_error("402 Payment Required: insufficient_credits")
    assert not _is_hol_insufficient_credits_error("request timed out")


def test_get_quote_paths_defaults_to_register_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REGISTRY_BROKER_REGISTER_PATHS", raising=False)
    monkeypatch.setenv("REGISTRY_BROKER_REGISTER_PATH", "/register")
    assert _get_quote_paths()[0] == "/register/quote"


def test_get_quote_paths_maps_publish_to_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REGISTRY_BROKER_REGISTER_PATHS", "/skills/publish,/register")
    paths = _get_quote_paths()
    assert paths[0] == "/skills/quote"
    assert "/register/quote" in paths


def test_search_agents_supports_hits_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8040/search")
    response = httpx.Response(
        200,
        json={
            "hits": [
                {
                    "uaid": "uaid:aid:demo",
                    "name": "Demo HOL Agent",
                    "description": "Demo description",
                    "capabilities": ["research"],
                    "transports": ["a2a"],
                    "pricing": {"rate": 1, "currency": "HBAR"},
                    "registry": "broker",
                    "trustScore": 42.5,
                    "trustScores": {"total": 42.5, "availability.uptime": 88.0},
                }
            ]
        },
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, path: str, json: dict | None = None) -> httpx.Response:
            assert path == "/search"
            assert json is not None
            assert json.get("query") == "data agent"
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    agents = search_agents("data agent", limit=1)
    assert len(agents) == 1
    assert agents[0].uaid == "uaid:aid:demo"
    assert agents[0].name == "Demo HOL Agent"
    assert agents[0].trust_score == 42.5
    assert agents[0].trust_scores == {"total": 42.5, "availability.uptime": 88.0}


def test_vector_search_agents_supports_nested_agent_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8040/search/vector")
    response = httpx.Response(
        200,
        json={
            "hits": [
                {
                    "agent": {
                        "uaid": "uaid:aid:vector-demo",
                        "metadata": {
                            "name": "Vector HOL Agent",
                            "description": "Semantic match",
                            "capabilities": ["analysis"],
                        },
                        "transports": ["http"],
                        "available": "true",
                    },
                    "score": 0.97,
                }
            ]
        },
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, path: str, json: dict | None = None) -> httpx.Response:
            assert path == "/search/vector"
            assert json is not None
            assert json.get("query") == "treasury risk monitoring assistant"
            assert json.get("filter") == {"registry": "hashgraph-online"}
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    agents = vector_search_agents(
        "treasury risk monitoring assistant",
        limit=3,
        filter={"registry": "hashgraph-online"},
    )
    assert len(agents) == 1
    assert agents[0].uaid == "uaid:aid:vector-demo"
    assert agents[0].name == "Vector HOL Agent"
    assert agents[0].available is True


def test_register_agent_uses_dedicated_registration_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOL_SDK_SIDECAR_REGISTER_TIMEOUT_SECONDS", "321")
    monkeypatch.setenv("HOL_SDK_SIDECAR_CONNECT_TIMEOUT_SECONDS", "9")

    request = httpx.Request("POST", "http://127.0.0.1:8040/register")
    response = httpx.Response(200, json={"uaid": "uaid:aid:registered"}, request=request)
    captured: dict[str, object] = {}

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(
            self,
            path: str,
            json: dict | None = None,
            timeout: httpx.Timeout | None = None,
        ) -> httpx.Response:
            captured["path"] = path
            captured["json"] = json
            captured["timeout"] = timeout
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    result = register_agent({"profile": {"display_name": "Demo Agent"}}, mode="register")

    assert result == {"uaid": "uaid:aid:registered"}
    assert captured["path"] == "/register"
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 321
    assert timeout.connect == 9


def test_hol_agents_search_exposes_candidate_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Agent:
        uaid = "uaid:aid:demo"
        name = "Demo HOL Agent"
        description = "Demo description"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {"rate": 1, "currency": "HBAR"}
        registry = "broker"
        available = True
        availability_status = "online"
        trust_score = 52.25
        trust_scores = {"total": 52.25, "availability.uptime": 77.0}
        source_url = "https://example.com/agent"
        adapter = "http-adapter"
        protocol = "http"

    monkeypatch.setattr("api.main.hol_search_agents", lambda query, limit=12: [_Agent()])

    response = client.get("/api/hol/agents/search", params={"q": "data agent"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "data agent"
    assert payload["agents"][0]["available"] is True
    assert payload["agents"][0]["availability_status"] == "online"
    assert payload["agents"][0]["trust_score"] == 52.25
    assert payload["agents"][0]["trust_scores"]["availability.uptime"] == 77.0
    assert payload["agents"][0]["source_url"] == "https://example.com/agent"
    assert payload["agents"][0]["protocol"] == "http"
    assert payload["agents"][0]["broker_marked_available"] is True
    assert payload["agents"][0]["synaptica_verified"] is False
    assert payload["agents"][0]["usability_tier"] == "broker_available"


def test_hol_agents_search_marks_recent_synaptica_success_as_verified(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Agent:
        uaid = "uaid:aid:verified"
        name = "Verified Agent"
        description = "Previously validated by Synaptica"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = False
        availability_status = None
        source_url = "https://example.com/verified"
        adapter = "http-adapter"
        protocol = "http"

    session = SessionLocal()
    try:
        session.add(
            HolAgentVerification(  # type: ignore[call-arg]
                uaid="uaid:aid:verified",
                last_success_at=datetime.utcnow(),
                last_success_mode="session",
                success_count=1,
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr("api.main.hol_search_agents", lambda query, limit=12: [_Agent()])

    response = client.get("/api/hol/agents/search", params={"q": "verified agent", "only_available": "true"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["agents"]) == 1
    assert payload["agents"][0]["available"] is False
    assert payload["agents"][0]["broker_marked_available"] is False
    assert payload["agents"][0]["synaptica_verified"] is True
    assert payload["agents"][0]["synaptica_verification_mode"] == "session"
    assert payload["agents"][0]["usability_tier"] == "verified"


def test_hol_agents_search_marks_newer_hard_failure_as_blocked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Agent:
        uaid = "uaid:aid:blocked"
        name = "Blocked Agent"
        description = "Unreachable endpoint"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://example.com/blocked"
        adapter = "http-adapter"
        protocol = "http"

    session = SessionLocal()
    try:
        session.add(
            HolAgentVerification(  # type: ignore[call-arg]
                uaid="uaid:aid:blocked",
                last_success_at=datetime.utcnow() - timedelta(hours=2),
                last_success_mode="session",
                last_hard_failure_at=datetime.utcnow() - timedelta(minutes=5),
                last_hard_failure_reason="422 Unprocessable Entity: This A2A agent is currently unreachable from the broker",
                success_count=1,
                failure_count=1,
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr("api.main.hol_search_agents", lambda query, limit=12: [_Agent()])

    response = client.get("/api/hol/agents/search", params={"q": "blocked agent"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"][0]["synaptica_verified"] is False
    assert payload["agents"][0]["usability_tier"] == "blocked"
    assert "currently unreachable from the broker" in payload["agents"][0]["usability_reason"]


def test_hol_agents_search_only_available_filters_unavailable_agents(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AvailableAgent:
        uaid = "uaid:aid:available"
        name = "Available Agent"
        description = "Available"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://example.com/available"
        adapter = "http-adapter"
        protocol = "http"

    class _UnavailableAgent:
        uaid = "uaid:aid:unavailable"
        name = "Unavailable Agent"
        description = "Unavailable"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = False
        availability_status = "offline"
        source_url = "https://example.com/unavailable"
        adapter = "http-adapter"
        protocol = "http"

    monkeypatch.setattr(
        "api.main.hol_search_agents",
        lambda query, limit=12: [_AvailableAgent(), _UnavailableAgent()],
    )

    response = client.get("/api/hol/agents/search", params={"q": "data agent", "only_available": "true"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["agents"]) == 1
    assert payload["agents"][0]["uaid"] == "uaid:aid:available"


def test_hol_agents_search_only_available_overfetches_before_filtering(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _AvailableAgent:
        uaid = "uaid:aid:available"
        name = "Available Agent"
        description = "Available"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = True
        availability_status = "online"
        source_url = "https://example.com/available"
        adapter = "http-adapter"
        protocol = "http"

    class _UnavailableAgent:
        uaid = "uaid:aid:unavailable"
        name = "Unavailable Agent"
        description = "Unavailable"
        capabilities = ["data"]
        categories = ["Data"]
        transports = ["http"]
        pricing = {}
        registry = "broker"
        available = False
        availability_status = "offline"
        source_url = "https://example.com/unavailable"
        adapter = "http-adapter"
        protocol = "http"

    def _mock_search(query: str, limit: int = 12):
        captured["limit"] = limit
        return [_UnavailableAgent(), _AvailableAgent()]

    monkeypatch.setattr("api.main.hol_search_agents", _mock_search)

    response = client.get("/api/hol/agents/search", params={"q": "data agent", "limit": 1, "only_available": "true"})
    assert response.status_code == 200
    payload = response.json()
    assert captured["limit"] == 5
    assert len(payload["agents"]) == 1
    assert payload["agents"][0]["uaid"] == "uaid:aid:available"


def test_supported_research_agents_use_public_hol_chat_surface(client: TestClient) -> None:
    session = SessionLocal()
    try:
        agent = session.query(Agent).filter(Agent.agent_id == "literature-miner-001").one()
        meta = dict(agent.meta or {})
        assert meta["endpoint_url"] == default_public_research_endpoint("literature-miner-001")
        assert meta["health_check_url"] == default_public_research_health_url("literature-miner-001")
    finally:
        session.close()


def test_supported_research_agent_public_a2a_endpoints_respond(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgent:
        name = "Literature Miner"
        description = "Searches for papers."
        capabilities = ["literature-mining", "evidence-gathering"]

        async def execute(self, request: str, context=None):
            assert request == "find papers about agent payments"
            assert context == {"source": "test"}
            return {
                "success": True,
                "agent_id": "literature-miner-001",
                "result": {"summary": "Found two relevant papers."},
            }

    monkeypatch.setattr("api.main._load_supported_research_runtime_agent", lambda agent_id: _FakeAgent())

    for path in (
        "/api/research-agent/literature-miner-001/.well-known/agent.json",
        "/api/research-agent/literature-miner-001/.well-known/agent-card.json",
    ):
        card = client.get(path)
        assert card.status_code == 200
        assert card.json()["id"] == "literature-miner-001"
        assert card.json()["url"].endswith("/api/research-agent/literature-miner-001")
        assert card.json()["extras"]["message_endpoint"].endswith(
            "/api/research-agent/literature-miner-001/a2a/v1/messages"
        )

    message = client.post(
        "/api/research-agent/literature-miner-001/a2a/v1/messages",
        json={"message": "find papers about agent payments", "metadata": {"source": "test"}},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["message_id"]
    assert payload["response"] == "Found two relevant papers."

    rpc_message = client.post(
        "/api/research-agent/literature-miner-001",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "message/send",
            "params": {
                "id": "task-1",
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "find papers about agent payments"}],
                    "metadata": {"source": "test"},
                },
            },
        },
    )
    assert rpc_message.status_code == 200
    rpc_payload = rpc_message.json()
    assert rpc_payload["id"] == "rpc-1"
    assert rpc_payload["result"]["id"] == "task-1"
    assert rpc_payload["result"]["status"]["message"]["parts"][0]["text"] == "Found two relevant papers."


def test_hol_chat_session_endpoint_returns_normalized_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.main.hol_create_session", lambda uaid, transport=None, as_uaid=None: "session-123")
    monkeypatch.setattr(
        "api.main.hol_get_history",
        lambda session_id, limit=50: [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "reply": "hi there"},
        ],
    )

    response = client.post(
        "/api/hol/chat/session",
        json={"uaid": "uaid:aid:demo", "transport": "http"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-123"
    assert payload["broker_response"]["mode"] == "session"
    assert len(payload["history"]) == 2
    assert payload["history"][1]["content"] == "hi there"


def test_hol_chat_session_endpoint_uses_direct_fallback_for_transient_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _failing_create_session(uaid, transport=None, as_uaid=None):
        raise hol_client.HolClientError("504 Gateway Timeout: registry broker request failed")

    monkeypatch.setattr("api.main.hol_create_session", _failing_create_session)

    response = client.post(
        "/api/hol/chat/session",
        json={"uaid": "uaid:aid:demo"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"].startswith("hol-direct:")
    assert payload["broker_response"]["mode"] == "direct"
    assert "504" in payload["broker_response"]["fallback_reason"]


def test_hol_chat_session_endpoint_persists_hard_reachability_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _failing_create_session(uaid, transport=None, as_uaid=None):
        raise hol_client.HolClientError(
            "422 Unprocessable Entity: This A2A agent is currently unreachable from the broker (agent card or endpoint check failed)."
        )

    monkeypatch.setattr("api.main.hol_create_session", _failing_create_session)

    response = client.post(
        "/api/hol/chat/session",
        json={"uaid": "uaid:aid:demo"},
    )
    assert response.status_code == 502

    session = SessionLocal()
    try:
        record = session.get(HolAgentVerification, "uaid:aid:demo")
        assert record is not None
        assert record.failure_count == 1
        assert "currently unreachable from the broker" in str(record.last_hard_failure_reason)
    finally:
        session.close()


def test_hol_chat_message_endpoint_returns_broker_response_and_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.main.hol_create_session", lambda uaid, transport=None, as_uaid=None: "session-123")
    monkeypatch.setattr(
        "api.main.hol_send_message",
        lambda session_id, message, as_uaid=None: {"reply": "ack", "sessionId": session_id},
    )
    monkeypatch.setattr(
        "api.main.hol_get_history",
        lambda session_id, limit=50: [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": "ack"},
        ],
    )

    session_response = client.post(
        "/api/hol/chat/session",
        json={"uaid": "uaid:aid:demo", "transport": "http"},
    )
    assert session_response.status_code == 200

    response = client.post(
        "/api/hol/chat/message",
        json={"session_id": "session-123", "message": "ping"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-123"
    assert payload["broker_response"]["mode"] == "session"
    assert payload["broker_response"]["reply"] == "ack"
    assert payload["history"][0]["content"] == "ping"

    session = SessionLocal()
    try:
        record = session.get(HolAgentVerification, "uaid:aid:demo")
        assert record is not None
        assert record.success_count == 1
        assert record.last_success_mode == "session"
        assert record.last_transport == "http"
    finally:
        session.close()


def test_hol_chat_message_endpoint_normalizes_non_dict_broker_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.main.hol_send_message",
        lambda session_id, message, as_uaid=None: "plain ack",
    )
    monkeypatch.setattr("api.main.hol_get_history", lambda session_id, limit=50: [])

    response = client.post(
        "/api/hol/chat/message",
        json={"session_id": "session-123", "message": "ping"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_response"] == {"mode": "session"}
    assert payload["history"][1]["content"] == "plain ack"
    assert payload["history"][1]["raw"] == {}


def test_hol_chat_message_endpoint_extracts_a2a_json_rpc_message_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.main.hol_send_message",
        lambda session_id, message, as_uaid=None: {
            "jsonrpc": "2.0",
            "id": "uss6nk549khmn360ewa",
            "result": {
                "id": "b82909bc1cb04f459bc93e9348648234",
                "kind": "task",
                "status": {
                    "state": "completed",
                    "message": {
                        "kind": "message",
                        "messageId": "b82909bc1cb04f459bc93e9348648234",
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "type": "text",
                                "text": (
                                    "No datasets are currently stored in the Synaptica Data Vault. "
                                    "Upload a failed or underused dataset first, then ask again."
                                ),
                            }
                        ],
                    },
                },
            },
        },
    )
    monkeypatch.setattr("api.main.hol_get_history", lambda session_id, limit=50: [])

    response = client.post(
        "/api/hol/chat/message",
        json={"session_id": "session-123", "message": "Hello"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["history"][1]["content"] == (
        "No datasets are currently stored in the Synaptica Data Vault. "
        "Upload a failed or underused dataset first, then ask again."
    )


def test_hol_chat_history_normalizes_stringified_a2a_json_rpc_message_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = {
        "jsonrpc": "2.0",
        "id": "w7gq0kki7hmn36457k",
        "result": {
            "id": "d63154595a224c49bb9a91540c55bb75",
            "kind": "task",
            "status": {
                "state": "completed",
                "message": {
                    "kind": "message",
                    "messageId": "d63154595a224c49bb9a91540c55bb75",
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "type": "text",
                            "text": (
                                "No datasets are currently stored in the Synaptica Data Vault. "
                                "Upload a failed or underused dataset first, then ask again."
                            ),
                        }
                    ],
                },
            },
        },
    }
    monkeypatch.setattr(
        "api.main.hol_send_message",
        lambda session_id, message, as_uaid=None: {"ok": True},
    )
    monkeypatch.setattr(
        "api.main.hol_get_history",
        lambda session_id, limit=50: [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": json.dumps(envelope)},
        ],
    )

    response = client.post(
        "/api/hol/chat/message",
        json={"session_id": "session-123", "message": "Hello!"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["history"][1]["content"] == (
        "No datasets are currently stored in the Synaptica Data Vault. "
        "Upload a failed or underused dataset first, then ask again."
    )


def test_create_session_normalizes_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8040/chat/session")
    response = httpx.Response(
        502,
        text="<html>bad gateway</html>",
        headers={"content-type": "text/html"},
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(
            self,
            path: str,
            json: dict | None = None,
            timeout: object | None = None,
        ) -> httpx.Response:
            assert path == "/chat/session"
            raise httpx.HTTPStatusError("502 Bad Gateway", request=request, response=response)

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    with pytest.raises(hol_client.HolClientError, match="HOL create_session failed: 502 Bad Gateway"):
        create_session("uaid:aid:demo")


def test_create_session_forwards_sender_uaid_auth_and_history_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8040/chat/session")
    response = httpx.Response(
        200,
        json={"sessionId": "session-123"},
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(
            self,
            path: str,
            json: dict | None = None,
            timeout: object | None = None,
        ) -> httpx.Response:
            assert path == "/chat/session"
            assert json == {
                "uaid": "uaid:aid:demo",
                "senderUaid": "uaid:aid:sender",
                "auth": {"type": "bearer", "token": "secret"},
                "historyTtlSeconds": 120,
            }
            assert timeout is not None
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    session_id = create_session(
        "uaid:aid:demo",
        as_uaid="uaid:aid:sender",
        auth={"type": "bearer", "token": "secret"},
        history_ttl_seconds=120,
    )
    assert session_id == "session-123"


def test_send_message_supports_agent_url_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8040/chat/message")
    response = httpx.Response(
        200,
        json={"reply": "ack"},
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, path: str, json: dict | None = None) -> httpx.Response:
            assert path == "/chat/message"
            assert json == {
                "message": "hello",
                "agentUrl": "https://agent.example.com",
                "senderUaid": "uaid:aid:sender",
                "auth": {"type": "bearer", "token": "secret"},
                "streaming": True,
            }
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    payload = send_message(
        None,
        "hello",
        agent_url="https://agent.example.com",
        as_uaid="uaid:aid:sender",
        auth={"type": "bearer", "token": "secret"},
        streaming=True,
    )
    assert payload["reply"] == "ack"


def test_get_history_passes_limit_and_decrypt_to_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "http://127.0.0.1:8040/chat/history/session-123")
    response = httpx.Response(
        200,
        json={
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "assistant", "content": "three"},
            ]
        },
        request=request,
    )

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, params: dict | None = None) -> httpx.Response:
            assert path == "/chat/history/session-123"
            assert params == {"limit": 2, "decrypt": "true"}
            return response

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    history = get_history("session-123", limit=2, decrypt=True)
    assert [message["content"] for message in history] == ["two", "three"]


def test_check_sidecar_health_surfaces_clear_unavailable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str) -> httpx.Response:
            assert path == "/health"
            request = httpx.Request("GET", "http://127.0.0.1:8040/health")
            raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(hol_client, "_build_sidecar_client", lambda: _FakeClient())

    with pytest.raises(hol_client.HolClientConfigurationError, match="HOL SDK sidecar unavailable"):
        hol_client.check_sidecar_health()


def test_hol_register_data_agent_auto_publishes_metadata_and_rewrites_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _mock_publish(agent_id: str, metadata: dict[str, object]):
        captured["published_agent_id"] = agent_id
        captured["published_metadata"] = metadata
        return type(
            "UploadResult",
            (),
            {
                "cid": "bafy-data-agent",
                "ipfs_uri": "ipfs://bafy-data-agent",
                "gateway_url": "https://gateway.pinata.cloud/ipfs/bafy-data-agent",
            },
        )()

    def _mock_register(payload: dict[str, object], *, mode: str = "register") -> dict[str, object]:
        captured["register_payload"] = payload
        captured["mode"] = mode
        return {"uaid": "uaid:aid:data-agent-001"}

    monkeypatch.setenv("HOL_PUBLIC_BASE_URL", "https://agents.example.com")
    monkeypatch.setattr("api.main.publish_agent_metadata", _mock_publish)
    monkeypatch.setattr("api.main.hol_register_agent", _mock_register)

    response = client.post("/api/hol/register-agent", json={"agent_id": "data-agent-001", "mode": "register"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["hol_registration_status"] == "registered"
    assert payload["hol_uaid"] == "uaid:aid:data-agent-001"

    register_payload = captured["register_payload"]
    assert isinstance(register_payload, dict)
    assert register_payload["endpoint_url"] == "https://agents.example.com/api/data-agent/agent"
    assert register_payload["metadata_uri"] == "ipfs://bafy-data-agent"

    session = SessionLocal()
    try:
        agent = session.query(Agent).filter(Agent.agent_id == "data-agent-001").one()
        assert agent.erc8004_metadata_uri == "ipfs://bafy-data-agent"
        assert agent.meta["metadata_cid"] == "bafy-data-agent"
        assert agent.meta["metadata_gateway_url"] == "https://gateway.pinata.cloud/ipfs/bafy-data-agent"
        assert agent.meta["hol"]["registration_status"] == "registered"
        assert agent.meta["hol"]["uaid"] == "uaid:aid:data-agent-001"
    finally:
        session.close()


def test_hol_register_agent_honors_explicit_overrides(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _unexpected_publish(agent_id: str, metadata: dict[str, object]):
        raise AssertionError("publish_agent_metadata should not be called when metadata override is supplied")

    def _mock_register(payload: dict[str, object], *, mode: str = "register") -> dict[str, object]:
        captured["register_payload"] = payload
        return {"uaid": "uaid:aid:override"}

    monkeypatch.setattr("api.main.publish_agent_metadata", _unexpected_publish)
    monkeypatch.setattr("api.main.hol_register_agent", _mock_register)

    response = client.post(
        "/api/hol/register-agent",
        json={
            "agent_id": "data-agent-001",
            "mode": "register",
            "endpoint_url_override": "https://override.example.com/agent",
            "metadata_uri_override": "ipfs://override-cid",
        },
    )
    assert response.status_code == 200
    register_payload = captured["register_payload"]
    assert isinstance(register_payload, dict)
    assert register_payload["endpoint_url"] == "https://override.example.com/agent"
    assert register_payload["metadata_uri"] == "ipfs://override-cid"


def test_hol_register_data_agent_requires_public_base_when_endpoint_not_public(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOL_PUBLIC_BASE_URL", raising=False)
    response = client.post("/api/hol/register-agent", json={"agent_id": "data-agent-001", "mode": "quote"})
    assert response.status_code == 400
    assert "HOL_PUBLIC_BASE_URL" in response.json()["detail"]
