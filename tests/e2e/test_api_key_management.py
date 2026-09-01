import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from tests.helpers import find_by_name, response_names

URL = "/api/key-management"

pytestmark = pytest.mark.usefixtures("mock_openrouter")


@pytest.mark.asyncio
async def test_full_lifecycle(authed_client, active_employee_uid):
    """create as main -> copy (real key) -> rename (syncs to OpenRouter) -> limit change
    (syncs) -> delete blocked while main -> demote -> delete -> gone from list and copy."""
    name = f"Journey {uuid4().hex[:8]}"

    create_resp = await authed_client.call(
        "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": True}
    )
    assert create_resp.status_code == 200
    created = find_by_name(create_resp.json()["data"], name)
    uid = created["uid"]

    # copy returns the real, unmasked key
    copy_resp = await authed_client.call("GET", f"{URL}/{uid}")
    assert copy_resp.status_code == 200
    assert copy_resp.json()["data"] != created["key"]  # the list value was masked

    # rename — the key's name lives on OpenRouter too, so this syncs
    renamed = f"{name}-v2"
    rename_resp = await authed_client.call(
        "PATCH", f"{URL}/{uid}", json={"name": renamed, "employee_uid": active_employee_uid, "is_main": True}
    )
    assert rename_resp.status_code == 200
    assert renamed in response_names(rename_resp.json())
    assert name not in response_names(rename_resp.json())

    # change the spending limit — also syncs
    limit_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={
            "name": renamed,
            "employee_uid": active_employee_uid,
            "is_main": True,
            "limit": 10.0,
            "limit_reset": "daily",
        },
    )
    assert limit_resp.status_code == 200
    updated = find_by_name(limit_resp.json()["data"], renamed)
    assert updated["limit"] == 10.0
    assert updated["limit_reset"] == "daily"
    assert updated["updater"] is not None

    # delete is blocked while the key is still main
    blocked = await authed_client.call("DELETE", f"{URL}/{uid}", raise_for_status=False)
    assert blocked.status_code == 422
    assert blocked.json()["message"] == resolve_message("cannot_delete_main_api_key", "en")

    # demote, then delete succeeds
    demote = await authed_client.call(
        "PATCH", f"{URL}/{uid}", json={"name": renamed, "employee_uid": active_employee_uid, "is_main": False}
    )
    assert demote.status_code == 200

    delete_resp = await authed_client.call("DELETE", f"{URL}/{uid}")
    assert delete_resp.status_code == 200
    assert renamed not in response_names(delete_resp.json())

    # gone on a fresh list, and copy now 404s
    assert renamed not in response_names((await authed_client.call("GET", URL)).json())
    final_copy = await authed_client.call("GET", f"{URL}/{uid}", raise_for_status=False)
    assert final_copy.status_code == 404
    assert final_copy.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_hard_delete_then_name_reuse_journey(authed_client, active_employee_uid):
    """A deleted key's name is free to create fresh — and the new key is a distinct record,
    not a resurrection of the old one."""
    name = f"Reused {uuid4().hex[:8]}"

    first_resp = await authed_client.call(
        "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
    )
    first_uid = find_by_name(first_resp.json()["data"], name)["uid"]

    assert (await authed_client.call("DELETE", f"{URL}/{first_uid}")).status_code == 200

    second_resp = await authed_client.call(
        "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
    )
    assert second_resp.status_code == 200
    second_uid = find_by_name(second_resp.json()["data"], name)["uid"]
    assert second_uid != first_uid

    assert (await authed_client.call("GET", f"{URL}/{first_uid}", raise_for_status=False)).status_code == 404
    assert (await authed_client.call("GET", f"{URL}/{second_uid}")).status_code == 200


@pytest.mark.asyncio
async def test_duplicate_name_per_pic_is_rejected_on_create_and_update(authed_client, active_employee_uid):
    """A key name must be unique per PIC — enforced on create (409) and on a rename into a
    sibling's name (409)."""
    name = f"Dup {uuid4().hex[:8]}"
    first = await authed_client.call(
        "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
    )
    assert first.status_code == 200

    dup_create = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert dup_create.status_code == 409
    assert dup_create.json()["message"] == resolve_message("api_key_already_exists", "en")

    other_name = f"Other {uuid4().hex[:8]}"
    other = await authed_client.call(
        "POST", URL, json={"name": other_name, "employee_uid": active_employee_uid, "is_main": False}
    )
    other_uid = find_by_name(other.json()["data"], other_name)["uid"]

    rename_collision = await authed_client.call(
        "PATCH",
        f"{URL}/{other_uid}",
        json={"name": name, "employee_uid": active_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert rename_collision.status_code == 409
    assert rename_collision.json()["message"] == resolve_message("api_key_already_exists", "en")


@pytest.mark.asyncio
async def test_position_guard_blocks_a_non_pm_pic_on_create(authed_client, wrong_position_employee_uid):
    """A non-(Assistant) Project Manager employee is rejected as PIC at create time."""
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": f"Guard {uuid4().hex[:8]}", "employee_uid": wrong_position_employee_uid, "is_main": False},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("employee_position_not_allowed", "en")
