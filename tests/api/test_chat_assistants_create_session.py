import pytest
from sqlalchemy import select
from services.mysql.model import DfEngineChatAssistants, DfEngineChatSessions


def _url(ctx):
    return f"/api/projects/{ctx.project_uid}/chat-assistants/new"


def _payload(ctx):
    return {"menu_uid": ctx.menu_uid, "feature_uid": ctx.feature_uid, "content": "make me a neon city prompt"}


@pytest.mark.asyncio
async def test_create_session_pushes_insertion_success_with_only_the_user_chat_uid(
    authed_client, db_session, chat_ctx, chat_settings, chat_calls
):
    """200; the new session is returned, `chat-insertion` success carries the user message uid, sent before the publish."""
    await chat_settings()
    resp = await authed_client.call("POST", _url(chat_ctx), json=_payload(chat_ctx), raise_for_status=False)
    assert resp.status_code == 200, resp.text
    session_uid = resp.json()["data"]
    session = (
        await db_session.execute(select(DfEngineChatSessions).where(DfEngineChatSessions.uid == session_uid))  # type: ignore
    ).scalar_one()
    user_row = (
        await db_session.execute(
            select(DfEngineChatAssistants).where(
                DfEngineChatAssistants.session_id == session.id,  # type: ignore
                DfEngineChatAssistants.role == "user",  # type: ignore
            )
        )
    ).scalar_one()
    assert chat_calls.insertions == [("success", session_uid, user_row.uid)]
    assert chat_calls.events == ["insertion", "publish"]


@pytest.mark.asyncio
async def test_create_session_pushes_insertion_failed_and_errors_when_rows_cannot_be_saved(
    authed_client, chat_ctx, chat_settings, chat_calls, fail_chat_insert
):
    """500; a failing insert pushes `failed` (no chat uid) and nothing is published."""
    await chat_settings()
    resp = await authed_client.call("POST", _url(chat_ctx), json=_payload(chat_ctx), raise_for_status=False)
    assert resp.status_code == 500
    assert [(status, uid is not None, cid) for status, uid, cid in chat_calls.insertions] == [("failed", True, None)]
    assert chat_calls.events == ["insertion"]
