# import pytest
# from uuid import uuid4
# from sqlalchemy import select
# from middlewares.lang import resolve_message
# from services.mysql.model import DfEngineApiKeys, DfEngineApiSnapshots, DfEngineOpenrouterLogs, Employees
# from tests.helpers import create_record, find_by_name, response_names

# URL = "/api/key-management"

# pytestmark = pytest.mark.usefixtures("mock_openrouter")


# async def _employee(db_session, employee_uid):
#     return (await db_session.execute(select(Employees).where(Employees.uid == employee_uid))).scalar_one()


# async def _fabricate_key(db_session, user_id, employee_id, **overrides):
#     """Insert a DfEngineApiKeys row directly (bypassing OpenRouter) — only valid for
#     scenarios that never reach the OpenRouter call (guards, not-found, auth)."""
#     data = dict(
#         uid=str(uuid4()),
#         name=f"Key {uuid4().hex[:8]}",
#         key=f"sk-or-v1-{uuid4().hex[:16]}",
#         hash=uuid4().hex,
#         employee_id=employee_id,
#         created_by=int(user_id),
#         is_main=False,
#     )
#     data.update(overrides)
#     return await create_record(db_session, DfEngineApiKeys, data)


# async def _create_key_via_api(authed_client, employee_uid, **overrides) -> dict:
#     """Create a real key through the API so it has a genuine OpenRouter hash — required
#     for any test that expects a delete/update/rotate call against it to actually succeed."""
#     payload = {"name": f"Key {uuid4().hex[:8]}", "employee_uid": employee_uid, "is_main": False}
#     payload.update(overrides)
#     resp = await authed_client.call("POST", URL, json=payload)
#     return find_by_name(resp.json()["data"], payload["name"])


# @pytest.mark.asyncio
# async def test_delete_success(authed_client, active_employee_uid):
#     """200 OK; deleted key no longer appears in the refreshed list."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)
#     resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert resp.status_code == 200
#     assert created["name"] not in response_names(resp.json())


# @pytest.mark.asyncio
# async def test_delete_is_hard_row_no_longer_exists(authed_client, db_session, active_employee_uid):
#     """200 OK; the row is hard-deleted, not soft-deleted — there's no status column to flag it."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)
#     resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert resp.status_code == 200

#     await db_session.rollback()
#     still_in_db = (
#         await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.uid == created["uid"]))
#     ).scalar_one_or_none()
#     assert still_in_db is None


# @pytest.mark.asyncio
# async def test_delete_archives_a_snapshot_with_employee_name_resolved(authed_client, db_session, active_employee_uid):
#     """200 OK; a matching df_engine_api_snapshots row is created, with `employee_name`
#     resolved from employees.nickname even though the create endpoint never stores it on
#     df_engine_api_keys itself."""
#     employee = await _employee(db_session, active_employee_uid)
#     employee_nickname = employee.nickname  # capture before rollback expires the ORM instance
#     created = await _create_key_via_api(authed_client, active_employee_uid)

#     resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert resp.status_code == 200

#     await db_session.rollback()
#     snapshot = (
#         await db_session.execute(select(DfEngineApiSnapshots).where(DfEngineApiSnapshots.name == created["name"]))
#     ).scalar_one()
#     assert snapshot.employee_name == employee_nickname


# @pytest.mark.asyncio
# async def test_delete_blocks_main_key(authed_client, db_session, user_id, active_employee_uid):
#     """422 cannot_delete_main_api_key; a key with is_main=true isn't deleted, snapshotted,
#     or removed. Never reaches OpenRouter, so a fabricated row is fine here."""
#     employee = await _employee(db_session, active_employee_uid)
#     row = await _fabricate_key(db_session, user_id, employee.id, is_main=True)
#     row_id, row_key = row.id, row.key  # capture before rollback expires the ORM instance

#     resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
#     assert resp.status_code == 422
#     assert resp.json()["message"] == resolve_message("cannot_delete_main_api_key", "en")

#     await db_session.rollback()
#     still_there = (
#         await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.id == row_id))
#     ).scalar_one_or_none()
#     assert still_there is not None
#     no_snapshot = (
#         await db_session.execute(select(DfEngineApiSnapshots).where(DfEngineApiSnapshots.key == row_key))
#     ).scalar_one_or_none()
#     assert no_snapshot is None


