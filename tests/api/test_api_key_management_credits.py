import pytest
from utils.formatter import format_credit_amount

URL = "/api/key-management/credits"


@pytest.fixture
def credits_store(monkeypatch):
    """In-memory stand-in for the stored row + the live OpenRouter fetch (no network, no DB writes)."""
    state = {"stored": None, "live": {"total_credits": 1550, "total_usage": 1526.2977413219999}, "refreshes": 0}

    async def fake_get_stored(db):
        return state["stored"]

    async def fake_refresh(db):
        state["refreshes"] += 1
        if state["live"] is None:
            return None
        state["stored"] = dict(state["live"])
        return state["stored"]

    monkeypatch.setattr("apps.controller.api_key_management.get_stored_credits", fake_get_stored)
    monkeypatch.setattr("apps.controller.api_key_management.refresh_credits", fake_refresh)
    return state


@pytest.mark.asyncio
async def test_get_reads_stored_row_without_calling_openrouter(authed_client, credits_store):
    credits_store["stored"] = {"total_credits": 100, "total_usage": 40}
    resp = await authed_client.call("GET", URL)
    assert resp.json()["data"] == {"total_credits": 100, "total_usage": 40, "remaining": 60}
    assert credits_store["refreshes"] == 0


@pytest.mark.asyncio
async def test_get_without_stored_row_fetches_once_and_formats(authed_client, credits_store):
    resp = await authed_client.call("GET", URL)
    assert resp.json()["data"] == {"total_credits": 1550, "total_usage": 1526.3, "remaining": 23.7}
    assert credits_store["refreshes"] == 1


@pytest.mark.asyncio
async def test_patch_refreshes_from_openrouter_and_get_then_uses_it(authed_client, credits_store):
    credits_store["stored"] = {"total_credits": 100, "total_usage": 40}
    resp = await authed_client.call("PATCH", URL)
    assert resp.json()["data"] == {"total_credits": 1550, "total_usage": 1526.3, "remaining": 23.7}
    assert credits_store["refreshes"] == 1
    resp = await authed_client.call("GET", URL)
    assert resp.json()["data"]["total_usage"] == 1526.3
    assert credits_store["refreshes"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_upstream_error_surfaces_as_service_error(authed_client, credits_store, method):
    credits_store["live"] = None
    resp = await authed_client.call(method, URL, raise_for_status=False)
    assert resp.status_code >= 500


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_credits_requires_auth(client, method):
    resp = await client.call(method, URL, raise_for_status=False)
    assert resp.status_code == 401


def test_credit_amount_int_stays_int_float_rounds_to_two_digits():
    assert format_credit_amount(1550) == 1550 and type(format_credit_amount(1550)) is int
    assert format_credit_amount(1550.0) == 1550 and type(format_credit_amount(1550.0)) is int
    assert format_credit_amount(1526.2977413219999) == 1526.3
    assert format_credit_amount(1550 - 1526.2977413219999) == 23.7
