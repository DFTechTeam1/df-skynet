import pytest
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import DfEngineActionMappings, DfEngineActions
from tests.helpers import find_by_name, response_names

URL = "/api/feature-management"
TEMPLATE_URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_full_feature_lifecycle(authed_client, db_session):
    template_a_name = f"Journey Template {uuid4().hex[:8]}-A"
    template_b_name = f"Journey Template {uuid4().hex[:8]}-B"

    # 1. create the two templates through the existing prompt-management API
    create_a = await authed_client.call(
        "POST", TEMPLATE_URL, json={"name": template_a_name, "prompt": "p"}
    )
    template_a_uid = find_by_name(create_a.json()["data"], template_a_name)["uid"]
    create_b = await authed_client.call(
        "POST", TEMPLATE_URL, json={"name": template_b_name, "prompt": "p"}
    )
    template_b_uid = find_by_name(create_b.json()["data"], template_b_name)["uid"]

    # 2. create a feature linked to both templates
    feature_name = f"Journey Feature {uuid4().hex[:8]}"
    create_resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": feature_name,
            "description": "v1 desc",
            "template_uids": [template_a_uid, template_b_uid],
        },
    )
    assert create_resp.status_code == 200
    created = find_by_name(create_resp.json()["data"], feature_name)
    feature_uid = created["uid"]
    assert {t["uid"] for t in created["templates"]} == {
        template_a_uid,
        template_b_uid,
    }

    # 3. fetch confirms nesting
    fetch_resp = await authed_client.call("GET", URL, params={"name": feature_name})
    fetched = find_by_name(fetch_resp.json()["data"], feature_name)
    assert {t["uid"] for t in fetched["templates"]} == {
        template_a_uid,
        template_b_uid,
    }

    # 4. update — swap template B out, toggle is_active off, rename
    renamed = f"{feature_name}-v2"
    update_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature_uid}",
        json={
            "name": renamed,
            "description": "v2 desc",
            "is_active": False,
            "template_uids": [template_a_uid],
        },
    )
    assert update_resp.status_code == 200
    updated = find_by_name(update_resp.json()["data"], renamed)
    assert updated["is_active"] is False
    assert updated["description"] == "v2 desc"
    assert {t["uid"] for t in updated["templates"]} == {template_a_uid}
    assert feature_name not in response_names(update_resp.json())

    # 5. list reflects the latest state (both active and inactive features show up)
    list_resp = await authed_client.call("GET", URL)
    latest = find_by_name(list_resp.json()["data"], renamed)
    assert latest["is_active"] is False

    # 6. capture the internal id before deleting, to check cascade below —
    # the API never exposes it, so this is the one place we drop to raw ORM
    feature_row = (
        await db_session.execute(
            select(DfEngineActions).where(DfEngineActions.uid == feature_uid)
        )
    ).scalar_one()
    feature_id = feature_row.id
    # Close out this transaction's REPEATABLE READ snapshot now, so the
    # verification query below (after the HTTP delete commits on its own
    # connection) opens a fresh one instead of reusing this stale read.
    await db_session.commit()

    # 7. delete
    delete_resp = await authed_client.call("DELETE", f"{URL}/{feature_uid}")
    assert delete_resp.status_code == 200
    assert renamed not in response_names(delete_resp.json())

    # 8. confirmed gone on a fresh list, and its mapping rows are gone too
    final_list = await authed_client.call("GET", URL)
    assert renamed not in response_names(final_list.json())
    remaining_mappings = (
        await db_session.execute(
            select(DfEngineActionMappings).where(
                DfEngineActionMappings.action_id == feature_id
            )
        )
    ).scalar_one_or_none()
    assert remaining_mappings is None


@pytest.mark.asyncio
async def test_duplicate_name_conflict_from_create_and_update(authed_client):
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
    create_conflict = await authed_client.call(
        "POST", URL, json={"name": alpha_name}, raise_for_status=False
    )
    assert create_conflict.status_code == 409

    # beta was never actually renamed by the failed attempt
    list_resp = await authed_client.call("GET", URL)
    assert beta_name in response_names(list_resp.json())


@pytest.mark.asyncio
async def test_same_template_linked_to_multiple_features(authed_client):
    shared_template_name = f"Shared {uuid4().hex[:8]}"
    template_resp = await authed_client.call(
        "POST", TEMPLATE_URL, json={"name": shared_template_name, "prompt": "p"}
    )
    shared_template_uid = find_by_name(
        template_resp.json()["data"], shared_template_name
    )["uid"]

    feature_one_name = f"Feature One {uuid4().hex[:8]}"
    feature_two_name = f"Feature Two {uuid4().hex[:8]}"

    await authed_client.call(
        "POST",
        URL,
        json={"name": feature_one_name, "template_uids": [shared_template_uid]},
    )
    await authed_client.call(
        "POST",
        URL,
        json={"name": feature_two_name, "template_uids": [shared_template_uid]},
    )

    resp = await authed_client.call("GET", URL)
    data = resp.json()["data"]
    item_one = find_by_name(data, feature_one_name)
    item_two = find_by_name(data, feature_two_name)
    assert shared_template_uid in [t["uid"] for t in item_one["templates"]]
    assert shared_template_uid in [t["uid"] for t in item_two["templates"]]
