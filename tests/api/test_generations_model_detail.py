import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory

URL = "/api/models"


def _url(model_uid):
    return f"{URL}/{model_uid}"


@pytest.mark.asyncio
async def test_returns_formatted_model_detail(authed_client):
    """200 OK; cache-miss builds the response from the DB row via ModelManagement().format()."""
    model = DfEngineModelOptionsFactory.create(name="Detail Model", is_enabled=True, is_main=False)

    resp = await authed_client.call("GET", _url(model.uid))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["uid"] == model.uid
    assert body["name"] == "Detail Model"
    assert body["is_enabled"] is True
    assert "id" not in body
    assert "is_available" not in body
    assert body["action"] == {
        "can_enable_disable": True,
        "can_set_as_main": False,
        "can_delete": False,
        "can_recover": False,
    }


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client):
    """200 OK; a second identical call returns the same data, exercising the cache-hit branch."""
    model = DfEngineModelOptionsFactory.create()

    first = await authed_client.call("GET", _url(model.uid))
    second = await authed_client.call("GET", _url(model.uid))
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_unknown_model_is_404(authed_client):
    """404 model_option_not_found for a model uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 401
