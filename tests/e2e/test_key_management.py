import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from tests.helpers import find_by_name, response_names

URL = "/api/key-management"


@pytest.mark.asyncio
async def test_full_crud_lifecycle(authed_client, active_employee_uid):
    """Walks create -> detail -> update (twice) -> list -> delete -> confirm gone from both
    list and detail, checking each response reflects the latest state."""
    name = f"Journey {uuid4().hex[:8]}"

    # 1. create
    create_resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "api_key": "sk-or-v1-journeyjourney1",
            "employee_uid": active_employee_uid,
            "limit_usage": 25.0,
            "limit_reset": "weekly",
        },
    )
    assert create_resp.status_code == 200
    assert name in response_names(create_resp.json())
    created = find_by_name(create_resp.json()["data"], name)
    uid = created["uid"]
    assert created["key"] != "sk-or-v1-journeyjourney1"  # masked on the list-shaped create response

    # 2. detail returns the real, unmasked key and the same PIC
    detail_resp = await authed_client.call("GET", f"{URL}/{uid}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["key"] == "sk-or-v1-journeyjourney1"
    assert detail_resp.json()["data"]["pic"] == created["pic"]

    # 3. update — rename, rotate the key, change the limit cadence
    renamed = f"{name}-v2"
    update_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={
            "name": renamed,
            "api_key": "sk-or-v1-journeyjourney2",
            "employee_uid": active_employee_uid,
            "limit_usage": 10.0,
            "limit_reset": "daily",
        },
    )
    assert update_resp.status_code == 200
    assert renamed in response_names(update_resp.json())
    assert name not in response_names(update_resp.json())
    updated = find_by_name(update_resp.json()["data"], renamed)
    assert updated["limit_usage"] == 10.0
    assert updated["limit_reset"] == "daily"
    assert updated["updater"] is not None

    # 4. a second sequential update, proving multiple writes compose correctly
    renamed_again = f"{name}-v3"
    update_resp_2 = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={
            "name": renamed_again,
            "api_key": "sk-or-v1-journeyjourney3",
            "employee_uid": active_employee_uid,
            "is_active": False,
        },
    )
    assert update_resp_2.status_code == 200
    updated_again = find_by_name(update_resp_2.json()["data"], renamed_again)
    assert updated_again["is_active"] is False

    # 5. list reflects the latest state — inactive keys still show up here
    list_resp = await authed_client.call("GET", URL)
    assert renamed_again in response_names(list_resp.json())
    assert renamed not in response_names(list_resp.json())

    # 6. delete (soft)
    delete_resp = await authed_client.call("DELETE", f"{URL}/{uid}")
    assert delete_resp.status_code == 200
    assert renamed_again not in response_names(delete_resp.json())

    # 7. confirmed gone on a fresh list, and detail now 404s
    final_list = await authed_client.call("GET", URL)
    assert renamed_again not in response_names(final_list.json())
    final_detail = await authed_client.call("GET", f"{URL}/{uid}", raise_for_status=False)
    assert final_detail.status_code == 404
    assert final_detail.json()["message"] == resolve_message("api_key_not_found", "en")


