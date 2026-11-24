import pytest
from tests.helpers import make_chat_session


def _failed_chat(ctx, user_id):
    return make_chat_session(
        ctx, user_id, [("user", "hi", {"status_code": 400}), ("assistant", "blocked", {"status_code": 400})]
    )


@pytest.mark.asyncio
async def test_resend_pushes_insertion_success(authed_client, chat_ctx, chat_settings, user_id, chat_calls):
    """200; resending a failed message saves a new copy and pushes its uid only, before the publish."""
    await chat_settings()
    session, rows = _failed_chat(chat_ctx, user_id)
    resp = await authed_client.call("PATCH", f"/api/chat-assistants/{session.uid}/resend/{rows[0].uid}")
    assert resp.status_code == 200
    assert chat_calls.insertions == [("success", str(session.uid), resp.json()["data"])]
    assert chat_calls.events == ["insertion", "publish"]


@pytest.mark.asyncio
async def test_resend_pushes_insertion_failed_and_errors_when_the_row_cannot_be_saved(
    authed_client, chat_ctx, chat_settings, user_id, chat_calls, fail_chat_insert
):
    """500; `failed` is pushed without a chat uid and nothing is published."""
    await chat_settings()
    session, rows = _failed_chat(chat_ctx, user_id)
    resp = await authed_client.call(
        "PATCH", f"/api/chat-assistants/{session.uid}/resend/{rows[0].uid}", raise_for_status=False
    )
    assert resp.status_code == 500
    assert chat_calls.insertions == [("failed", str(session.uid), None)] and chat_calls.events == ["insertion"]
