"""Tests for endpoint override helpers in shared.registry_sync."""

from __future__ import annotations

from shared import registry_sync


def _call(url: str | None, *, agent_id: str = "bias-detector-001", kind: str = "primary") -> str | None:
    return registry_sync._override_endpoint(url, agent_id=agent_id, endpoint_kind=kind)


def test_primary_endpoint_override_replaces_base(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com")

    result = _call("http://localhost:5001/agents/bias-detector-001")

    assert result == "https://agents.example.com/agents/bias-detector-001"


def test_override_preserves_path_and_query(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com/root")

    url = "http://localhost:5001/custom/path?foo=bar"
    result = _call(url, agent_id="custom-agent")

    assert result == "https://agents.example.com/root/custom/path?foo=bar"


def test_override_falls_back_to_default_path_when_missing(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com")

    result = _call(None)

    assert result == "https://agents.example.com/agents/bias-detector-001"


def test_override_skips_non_http_endpoints(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com")

    url = "did:pkh:eip155:1:0x1234"
    result = _call(url)

    assert result == url


def test_health_override_prefers_specific_env(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.delenv("AGENT_HEALTH_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com")
    monkeypatch.setenv("AGENT_HEALTH_ENDPOINT_BASE_URL_OVERRIDE", "https://health.example.com")

    url = "http://localhost:5001/agents/bias-detector-001/health"
    result = _call(url, kind="health")

    assert result == "https://health.example.com/agents/bias-detector-001/health"


def test_health_override_falls_back_to_primary_env(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.delenv("AGENT_HEALTH_ENDPOINT_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AGENT_ENDPOINT_BASE_URL_OVERRIDE", "https://agents.example.com")

    url = "http://localhost:5001/agents/bias-detector-001/health"
    result = _call(url, kind="health")

    assert result == "https://agents.example.com/agents/bias-detector-001/health"


def test_supported_agents_keep_local_reputation_floor():
    result = registry_sync._effective_reputation_score("problem-framer-001", 0.0)

    assert result == 0.8


def test_non_supported_agents_use_raw_reputation_score():
    result = registry_sync._effective_reputation_score("bias-detector-001", 0.25)

    assert result == 0.25
