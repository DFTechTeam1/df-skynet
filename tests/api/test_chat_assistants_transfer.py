import pytest
from tests.helpers import make_chat_session


def _url(session):
    return f"/api/chat-assistants/{session.uid}/transfer-knowledge"


@pytest.mark.asyncio
async def test_transfer_with_nothing_answered_is_422(authed_client, chat_ctx, chat_settings, user_id, chat_calls):
    """422; a chat with no answered message has nothing to carry over, whatever its size."""
    await chat_settings()
    session, _ = make_chat_session(chat_ctx, user_id, [("system", "rules")])
    resp = await authed_client.call("POST", _url(session), raise_for_status=False)
    assert resp.status_code == 422 and chat_calls.events == []


@pytest.mark.asyncio
async def test_transfer_is_allowed_for_a_short_chat_and_sends_no_insertion_push(
    authed_client, chat_ctx, chat_settings, user_id, chat_calls
):
    """200 for a chat far below any message limit (no percentage rule any more); no `chat-insertion` push."""
    await chat_settings()
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), raise_for_status=False)
    assert resp.status_code == 200, resp.text
    assert chat_calls.insertions == [] and chat_calls.events == ["publish"]
    assert chat_calls.published[0]["from_session_uid"] == str(session.uid)
    assert chat_calls.published[0]["session_uid"] == resp.json()["data"]


@pytest.mark.asyncio
async def test_transfer_by_non_owner_is_403(authed_client, chat_ctx, chat_settings, other_user_id, chat_calls):
    await chat_settings()
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), raise_for_status=False)
    assert resp.status_code == 403 and chat_calls.events == []
