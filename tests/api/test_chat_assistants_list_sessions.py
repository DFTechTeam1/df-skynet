import json
import pytest
from sqlalchemy import update
from services.mysql.model import DfEngineSettings
from tests.helpers import attach_upload, make_chat_session


def _url(ctx, suffix=""):
    return f"/api/projects/{ctx.project_uid}/chat-assistants/{ctx.menu_uid}{suffix}"


@pytest.mark.asyncio
async def test_list_returns_own_sessions_and_filters_by_topic_and_archive(
    authed_client, chat_ctx, user_id, other_user_id
):
    """200; own sessions only, topic search is case-insensitive, `archieved` splits archived from active."""
    active, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    archived, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")], archieved=True)
    foreign, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])

    everything = (await authed_client.call("GET", _url(chat_ctx, "?itemsPerPage=100"))).json()["data"]["paginated"]
    uids = {s["uid"] for s in everything}
    assert {active.uid, archived.uid} <= uids and foreign.uid not in uids

    only_archived = (await authed_client.call("GET", _url(chat_ctx, "?archieved=true&itemsPerPage=100"))).json()["data"]
    assert archived.uid in {s["uid"] for s in only_archived["paginated"]}
    assert active.uid not in {s["uid"] for s in only_archived["paginated"]}

    only_active = (await authed_client.call("GET", _url(chat_ctx, "?archieved=false&itemsPerPage=100"))).json()["data"]
    assert active.uid in {s["uid"] for s in only_active["paginated"]}

    found = (await authed_client.call("GET", _url(chat_ctx, f"?topic={active.topic.upper()}"))).json()["data"]
    assert [s["uid"] for s in found["paginated"]] == [active.uid] and found["totalData"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("max_messages,can_transfer", [(500, False), (2, True)])
async def test_list_reports_attachment_and_transfer_flags(
    authed_client, chat_ctx, chat_settings, user_id, max_messages, can_transfer
):
    await chat_settings(max_chat_messages=max_messages)
    session, rows = make_chat_session(chat_ctx, user_id, [("system", "s"), ("user", "hi"), ("assistant", "yo")])
    attach_upload(rows[1], user_id, chat_ctx.project_id)
    attach_upload(rows[2], user_id, chat_ctx.project_id)

    data = (await authed_client.call("GET", _url(chat_ctx, f"?topic={session.topic}"))).json()["data"]
    [item] = data["paginated"]
    assert item["action"]["can_send_attachment"] is True
    assert item["action"]["can_transfer_knowledge"] is can_transfer


@pytest.mark.asyncio
async def test_list_blocks_attachments_once_the_file_limit_is_reached(
    authed_client, db_session, chat_ctx, chat_settings, user_id
):
    await chat_settings()
    session, rows = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    attach_upload(rows[0], user_id, chat_ctx.project_id)
    await db_session.execute(
        update(DfEngineSettings)
        .where(DfEngineSettings.key == "chat_assistant_settings")  # type: ignore
        .values(value=json.dumps({"max_chat_messages": 500, "max_unique_attachments": 1}))
    )
    await db_session.commit()

    data = (await authed_client.call("GET", _url(chat_ctx, f"?topic={session.topic}"))).json()["data"]
    action = data["paginated"][0]["action"]
    assert action["can_send_attachment"] is False and action["can_transfer_knowledge"] is True
