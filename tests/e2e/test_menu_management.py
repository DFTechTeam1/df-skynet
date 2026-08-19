import pytest
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import DfEngineMenuFeatureMappings, DfEngineMenus
from tests.helpers import find_by_name, response_names

URL = "/api/menu-management"
FEATURE_URL = "/api/feature-management"


@pytest.mark.asyncio
async def test_full_menu_lifecycle(authed_client, db_session):
    """Walks create -> fetch -> update -> list -> delete for one menu, checking each response and the mapping cascade at the end."""
    feature_a_name = f"Journey Feature {uuid4().hex[:8]}-A"
    feature_b_name = f"Journey Feature {uuid4().hex[:8]}-B"

    # 1. create the two features through the existing feature-management API
    create_a = await authed_client.call("POST", FEATURE_URL, json={"name": feature_a_name})
    feature_a_uid = find_by_name(create_a.json()["data"], feature_a_name)["uid"]
    create_b = await authed_client.call("POST", FEATURE_URL, json={"name": feature_b_name})
    feature_b_uid = find_by_name(create_b.json()["data"], feature_b_name)["uid"]

    # 2. create a menu linked to both features
    menu_name = f"Journey Menu {uuid4().hex[:8]}"
    create_resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": menu_name,
            "description": "v1 desc",
            "feature_uids": [feature_a_uid, feature_b_uid],
        },
    )
    assert create_resp.status_code == 200
    created = find_by_name(create_resp.json()["data"], menu_name)
    menu_uid = created["uid"]
    assert {f["feature_uid"] for f in created["features"]} == {
        feature_a_uid,
        feature_b_uid,
    }

    # 3. fetch confirms nesting
    fetch_resp = await authed_client.call("GET", URL, params={"name": menu_name})
    fetched = find_by_name(fetch_resp.json()["data"], menu_name)
    assert {f["feature_uid"] for f in fetched["features"]} == {
        feature_a_uid,
        feature_b_uid,
    }

    # 4. update — swap feature B out, toggle is_active off, rename
    renamed = f"{menu_name}-v2"
    update_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{menu_uid}",
        json={
            "name": renamed,
            "description": "v2 desc",
            "is_active": False,
            "feature_uids": [feature_a_uid],
        },
    )
    assert update_resp.status_code == 200
    updated = find_by_name(update_resp.json()["data"], renamed)
    assert updated["is_active"] is False
    assert updated["description"] == "v2 desc"
    # confirms the self-cascade: deactivating the menu wipes its own mappings,
    # so even the feature that would otherwise still be linked (A) is gone.
    assert updated["features"] == []
    assert menu_name not in response_names(update_resp.json())

    # 5. list reflects the latest state (both active and inactive menus show up)
    list_resp = await authed_client.call("GET", URL)
    latest = find_by_name(list_resp.json()["data"], renamed)
    assert latest["is_active"] is False

    # 6. capture the internal id before deleting, to check cascade below —
    # the API never exposes it, so this is the one place we drop to raw ORM
    menu_row = (await db_session.execute(select(DfEngineMenus).where(DfEngineMenus.uid == menu_uid))).scalar_one()
    menu_id = menu_row.id
    # Close out this transaction's REPEATABLE READ snapshot now, so the
    # verification query below (after the HTTP delete commits on its own
    # connection) opens a fresh one instead of reusing this stale read.
    await db_session.commit()

    # 7. delete
    delete_resp = await authed_client.call("DELETE", f"{URL}/{menu_uid}")
    assert delete_resp.status_code == 200
    assert renamed not in response_names(delete_resp.json())

    # 8. confirmed gone on a fresh list, and its mapping rows are gone too
    final_list = await authed_client.call("GET", URL)
    assert renamed not in response_names(final_list.json())
    remaining_mappings = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.menu_id == menu_id)
        )
    ).scalar_one_or_none()
    assert remaining_mappings is None


