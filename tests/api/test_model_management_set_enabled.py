import pytest
from typing import Any
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record

URL = "/api/models"


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"SetEnabledTest-{unique}",
        type="text",
        is_available=True,
        is_enabled=False,
        is_main=False,
    )
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_enable_disabled_available_model(authed_client, db_session):
    """200 OK; enabling an available, disabled model flips is_enabled true."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=False))

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is True
    assert resp.json()["data"]["is_main"] is False


@pytest.mark.asyncio
async def test_disable_enabled_model(authed_client, db_session):
    """200 OK; disabling an enabled, non-main model just flips is_enabled false."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=False))

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is False
    assert resp.json()["data"]["is_main"] is False


@pytest.mark.asyncio
async def test_disabling_main_model_clears_is_main(authed_client, db_session):
    """200 OK; disabling a model that currently holds is_main also clears is_main in the same call."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=True))

    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": False})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["is_enabled"] is False
    assert body["is_main"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("target_state", [True, False], ids=["enable", "disable"])
async def test_set_enabled_rejected_when_unavailable(authed_client, db_session, target_state):
    """422 model_option_unavailable_cannot_set_enabled; neither direction is allowed once is_available=False."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_available=False))

    resp = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"is_enabled": target_state}, raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("model_option_unavailable_cannot_set_enabled", "en")


@pytest.mark.asyncio
async def test_set_enabled_unknown_uid_is_404(authed_client):
    """404 model_option_not_found when the path uid matches no row."""
    resp = await authed_client.call("PATCH", f"{URL}/{uuid4()}", json={"is_enabled": True}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_set_enabled_missing_body_is_a_validation_error(authed_client, db_session):
    """422 when the required `is_enabled` field is omitted from the body."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data())
    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client, db_session):
    """401 when the request carries no bearer token."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data())
    resp = await client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": True}, raise_for_status=False)
    assert resp.status_code == 401
