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
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "chat_assistant": {"max_previous_conversation": 0},
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
    """200 OK; a model that is type=text, is_enabled, is_available can be saved as enhancer_model.

    The client sends the model UID; the setting is stored and returned as the model name.
    """
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)

    resp = await authed_client.call("POST", URL, json=_base_payload(enhancer_model=model.uid))
    assert resp.status_code == 200
    assert resp.json()["data"]["enhancer_model"] == model.name


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
async def test_post_omitted_group_falls_back_to_its_default(authed_client, db_session):
    """200 OK; every group has a schema default, so omitting one (e.g. admin_view) saves that default."""
    await clear_setting_state(db_session)
    payload = _base_payload()
    del payload["admin_view"]

    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 200
    assert resp.json()["data"]["admin_view"] == {"see_all_asset": True}


@pytest.mark.asyncio
async def test_post_without_override_leaves_it_null_in_the_response(authed_client, db_session):
    """200 OK; project_limit_override is optional — omitting it echoes null."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json=_base_payload())
    assert resp.status_code == 200
    assert resp.json()["data"]["project_limit_override"] is None


@pytest.mark.asyncio
async def test_post_with_override_upserts_and_echoes_it_without_project_uid(authed_client, db_session, project_uid):
    """200 OK; sending {project_uid, limit} upserts that project's cap; the echo drops project_uid."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST", URL, json=_base_payload(project_limit_override={"project_uid": project_uid, "limit": 4})
    )
    assert resp.status_code == 200
    override = resp.json()["data"]["project_limit_override"]
    assert override["limit"] == 4
    assert set(override) == {"project_name", "limit"}

    fetched = await authed_client.call("GET", URL, params={"project_uid": project_uid})
    assert fetched.json()["data"]["project_limit_override"]["limit"] == 4


@pytest.mark.asyncio
async def test_post_rejects_unknown_project_uid_in_override(authed_client, db_session):
    """404 project_not_found when project_limit_override.project_uid matches no project."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST",
        URL,
        json=_base_payload(project_limit_override={"project_uid": str(uuid4()), "limit": 1}),
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_not_found", "en")


@pytest.mark.asyncio
async def test_post_rejects_unknown_project_class_id(authed_client, db_session, project_class_id):
    """404 project_class_not_found; the offending payload path is named in `error`."""
    await clear_setting_state(db_session)

    resp = await authed_client.call(
        "POST",
        URL,
        json=_base_payload(
            project_class_limits=[
                {"project_class_id": project_class_id, "limit": 3},
                {"project_class_id": 999999999, "limit": 5},
            ]
        ),
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_class_not_found", "en")
    assert resp.json()["error"] == {
        "project_class_limits.1.project_class_id": [resolve_message("project_class_not_found", "en")]
    }


@pytest.mark.asyncio
async def test_post_dedupes_project_class_limits_keeping_the_last(authed_client, db_session, project_class_id):
    """200 OK; a repeated project_class_id is collapsed to its last value."""
    await clear_setting_state(db_session)

    await authed_client.call(
        "POST",
        URL,
        json=_base_payload(
            project_class_limits=[
                {"project_class_id": project_class_id, "limit": 10},
                {"project_class_id": project_class_id, "limit": 2},
            ]
        ),
    )
    body = (await authed_client.call("GET", URL)).json()["data"]
    limits = [row["limit"] for row in body["project_class_limits"]]
    assert 10 not in limits and 2 in limits


@pytest.mark.asyncio
async def test_post_rejects_empty_project_class_limits(authed_client, db_session):
    """422; when project_class_limits is sent it must carry at least one entry."""
    await clear_setting_state(db_session)

    resp = await authed_client.call("POST", URL, json=_base_payload(project_class_limits=[]), raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_fills_unspecified_project_classes_with_zero(authed_client, db_session, project_class_id):
    """200 OK; only the listed class carries its limit — every other current class comes back at 0."""
    await clear_setting_state(db_session)

    await authed_client.call(
        "POST", URL, json=_base_payload(project_class_limits=[{"project_class_id": project_class_id, "limit": 8}])
    )
    body = (await authed_client.call("GET", URL)).json()["data"]
    limits = {row["project_class_name"]: row["limit"] for row in body["project_class_limits"]}
    assert 8 in limits.values()
    assert sum(1 for v in limits.values() if v == 0) == len(limits) - 1


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 401
