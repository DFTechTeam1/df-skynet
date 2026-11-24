import pytest
from sqlalchemy import func, select
from services.mysql.model import DfEngineChatAssistants
from tests.helpers import make_chat_session


def _url(session):
    return f"/api/chat-assistants/{session.uid}"


async def _count(db_session, session_id):
    await db_session.commit()
    stmt = (
        select(func.count()).select_from(DfEngineChatAssistants).where(DfEngineChatAssistants.session_id == session_id)
    )  # type: ignore
    return (await db_session.execute(stmt)).scalar()


@pytest.mark.asyncio
async def test_continue_by_non_owner_is_403(authed_client, chat_ctx, other_user_id, chat_calls):
    session, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), json={"content": "more"}, raise_for_status=False)
    assert resp.status_code == 403 and chat_calls.events == []


@pytest.mark.asyncio
async def test_continue_archived_session_is_422(authed_client, chat_ctx, user_id, chat_calls):
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi"), ("assistant", "hello")], archieved=True)
    resp = await authed_client.call("POST", _url(session), json={"content": "more"}, raise_for_status=False)
    assert resp.status_code == 422 and chat_calls.events == []


@pytest.mark.asyncio
async def test_continue_when_message_limit_is_reached_is_422(
    authed_client, db_session, chat_ctx, chat_settings, user_id, chat_calls
):
    """422 and nothing is saved, pushed or published once the chat holds `max_chat_messages` messages."""
    await chat_settings(max_chat_messages=2)
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), json={"content": "more"}, raise_for_status=False)
    assert resp.status_code == 422
    assert chat_calls.events == [] and await _count(db_session, session.id) == 2


@pytest.mark.asyncio
async def test_continue_pushes_insertion_success_with_only_the_user_chat_uid(
    authed_client, db_session, chat_ctx, chat_settings, user_id, chat_calls
):
    """200; the push carries the new user message uid (the response data) and is sent before the RMQ publish."""
    await chat_settings()
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), json={"content": "and now?"}, raise_for_status=False)
    assert resp.status_code == 200, resp.text
    user_chat_uid = resp.json()["data"]
    assert chat_calls.insertions == [("success", str(session.uid), user_chat_uid)]
    assert chat_calls.events == ["insertion", "publish"]
    assert chat_calls.published[0]["session_uid"] == str(session.uid)
    row = (
        await db_session.execute(select(DfEngineChatAssistants).where(DfEngineChatAssistants.uid == user_chat_uid))  # type: ignore
    ).scalar_one()
    assert (row.role, row.content, row.session_id) == ("user", "and now?", session.id)


@pytest.mark.asyncio
async def test_continue_pushes_insertion_failed_and_errors_when_rows_cannot_be_saved(
    authed_client, db_session, chat_ctx, chat_settings, user_id, chat_calls, fail_chat_insert
):
    """500; a failing insert pushes `failed` (no chat uid), nothing is published and no row is left behind."""
    await chat_settings()
    session, _ = make_chat_session(chat_ctx, user_id, [("user", "hi"), ("assistant", "hello")])
    resp = await authed_client.call("POST", _url(session), json={"content": "more"}, raise_for_status=False)
    assert resp.status_code == 500
    assert chat_calls.insertions == [("failed", str(session.uid), None)]
    assert chat_calls.events == ["insertion"] and await _count(db_session, session.id) == 2
