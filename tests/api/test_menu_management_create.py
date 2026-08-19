import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineFeatures, DfEngineMenus
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/menu-management"


async def _make_feature(db_session, user_id):
    return await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client):
    """200 OK; response body is the refreshed menu list, with the new menu's fields as given."""
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "description": "a desc",
            "is_active": True,
            "feature_uids": [],
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["description"] == "a desc"
    assert item["is_active"] is True
    assert item["features"] == []


@pytest.mark.asyncio
async def test_create_defaults_is_active_true_and_no_features_required(authed_client):
    """200 OK; omitting is_active/description/feature_uids falls back to active, null desc, no features."""
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call("POST", URL, json={"name": name})
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["is_active"] is True
    assert item["description"] is None
    assert item["features"] == []


@pytest.mark.asyncio
async def test_create_with_linked_features(authed_client, db_session, user_id):
    """200 OK; process links every given feature_uid via a new df_engine_menu_feature_mappings row in the same call."""
    feature_a = await _make_feature(db_session, user_id)
    feature_b = await _make_feature(db_session, user_id)
    name = f"Create Linked {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "feature_uids": [feature_a.uid, feature_b.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    linked_uids = {f["feature_uid"] for f in item["features"]}
    assert linked_uids == {feature_a.uid, feature_b.uid}


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(authed_client, db_session, user_id):
    """200 OK; created_by comes from the bearer token's user, not from the request body."""
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
    """422 for each individually invalid field: empty name, oversized name, empty description."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}"}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_missing_required_name(authed_client):
    """422 when `name` is omitted entirely."""
    resp = await authed_client.call("POST", URL, json={}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict(authed_client, db_session, user_id):
    """409 when `name` already belongs to another menu."""
    existing = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
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
    assert resp.json()["message"] == resolve_message("menu_already_exists", "en")


@pytest.mark.asyncio
async def test_create_unknown_feature_uid_is_422(authed_client):
    """422; process rejects the whole request before inserting anything if a feature_uid doesn't exist."""
    unknown_uid = str(uuid4())
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Bad Feature {uuid4().hex[:8]}",
            "feature_uids": [unknown_uid],
        },
        raise_for_status=False,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["message"] == resolve_message("menu_feature_not_found", "en")
    assert body["error"]["feature_uids.0"] == [resolve_message("feature_not_found", "en")]


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST",
        URL,
        json={"name": f"Unauth {uuid4().hex[:8]}"},
        raise_for_status=False,
    )
    assert resp.status_code == 401
