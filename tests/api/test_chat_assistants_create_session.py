import pytest
from sqlalchemy import select
from types import SimpleNamespace
from tests.helpers import feature_prompts
from middlewares.lang import resolve_message
from schemas.payload.feature_management import FeatureTypes
from services.openrouter import CHAT_ASSISTANT_INSTRUCTION
from services.mysql.model import DfEngineChatAssistants, DfEngineChatSessions


def _url(ctx):
    return f"/api/projects/{ctx.project_uid}/chat-assistants/new"


def _payload(ctx):
    return {"menu_uid": ctx.menu_uid, "content": "make me a neon city prompt"}


@pytest.mark.asyncio
async def test_create_session_pushes_insertion_success_with_only_the_user_chat_uid(
    authed_client, db_session, chat_ctx, chat_settings, chat_calls, chat_features
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
    authed_client, chat_ctx, chat_settings, chat_calls, chat_features, fail_chat_insert
):
    """500; a failing insert pushes `failed` (no chat uid) and nothing is published."""
    await chat_settings()
    resp = await authed_client.call("POST", _url(chat_ctx), json=_payload(chat_ctx), raise_for_status=False)
    assert resp.status_code == 500
    assert [(status, uid is not None, cid) for status, uid, cid in chat_calls.insertions] == [("failed", True, None)]
    assert chat_calls.events == ["insertion"]


@pytest.mark.asyncio
async def test_create_session_system_prompts_come_from_chat_assistant(
    authed_client, db_session, chat_ctx, chat_settings, chat_calls, chat_features
):
    """200; the stored system rows are the global rules, then the templates of the `chat_assistant` feature."""
    await chat_settings()
    resp = await authed_client.call("POST", _url(chat_ctx), json=_payload(chat_ctx), raise_for_status=False)
    assert resp.status_code == 200, resp.text
    session = (
        await db_session.execute(select(DfEngineChatSessions).where(DfEngineChatSessions.uid == resp.json()["data"]))  # type: ignore
    ).scalar_one()
    system_rows = (
        (
            await db_session.execute(
                select(DfEngineChatAssistants.content)  # type: ignore
                .where(DfEngineChatAssistants.session_id == session.id, DfEngineChatAssistants.role == "system")  # type: ignore
                .order_by(DfEngineChatAssistants.id)  # type: ignore
            )
        )
        .scalars()
        .all()
    )
    expected = await feature_prompts(db_session, FeatureTypes.chat_assistant)
    assert system_rows == [CHAT_ASSISTANT_INSTRUCTION.strip(), *expected]


@pytest.mark.asyncio
async def test_create_session_without_a_chat_assistant_feature_is_404(
    authed_client, chat_ctx, chat_settings, chat_calls, monkeypatch
):
    """404 `chat_assistant_feature_not_configured` and nothing is published when no active feature has the chat_assistant type."""
    await chat_settings()
    monkeypatch.setattr("apps.controller.chat_assistants.FeatureTypes", SimpleNamespace(chat_assistant="no_such_type"))
    resp = await authed_client.call("POST", _url(chat_ctx), json=_payload(chat_ctx), raise_for_status=False)
    assert resp.status_code == 404 and chat_calls.events == []
    assert resp.json()["message"] == resolve_message("chat_assistant_feature_not_configured", "en")
