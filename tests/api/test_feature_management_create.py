import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineActions, DfEnginePromptTemplates
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/feature-management"


async def _make_template(db_session, user_id):
    return await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client):
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "description": "a desc",
            "is_active": True,
            "template_uids": [],
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["description"] == "a desc"
    assert item["is_active"] is True
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_create_defaults_is_active_true_and_no_templates_required(
    authed_client,
):
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call("POST", URL, json={"name": name})
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["is_active"] is True
    assert item["description"] is None
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_create_with_linked_templates(authed_client, db_session, user_id):
    template_a = await _make_template(db_session, user_id)
    template_b = await _make_template(db_session, user_id)
    name = f"Create Linked {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "template_uids": [template_a.uid, template_b.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    linked_uids = {t["uid"] for t in item["templates"]}
    assert linked_uids == {template_a.uid, template_b.uid}


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(
    authed_client, db_session, user_id
):
    name = f"Create Creater {uuid4().hex[:8]}"
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call("POST", URL, json={"name": name})
    item = find_by_name(resp.json()["data"], name)
    assert item["creater"] == creater
    assert item["updater"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "x" * 256},
        {"description": ""},
    ],
    ids=["empty_name", "oversized_name", "empty_description"],
)
async def test_create_validation_errors(authed_client, overrides):
    payload = {"name": f"Invalid {uuid4().hex[:8]}"}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_missing_required_name(authed_client):
    resp = await authed_client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict(authed_client, db_session, user_id):
    existing = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": existing.name},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("feature_already_exists", "en")


@pytest.mark.asyncio
async def test_create_unknown_template_uid_is_404(authed_client):
    unknown_uid = str(uuid4())
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Bad Template {uuid4().hex[:8]}",
            "template_uids": [unknown_uid],
        },
        raise_for_status=False,
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["message"] == resolve_message("feature_template_not_found", "en")
    assert unknown_uid in body["error"]["template_uids"]


@pytest.mark.asyncio
async def test_requires_auth(client):
    resp = await client.call(
        "POST",
        URL,
        json={"name": f"Unauth {uuid4().hex[:8]}"},
        raise_for_status=False,
    )
    assert resp.status_code == 401
