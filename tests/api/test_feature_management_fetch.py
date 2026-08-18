import pytest
from datetime import timedelta
from uuid import uuid4
from services.mysql.model import (
    DfEngineActionMappings,
    DfEngineActions,
    DfEnginePromptTemplates,
)
from utils import local_time
from tests.helpers import create_record, expected_user, find_by_name, response_names

URL = "/api/feature-management"


@pytest.mark.asyncio
async def test_fetch_all_features(authed_client):
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_fetch_includes_inactive_features(authed_client, db_session, user_id):
    inactive = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            is_active=False,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    item = find_by_name(body["data"], inactive.name)
    assert item["is_active"] is False


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, db_session, user_id):
    # `created_at` is DATETIME(0) in MySQL (no fractional seconds), so two
    # rows created back-to-back can land on the same wall-clock second —
    # pass explicit, clearly-ordered timestamps instead of relying on that.
    now = local_time()
    older = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-older",
            created_by=int(user_id),
            created_at=now - timedelta(seconds=5),
        ),
    )
    newer = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-newer",
            created_by=int(user_id),
            created_at=now,
        ),
    )

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert found.index(newer.name) < found.index(older.name)


@pytest.mark.asyncio
async def test_name_search_is_a_prefix_match(authed_client, db_session, user_id):
    prefix = f"Search{uuid4().hex[:8]}"
    matching = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"{prefix}-one",
            created_by=int(user_id),
        ),
    )
    # prefix appears mid-string, shouldn't match
    await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"other-{prefix}",
            created_by=int(user_id),
        ),
    )

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert matching.name in found
    assert f"other-{prefix}" not in found


@pytest.mark.asyncio
async def test_name_search_with_no_match_returns_empty_list(authed_client):
    prefix = f"NoMatch{uuid4().hex[:8]}"
    resp = await authed_client.call("GET", URL, params={"name": prefix})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_name_search_empty_string_is_a_validation_error(authed_client):
    resp = await authed_client.call(
        "GET", URL, params={"name": ""}, raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_response_shape_has_creater_not_created_by_user(
    authed_client, db_session, user_id
):
    row = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)

    assert "id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert "created_by_user" not in item
    assert "updated_by_user" not in item
    assert item["creater"] == creater
    assert set(item["creater"].keys()) == {"image", "nickname"}
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_action_flags_reflect_current_users_real_permissions(
    authed_client, db_session, user_id
):
    row = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_features",
        "can_create_feature",
        "can_update_feature",
        "can_delete_feature",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_templates_array_is_empty_when_unlinked(
    authed_client, db_session, user_id
):
    row = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_templates_array_reflects_linked_rows(authed_client, db_session, user_id):
    feature = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    template = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    mapping = await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=feature.id, template_id=template.id),
    )

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], feature.name)
    assert len(item["templates"]) == 1
    entry = item["templates"][0]
    assert entry["mapping_uid"] == mapping.uid
    assert entry["uid"] == template.uid
    assert entry["name"] == template.name
    assert entry["is_active"] is True


@pytest.mark.asyncio
async def test_requires_auth(client):
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
