import pytest
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import Employees
from tests.helpers import make_chat_session


def _url(project_uid):
    return f"/api/chat-assistant-sessions/{project_uid}"


async def _get(client, project_uid, **params):
    return (await client.call("GET", _url(project_uid), params={"itemsPerPage": 100, **params})).json()["data"]


@pytest.mark.asyncio
async def test_root_sees_everyones_sessions_in_the_project(authed_client, chat_ctx, user_id, other_user_id, as_roles):
    """Newest first; only the viewer's own session is editable."""
    mine, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    foreign, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")], archieved=True)
    as_roles(["root"])

    data = await _get(authed_client, chat_ctx.project_uid)
    sessions = {s["uid"]: s for s in data["paginated"]}
    assert sessions[mine.uid]["creator"]["user_id"] == int(user_id)
    assert sessions[mine.uid]["action"]["can_update"] is True
    assert sessions[foreign.uid]["creator"]["user_id"] == other_user_id
    action = sessions[foreign.uid]["action"]
    assert action["can_fetch_detail"] and not action["can_update"] and not action["can_set_archieve"]

    first_page = await _get(authed_client, chat_ctx.project_uid, itemsPerPage=1)
    assert len(first_page["paginated"]) == 1 and first_page["totalData"] == data["totalData"] >= 2

    empty = {"paginated": [], "totalData": 0}
    assert await _get(authed_client, uuid4()) == empty
    assert await _get(authed_client, chat_ctx.project_uid, nickname="no-such-employee-%_") == empty


@pytest.mark.asyncio
async def test_nickname_filter_keeps_only_matching_creators(
    authed_client, chat_ctx, user_id, other_user_id, as_roles, db_session
):
    """Case-insensitive match on the employee nickname; other creators' sessions drop out."""
    nickname = await db_session.scalar(select(Employees.nickname).where(Employees.user_id == int(user_id)))
    assert nickname, "the test user needs an employee nickname"
    mine, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    foreign, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    as_roles(["root"])

    data = await _get(authed_client, chat_ctx.project_uid, nickname=f"  {nickname.upper()}  ")
    uids = {s["uid"] for s in data["paginated"]}
    assert mine.uid in uids and foreign.uid not in uids


@pytest.mark.asyncio
async def test_non_root_is_403(authed_client, as_roles):
    as_roles([])
    assert (await authed_client.call("GET", _url(uuid4()), raise_for_status=False)).status_code == 403
