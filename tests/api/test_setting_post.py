import pytest
from typing import Any
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import clear_setting_state

URL = "/api/setting"


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admin_view": {"see_all_asset": True},
        "limit": {"generate_per_min": 0, "enhance_per_min": 0},
        "spend_ceiling": {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0},
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "enhancer_model": None,
        "assistant_model": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_post_creates_settings_on_first_save(authed_client, db_session):
    """200 OK; POST inserts settings when none exist yet."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST", URL, json=_base_payload(limit={"generate_per_min": 3, "enhance_per_min": 7})
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["limit"] == {"generate_per_min": 3, "enhance_per_min": 7}


@pytest.mark.asyncio
async def test_post_updates_existing_settings_instead_of_duplicating(authed_client, db_session):
    """200 OK; a second POST overwrites the same settings rather than creating a new set."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", URL, json=_base_payload())

    resp = await authed_client.call("POST", URL, json=_base_payload(admin_view={"see_all_asset": False}))
    assert resp.status_code == 200
    assert resp.json()["data"]["admin_view"] == {"see_all_asset": False}

    fetch = await authed_client.call("GET", URL)
    assert fetch.json()["data"]["admin_view"] == {"see_all_asset": False}


@pytest.mark.asyncio
async def test_post_accepts_enabled_available_text_model(authed_client, db_session):
    """200 OK; a model that is type=text, is_enabled, is_available can be saved as enhancer_model."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json=_base_payload(enhancer_model=model.uid))
    assert resp.status_code == 200
    assert resp.json()["data"]["enhancer_model"]["uid"] == model.uid


@pytest.mark.asyncio
async def test_post_accepts_null_enhancer_and_assistant_model(authed_client, db_session):
    """200 OK; leaving enhancer_model/assistant_model blank falls back to null (engine default)."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json=_base_payload())
    assert resp.status_code == 200
    assert resp.json()["data"]["enhancer_model"] is None
    assert resp.json()["data"]["assistant_model"] is None


@pytest.mark.asyncio
async def test_post_rejects_unknown_model_uid(authed_client, db_session):
    """404 model_option_not_found when enhancer_model references no row."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST", URL, json=_base_payload(enhancer_model=str(uuid4())), raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_post_rejects_non_text_model(authed_client, db_session):
    """422 setting_engine_model_must_be_text when the model isn't a text model."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="image", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json=_base_payload(enhancer_model=model.uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_text", "en")


@pytest.mark.asyncio
async def test_post_rejects_disabled_model(authed_client, db_session):
    """422 setting_engine_model_must_be_enabled when the model isn't enabled."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)

    resp = await authed_client.call("POST", URL, json=_base_payload(assistant_model=model.uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_enabled", "en")


@pytest.mark.asyncio
async def test_post_rejects_unavailable_model(authed_client, db_session):
    """422 setting_engine_model_must_be_available when the model isn't available."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=False, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json=_base_payload(enhancer_model=model.uid), raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_available", "en")


@pytest.mark.asyncio
async def test_post_missing_required_group_is_422(authed_client, db_session):
    """422 when a required top-level group (e.g. admin_view) is omitted entirely."""
    await clear_setting_state(db_session)
    payload = _base_payload()
    del payload["admin_view"]

    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 401
