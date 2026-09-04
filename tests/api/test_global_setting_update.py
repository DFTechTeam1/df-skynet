import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import clear_setting_state

URL = "/api/setting"


@pytest.mark.asyncio
async def test_update_creates_settings_on_first_save(authed_client, db_session):
    """200 OK; POST inserts the settings rows when none exist yet."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": False}})
    assert resp.status_code == 200
    assert resp.json()["data"]["admin_view"] == {"see_all_asset": False}


@pytest.mark.asyncio
async def test_update_overwrites_instead_of_duplicating(authed_client, db_session):
    """200 OK; a second POST overwrites the same rows rather than creating a new set."""
    await clear_setting_state(db_session)
    await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": True}})

    resp = await authed_client.call("POST", URL, json={"admin_view": {"see_all_asset": False}})
    assert resp.status_code == 200

    fetch = await authed_client.call("GET", URL)
    assert fetch.json()["data"]["admin_view"] == {"see_all_asset": False}


@pytest.mark.asyncio
async def test_update_accepts_enabled_available_text_model(authed_client, db_session):
    """200 OK; a type=text, enabled, available model can be saved as enhancer_model.

    The client sends the model UID; it is stored and returned as the model name.
    """
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json={"enhancer_model": model.uid})
    assert resp.status_code == 200
    assert resp.json()["data"]["enhancer_model"] == model.name


@pytest.mark.asyncio
async def test_update_accepts_null_enhancer_and_assistant_model(authed_client, db_session):
    """200 OK; leaving the models blank falls back to null (engine default)."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json={"enhancer_model": None, "assistant_model": None})
    assert resp.status_code == 200
    assert resp.json()["data"]["enhancer_model"] is None
    assert resp.json()["data"]["assistant_model"] is None


@pytest.mark.asyncio
async def test_update_rejects_unknown_model_uid(authed_client, db_session):
    """404 model_option_not_found when enhancer_model references no row."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json={"enhancer_model": str(uuid4())}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_update_rejects_non_text_model(authed_client, db_session):
    """422 setting_engine_model_must_be_text when the model isn't a text model."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="image", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json={"enhancer_model": model.uid}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_text", "en")


@pytest.mark.asyncio
async def test_update_rejects_disabled_model(authed_client, db_session):
    """422 setting_engine_model_must_be_enabled when the model isn't enabled."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)

    resp = await authed_client.call("POST", URL, json={"assistant_model": model.uid}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_enabled", "en")


@pytest.mark.asyncio
async def test_update_rejects_unavailable_model(authed_client, db_session):
    """422 setting_engine_model_must_be_available when the model isn't available."""
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=False, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json={"enhancer_model": model.uid}, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("setting_engine_model_must_be_available", "en")


@pytest.mark.asyncio
async def test_update_omitted_admin_view_falls_back_to_its_default(authed_client, db_session):
    """200 OK; admin_view has a schema default, so omitting it saves {see_all_asset: True}."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 200
    assert resp.json()["data"]["admin_view"] == {"see_all_asset": True}


@pytest.mark.asyncio
async def test_update_rejects_unknown_project_class_id(authed_client, db_session, project_class_id):
    """404 project_class_not_found; the offending payload path is named in `error`."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "project_class_limitations": [
                {"id": project_class_id, "token_usage_limit": 3},
                {"id": 999999999, "token_usage_limit": 5},
            ]
        },
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_class_not_found", "en")
    assert resp.json()["error"] == {
        "project_class_limitations.1.id": [resolve_message("project_class_not_found", "en")]
    }


@pytest.mark.asyncio
async def test_update_dedupes_project_class_limitations_keeping_the_last(authed_client, db_session, project_class_id):
    """200 OK; a repeated class id is collapsed to its last value."""
    await clear_setting_state(db_session)

    await authed_client.call(
        "POST",
        URL,
        json={
            "project_class_limitations": [
                {"id": project_class_id, "token_usage_limit": 10},
                {"id": project_class_id, "token_usage_limit": 2},
            ]
        },
    )
    body = (await authed_client.call("GET", URL)).json()["data"]
    saved = next(row for row in body["project_class_limitations"] if row["id"] == project_class_id)
    assert saved["token_usage_limit"] == 2


@pytest.mark.asyncio
async def test_update_leaves_unlisted_classes_at_their_current_values(authed_client, db_session, project_class_id):
    """200 OK; sending one class only touches that class — the rest keep what they had."""
    await clear_setting_state(db_session)
    await authed_client.call(
        "POST", URL, json={"project_class_limitations": [{"id": project_class_id, "token_usage_limit": 7}]}
    )

    # a second save for a different value on the same class; other classes untouched
    body = (await authed_client.call("GET", URL)).json()["data"]["project_class_limitations"]
    touched = next(row for row in body if row["id"] == project_class_id)
    others = [row for row in body if row["id"] != project_class_id]
    assert touched["token_usage_limit"] == 7
    assert others and all(row["token_usage_limit"] == 1 for row in others)


@pytest.mark.asyncio
async def test_update_accepts_empty_project_class_limitations(authed_client, db_session):
    """200 OK; project_class_limitations is optional and defaults to leaving every class as-is."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json={"project_class_limitations": []}, raise_for_status=False)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_update_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 401
