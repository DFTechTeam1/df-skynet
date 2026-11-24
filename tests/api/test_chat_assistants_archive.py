import pytest
from tests.helpers import make_chat_session


@pytest.mark.asyncio
async def test_archive_toggles_the_session(authed_client, chat_ctx, user_id):
    """200; the first call archives (can_set_archieve turns false), the second brings it back."""
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    url = f"/api/chat-assistants/{session.uid}/set-archieve"
    assert (await authed_client.call("PATCH", url)).json()["data"]["action"]["can_set_archieve"] is False
    assert (await authed_client.call("PATCH", url)).json()["data"]["action"]["can_set_archieve"] is True


@pytest.mark.asyncio
async def test_archive_of_another_users_session_is_403(authed_client, chat_ctx, other_user_id):
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])
    resp = await authed_client.call("PATCH", f"/api/chat-assistants/{session.uid}/set-archieve", raise_for_status=False)
    assert resp.status_code == 403
