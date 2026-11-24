import pytest
from tests.helpers import make_chat_session


@pytest.mark.asyncio
async def test_update_topic_renames_the_session_even_when_archived(authed_client, chat_ctx, user_id):
    """200; the topic changes whether or not the session is archived."""
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")], archieved=True)
    resp = await authed_client.call("PATCH", f"/api/chat-assistants/{session.uid}", json={"topic": "New topic"})
    assert resp.status_code == 200
    assert resp.json()["data"]["topic"] == "New topic" and resp.json()["data"]["uid"] == session.uid


@pytest.mark.asyncio
async def test_update_topic_of_another_users_session_is_403(authed_client, chat_ctx, other_user_id):
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    resp = await authed_client.call(
        "PATCH", f"/api/chat-assistants/{session.uid}", json={"topic": "x"}, raise_for_status=False
    )
    assert resp.status_code == 403
