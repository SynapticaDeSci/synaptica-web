import httpx
import pytest
from fastapi import HTTPException

from api.main import _build_hol_registration_payload, _resolve_hol_error_status
from shared.database import Agent
from shared.hol_client import _format_http_error


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


def test_resolve_hol_error_status_marks_transient_failures_unregistered() -> None:
    message = "HOL register_agent failed after trying paths (/register): request timed out while waiting for HOL registry response"
    assert _resolve_hol_error_status("unregistered", message) == "unregistered"


def test_resolve_hol_error_status_marks_non_transient_failures_error() -> None:
    message = "HOL register_agent failed after trying paths (/register): 402 Payment Required: insufficient_credits"
    assert _resolve_hol_error_status("unregistered", message) == "error"
