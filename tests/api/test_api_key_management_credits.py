import pytest

URL = "/api/key-management/credits"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


@pytest.mark.asyncio
async def test_credits_success(authed_client):
    """200 OK; returns total, used and remaining credits."""
    resp = await authed_client.call("GET", URL)
    assert resp.status_code == 200
    assert resp.json()["data"] == {"total_credits": 100, "total_usage": 40, "remaining": 60}


@pytest.mark.asyncio
async def test_credits_upstream_error(authed_client, monkeypatch):
    """Upstream OpenRouter failure surfaces as a service error, not a 200."""
    from apps.controller import api_key_management

    monkeypatch.setattr(api_key_management.APICaller, "credits_status", 502)
    resp = await authed_client.call("GET", URL, raise_for_status=False)
    assert resp.status_code >= 500


@pytest.mark.asyncio
async def test_credits_requires_auth(client):
    """Unauthenticated requests are rejected."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401


def test_credit_amount_int_stays_int_float_rounds_to_two_digits():
    from utils.formatter import format_credit_amount

    assert format_credit_amount(1550) == 1550 and type(format_credit_amount(1550)) is int
    assert format_credit_amount(1550.0) == 1550 and type(format_credit_amount(1550.0)) is int
    assert format_credit_amount(1526.2977413219999) == 1526.3
    assert format_credit_amount(1550 - 1526.2977413219999) == 23.7
