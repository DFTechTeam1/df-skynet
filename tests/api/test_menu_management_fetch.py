import pytest
from datetime import timedelta
from uuid import uuid4
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
)
from utils import local_time
from middlewares.lang import resolve_message
from tests.helpers import create_record, expected_user, find_by_name, response_names

URL = "/api/menu-management"


@pytest.mark.asyncio
async def test_fetch_all_menus(authed_client):
    """200 OK; returns a list when no name filter is given."""
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_fetch_includes_inactive_menus(authed_client, db_session, user_id):
    """200 OK; list includes inactive menus too."""
    inactive = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
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
    """200 OK; list is ordered by created_at descending, newest menu first."""
    now = local_time()
    older = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-older",
            created_by=int(user_id),
            created_at=now - timedelta(seconds=5),
        ),
    )
    newer = await create_record(
        db_session,
        DfEngineMenus,
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
    """200 OK; `name` filter matches only menus whose name starts with it, not mid-string occurrences."""
    prefix = f"Search{uuid4().hex[:8]}"
    matching = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"{prefix}-one",
            created_by=int(user_id),
        ),
    )
    await create_record(
        db_session,
        DfEngineMenus,
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
    """200 OK with an empty list when no menu name matches the filter."""
    prefix = f"NoMatch{uuid4().hex[:8]}"
    resp = await authed_client.call("GET", URL, params={"name": prefix})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_name_search_empty_string_is_a_validation_error(authed_client):
    """422; empty `name` fails the query param's min_length=1 constraint."""
    resp = await authed_client.call("GET", URL, params={"name": ""}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_response_shape_has_creater_not_created_by_user(authed_client, db_session, user_id):
    """200 OK; internal columns (id, created_by_user, etc.) are stripped, resolved creater/updater are exposed instead."""
    row = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
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
async def test_action_flags_reflect_current_users_real_permissions(authed_client, db_session, user_id):
    """200 OK; each item's action block has exactly the fetch-detail/update/delete flags, all booleans."""
    row = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_detail",
        "can_update_menu",
        "can_delete_menu",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_features_array_is_empty_when_unlinked(authed_client, db_session, user_id):
    """200 OK; `features` is an empty list for a menu with no df_engine_menu_feature_mappings rows."""
    row = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["features"] == []


@pytest.mark.asyncio
async def test_features_array_reflects_linked_rows(authed_client, db_session, user_id):
    """200 OK; `features` nests the mapped feature's own fields via the join table."""
    menu = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, menu_id=menu.id),
    )

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], menu.name)
    assert len(item["features"]) == 1
    entry = item["features"][0]
    assert entry["feature_uid"] == feature.uid
    assert entry["name"] == feature.name
    assert entry["is_active"] is True


@pytest.mark.asyncio
async def test_features_array_excludes_inactive_mapped_features(authed_client, db_session, user_id):
    """200 OK; `features` omits a mapped feature whose is_active is False, even though the mapping row still exists."""
    menu = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    inactive_feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            is_active=False,
            created_by=int(user_id),
        ),
    )
    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=inactive_feature.id, menu_id=menu.id),
    )

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], menu.name)
    assert item["features"] == []


@pytest.mark.asyncio
async def test_detail_by_uid_returns_full_shape(authed_client, db_session, user_id):
    """200 OK; GET /menu-management/{uid} returns the same shape as a list entry."""
    row = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == row.name
    assert resp.json()["data"]["features"] == []


@pytest.mark.asyncio
async def test_detail_unknown_uid_is_404(authed_client):
    """404 menu_not_found when the uid matches no menu."""
    resp = await authed_client.call("GET", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