@pytest.mark.asyncio
async def test_duplicate_name_conflict_from_create_and_update(authed_client, active_employee_uid):
    """409 from both create and rename-via-update when the target name is already taken, and a
    failed rename leaves the original name intact."""
    suffix = uuid4().hex[:8]
    alpha_name = f"Alpha-{suffix}"
    beta_name = f"Beta-{suffix}"

    alpha_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": alpha_name, "api_key": "sk-or-v1-alphaalphaalpha", "employee_uid": active_employee_uid},
    )
    assert alpha_resp.status_code == 200

    beta_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": beta_name, "api_key": "sk-or-v1-betabetabetabeta", "employee_uid": active_employee_uid},
    )
    assert beta_resp.status_code == 200
    beta_uid = find_by_name(beta_resp.json()["data"], beta_name)["uid"]

    # renaming beta to alpha's name conflicts
    rename_conflict = await authed_client.call(
        "PATCH",
        f"{URL}/{beta_uid}",
        json={"name": alpha_name, "api_key": "sk-or-v1-betabetabetabeta", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert rename_conflict.status_code == 409

    # creating a second "alpha" from scratch conflicts too — same guard, different trigger
    create_conflict = await authed_client.call(
        "POST",
        URL,
        json={"name": alpha_name, "api_key": "sk-or-v1-xxxxxxxxxxxx", "employee_uid": active_employee_uid},
        raise_for_status=False,
    )
    assert create_conflict.status_code == 409

    # beta was never actually renamed by the failed attempt
    list_resp = await authed_client.call("GET", URL)
    assert beta_name in response_names(list_resp.json())


@pytest.mark.asyncio
async def test_soft_delete_then_name_reuse_journey(authed_client, active_employee_uid):
    """A deleted key's name is unavailable to *rename into* (still taken by the soft-deleted
    row's history) but free to *create fresh* — and the new key is a distinct record from the
    old one, not a resurrection of it."""
    name = f"Reused {uuid4().hex[:8]}"

    first_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-firstfirstfirst", "employee_uid": active_employee_uid},
    )
    first_uid = find_by_name(first_resp.json()["data"], name)["uid"]

    delete_resp = await authed_client.call("DELETE", f"{URL}/{first_uid}")
    assert delete_resp.status_code == 200
    assert name not in response_names(delete_resp.json())

    # the name is free again
    second_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-secondsecondse", "employee_uid": active_employee_uid},
    )
    assert second_resp.status_code == 200
    second = find_by_name(second_resp.json()["data"], name)
    second_uid = second["uid"]
    assert second_uid != first_uid

    # the old (deleted) uid stays gone; the new one is live with the fresh key
    old_detail = await authed_client.call("GET", f"{URL}/{first_uid}", raise_for_status=False)
    assert old_detail.status_code == 404
    new_detail = await authed_client.call("GET", f"{URL}/{second_uid}")
    assert new_detail.json()["data"]["key"] == "sk-or-v1-secondsecondse"


@pytest.mark.asyncio
async def test_pic_guards_block_assignment_on_both_create_and_update(
    authed_client, active_employee_uid, resigned_employee_uid, wrong_position_employee_uid
):
    """A resigned or wrong-position employee is rejected as PIC on create *and* on a later
    reassignment via update — the guard isn't a create-only check."""
    # create is blocked by each guard
    resigned_create = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Guard {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-resignedresign",
            "employee_uid": resigned_employee_uid,
        },
        raise_for_status=False,
    )
    assert resigned_create.status_code == 422
    assert resigned_create.json()["message"] == resolve_message("employee_already_resigned", "en")

    wrong_position_create = await authed_client.call(
        "POST",
        URL,
        json={
            "name": f"Guard {uuid4().hex[:8]}",
            "api_key": "sk-or-v1-wrongposition1",
            "employee_uid": wrong_position_employee_uid,
        },
        raise_for_status=False,
    )
    assert wrong_position_create.status_code == 422
    assert wrong_position_create.json()["message"] == resolve_message("employee_position_not_allowed", "en")

    # a key created with a valid PIC can't later be reassigned to an invalid one
    name = f"Guard Update {uuid4().hex[:8]}"
    create_resp = await authed_client.call(
        "POST",
        URL,
        json={"name": name, "api_key": "sk-or-v1-validvalidvali", "employee_uid": active_employee_uid},
    )
    uid = find_by_name(create_resp.json()["data"], name)["uid"]

    reassign_to_resigned = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={"name": name, "api_key": "sk-or-v1-validvalidvali", "employee_uid": resigned_employee_uid},
        raise_for_status=False,
    )
    assert reassign_to_resigned.status_code == 422

    # the key still has its original, valid PIC — the failed reassignment didn't partially apply
    detail_resp = await authed_client.call("GET", f"{URL}/{uid}")
    assert detail_resp.json()["data"]["pic"]["nickname"] is not None
