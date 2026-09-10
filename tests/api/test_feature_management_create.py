import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from tests.helpers import expected_user, find_by_name

URL = "/api/feature-management"


def _make_template(user_id):
    return DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client):
    """200 OK; response body is the refreshed feature list, with the new feature's fields as given."""
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "type": "generate_image",
            "description": "a desc",
            "is_active": True,
            "template_uids": [],
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["type"] == "generate_image"
    assert item["description"] == "a desc"
    assert item["is_active"] is True
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_create_defaults_is_active_true_and_no_templates_required(
    authed_client,
):
    """200 OK; omitting is_active/description/template_uids falls back to active, null desc, no templates."""
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call("POST", URL, json={"name": name, "type": "generate_video"})
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["type"] == "generate_video"
    assert item["is_active"] is True
    assert item["description"] is None
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_create_with_linked_templates(authed_client, user_id):
    """200 OK; process links every given template_uid via a new df_engine_feature_prompt_mappings row in the same call."""
    template_a = _make_template(user_id)
    template_b = _make_template(user_id)
    name = f"Create Linked {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "type": "generate_image", "template_uids": [template_a.uid, template_b.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    linked_uids = {t["template_uid"] for t in item["templates"]}
    assert linked_uids == {template_a.uid, template_b.uid}


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(authed_client, db_session, user_id):
    """200 OK; created_by comes from the bearer token's user, not from the request body."""
    name = f"Create Creater {uuid4().hex[:8]}"
    creator = await expected_user(db_session, user_id)

    resp = await authed_client.call("POST", URL, json={"name": name, "type": "generate_image"})
    item = find_by_name(resp.json()["data"], name)
    assert item["creator"] == creator
    assert item["updater"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "x" * 256},
        {"description": ""},
        {"type": "not_a_real_type"},
        {"type": None},
    ],
    ids=["empty_name", "oversized_name", "empty_description", "unknown_type", "null_type"],
)
async def test_create_validation_errors(authed_client, overrides):
    """422 for each individually invalid field: empty name, oversized name, empty description, bad/missing type."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}", "type": "generate_image"}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_missing_required_fields(authed_client):
    """422 when required fields (`name`, `type`) are omitted entirely."""
    resp = await authed_client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict(authed_client, user_id):
    """409 when `name` already belongs to another feature."""
    existing = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": existing.name, "type": "generate_image"},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("feature_already_exists", "en")


@pytest.mark.asyncio
async def test_create_unknown_template_uid_is_422(authed_client):
    """422; process rejects the whole request before inserting anything if a template_uid doesn't exist."""
    unknown_uid = str(uuid4())
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Bad Template {uuid4().hex[:8]}",
            "type": "generate_image",
            "template_uids": [unknown_uid],
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["message"] == resolve_message("feature_template_not_found", "en")
    assert body["error"]["template_uids.0"] == [resolve_message("prompt_template_not_found", "en")]


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST",
        URL,
        json={"name": f"Unauth {uuid4().hex[:8]}", "type": "generate_image"},
        raise_for_status=False,
    )
    assert resp.status_code == 401