@pytest.mark.asyncio
async def test_duplicate_name_conflict_from_create_and_update(authed_client):
    """409 from both create and rename-via-update when the target name is already taken, and a failed rename leaves the original name intact."""
    suffix = uuid4().hex[:8]
    alpha_name = f"Alpha-{suffix}"
    beta_name = f"Beta-{suffix}"

    alpha_resp = await authed_client.call("POST", URL, json={"name": alpha_name})
    assert alpha_resp.status_code == 200

    beta_resp = await authed_client.call("POST", URL, json={"name": beta_name})
    assert beta_resp.status_code == 200
    beta_uid = find_by_name(beta_resp.json()["data"], beta_name)["uid"]

    # renaming beta to alpha's name conflicts
    rename_conflict = await authed_client.call(
        "PATCH",
        f"{URL}/{beta_uid}",
        json={"name": alpha_name},
        raise_for_status=False,
    )
    assert rename_conflict.status_code == 409

    # creating a second "alpha" from scratch conflicts too — same guard, different trigger
    create_conflict = await authed_client.call("POST", URL, json={"name": alpha_name}, raise_for_status=False)
    assert create_conflict.status_code == 409

    # beta was never actually renamed by the failed attempt
    list_resp = await authed_client.call("GET", URL)
    assert beta_name in response_names(list_resp.json())


@pytest.mark.asyncio
async def test_deactivating_a_mapped_feature_removes_it_from_menu_response(authed_client, db_session):
    """200 OK; PATCHing a mapped feature's is_active to False also drops it from the menu's features array, and the underlying mapping row is actually deleted."""
    feature_name = f"Fadeout Feature {uuid4().hex[:8]}"
    create_feature = await authed_client.call("POST", FEATURE_URL, json={"name": feature_name})
    feature_uid = find_by_name(create_feature.json()["data"], feature_name)["uid"]

    menu_name = f"Fadeout Menu {uuid4().hex[:8]}"
    create_menu = await authed_client.call("POST", URL, json={"name": menu_name, "feature_uids": [feature_uid]})
    created = find_by_name(create_menu.json()["data"], menu_name)
    menu_uid = created["uid"]
    assert feature_uid in [f["feature_uid"] for f in created["features"]]

    menu_row = (await db_session.execute(select(DfEngineMenus).where(DfEngineMenus.uid == menu_uid))).scalar_one()
    mapping_before = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.menu_id == menu_row.id)
        )
    ).scalar_one()
    mapping_uid = mapping_before.uid
    await db_session.commit()

    deactivate = await authed_client.call(
        "PATCH",
        f"{FEATURE_URL}/{feature_uid}",
        json={"name": feature_name, "is_active": False},
    )
    assert deactivate.status_code == 200

    detail_resp = await authed_client.call("GET", f"{URL}/{menu_uid}")
    assert feature_uid not in [f["feature_uid"] for f in detail_resp.json()["data"]["features"]]

    remaining_mapping = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.uid == mapping_uid)
        )
    ).scalar_one_or_none()
    assert remaining_mapping is None


@pytest.mark.asyncio
async def test_same_feature_linked_to_multiple_menus(authed_client):
    """200 OK; the same feature can be mapped to two different menus simultaneously."""
    shared_feature_name = f"Shared {uuid4().hex[:8]}"
    feature_resp = await authed_client.call("POST", FEATURE_URL, json={"name": shared_feature_name})
    shared_feature_uid = find_by_name(feature_resp.json()["data"], shared_feature_name)["uid"]

    menu_one_name = f"Menu One {uuid4().hex[:8]}"
    menu_two_name = f"Menu Two {uuid4().hex[:8]}"

    await authed_client.call(
        "POST",
        URL,
        json={"name": menu_one_name, "feature_uids": [shared_feature_uid]},
    )
    await authed_client.call(
        "POST",
        URL,
        json={"name": menu_two_name, "feature_uids": [shared_feature_uid]},
    )

    resp = await authed_client.call("GET", URL)
    data = resp.json()["data"]
    item_one = find_by_name(data, menu_one_name)
    item_two = find_by_name(data, menu_two_name)
    assert shared_feature_uid in [f["feature_uid"] for f in item_one["features"]]
    assert shared_feature_uid in [f["feature_uid"] for f in item_two["features"]]
