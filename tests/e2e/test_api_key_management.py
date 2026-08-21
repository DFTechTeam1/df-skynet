# import pytest
# from uuid import uuid4
# from middlewares.lang import resolve_message
# from tests.helpers import find_by_name, response_names

# URL = "/api/key-management"

# pytestmark = pytest.mark.usefixtures("mock_openrouter")


# @pytest.mark.asyncio
# async def test_full_lifecycle(authed_client, active_employee_uid):
#     """Walks create -> copy -> update (rename only) -> update (limit change) -> delete
#     blocked while main -> update to non-main -> delete -> confirm gone from list and copy,
#     checking each response reflects the latest state."""
#     name = f"Journey {uuid4().hex[:8]}"

#     # 1. create as main
#     create_resp = await authed_client.call(
#         "POST",
#         URL,
#         json={"name": name, "employee_uid": active_employee_uid, "is_main": True},
#     )
#     assert create_resp.status_code == 200
#     assert name in response_names(create_resp.json())
#     created = find_by_name(create_resp.json()["data"], name)
#     uid = created["uid"]

#     # 2. copy returns the real, unmasked key
#     copy_resp = await authed_client.call("GET", f"{URL}/{uid}")
#     assert copy_resp.status_code == 200
#     real_key = copy_resp.json()["data"]
#     assert real_key != created["key"]  # list-shaped response was masked

#     # 3. update — rename only, doesn't touch OpenRouter
#     renamed = f"{name}-v2"
#     rename_resp = await authed_client.call(
#         "PATCH",
#         f"{URL}/{uid}",
#         json={"name": renamed, "employee_uid": active_employee_uid, "is_main": True},
#     )
#     assert rename_resp.status_code == 200
#     assert renamed in response_names(rename_resp.json())
#     assert name not in response_names(rename_resp.json())

#     # 4. update — change the spending limit, which does contact OpenRouter this time
#     limit_resp = await authed_client.call(
#         "PATCH",
#         f"{URL}/{uid}",
#         json={
#             "name": renamed,
#             "employee_uid": active_employee_uid,
#             "is_main": True,
#             "limit": 10.0,
#             "limit_reset": "daily",
#         },
#     )
#     assert limit_resp.status_code == 200
#     updated = find_by_name(limit_resp.json()["data"], renamed)
#     assert updated["limit"] == 10.0
#     assert updated["limit_reset"] == "daily"
#     assert updated["updater"] is not None

#     # 5. delete is blocked while the key is still main
#     blocked_delete = await authed_client.call("DELETE", f"{URL}/{uid}", raise_for_status=False)
#     assert blocked_delete.status_code == 422
#     assert blocked_delete.json()["message"] == resolve_message("cannot_delete_main_api_key", "en")

#     # 6. update to no longer be main
#     unmain_resp = await authed_client.call(
#         "PATCH",
#         f"{URL}/{uid}",
#         json={"name": renamed, "employee_uid": active_employee_uid, "is_main": False},
#     )
#     assert unmain_resp.status_code == 200

#     # 7. delete now succeeds
#     delete_resp = await authed_client.call("DELETE", f"{URL}/{uid}")
#     assert delete_resp.status_code == 200
#     assert renamed not in response_names(delete_resp.json())

#     # 8. confirmed gone on a fresh list, and copy now 404s
#     final_list = await authed_client.call("GET", URL)
#     assert renamed not in response_names(final_list.json())
#     final_copy = await authed_client.call("GET", f"{URL}/{uid}", raise_for_status=False)
#     assert final_copy.status_code == 404
#     assert final_copy.json()["message"] == resolve_message("api_key_not_found", "en")


# @pytest.mark.asyncio
# async def test_hard_delete_then_name_reuse_journey(authed_client, active_employee_uid):
#     """A deleted key's name is free to create fresh — and the new key is a distinct
#     record from the old one, not a resurrection of it."""
#     name = f"Reused {uuid4().hex[:8]}"

#     first_resp = await authed_client.call(
#         "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
#     )
#     first_uid = find_by_name(first_resp.json()["data"], name)["uid"]

#     delete_resp = await authed_client.call("DELETE", f"{URL}/{first_uid}")
#     assert delete_resp.status_code == 200
#     assert name not in response_names(delete_resp.json())

#     # the name is free again
#     second_resp = await authed_client.call(
#         "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
#     )
#     assert second_resp.status_code == 200
#     second_uid = find_by_name(second_resp.json()["data"], name)["uid"]
#     assert second_uid != first_uid

#     # the old (deleted) uid stays gone; the new one is live
#     old_copy = await authed_client.call("GET", f"{URL}/{first_uid}", raise_for_status=False)
#     assert old_copy.status_code == 404
#     new_copy = await authed_client.call("GET", f"{URL}/{second_uid}")
#     assert new_copy.status_code == 200


# @pytest.mark.asyncio
# async def test_pic_guards_block_assignment_on_both_create_and_update(
#     authed_client, active_employee_uid, resigned_employee_uid, wrong_position_employee_uid
# ):
#     """A resigned or wrong-position employee is rejected as PIC on create *and* on a later
#     reassignment via update — the guard isn't a create-only check."""
#     resigned_create = await authed_client.call(
#         "POST",
#         URL,
#         json={"name": f"Guard {uuid4().hex[:8]}", "employee_uid": resigned_employee_uid, "is_main": False},
#         raise_for_status=False,
#     )
#     assert resigned_create.status_code == 422
#     assert resigned_create.json()["message"] == resolve_message("employee_already_resigned", "en")

#     wrong_position_create = await authed_client.call(
#         "POST",
#         URL,
#         json={"name": f"Guard {uuid4().hex[:8]}", "employee_uid": wrong_position_employee_uid, "is_main": False},
#         raise_for_status=False,
#     )
#     assert wrong_position_create.status_code == 422
#     assert wrong_position_create.json()["message"] == resolve_message("employee_position_not_allowed", "en")

#     # a key created with a valid PIC can't later be reassigned to an invalid one
#     name = f"Guard Update {uuid4().hex[:8]}"
#     create_resp = await authed_client.call(
#         "POST", URL, json={"name": name, "employee_uid": active_employee_uid, "is_main": False}
#     )
#     uid = find_by_name(create_resp.json()["data"], name)["uid"]

#     reassign_to_resigned = await authed_client.call(
#         "PATCH",
#         f"{URL}/{uid}",
#         json={"name": name, "employee_uid": resigned_employee_uid, "is_main": False},
#         raise_for_status=False,
#     )
#     assert reassign_to_resigned.status_code == 422

#     # the key still has its original, valid PIC — the failed reassignment didn't partially apply
#     list_resp = await authed_client.call("GET", URL)
#     item = find_by_name(list_resp.json()["data"], name)
#     assert item["pic"]["nickname"] is not None