# @pytest.mark.asyncio
# async def test_delete_blocks_missing_hash(authed_client, db_session, user_id, active_employee_uid):
#     """422 api_key_missing_hash; a key with no OpenRouter hash on record can't be deleted
#     remotely, so the call is rejected before ever reaching OpenRouter."""
#     employee = await _employee(db_session, active_employee_uid)
#     row = await _fabricate_key(db_session, user_id, employee.id, hash=None)

#     resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
#     assert resp.status_code == 422
#     assert resp.json()["message"] == resolve_message("api_key_missing_hash", "en")


# @pytest.mark.asyncio
# async def test_delete_excludes_key_from_copy_endpoint(authed_client, active_employee_uid):
#     """200 OK on delete; the copy endpoint then 404s for the same uid."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)
#     delete_resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert delete_resp.status_code == 200

#     copy_resp = await authed_client.call("GET", f"{URL}/{created['uid']}", raise_for_status=False)
#     assert copy_resp.status_code == 404
#     assert copy_resp.json()["message"] == resolve_message("api_key_not_found", "en")


# @pytest.mark.asyncio
# async def test_delete_logs_the_openrouter_call(authed_client, db_session, active_employee_uid):
#     """A DfEngineOpenrouterLogs row is written for the DELETE /keys/{hash} attempt."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)

#     resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert resp.status_code == 200

#     await db_session.rollback()
#     logs = (
#         (
#             await db_session.execute(
#                 select(DfEngineOpenrouterLogs).order_by(DfEngineOpenrouterLogs.created_at.desc()).limit(10)
#             )
#         )
#         .scalars()
#         .all()
#     )
#     assert any(log.method == "DELETE" for log in logs)


# @pytest.mark.asyncio
# async def test_deleted_key_name_can_be_reused_by_a_new_key(authed_client, active_employee_uid):
#     """200 OK; once a key is hard-deleted, its name is free — creating a new key with the
#     same name succeeds instead of 409ing."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)

#     delete_resp = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert delete_resp.status_code == 200

#     create_resp = await authed_client.call(
#         "POST",
#         URL,
#         json={"name": created["name"], "employee_uid": active_employee_uid, "is_main": False},
#         raise_for_status=False,
#     )
#     assert create_resp.status_code == 200
#     assert created["name"] in response_names(create_resp.json())


# @pytest.mark.asyncio
# async def test_delete_twice_is_404_on_the_second_call(authed_client, active_employee_uid):
#     """First delete is 200 OK; repeating it is 404 api_key_not_found since the row is already gone."""
#     created = await _create_key_via_api(authed_client, active_employee_uid)
#     first = await authed_client.call("DELETE", f"{URL}/{created['uid']}")
#     assert first.status_code == 200
#     second = await authed_client.call("DELETE", f"{URL}/{created['uid']}", raise_for_status=False)
#     assert second.status_code == 404
#     assert second.json()["message"] == resolve_message("api_key_not_found", "en")


# @pytest.mark.asyncio
# async def test_delete_unknown_uid_is_404(authed_client):
#     """404 api_key_not_found when the uid matches no key."""
#     resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
#     assert resp.status_code == 404
#     assert resp.json()["message"] == resolve_message("api_key_not_found", "en")


# @pytest.mark.asyncio
# async def test_requires_auth(client, db_session, user_id, active_employee_uid):
#     """401 when the request carries no bearer token. Never reaches OpenRouter, so a
#     fabricated row is fine here."""
#     employee = await _employee(db_session, active_employee_uid)
#     row = await _fabricate_key(db_session, user_id, employee.id)
#     resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
#     assert resp.status_code == 401


# # --- localization ------------------------------------------------------------


# @pytest.mark.asyncio
# async def test_not_found_message_respects_accept_language(authed_client):
#     """404; the not_found message text is localized per the Accept-Language header, differing between en and id."""
#     unknown_uid = uuid4()

#     en_resp = await authed_client.call(
#         "DELETE",
#         f"{URL}/{unknown_uid}",
#         headers={"Accept-Language": "en"},
#         raise_for_status=False,
#     )
#     id_resp = await authed_client.call(
#         "DELETE",
#         f"{URL}/{unknown_uid}",
#         headers={"Accept-Language": "id"},
#         raise_for_status=False,
#     )

#     assert en_resp.json()["message"] == resolve_message("api_key_not_found", "en")
#     assert id_resp.json()["message"] == resolve_message("api_key_not_found", "id")
#     assert en_resp.json()["message"] != id_resp.json()["message"]
