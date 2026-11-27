import pytest
from uuid import uuid4
from tests.helpers import make_chat_session

PROMPT = "Here you go\n```\nSCENE: neon city\n```"


@pytest.mark.asyncio
async def test_detail_hides_system_rows_and_has_no_generation_prompt(authed_client, chat_ctx, user_id):
    """200; only user/assistant messages, oldest first; `has_generation_prompt` stays, `generation_prompt` is gone."""
    session, rows = make_chat_session(
        chat_ctx,
        user_id,
        [("system", "rules"), ("user", "make a prompt"), ("assistant", PROMPT, {"has_generation_prompt": True})],
    )
    resp = await authed_client.call("GET", f"/api/chat-assistants/{session.uid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [m["uid"] for m in data] == [rows[1].uid, rows[2].uid]
    assert all("generation_prompt" not in m for m in data)
    assert data[1]["has_generation_prompt"] is True and "```" in data[1]["content"]


@pytest.mark.asyncio
async def test_detail_of_another_users_session_is_403(authed_client, chat_ctx, other_user_id, as_roles):
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    as_roles([])  # the real test login may carry `root`, which is allowed in
    resp = await authed_client.call("GET", f"/api/chat-assistants/{session.uid}", raise_for_status=False)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_root_can_read_another_users_session(authed_client, chat_ctx, other_user_id, as_roles):
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    as_roles(["root"])
    resp = await authed_client.call("GET", f"/api/chat-assistants/{session.uid}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_detail_of_unknown_session_is_404(authed_client):
    """404 chat_session_not_found: the session repository reports a missing session as not found."""
    resp = await authed_client.call("GET", f"/api/chat-assistants/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
