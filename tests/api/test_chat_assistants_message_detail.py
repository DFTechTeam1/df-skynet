import pytest
from tests.helpers import make_chat_session

PROMPT = "Here you go\n```\nSCENE: neon city\n```"


def _url(session, chat):
    return f"/api/chat-assistants/{session.uid}/messages/{chat.uid}"


@pytest.mark.asyncio
async def test_single_message_has_no_generation_prompt(authed_client, chat_ctx, user_id):
    """200; the single-message endpoint keeps `has_generation_prompt` but has no `generation_prompt`."""
    session, rows = make_chat_session(
        chat_ctx, user_id, [("user", "hi"), ("assistant", PROMPT, {"has_generation_prompt": True})]
    )
    resp = await authed_client.call("GET", _url(session, rows[1]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "generation_prompt" not in data and data["has_generation_prompt"] is True and data["uid"] == rows[1].uid


@pytest.mark.asyncio
async def test_single_message_of_another_users_session_is_403(authed_client, chat_ctx, other_user_id):
    session, rows = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    resp = await authed_client.call("GET", _url(session, rows[0]), raise_for_status=False)
    assert resp.status_code == 403
