import pytest
from middlewares.lang import resolve_message

URL = "/api/key-management"


@pytest.mark.asyncio
async def test_success_message_defaults_to_english(authed_client):
    """200 OK; with no Accept-Language header, the default success message is English."""
    resp = await authed_client.call("GET", URL)
    assert resp.json()["message"] == "Success"


@pytest.mark.asyncio
async def test_success_message_respects_accept_language(authed_client):
    """200 OK for both, but the success message text differs between en and id."""
    en_resp = await authed_client.call("GET", URL, headers={"Accept-Language": "en"})
    id_resp = await authed_client.call("GET", URL, headers={"Accept-Language": "id"})

    assert en_resp.json()["message"] == resolve_message("success", "en")
    assert id_resp.json()["message"] == resolve_message("success", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
    assert id_resp.json()["message"] == "Sukses"
