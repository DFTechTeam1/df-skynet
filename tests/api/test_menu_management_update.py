import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineMenuFeatureMappings
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.redis import client as redis_client
from tests.helpers import find_by_name, response_names

URL = "/api/menu-management"


def _make_menu(user_id):
    return DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)


def _make_feature(user_id):
    return DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)


@pytest.mark.asyncio
async def test_update_replaces_name_description_and_active(authed_client, user_id):
    """200 OK; PATCH is a full replace of name/description/is_active, not a partial diff."""
    menu = _make_menu(user_id)
    renamed = f"{menu.name}-v2"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": renamed, "description": "new desc", "is_active": True},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], renamed)
    assert item["description"] == "new desc"
    assert item["is_active"] is True


@pytest.mark.asyncio
async def test_update_add_and_remove_features_in_one_call(authed_client, user_id):
    """200 OK; process diffs feature_uids against existing mappings — unlinks removed, links added, in one call."""
    menu = _make_menu(user_id)
    kept = _make_feature(user_id)
    removed = _make_feature(user_id)
    added = _make_feature(user_id)

    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=kept)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=removed)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={
            "name": menu.name,
            "feature_uids": [kept.uid, added.uid],
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    linked_uids = {f["feature_uid"] for f in item["features"]}
    assert linked_uids == {kept.uid, added.uid}


@pytest.mark.asyncio
async def test_update_preserves_mapping_uid_for_unchanged_feature(authed_client, db_session, user_id):
    """200 OK; process leaves an unchanged mapping row untouched instead of deleting and recreating it."""
    menu = _make_menu(user_id)
    feature = _make_feature(user_id)
    mapping = DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "feature_uids": [feature.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    assert len(item["features"]) == 1
    assert item["features"][0]["feature_uid"] == feature.uid
    await db_session.commit()
    still_present = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.uid == mapping.uid)  # type: ignore
        )
    ).scalar_one_or_none()
    assert still_present is not None


@pytest.mark.asyncio
async def test_update_empty_feature_uids_unlinks_everything(authed_client, user_id):
    """200 OK; passing an empty feature_uids list unlinks every currently-mapped feature."""
    menu = _make_menu(user_id)
    feature = _make_feature(user_id)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "feature_uids": []},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    assert item["features"] == []


@pytest.mark.asyncio
async def test_update_deactivating_keeps_its_feature_mappings(authed_client, db_session, user_id):
    """200 OK; setting is_active False leaves the menu's df_engine_menu_feature_mappings rows untouched."""
    menu = _make_menu(user_id)
    feature = _make_feature(user_id)
    mapping = DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "is_active": False, "feature_uids": [feature.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    assert item["is_active"] is False
    assert {f["feature_uid"] for f in item["features"]} == {feature.uid}
    await db_session.commit()

    remaining = (
        (
            await db_session.execute(
                select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.menu_id == menu.id)  # type: ignore
            )
        )
        .scalars()
        .all()
    )
    assert [m.uid for m in remaining] == [mapping.uid]


@pytest.mark.asyncio
async def test_update_unknown_uid_is_404(authed_client):
    """404 menu_not_found when the path uid matches no menu."""
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uuid4()}",
        json={"name": f"Ghost {uuid4().hex[:8]}"},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_update_unknown_feature_uid_is_422(authed_client, user_id):
    """422; process rejects the whole update if a given feature_uid doesn't exist."""
    menu = _make_menu(user_id)
    unknown_uid = str(uuid4())

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "feature_uids": [unknown_uid]},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["message"] == resolve_message("menu_feature_not_found", "en")
    assert body["error"]["feature_uids.0"] == [resolve_message("feature_not_found", "en")]


@pytest.mark.asyncio
async def test_update_rename_into_collision_is_409(authed_client, user_id):
    """409 when renaming a menu to a name another menu already has."""
    existing = _make_menu(user_id)
    other = _make_menu(user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": existing.name},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("menu_already_exists", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, user_id):
    """401 when the request carries no bearer token."""
    menu = _make_menu(user_id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name},
        raise_for_status=False,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_invalidates_the_detail_cache(authed_client, user_id):
    """200 OK; PATCH clears the cached detail so the next GET-by-uid reflects the new name, not the stale cache."""
    menu = _make_menu(user_id)
    detail_before = await authed_client.call("GET", f"{URL}/{menu.uid}")
    assert detail_before.json()["data"]["name"] == menu.name

    renamed = f"{menu.name}-v2"
    await authed_client.call("PATCH", f"{URL}/{menu.uid}", json={"name": renamed})

    detail_after = await authed_client.call("GET", f"{URL}/{menu.uid}")
    assert detail_after.json()["data"]["name"] == renamed


@pytest.mark.asyncio
async def test_update_invalidates_the_list_cache(authed_client, user_id):
    """200 OK; PATCH clears the cached list so a subsequent GET reflects the rename, not the stale cache."""
    menu = _make_menu(user_id)
    await authed_client.call("GET", URL)  # warm the unfiltered list cache
    assert await redis_client().exists("menu_management:list:all")

    renamed = f"{menu.name}-v2"
    await authed_client.call("PATCH", f"{URL}/{menu.uid}", json={"name": renamed})

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert renamed in found
    assert menu.name not in found
