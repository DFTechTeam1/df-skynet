import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import (
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
)
from tests.helpers import create_record, find_by_name

URL = "/api/menu-management"


async def _make_menu(db_session, user_id):
    return await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )


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
async def test_update_replaces_name_description_and_active(authed_client, db_session, user_id):
    """200 OK; PATCH is a full replace of name/description/is_active, not a partial diff."""
    menu = await _make_menu(db_session, user_id)
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
async def test_update_add_and_remove_features_in_one_call(authed_client, db_session, user_id):
    """200 OK; process diffs feature_uids against existing mappings — unlinks removed, links added, in one call."""
    menu = await _make_menu(db_session, user_id)
    kept = await _make_feature(db_session, user_id)
    removed = await _make_feature(db_session, user_id)
    added = await _make_feature(db_session, user_id)

    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=kept.id, menu_id=menu.id),
    )
    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=removed.id, menu_id=menu.id),
    )

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
    menu = await _make_menu(db_session, user_id)
    feature = await _make_feature(db_session, user_id)
    mapping = await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, menu_id=menu.id),
    )

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
async def test_update_empty_feature_uids_unlinks_everything(authed_client, db_session, user_id):
    """200 OK; passing an empty feature_uids list unlinks every currently-mapped feature."""
    menu = await _make_menu(db_session, user_id)
    feature = await _make_feature(db_session, user_id)
    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, menu_id=menu.id),
    )

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "feature_uids": []},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    assert item["features"] == []


@pytest.mark.asyncio
async def test_update_deactivating_removes_its_own_feature_mappings(authed_client, db_session, user_id):
    """200 OK; setting is_active False on the menu deletes its own df_engine_menu_feature_mappings rows."""
    menu = await _make_menu(db_session, user_id)
    feature = await _make_feature(db_session, user_id)
    await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, menu_id=menu.id),
    )

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name, "is_active": False, "feature_uids": [feature.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], menu.name)
    assert item["is_active"] is False
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
    assert remaining == []


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
async def test_update_unknown_feature_uid_is_422(authed_client, db_session, user_id):
    """422; process rejects the whole update if a given feature_uid doesn't exist."""
    menu = await _make_menu(db_session, user_id)
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
async def test_update_rename_into_collision_is_409(authed_client, db_session, user_id):
    """409 when renaming a menu to a name another menu already has."""
    existing = await _make_menu(db_session, user_id)
    other = await _make_menu(db_session, user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": existing.name},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("menu_already_exists", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id):
    """401 when the request carries no bearer token."""
    menu = await _make_menu(db_session, user_id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{menu.uid}",
        json={"name": menu.name},
        raise_for_status=False,
    )
    assert resp.status_code == 401
